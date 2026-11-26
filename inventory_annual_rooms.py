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
import unicodedata

from inventory_annual_pilot import (
    AUDIT, FIRST, SECOND, CATALOG, ELIGIBLE, EXCLUDED, TEAMS, INDEPENDENT, AnnualPilot, Position, qty,
)

COORD = "Coordenação"
AUDITOR = "Auditoria"
TITLE = "Inventário anual S2"
EXTRA = "Conferência extra"
INDIVIDUAL = "Individual"
PAIRS = "Em duplas"
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


def normalize_address(value):
    text = unicodedata.normalize("NFKC", str(value or "")).upper()
    text = re.sub(r"[‐‑‒–—−]", "-", text)
    text = re.sub(r"\s*([-./])\s*", r"\1", " ".join(text.split()))
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9 ._/-]{0,59}", text):
        raise ValueError("Informe um endereço válido do S2.")
    if text in EXCLUDED:
        raise ValueError("Este endereço não é apto para contagem no S2.")
    return text


def reading(product, address, lot, amount, label_id=""):
    product, address, lot, label_id = (v.strip().upper() for v in (product, address, lot, label_id))
    product = DEMO_PRODUCTS.get(product, product)
    if product not in CATALOG:
        raise ValueError("Produto não encontrado no catálogo fictício.")
    address = normalize_address(address)
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


def worker_roles(teams):
    return (*teams, *((INDEPENDENT,) if len(teams) == 1 else ()), AUDITOR)


def worker_codes(coordinator_code, teams=TEAMS):
    return {role: hmac_new(coordinator_code.encode("ascii"), role.encode(), sha256).hexdigest()[:32]
            for role in worker_roles(teams)}


def _state(pilot, drafts=None, evidence=None, *, info=None, extras=None):
    return {"assignment": pilot.assignment, "started": pilot.started_at.isoformat(),
            "closed": pilot.closed_at.isoformat() if pilot.closed_at else None,
            "snapshot": pilot._snapshot, "system": pilot._total, "catalog": pilot._catalog,
            "positions": {a: {k: asdict(row) for k, row in rows.items()} for a, rows in pilot.positions.items()},
            "drafts": drafts or {}, "evidence": evidence or {}, "info": info or {},
            "free": pilot.free, "roster": pilot.roster, "extras": extras or {}}


