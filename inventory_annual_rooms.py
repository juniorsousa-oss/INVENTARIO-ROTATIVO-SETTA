"""Shared synthetic annual-count rooms; no Central, ERP, or Rotativo dependency."""
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from hmac import new as hmac_new
from pathlib import Path
import json
import re
import secrets
import sqlite3
import tempfile
import time

from inventory_annual_pilot import (
    AUDIT, FIRST, SECOND, VALIDATED, CATALOG, ELIGIBLE, TEAMS, AnnualPilot, Position, qty,
)

COORD = "Coordenação"
AUDITOR = "Auditoria"
WORKERS = (*TEAMS, AUDITOR)
PATH = Path(tempfile.gettempdir()) / "setta-annual-demo-v2" / "rooms.sqlite3"
TTL = 3 * 24 * 60 * 60
MAX_ROOMS = 200
MAX_READINGS = 500
FIELD = re.compile(r"[A-Z0-9][A-Z0-9_.-]{0,31}")
DEMO_PRODUCTS = {f"{i:08}": product for i, product in enumerate(CATALOG, start=1)}
TOKEN = re.compile(r"[A-Za-z0-9_-]{32}")


@dataclass(frozen=True)
class Reading:
    product: str
    address: str
    lot: str
    quantity: Decimal
    label_id: str = ""


def reading(product, address, lot, amount, label_id=""):
    product, address, lot, label_id = (v.strip().upper() for v in (product, address, lot, label_id))
    product = DEMO_PRODUCTS.get(product, product)
    if product not in CATALOG:
        raise ValueError("Produto não encontrado no catálogo fictício.")
    if address not in ELIGIBLE:
        raise ValueError("Endereço não apto neste piloto.")
    if not FIELD.fullmatch(lot) or (label_id and not FIELD.fullmatch(label_id)):
        raise ValueError("Informe um lote válido. Use apenas letras, números, ponto, hífen ou sublinhado.")
    if not re.fullmatch(r"\d{1,10}(?:[.,]\d{1,6})?", str(amount).strip(), flags=re.ASCII):
        raise ValueError("Informe a quantidade sem separador de milhar, com até seis casas decimais.")
    value = qty(str(amount).strip())
    if not value:
        raise ValueError("A etiqueta precisa ter quantidade maior que zero.")
    return Reading(product, address, lot, value, label_id)


def parse_qr_fields(payload):
    """Etiqueta atual: produto,lote,quantidade. Preserve zeros no produto/lote."""
    if not isinstance(payload, str) or len(payload) > 180:
        raise ValueError("QR inválido.")
    parts = [part.strip() for part in payload.strip().split(",", 2)]
    if len(parts) != 3 or not FIELD.fullmatch(parts[0].upper()) or not FIELD.fullmatch(parts[1].upper()):
        raise ValueError("Formato de QR esperado: produto,lote,quantidade.")
    return tuple(parts)


def parse_demo_label(payload, address):
    product, lot, quantity = parse_qr_fields(payload)
    return reading(product, address, lot, quantity)


def _sha(token):
    return sha256(token.encode("ascii")).hexdigest()


def worker_codes(coordinator_code):
    return {role: hmac_new(coordinator_code.encode("ascii"), role.encode(), sha256).hexdigest()[:32]
            for role in WORKERS}


def _state(pilot, drafts=None, evidence=None):
    return {"assignment": pilot.assignment, "started": pilot.started_at.isoformat(),
            "closed": pilot.closed_at.isoformat() if pilot.closed_at else None,
            "snapshot": pilot._snapshot, "system": pilot._total, "catalog": pilot._catalog,
            "positions": {a: {k: asdict(row) for k, row in rows.items()} for a, rows in pilot.positions.items()},
            "drafts": drafts or {}, "evidence": evidence or {}}


def _restore(state):
    def dec(v):
        return Decimal(v) if v is not None else None
    p = AnnualPilot(assignment=state["assignment"], started_at=datetime.fromisoformat(state["started"]),
                    closed_at=datetime.fromisoformat(state["closed"]) if state["closed"] else None)
    p._snapshot = {a: {k: dec(v) for k, v in rows.items()} for a, rows in state["snapshot"].items()}
    p._total = {k: dec(v) for k, v in state["system"].items()}
    p._catalog = {k: (v[0], dec(v[1])) for k, v in state["catalog"].items()}
    p.positions = {a: {k: Position(**{f: dec(v) if f in ("system", "first", "second", "final") else v
                                    for f, v in record.items()}) for k, record in rows.items()}
                   for a, rows in state["positions"].items()}
    return p


