import unittest
from unittest.mock import patch

import pandas as pd

from inventory_annual_addresses import address_book_from_report, pilot_address_report
from inventory_annual_pilot import AnnualPilot, EXCLUDED


class AnnualAddressTests(unittest.TestCase):
    def test_endereco_is_source_of_truth_including_reported_zero(self):
        catalog = address_book_from_report(pilot_address_report(), excluded=EXCLUDED)
        self.assertEqual(list(catalog), ["A-01", "A-02", "B-01", "B-02", "E2-01", "X-01"])
        self.assertEqual(catalog["B-02"], ("S2", True))
        self.assertEqual(catalog["X-01"], ("S2", False))
        self.assertEqual(catalog["E2-01"], ("E2", False))
        self.assertNotIn("A-99", catalog)

    def test_missing_or_mixed_warehouse_evidence_never_promotes_address(self):
        report = pd.DataFrame(
            [["00000001", "A-01", 0], ["00000002", "A-02", 4],
             ["00000001", "B-01", 5], ["00000002", "B-01", 5],
             ["00000004", "C-01", 5]],
            columns=["COD", "Endereço", "Quantidade"])
        analytic = pd.DataFrame(
            [["00000001", "S2"], ["00000002", "S2"], ["00000002", "E2"]],
            columns=["COD", "ARMZ"])
        with self.assertRaisesRegex(ValueError, "nenhum endereço apto"):
            address_book_from_report(report)
        result = address_book_from_report(report, analytic=analytic)
        self.assertEqual(result["A-01"], ("S2", True))
        self.assertEqual({result[a] for a in ("A-02", "B-01", "C-01")}, {("INDEFINIDO", False)})
        explicit = pilot_address_report()
        explicit.loc[len(explicit.index)] = ["00000002", "E2", "A-01", 5]
        self.assertEqual(address_book_from_report(explicit)["A-01"], ("INDEFINIDO", False))

    def test_freezes_report_once_for_open_pilot(self):
        p = AnnualPilot()
        p.start({}, True, free=True, checked=True)
        with patch("inventory_annual_pilot.pilot_address_report", side_effect=AssertionError):
            self.assertEqual(p.eligible_addresses(), ("A-01", "A-02", "B-01", "B-02"))
            p.validate_address("B-02")
            with self.assertRaisesRegex(ValueError, "não encontrado"):
                p.validate_address("A-99")