def team_ids(people):
    if type(people) is not int or not 2 <= people <= len(ELIGIBLE) * 2 or people % 2:
        raise ValueError("Escolha um total par de 2 a 8 pessoas para formar as duplas do piloto.")
    return tuple(f"EQ-{i:02}" for i in range(1, people // 2 + 1))


def _label(value, name):
    value = " ".join(str(value or "").split())
    if not value or len(value) > 60:
        raise ValueError(f"Preencha {name} (até 60 caracteres).")
    return value


def validate_teams(teams, people, title):
    ids = team_ids(people)
    if not isinstance(teams, dict) or set(teams) != set(ids):
        raise ValueError("Defina uma equipe para cada dupla de contagem.")
    names, members = set(), set()
    out = {}
    for idx in ids:
        row = teams[idx]
        name = _label(row.get("name"), "o nome de cada equipe")
        head = _label(row.get("lead"), "o nome do cabeça de chave")
        assistant = _label(row.get("assistant"), "o nome do auxiliar")
        members.update((head.casefold(), assistant.casefold()))
        names.add(name.casefold())
        out[idx] = {"name": name, "lead": head, "assistant": assistant}
    if len(names) != len(ids):
        raise ValueError("Cada equipe precisa ter um nome diferente.")
    if len(members) != people:
        raise ValueError("Cada pessoa só pode participar de uma dupla, em uma função.")
    return {"title": _label(title, "o nome do inventário"), "teams": out}


def _restore(state):
    def dec(v):
        return Decimal(v) if v is not None else None
    p = AnnualPilot(assignment=state["assignment"], started_at=datetime.fromisoformat(state["started"]),
                    closed_at=datetime.fromisoformat(state["closed"]) if state["closed"] else None,
                    free=state.get("free", False), roster=tuple(state.get("roster", ())))
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


def formation(people, mode, participants, title):
    if type(people) is not int or people < 1 or mode not in (INDIVIDUAL, PAIRS):
        raise ValueError("Informe a quantidade de pessoas e o modo de contagem.")
    names = [_label(line, "o nome de cada participante") for line in participants.splitlines() if line.strip()]
    if len(names) != people:
        raise ValueError(f"Informe um nome por linha. Quantidade esperada: {people}; informada: {len(names)}.")
    if len(set(n.casefold() for n in names)) != people:
        raise ValueError("Cada participante só pode aparecer uma vez.")
    size = 1 if mode == INDIVIDUAL else 2
    teams = {}
    for i in range(0, people, size):
        lead = names[i]
        assistant = names[i+1] if size == 2 and i+1 < people else ""
        teams[f"EQ-{i//size+1:06}"] = {"name": f"{lead} / {assistant}" if assistant else lead,
                                     "lead": lead, "assistant": assistant}
    return {"title": _label(title, "o nome do inventário"), "teams": teams, "mode": mode}


def create_room(assignment, locked, *, teams=None, people=None, title=TITLE, mode=None, participants="", path=PATH):
    info = formation(people, mode, participants, title) if mode else (validate_teams(teams, people, title) if teams is not None else {})
    p = AnnualPilot()
    p.start(assignment, locked, teams=tuple(info["teams"]) if info else TEAMS, free=mode is not None)
    token = secrets.token_urlsafe(24)
    room = secrets.token_hex(8)
    now = int(time.time())
    with _connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM annual_rooms WHERE expires <= ?", (now,))
        if conn.execute("SELECT COUNT(*) FROM annual_rooms").fetchone()[0] >= MAX_ROOMS:
            raise ValueError("Limite de pilotos em uso. Entre em um piloto existente.")
        conn.execute("INSERT INTO annual_rooms VALUES (?,?,?)", (room, now + TTL, _encode(_state(p, info=info))))
        keys = {COORD: token, **worker_codes(token, p.teams)}
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


class AddressConflict(ValueError):
    def __init__(self, owner, name, submitted):
        self.owner = owner
        self.name = name
        self.submitted = submitted
        state = "já foi contado e enviado" if submitted else "já está em contagem"
        super().__init__(f"Este endereço {state} pela equipe {name}.")


def _assert_task(pilot, role, stage, address, product, extras):
    pilot._require_open()
    if stage == FIRST and role in pilot.teams and pilot.assignment.get(address) == role and address not in pilot.positions and product == "":
        return
    if stage == SECOND and (address, product) in pilot.queue(role):
        return
    if stage == AUDIT and role == AUDITOR and (address, product) in pilot.audit_queue():
        return
    if stage == EXTRA and role in pilot.teams and not product and extras.get(address, {}).get(role) == "open":
        return
    raise ValueError("Esta tarefa não está disponível para o seu papel. Atualize a fila.")


def task_key(stage, address, product, role):
    return _key(stage, address, role if stage == EXTRA else product)


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
        room_id, role, state = _authorized(conn, token)
    p = _restore(state)
    info = state.get("info") or {}
    teams = info.get("teams") or {idx: {"name": idx, "lead": "", "assistant": ""} for idx in p.teams}
    display = teams.get(role, {}).get("name", role)
    common = {"role": role, "closed": bool(p.closed_at), "display": display, "title": info.get("title", TITLE),
              "room_id": room_id, "free": p.free}
    extras = state.get("extras") or {}
    if role == COORD:
        queue = []
        if p.free:
            queue.extend((a, "", FIRST, "Ainda não iniciado", False) for a in ELIGIBLE if a not in p.assignment)
        for a, team in p.assignment.items():
            status = p.address_status(a)
            if status == FIRST:
                queue.append((a, "", FIRST, team, bool(state["drafts"].get(_key(FIRST, a)))))
            for code, pos in p.positions.get(a, {}).items():
                if pos.stage in (SECOND, AUDIT):
                    responsible = p.recount_owner(a) if pos.stage == SECOND else AUDITOR
                    queue.append((a, code, pos.stage, responsible, bool(state["drafts"].get(_key(pos.stage, a, code)))))
        extra_report = []
        for address, actions in extras.items():
            for team, status in actions.items():
                key = task_key(EXTRA,address,"",team)
                rows = state["evidence"].get(key, [])
                extra_report.append((address, team, status, grouped(rows)))
        final = {key: lines for key, lines in state["evidence"].items() if not key.startswith(EXTRA + "|")}
        return {**common, "pilot": p, "teams": teams, "queue": queue, "extras": extra_report,
                "evidence": _draft_details(final) if p.closed_at else {}}
    tasks = {}
    if not p.closed_at:
        if role in p.teams:
            tasks[FIRST] = [(a, "") for a, owner in sorted(p.assignment.items()) if owner == role and a not in p.positions]
            tasks[SECOND] = p.queue(role)
            if p.free:
                tasks[EXTRA] = [(a,"") for a, attempts in sorted(extras.items()) if attempts.get(role) == "open"]
        elif role == INDEPENDENT:
            tasks[SECOND] = p.queue(role)
        else:
            tasks[AUDIT] = p.audit_queue()
    own = {task_key(stage, a, c, role): state["drafts"].get(task_key(stage, a, c, role), [])
           for stage, pairs in tasks.items() for a, c in pairs}
    return {**common, "tasks": tasks, "drafts": own}


def draft_version(lines):
    return sha256(_encode(lines).encode()).hexdigest()


def action(token, event, stage="", address="", product="", *, item=None, repeat=False, line_id="",
           empty=False, complete=False, note="", expected=None, confirm_owner="", path=PATH):
    """Recheck permissions and mutate the freshest room in one transaction."""
    with _connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        room, role, state = _authorized(conn, token)
        p = _restore(state)
        drafts, evidence = state["drafts"], state["evidence"]
        extras = state.get("extras") or {}
        result = None
        if event == "open":
            p._require_open()
            if not p.free or role not in p.teams:
                raise ValueError("Somente a equipe de contagem pode iniciar um endereço.")
            address = normalize_address(address)
            owner = p.assignment.get(address)
            if owner is None:
                p.assignment[address] = role
                result = (FIRST, address)
            elif owner == role:
                if address in p.positions:
                    raise ValueError("Seu endereço já foi enviado para conferência e não pode ser editado.")
                result = (FIRST, address)
            elif extras.get(address, {}).get(role) == "open":
                result = (EXTRA, address)
            elif extras.get(address, {}).get(role) == "submitted":
                raise ValueError("Sua equipe já enviou uma conferência extra neste endereço.")
            elif confirm_owner == owner:
                extras.setdefault(address, {})[role] = "open"
                result = (EXTRA, address)
            else:
                name = (state.get("info", {}).get("teams") or {}).get(owner, {}).get("name", owner)
                raise AddressConflict(owner, name, address in p.positions)
        elif event == "close" and role == COORD:
            p.close()
        else:
            _assert_task(p, role, stage, address, product, extras)
            key = task_key(stage, address, product, role)
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
                old = next((r for r in lines if r["id"] == line_id), None)
                if old is None or (expected is not None and expected != old):
                    raise ValueError("O rascunho mudou em outro aparelho. Atualize e confira antes de remover.")
                drafts[key] = [r for r in lines if r["id"] != line_id]
            elif event == "edit":
                if not isinstance(item, Reading) or item.address != address or (product and item.product != product):
                    raise ValueError("Mantenha o endereço e o produto da tarefa de recontagem.")
                index = next((i for i, row in enumerate(lines) if row["id"] == line_id), None)
                if index is None or lines[index] != expected:
                    raise ValueError("O rascunho mudou em outro aparelho. Atualize e confira antes de editar.")
                lines[index] = {**asdict(item), "quantity": str(item.quantity), "id": line_id}
                drafts[key] = lines
            elif event == "submit":
                if expected is not None and expected != draft_version(lines):
                    raise ValueError("O rascunho mudou em outro aparelho. Atualize e confira antes de enviar.")
                totals = defaultdict(Decimal)
                for r in lines:
                    totals[r["product"]] += qty(r["quantity"])
                if stage == FIRST:
                    p.first(role, address, dict(totals), empty=empty, complete=complete)
                elif not complete or (empty and lines) or (not empty and not lines):
                    raise ValueError("Confirme a conferência e registre as etiquetas ou marque produto não encontrado.")
                elif stage == EXTRA:
                    extras[address][role] = "submitted"
                elif stage == SECOND:
                    p.recount(role, address, product, totals[product])
                else:
                    p.audit(address, product, totals[product], note[:400], role)
                evidence[key] = lines
                drafts.pop(key, None)
            else:
                raise ValueError("Ação não reconhecida.")
        conn.execute("UPDATE annual_rooms SET state=? WHERE id=?", (_encode(_state(p, drafts, evidence, info=state.get("info"), extras=extras)), room))
    return result