@contextmanager
def _connect(path):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS annual_rooms
                (id TEXT PRIMARY KEY, expires INTEGER NOT NULL, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS annual_access
                (token_hash TEXT PRIMARY KEY, room_id TEXT NOT NULL
                 REFERENCES annual_rooms(id) ON DELETE CASCADE, role TEXT NOT NULL);
        """)
        with conn:
            yield conn
    finally:
        conn.close()


def _encode(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def create_room(assignment, locked, *, path=PATH):
    p = AnnualPilot()
    p.start(assignment, locked)
    token = secrets.token_urlsafe(24)
    room = secrets.token_hex(8)
    now = int(time.time())
    with _connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM annual_rooms WHERE expires <= ?", (now,))
        if conn.execute("SELECT COUNT(*) FROM annual_rooms").fetchone()[0] >= MAX_ROOMS:
            raise ValueError("Limite de pilotos em uso. Entre em um piloto existente.")
        conn.execute("INSERT INTO annual_rooms VALUES (?,?,?)", (room, now + TTL, _encode(_state(p))))
        keys = {COORD: token, **worker_codes(token)}
        conn.executemany("INSERT INTO annual_access VALUES (?,?,?)",
                         [(_sha(code), room, role) for role, code in keys.items()])
    return token


def _authorized(conn, token):
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise ValueError("Código de acesso inválido ou expirado.")
    item = conn.execute("""SELECT a.room_id, a.role, r.state
                           FROM annual_access a JOIN annual_rooms r ON a.room_id=r.id
                           WHERE a.token_hash=? AND r.expires>?""",
                        (_sha(token), int(time.time()))).fetchone()
    if not item:
        raise ValueError("Código de acesso inválido ou expirado.")
    room, role, raw = item
    return room, role, json.loads(raw)


def _key(stage, address, product=""):
    return "|".join((stage, address, product))


def _assert_task(pilot, role, stage, address, product):
    pilot._require_open()
    if stage == FIRST and role in TEAMS and pilot.assignment.get(address) == role and address not in pilot.positions and product == "":
        return
    if stage == SECOND and role in TEAMS and (address, product) in pilot.queue(role):
        return
    if stage == AUDIT and role == AUDITOR and (address, product) in pilot.audit_queue():
        return
    raise ValueError("Esta tarefa não está disponível para o seu papel. Atualize a fila.")


def grouped(lines):
    total = defaultdict(Decimal)
    for item in lines:
        total[(item["product"], item["lot"])] += Decimal(item["quantity"])
    return [{"Produto": a, "Lote": b, "Quantidade": q}
            for (a, b), q in sorted(total.items())]


def _draft_details(rows):
    return {k: grouped(v) for k, v in rows.items()}


def view(token, *, path=PATH):
    """Only return the caller's workflow view; counter views have no cut or peer counts."""
    with _connect(path) as conn:
        _, role, state = _authorized(conn, token)
    p = _restore(state)
    common = {"role": role, "closed": bool(p.closed_at)}
    if role == COORD:
        queue = []
        for a, team in p.assignment.items():
            status = p.address_status(a)
            if status == FIRST:
                queue.append((a, "", FIRST, team, bool(state["drafts"].get(_key(FIRST, a)))))
            for code, pos in p.positions.get(a, {}).items():
                if pos.stage in (SECOND, AUDIT):
                    responsible = next(t for t in TEAMS if t != team) if pos.stage == SECOND else AUDITOR
                    queue.append((a, code, pos.stage, responsible, bool(state["drafts"].get(_key(pos.stage, a, code)))))
        return {**common, "pilot": p, "queue": queue, "evidence": _draft_details(state["evidence"]) if p.closed_at else {}}
    tasks = {}
    if not p.closed_at:
        if role in TEAMS:
            tasks[FIRST] = [(a, "") for a in ELIGIBLE if p.assignment[a] == role and a not in p.positions]
            tasks[SECOND] = p.queue(role)
        else:
            tasks[AUDIT] = p.audit_queue()
    own = {_key(stage, a, c): state["drafts"].get(_key(stage, a, c), [])
           for stage, pairs in tasks.items() for a, c in pairs}
    return {**common, "tasks": tasks, "drafts": own}


def action(token, event, stage="", address="", product="", *, item=None, repeat=False, line_id="",
           empty=False, complete=False, note="", path=PATH):
    """Recheck permissions and mutate the freshest room in one transaction."""
    with _connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        room, role, state = _authorized(conn, token)
        p = _restore(state)
        drafts, evidence = state["drafts"], state["evidence"]
        if event == "close" and role == COORD:
            p.close()
        else:
            _assert_task(p, role, stage, address, product)
            key = _key(stage, address, product)
            lines = drafts.get(key, [])
            if event == "add":
                if not isinstance(item, Reading) or item.address != address or (product and item.product != product):
                    raise ValueError("A etiqueta não pertence ao endereço ou ao produto desta tarefa.")
                if len(lines) >= MAX_READINGS:
                    raise ValueError("Limite de lançamentos no endereço do piloto.")
                if item.label_id and any(r["label_id"] == item.label_id for r in lines):
                    raise ValueError("Este ID de etiqueta já foi registrado nesta contagem.")
                if not item.label_id and not repeat and any(
                    (r["product"], r["lot"], Decimal(r["quantity"])) == (item.product, item.lot, item.quantity)
                    for r in lines
                ):
                    raise ValueError("Leitura idêntica. Confirme que é outra etiqueta física para somar.")
                lines.append({**asdict(item), "quantity": str(item.quantity), "id": secrets.token_hex(8)})
                drafts[key] = lines
            elif event == "remove":
                if not any(r["id"] == line_id for r in lines):
                    raise ValueError("Lançamento não encontrado. Atualize o rascunho.")
                drafts[key] = [r for r in lines if r["id"] != line_id]
            elif event == "submit":
                totals = defaultdict(Decimal)
                for r in lines:
                    totals[r["product"]] += qty(r["quantity"])
                if stage == FIRST:
                    p.first(role, address, dict(totals), empty=empty, complete=complete)
                elif not complete or (empty and lines) or (not empty and not lines):
                    raise ValueError("Confirme a conferência e registre as etiquetas ou marque produto não encontrado.")
                elif stage == SECOND:
                    p.recount(role, address, product, totals[product])
                else:
                    p.audit(address, product, totals[product], note[:400], role)
                evidence[key] = lines
                drafts.pop(key, None)
            else:
                raise ValueError("Ação não reconhecida.")
        conn.execute("UPDATE annual_rooms SET state=? WHERE id=?", (_encode(_state(p, drafts, evidence)), room))
