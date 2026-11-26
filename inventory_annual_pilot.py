"""Piloto isolado: dados sintéticos e estado descartável, sem acesso externo."""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime
from zoneinfo import ZoneInfo

TEAMS = ("Dupla A", "Dupla B")
INDEPENDENT = "Conferência independente"
ELIGIBLE = ("A-01", "A-02", "B-01", "B-02")
EXCLUDED = {"X-01": "Área de produção (não apta)"}
CATALOG = {"SIM-001": ("Parafuso", Decimal("10.00")),
           "SIM-002": ("Conector", Decimal("25.00")),
           "SIM-003": ("Abraçadeira", Decimal("5.00"))}
# Saldos por endereço e saldo analítico independentes, ambos do S2 fictício.
SNAPSHOT = {"A-01": {"SIM-001": 10, "SIM-002": 5},
            "A-02": {"SIM-001": 3}, "B-01": {"SIM-003": 4},
            "B-02": {}, "X-01": {"SIM-001": 2, "SIM-002": 1}}
SYSTEM_TOTAL = {"SIM-001": 15, "SIM-002": 6, "SIM-003": 4}
FIRST = "1ª contagem"
SECOND = "2ª contagem"
AUDIT = "3ª contagem / Auditoria"
VALIDATED = "Validado"


def qty(value):
    try:
        result = Decimal(str(value).replace(",", "."))
        if not result.is_finite() or result < 0 or result > 1_000_000_000:
            raise ValueError
        return result
    except (InvalidOperation, ValueError):
        raise ValueError("Informe uma quantidade válida, maior ou igual a zero.") from None


@dataclass
class Position:
    system: Decimal
    first: Decimal
    stage: str
    second: Decimal | None = None
    final: Decimal | None = None
    decision: str = ""
    audit_note: str = ""
    auditor: str = ""


@dataclass
class AnnualPilot:
    assignment: dict = field(default_factory=dict)
    started_at: datetime | None = None
    positions: dict = field(default_factory=dict)
    closed_at: datetime | None = None
    roster: tuple = ()
    free: bool = False

    def start(self, assignment, locked, *, teams=TEAMS, free=False):
        valid = not assignment if free else set(assignment) == set(ELIGIBLE) and set(assignment.values()) == set(teams)
        if self.started_at or not locked or not valid or not teams:
            raise ValueError("Confirme o bloqueio simulado e distribua todos os endereços entre as duplas.")
        # Uma foto defensiva é copiada para a sessão; mudanças futuras às
        # constantes ou à interface não alteram o corte de uma sessão aberta.
        self.assignment = dict(assignment)
        self.roster = tuple(teams) if free else ()
        self.free = free
        self._snapshot = {a: {k: qty(v) for k, v in rows.items()} for a, rows in SNAPSHOT.items()}
        self._total = {k: qty(v) for k, v in SYSTEM_TOTAL.items()}
        self._catalog = dict(CATALOG)
        self.started_at = datetime.now(ZoneInfo("America/Sao_Paulo"))

    def _require_open(self):
        if not self.started_at or self.closed_at:
            raise ValueError("A contagem não está aberta.")

    def first(self, team, address, counts, *, empty=False, complete=False):
        self._require_open()
        if address not in self.assignment or self.assignment[address] != team or address in self.positions:
            raise ValueError("Endereço indisponível para esta dupla.")
        if not complete or (empty and counts) or (not empty and not counts):
            raise ValueError("Confirme a vistoria e registre os itens ou declare o endereço vazio.")
        if any(code not in self._catalog for code in counts):
            raise ValueError("Selecione um produto do catálogo fictício.")
        observed = {k: qty(v) for k, v in counts.items()}
        if any(v == 0 for v in observed.values()):
            raise ValueError("Registre só os produtos encontrados, com quantidade positiva.")
        expected = self._snapshot.get(address, {})
        rows = {}
        for code in sorted(expected.keys() | observed.keys()):
            system, first = expected.get(code, Decimal(0)), observed.get(code, Decimal(0))
            matches = system == first
            rows[code] = Position(system, first, VALIDATED if matches else SECOND,
                                  final=first if matches else None,
                                  decision="1ª confirma o sistema" if matches else "")
        self.positions[address] = rows

    @property
    def teams(self):
        return self.roster or tuple(sorted(set(self.assignment.values())))

    def recount_owner(self, address):
        first_team = self.assignment[address]
        teams = self.teams
        if len(teams) == 1:
            return INDEPENDENT
        return teams[(teams.index(first_team) + 1) % len(teams)]

    def queue(self, team):
        return [(a, k) for a, rows in self.positions.items() if self.recount_owner(a) == team
                for k, row in rows.items() if row.stage == SECOND]

    def recount(self, team, address, code, value):
        self._require_open()
        if (address, code) not in self.queue(team):
            raise ValueError("A recontagem cabe à equipe ou conferente independente designado.")
        row = self.positions[address][code]
        second = qty(value)
        row.second = second
        if second in (row.first, row.system):
            row.final = second
            row.stage = VALIDATED
            row.decision = "2ª confirma a 1ª" if second == row.first else "2ª confirma o sistema"
        else:
            row.stage = AUDIT

    def audit_queue(self):
        return [(a, k) for a, rows in self.positions.items() for k, row in rows.items() if row.stage == AUDIT]

    def audit(self, address, code, value, note, actor):
        self._require_open()
        if (address, code) not in self.audit_queue() or not note.strip() or not actor.strip():
            raise ValueError("Informe a contagem final e justifique a decisão da auditoria.")
        row = self.positions[address][code]
        row.final = qty(value)
        row.audit_note = note.strip()
        row.auditor = actor.strip()
        row.stage = VALIDATED
        row.decision = "Validado pela auditoria"

    def address_status(self, address):
        if address not in self.positions:
            return FIRST
        states = {row.stage for row in self.positions[address].values()}
        if SECOND in states:
            return SECOND
        if AUDIT in states:
            return AUDIT
        return VALIDATED

    def ready(self):
        return bool(self.started_at and all(self.address_status(a) == VALIDATED for a in set(ELIGIBLE) | self.assignment.keys()))

    def close(self):
        self._require_open()
        if not self.ready():
            raise ValueError("Conclua todos os endereços, recontagens e auditorias antes do fechamento.")
        self.closed_at = datetime.now(ZoneInfo("America/Sao_Paulo"))

    def totals(self):
        if not self.closed_at:
            raise ValueError("Feche o piloto para apurar as diferenças.")
        totals = []
        for code, (description, cost) in self._catalog.items():
            counted = sum((rows[code].final for rows in self.positions.values() if code in rows), Decimal(0))
            excluded = sum((self._snapshot[a].get(code, Decimal(0)) for a in EXCLUDED), Decimal(0))
            adjusted = counted + excluded
            system = self._total.get(code, Decimal(0))
            delta = adjusted - system
            totals.append((code, description, counted, excluded, adjusted, system, delta,
                           (delta * cost).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)))
        return totals

    def discrepancies(self):
        if not self.closed_at:
            raise ValueError("Feche o piloto para apurar as diferenças.")
        return [(a, code, row.system, row.final, row.final - row.system, row.decision, row.audit_note, row.first, row.second, row.auditor)
                for a, rows in sorted(self.positions.items()) for code, row in rows.items()
                if row.second is not None or row.audit_note]
