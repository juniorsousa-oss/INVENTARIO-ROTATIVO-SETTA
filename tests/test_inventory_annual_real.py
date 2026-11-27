from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import pandas as pd

import inventory_annual_rooms as room
from inventory_annual_pilot import FIRST
from inventory_annual_real import sample


class AnnualRealTests(TestCase):
    def setUp(self):
        self.end = pd.DataFrame([
            ("00203040", "S2", "R-001", "000023", 2),
            ("00203040", "S2", "R-001", "000023", 3),
            ("00203040", "S2", "R-001", "", 1),
            ("00203040", "S2", "R-005", "000044", 8),
            ("00203040", "S2", "BLOQ", "", 3),
            ("00203040", "E2", "R-003", "", 7),
        ], columns=["Produto", "Armazem", "Endereco", "Lote", "Quantidade"])
        self.analytic = pd.DataFrame([
            ("00203040", "S2", "Material A", 17, "25,50"),
            ("00800000", "S2", "Material B", 8, 24),
            ("00203040", "E2", "Não é esta descrição", 7, 77),
        ], columns=["CODIGO", "ARMZ", "DESCRICAO", "SALDO EM ESTOQUE", "VALOR EM ESTOQUE"])

    def test_scoped_cut_sums_repeated_lot_and_accepts_a_lotless_position(self):
        cut = sample(self.end, self.analytic, "r – 001\nR-001", excluded=["BLOQ"])
        self.assertEqual(set(cut.addresses), {"R-001"})
        self.assertEqual(cut.totals, {"00203040": Decimal(6)})
        self.assertEqual(cut.lots["R-001"]["00203040"], {"000023": Decimal(5), "SEM-LOTE": Decimal(1)})
        self.assertEqual(cut.catalog["00203040"], ("Material A", Decimal("1.5")))

    def test_nonexistent_wrong_warehouse_and_excluded_rejected(self):
        for address in ("Z-001", "R-003", "BLOQ"):
            with self.subTest(address=address), self.assertRaisesRegex(ValueError, "não apto"):
                sample(self.end, self.analytic, address, excluded=["BLOQ"])

    def test_negative_cut_is_not_silently_ignored(self):
        self.end.loc[0, "Quantidade"] = -2
        with self.assertRaisesRegex(ValueError, "saldo negativo"):
            sample(self.end, self.analytic, "R-001")

    def test_real_room_not_published_or_readable_anonymously_and_preserves_blind_flow(self):
        cut = sample(self.end, self.analytic, "R-001")
        with TemporaryDirectory() as td:
            path = Path(td) / "rooms.sqlite3"
            key = room.create_room({}, True, mode=room.INDIVIDUAL, people=1,
                                   participants="Validação", sample=cut, path=path)
            rid = room.view(key, path=path)["room_id"]
            manager = room.RoomAccess(rid, room.COORD, True)
            guest = room.RoomAccess(rid, "EQ-000001")
            operator = room.RoomAccess(rid, "EQ-000001", True)
            self.assertEqual(room.list_rooms(path=path), [])
            with self.assertRaisesRegex(ValueError, "privada"):
                room.action(manager, "publish", path=path)
            with self.assertRaises(ValueError):
                room.view(guest, path=path)
            with self.assertRaises(ValueError):
                room.view(room.worker_codes(key, ("EQ-000001",))["EQ-000001"], path=path)
            current = room.view(operator, path=path)
            self.assertNotIn("pilot", current)
            self.assertEqual(current["catalog"]["00203040"], "Material A")
            room.action(operator, "open", address="R-001", path=path)
            for lot, qty in [("000023", 5), ("", 1)]:
                item = room.reading("00203040", "R-001", lot, qty, catalog=current["catalog"])
                room.action(operator, "add", FIRST, "R-001", item=item, path=path)
            room.action(operator, "submit", FIRST, "R-001", complete=True, path=path)
            room.action(manager, "close", path=path)
            (result,) = room.view(manager, path=path)["pilot"].totals()
            self.assertEqual(result[2:], (6, 0, 6, 6, 0, 0))

    def test_real_catalog_does_not_apply_demo_aliases(self):
        self.assertEqual(room.resolve_product("00000001"), "SIM-001")
        with self.assertRaisesRegex(ValueError, "não encontrado"):
            room.resolve_product("00000001", {"SIM-001": "Real code"})
