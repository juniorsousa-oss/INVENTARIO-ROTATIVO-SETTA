import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from inventory_annual_pilot import AUDIT, FIRST, SECOND, ELIGIBLE, TEAMS
import inventory_annual_rooms as r


class AnnualRoomsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "annual.sqlite3"
        self.assignment = {a: TEAMS[i // 2] for i, a in enumerate(ELIGIBLE)}
        self.key = r.create_room(self.assignment, True, path=self.path)
        self.codes = r.worker_codes(self.key)
        self.a, self.b = (self.codes[t] for t in TEAMS)
        self.audit = self.codes[r.AUDITOR]

    def view(self, token):
        return r.view(token, path=self.path)

    def act(self, token, event, stage="", address="", product="", **kw):
        return r.action(token, event, stage, address, product, path=self.path, **kw)

    def qr(self, key, stage, a, product, text, **kwargs):
        self.act(key, "add", stage, a, product, item=r.parse_demo_label(text, a), **kwargs)

    def test_label_format_zeroes_address_from_task_and_legacy_line(self):
        read = r.parse_demo_label("00000001,000101,3\r\n", "A-01")
        self.assertEqual((read.product, read.lot, read.quantity, read.address), ("SIM-001", "000101", 3, "A-01"))
        self.assertEqual(r.reading("00000002", "A-01", "000000000", "1,5").quantity, Decimal("1.5"))
        self.assertEqual(r.parse_demo_label("00000001,000101,3,5", "A-02").quantity, Decimal("3.5"))
        for text in ("00000001|000101|3", "00000001,000101,3,A01", "00000001,000101,0",
                     "00000001,000101,-1", "00006999,000101,3", "00000001,,1", "00000001,L1,NaN"):
            with self.assertRaises(ValueError, msg=text):
                r.parse_demo_label(text, "A-01")
        with self.assertRaises(ValueError):
            self.act(self.a, "add", FIRST, "A-02", item=read)

    def test_grouping_duplicates_removal_and_role_isolation(self):
        self.qr(self.a, FIRST, "A-01", "", "00000001,000101,3")
        self.qr(self.a, FIRST, "A-01", "", "00000001,000101,2")
        with self.assertRaisesRegex(ValueError, "Leitura idêntica"):
            self.qr(self.a, FIRST, "A-01", "", "00000001,000101,3")
        self.qr(self.a, FIRST, "A-01", "", "00000001,000101,3", repeat=True)
        self.qr(self.a, FIRST, "A-01", "", "00000001,000102,2.5")
        current = self.view(self.a)
        key = r._key(FIRST, "A-01")
        lines = current["drafts"][key]
        self.assertEqual([row["Quantidade"] for row in r.grouped(lines)], [8, Decimal("2.5")])
        self.assertNotIn("pilot", current)
        self.assertNotIn(key, self.view(self.b)["drafts"])
        self.assertNotIn(key, self.view(self.audit)["drafts"])
        self.assertIn(("A-01", "", FIRST, TEAMS[0], True), self.view(self.key)["queue"])
        with self.assertRaises(ValueError):
            self.act(self.b, "remove", FIRST, "A-01", line_id=lines[0]["id"])
        with self.assertRaises(ValueError):
            self.act(self.a, "close")
        self.act(self.a, "remove", FIRST, "A-01", line_id=lines[1]["id"])
        self.assertEqual([row["Quantidade"] for row in r.grouped(self.view(self.a)["drafts"][key])], [6, Decimal("2.5")])

    def test_separate_rooms_and_simultaneous_saves(self):
        other = r.create_room(self.assignment, True, path=self.path)
        other_a = r.worker_codes(other)[TEAMS[0]]
        tasks = [(self.a, "A-01", "00000001,000101,1"), (self.b, "B-01", "00000003,000303,2"),
                 (self.a, "A-01", "00000001,000101,4")]
        with ThreadPoolExecutor(3) as ex:
            list(ex.map(lambda work: self.qr(work[0], FIRST, work[1], "", work[2]), tasks))
        self.assertEqual(r.grouped(self.view(self.a)["drafts"][r._key(FIRST, "A-01")])[0]["Quantidade"], 5)
        self.assertEqual(r.grouped(self.view(self.b)["drafts"][r._key(FIRST, "B-01")])[0]["Quantidade"], 2)
        self.assertEqual(self.view(other_a)["drafts"][r._key(FIRST, "A-01")], [])

    def test_full_flow_queue_changes_responsibility_keeps_lots_and_earlier_counts_blind(self):
        self.qr(self.a, FIRST, "A-01", "", "00000001,L1,3")
        self.qr(self.a, FIRST, "A-01", "", "00000001,L1,2")
        self.qr(self.a, FIRST, "A-01", "", "00000001,L2,4")
        self.qr(self.a, FIRST, "A-01", "", "00000002,L3,5")
        with self.assertRaises(ValueError):
            self.act(self.key, "close")
        self.act(self.a, "submit", FIRST, "A-01", complete=True)
        self.assertIn(("A-01", "SIM-001", SECOND, TEAMS[1], False), self.view(self.key)["queue"])
        self.assertEqual(self.view(self.b)["drafts"][r._key(SECOND, "A-01", "SIM-001")], [])
        self.qr(self.b, SECOND, "A-01", "SIM-001", "00000001,L1,8")
        self.act(self.b, "submit", SECOND, "A-01", "SIM-001", complete=True)
        self.assertIn(("A-01", "SIM-001", AUDIT, r.AUDITOR, False), self.view(self.key)["queue"])
        self.qr(self.audit, AUDIT, "A-01", "SIM-001", "00000001,L1,5")
        self.qr(self.audit, AUDIT, "A-01", "SIM-001", "00000001,L2,4")
        with self.assertRaises(ValueError):
            self.act(self.audit, "submit", AUDIT, "A-01", "SIM-001", complete=True)
        self.act(self.audit, "submit", AUDIT, "A-01", "SIM-001", complete=True, note="Recontagem física")
        self.qr(self.a, FIRST, "A-02", "", "00000001,L1,3")
        self.act(self.a, "submit", FIRST, "A-02", complete=True)
        self.qr(self.b, FIRST, "B-01", "", "00000003,L1,4")
        self.act(self.b, "submit", FIRST, "B-01", complete=True)
        self.act(self.b, "submit", FIRST, "B-02", empty=True, complete=True)
        self.act(self.key, "close")
        result = self.view(self.key)
        self.assertEqual(result["queue"], [])
        self.assertEqual(result["pilot"].totals()[0][-1], -10)
        self.assertEqual([line["Quantidade"] for line in result["evidence"][r._key(AUDIT,"A-01","SIM-001")]], [5,4])
        self.assertEqual(set(self.view(self.a)), {"role", "closed", "tasks", "drafts"})
