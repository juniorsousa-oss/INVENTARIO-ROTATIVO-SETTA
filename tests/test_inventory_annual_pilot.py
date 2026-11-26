import unittest
from unittest.mock import patch
from decimal import Decimal

from inventory_annual_pilot import AnnualPilot, ELIGIBLE, FIRST, SECOND, AUDIT, VALIDATED, qty


ASSIGNED = {a: "Dupla A" if i < 2 else "Dupla B" for i, a in enumerate(ELIGIBLE)}


class AnnualPilotTests(unittest.TestCase):
    def setUp(self):
        self.pilot = AnnualPilot()

    def finish_first(self):
        p = self.pilot
        p.first("Dupla A", "A-01", {"SIM-001": 8, "SIM-002": 3}, complete=True)
        p.first("Dupla A", "A-02", {"SIM-001": 5, "SIM-002": 4}, complete=True)
        p.first("Dupla B", "B-01", {"SIM-003": 4}, complete=True)
        p.first("Dupla B", "B-02", {}, empty=True, complete=True)

    def test_requires_lock_and_complete_mapping(self):
        for mapping, locked in ((ASSIGNED, False), ({"A-01": "Dupla A"}, True),
                                ({**ASSIGNED, "X-01": "Dupla A"}, True),
                                (dict.fromkeys(ELIGIBLE, "Dupla A"), True)):
            with self.assertRaises(ValueError):
                self.pilot.start(mapping, locked)
        self.pilot.start(ASSIGNED, True)
        with self.assertRaises(ValueError):
            self.pilot.start(ASSIGNED, True)

    def test_requires_team_and_explicit_delivery(self):
        p = self.pilot
        p.start(ASSIGNED, True)
        for team, address, rows, empty, complete in (
            ("Dupla B", "A-01", {"SIM-001": 1}, False, True),
            ("Dupla A", "X-01", {"SIM-001": 1}, False, True),
            ("Dupla A", "A-01", {}, False, True),
            ("Dupla A", "A-01", {}, True, False),
            ("Dupla A", "A-01", {"SIM-001": 1}, True, True),
            ("Dupla A", "A-01", {"SIM-001": 0}, False, True),
        ):
            with self.assertRaises(ValueError):
                p.first(team, address, rows, empty=empty, complete=complete)
        self.assertEqual(p.address_status("A-01"), FIRST)
        self.assertEqual(p.positions, {})

    def test_full_flow_freezes_basis_offsets_addresses_and_audits(self):
        p = self.pilot
        p.start(ASSIGNED, True)
        with patch("inventory_annual_pilot.SNAPSHOT", {}), patch("inventory_annual_pilot.SYSTEM_TOTAL", {}):
            self.finish_first()
            self.assertEqual(p.address_status("B-01"), VALIDATED)
            self.assertEqual(p.address_status("B-02"), VALIDATED)
            self.assertEqual(p.address_status("A-01"), SECOND)
            self.assertEqual(p.queue("Dupla A"), [])
            with self.assertRaises(ValueError):
                p.recount("Dupla A", "A-01", "SIM-001", 8)
            with self.assertRaises(ValueError):
                p.close()
            p.recount("Dupla B", "A-01", "SIM-001", 8)
            p.recount("Dupla B", "A-01", "SIM-002", 5)
            p.recount("Dupla B", "A-02", "SIM-001", 5)
            p.recount("Dupla B", "A-02", "SIM-002", 2)
            self.assertEqual(p.address_status("A-02"), AUDIT)
            with self.assertRaises(ValueError):
                p.audit("A-02", "SIM-002", 1, "  ", "Auditoria")
            p.audit("A-02", "SIM-002", "1,5", "Conferido no endereço.", "Auditoria")
            p.close()
            per_code = {r[0]: r for r in p.totals()}
            self.assertEqual(per_code["SIM-001"][2:], (13, 2, 15, 15, 0, 0))
            self.assertEqual(per_code["SIM-002"][2:], (Decimal("6.5"), 1, Decimal("7.5"), 6, Decimal("1.5"), Decimal("37.50")))
            self.assertEqual([(r[0], r[1], r[4]) for r in p.discrepancies()],
                             [("A-01", "SIM-001", -2), ("A-01", "SIM-002", 0), ("A-02", "SIM-001", 2), ("A-02", "SIM-002", Decimal("1.5"))])
        with self.assertRaises(ValueError):
            p.close()

    def test_missing_expected_stock_routes_to_recount_as_zero(self):
        p = self.pilot
        p.start(ASSIGNED, True)
        p.first("Dupla A", "A-01", {}, empty=True, complete=True)
        self.assertEqual(p.positions["A-01"]["SIM-001"].first, 0)
        p.recount("Dupla B", "A-01", "SIM-001", 0)
        self.assertEqual(p.positions["A-01"]["SIM-001"].final, 0)

    def test_independent_sessions_and_invalid_amounts(self):
        self.pilot.start(ASSIGNED, True)
        p2 = AnnualPilot()
        self.assertIsNone(p2.started_at)
        for value in (None, "nan", "inf", -1, "", "  ", 1_000_000_001):
            with self.assertRaises(ValueError):
                qty(value)
