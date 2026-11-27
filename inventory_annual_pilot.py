"""Piloto isolado: dados sintéticos e estado descartável, sem acesso externo."""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime
from zoneinfo import ZoneInfo

from inventory_annual_addresses import address_book_from_report, pilot_address_report

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
# Cadastro e detalhe de lotes fictícios, separados do Analítico.
TRACKED = {"SIM-001"}
LOT_SNAPSHOT = {
    "A-01": {"SIM-001": {"000101": 6, "000102": 4}},
    "A-02": {"SIM-001": {"000101": 3}},
}
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
    system_lots: dict | None = None
    first_lots: dict | None = None
    second_lots: dict | None = None
    final_lots: dict | None = None


@dataclass
class AnnualPilot:
    assignment: dict = field(default_factory=dict)
    started_at: datetime | None = None
    positions: dict = field(default_factory=dict)
    closed_at: datetime | None = None
    roster: tuple = ()
    free: bool = False
    address_book: dict = field(default_factory=dict)
    tracked: set = field(default_factory=set)
    lot_snapshot: dict = field(default_factory=dict)

    def start(self, assignment, locked, *, teams=TEAMS, free=False, checked=False):
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
        if checked:
            self.address_book = address_book_from_report(pilot_address_report(), excluded=EXCLUDED)
            self.tracked = set(TRACKED)
            self.lot_snapshot = {a: {k: {lot: qty(q) for lot, q in values.items()} for k, values in products.items()}
                                 for a, products in LOT_SNAPSHOT.items()}
            for a in ELIGIBLE:
                for k in self.tracked:
                    if sum(self.lot_snapshot.get(a, {}).get(k, {}).values(), Decimal(0)) != self._snapshot[a].get(k, 0):
                        raise ValueError("A base de lotes do piloto não fecha com os saldos por endereço.")
        self.started_at = datetime.now(ZoneInfo("America/Sao_Paulo"))

    def _require_open(self):
        if not self.started_at or self.closed_at:
            raise ValueError("A contagem não está aberta.")

    def validate_address(self, address):
        if not self.address_book:  # sessões anteriores conservam a base de corte
            return
        data = self.address_book.get(address)
        if data is None:
            raise ValueError("Endereço não encontrado no cadastro do piloto. Confira o código digitado.")
        warehouse, eligible = data
        if warehouse == "INDEFINIDO":
            raise ValueError("Não foi possível confirmar este endereço no estoque.")
        if warehouse != "S2":
            raise ValueError("Este endereço pertence a outro armazém e não entra na contagem do estoque.")
        if not eligible:
            raise ValueError("Este endereço não é apto para contagem.")

    def eligible_addresses(self):
        if self.address_book:
            return tuple(sorted(a for a, (warehouse, eligible) in self.address_book.items()
                                if warehouse == "S2" and eligible))
        return ELIGIBLE

    def _lots(self, product, value, distribution):
        if product not in self.tracked:
            return None
        result = {str(lot): qty(amount) for lot, amount in (distribution or {}).items()}
        result = {lot: amount for lot, amount in result.items() if amount > 0}
        if any(not lot for lot in result) or sum(result.values(), Decimal(0)) != value:
            raise ValueError("A soma dos lotes precisa corresponder à quantidade contada do produto.")
        return result

    def first(self, team, address, counts, *, empty=False, complete=False, by_lot=None):
        self._require_open()
        if address not in self.assignment or self.assignment[address] != team or address in self.positions:
            raise ValueError("Endereço indisponível para esta dupla.")
        self.validate_address(address)
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
            expected_lots = (self.lot_snapshot.get(address, {}).get(code, {}) if code in self.tracked else None)
            first_lots = self._lots(code, first, (by_lot or {}).get(code))
            matches = system == first and expected_lots == first_lots
            rows[code] = Position(system, first, VALIDATED if matches else SECOND,
                                  final=first if matches else None,
                                  decision="1ª confirma o sistema" if matches else "",
                                  system_lots=expected_lots, first_lots=first_lots,
                                  final_lots=first_lots if matches else None)
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

    def recount(self, team, address, code, value, *, by_lot=None):
        self._require_open()
        if (address, code) not in self.queue(team):
            raise ValueError("A recontagem cabe à equipe ou conferente independente designado.")
        row = self.positions[address][code]
        second = qty(value)
        second_lots = self._lots(code, second, by_lot)
        row.second = second
        row.second_lots = second_lots
        confirms_first = second == row.first and second_lots == row.first_lots
        confirms_system = second == row.system and second_lots == row.system_lots
        if confirms_first or confirms_system:
            row.final = second
            row.final_lots = second_lots
            row.stage = VALIDATED
            row.decision = "2ª confirma a 1ª" if confirms_first else "2ª confirma o sistema"
        else:
            row.stage = AUDIT

    def audit_queue(self):
        return [(a, k) for a, rows in self.positions.items() for k, row in rows.items() if row.stage == AUDIT]

    def audit(self, address, code, value, note, actor, *, by_lot=None):
        self._require_open()
        if (address, code) not in self.audit_queue() or not note.strip() or not actor.strip():
            raise ValueError("Informe a contagem final e justifique a decisão da auditoria.")
        row = self.positions[address][code]
        final = qty(value)
        row.final_lots = self._lots(code, final, by_lot)
        row.final = final
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
        return bool(self.started_at and all(self.address_status(a) == VALIDATED for a in set(self.eligible_addresses()) | self.assignment.keys()))

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

    def lot_discrepancies(self):
        if not self.closed_at:
            raise ValueError("Feche o piloto para apurar as diferenças.")
        rows = []
        for address, products in sorted(self.positions.items()):
            for code, row in sorted(products.items()):
                if row.system_lots is None:
                    continue
                maps = (row.system_lots, row.first_lots, row.second_lots, row.final_lots)
                for lot in sorted(set().union(*(m or {} for m in maps))):
                    system, first, second, final = (m.get(lot, Decimal(0)) if m is not None else None for m in maps)
                    if any(v != system for v in (first, second, final) if v is not None):
                        rows.append((address, code, lot, system, first, second, final, final - system))
        return rows
