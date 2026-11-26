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
        self.assertEqual(set(self.view(self.a)), {"role", "closed", "tasks", "drafts", "display", "title", "room_id", "free"})

    def configured(self, people):
        ids = r.team_ids(people)
        teams = {idx: {"name": f"Equipe {n}", "lead": f"T{n} Líder", "assistant": f"T{n} Apoio"}
                 for n, idx in enumerate(ids, start=1)}
        assignment = {a: ids[i % len(ids)] for i, a in enumerate(ELIGIBLE)}
        return ids, teams, assignment

    def test_management_validates_parity_named_roles_distinct_members_and_coverage(self):
        for value in (0, 1, 3, 5, 10, 4.0, "4"):
            with self.assertRaises(ValueError):
                r.team_ids(value)
        ids, teams, assignment = self.configured(6)
        with self.assertRaises(ValueError):
            r.create_room(dict.fromkeys(ELIGIBLE, ids[0]), True, teams=teams, people=6, path=self.path)
        for changes in ({"name": "equIpe 1"}, {"lead": " t1   líder "}, {"assistant": " "}):
            bad = {**teams, ids[1]: {**teams[ids[1]], **changes}}
            with self.assertRaises(ValueError):
                r.create_room(assignment, True, teams=bad, people=6, path=self.path)
        key = r.create_room(assignment, True, teams=teams, people=6, title="Piloto de turno", path=self.path)
        current = self.view(key)
        self.assertEqual(current["teams"], teams)
        tokens = r.worker_codes(key, ids)
        self.assertEqual(len(tokens), 4)
        team = self.view(tokens[ids[2]])
        self.assertEqual((team["display"], team["title"], team["tasks"][FIRST]), ("Equipe 3", "Piloto de turno", [("B-01","")]))
        self.assertNotIn("teams", team)
        self.qr(tokens[ids[0]], FIRST, "A-01", "", "00000001,L1,7")
        self.act(tokens[ids[0]], "submit", FIRST, "A-01", complete=True)
        self.assertTrue(self.view(tokens[ids[1]])["tasks"][SECOND])
        self.assertFalse(self.view(tokens[ids[2]])["tasks"][SECOND])

    def test_single_team_needs_independent_recount_and_separate_audit(self):
        ids, teams, assignment = self.configured(2)
        key = r.create_room(assignment, True, teams=teams, people=2, path=self.path)
        tokens = r.worker_codes(key, ids)
        self.qr(tokens[ids[0]], FIRST, "A-01", "", "00000001,L1,8")
        self.act(tokens[ids[0]], "submit", FIRST, "A-01", complete=True)
        self.assertFalse(self.view(tokens[ids[0]])["tasks"][SECOND])
        reviewer = tokens[r.INDEPENDENT]
        self.assertNotIn(FIRST, self.view(reviewer)["tasks"])
        self.qr(reviewer, SECOND, "A-01", "SIM-001", "00000001,L1,7")
        self.act(reviewer, "submit", SECOND, "A-01", "SIM-001", complete=True)
        self.assertIn(("A-01", "SIM-001"), self.view(tokens[r.AUDITOR])["tasks"][AUDIT])

    def test_edit_and_final_submit_protect_against_stale_or_final_draft(self):
        key = r._key(FIRST, "A-01")
        self.qr(self.a, FIRST, "A-01", "", "00000001,L1,3")
        lines_before = self.view(self.a)["drafts"][key]
        line = lines_before[0]
        updated = r.reading("00000001", "A-01", "L2", "9")
        self.act(self.a, "edit", FIRST, "A-01", item=updated, expected=line, line_id=line["id"])
        with self.assertRaisesRegex(ValueError, "outro aparelho"):
            self.act(self.a, "edit", FIRST, "A-01", item=updated, expected=line, line_id=line["id"])
        with self.assertRaisesRegex(ValueError, "outro aparelho"):
            self.act(self.a, "submit", FIRST, "A-01", complete=True, expected=r.draft_version(lines_before))
        self.assertFalse(self.view(self.b)["tasks"][SECOND])
        lines = self.view(self.a)["drafts"][key]
        self.assertEqual(r.grouped(lines), [{"Produto":"SIM-001", "Lote":"L2", "Quantidade":9}])
        self.act(self.a, "submit", FIRST, "A-01", complete=True, expected=r.draft_version(lines))
        self.assertIn(("A-01", "SIM-001"), self.view(self.b)["tasks"][SECOND])
        self.assertNotIn(key, self.view(self.a)["drafts"])
        for event in ("edit", "remove", "submit"):
            with self.assertRaises(ValueError):
                self.act(self.a, event, FIRST, "A-01", item=updated, expected=line, line_id=line["id"])

    def free_room(self, people=3, mode=r.PAIRS):
        names = "\n".join(f"Pessoa {i}" for i in range(1, people + 1))
        key = r.create_room({}, True, people=people, mode=mode, participants=names, path=self.path)
        info = self.view(key)
        return key, list(r.worker_codes(key, info["pilot"].teams).values())

    def test_free_formation_individual_odd_and_more_than_eight(self):
        nine = "\n".join(f"Pessoa {i}" for i in range(9))
        pair = list(r.formation(9, r.PAIRS, nine, "Teste")["teams"].values())
        self.assertEqual(len(pair), 5)
        self.assertEqual(pair[0], {"name":"Pessoa 0 / Pessoa 1","lead":"Pessoa 0","assistant":"Pessoa 1"})
        self.assertEqual(pair[-1], {"name":"Pessoa 8","lead":"Pessoa 8","assistant":""})
        individual = list(r.formation(9, r.INDIVIDUAL, nine, "Teste")["teams"].values())
        self.assertEqual(len(individual), 9)
        self.assertTrue(all(not team["assistant"] for team in individual))
        with self.assertRaises(ValueError):
            r.formation(2, r.PAIRS, "Pessoa A", "Teste")

    def test_free_address_duplicate_runs_separately_and_never_enters_total(self):
        key, (a,b,_) = self.free_room()
        self.assertEqual(self.view(key)["pilot"].assignment, {})
        with self.assertRaisesRegex(ValueError,"não é apto"):
            self.act(a, "open", address=" X - 01 ")
        self.assertEqual(self.act(a, "open", address="  a – 01 "), (FIRST, "A-01"))
        with self.assertRaises(r.AddressConflict) as conflict:
            self.act(b, "open", address="A-01")
        self.assertEqual(conflict.exception.name, "Pessoa 1 / Pessoa 2")
        self.assertFalse(conflict.exception.submitted)
        self.qr(a,FIRST,"A-01","","00000001,000101,6")
        self.qr(a,FIRST,"A-01","","00000001,000102,4")
        self.qr(a,FIRST,"A-01","","00000002,L2,5")
        self.act(a,"submit",FIRST,"A-01",complete=True)
        with self.assertRaises(r.AddressConflict) as counted:
            self.act(b,"open",address=" a-01")
        self.assertTrue(counted.exception.submitted)
        owner = counted.exception.owner
        self.assertEqual(self.act(b,"open",address="A-01",confirm_owner=owner),(r.EXTRA,"A-01"))
        self.qr(b,r.EXTRA,"A-01","","00000001,L1,99")
        self.act(b,"submit",r.EXTRA,"A-01",complete=True)
        with self.assertRaises(ValueError):
            self.act(b,"open",address="A-01",confirm_owner=owner)
        for address, code, amount in (("A-02","00000001",3),("B-01","00000003",4),("B-02","",0)):
            self.act(b,"open",address=address)
            if code:
                self.qr(b,FIRST,address,"",f"{code},000101,{amount}")
            self.act(b,"submit",FIRST,address,complete=True,empty=not code)
        self.act(key,"close")
        result = self.view(key)
        self.assertEqual(result["pilot"].totals()[0][2:8], (13,2,15,15,0,0))
        self.assertEqual(result["extras"][0][3][0]["Quantidade"],99)
        self.assertTrue(all(not k.startswith(r.EXTRA) for k in result["evidence"]))

    def test_simultaneous_address_claim_creates_exactly_one_official_count(self):
        key,(a,b,_) = self.free_room()
        def claim(team_text):
            team, address = team_text
            try:
                return self.act(team,"open",address=address)
            except r.AddressConflict as exc:
                return exc
        with ThreadPoolExecutor(2) as executor:
            results = list(executor.map(claim, [(a,"a – 01"),(b,"  A-01 ")]))
        self.assertEqual(sum(isinstance(o, r.AddressConflict) for o in results),1)
        self.assertIn((FIRST,"A-01"),results)
        self.assertEqual(list(self.view(key)["pilot"].assignment),["A-01"])
        winner = b if isinstance(results[0],r.AddressConflict) else a
        self.qr(winner,FIRST,"A-01","","00000001,000101,1")
        self.act(winner,"submit",FIRST,"A-01",complete=True)
        receiver = a if winner == b else b
        self.assertEqual(self.view(receiver)["tasks"][SECOND],[("A-01","SIM-001"),("A-01","SIM-002")])

    def test_new_pilot_validates_address_book_without_assigning_addresses(self):
        c,(a,b,_) = self.free_room()
        for code,message in (("B-20","não encontrado"),("X-01","não é apto"),("E2-01","outro armazém")):
            with self.assertRaisesRegex(ValueError,message):
                self.act(a,"open",address=code)
        self.assertFalse(self.view(c)["pilot"].assignment)
        self.assertEqual(self.act(b,"open",address=" b-02 "),(FIRST,"B-02"))

    def test_equal_total_lot_swap_recount_and_zero_financial_delta(self):
        c,(a,b,_) = self.free_room()
        self.act(a,"open",address="A-01")
        self.qr(a,FIRST,"A-01","","00000001,000101,4")
        self.qr(a,FIRST,"A-01","","00000001,000102,6")
        self.qr(a,FIRST,"A-01","","00000002,LOTE-NOVO,5")
        self.act(a,"submit",FIRST,"A-01",complete=True)
        self.assertEqual(self.view(b)["tasks"][SECOND],[("A-01","SIM-001")])
        self.assertEqual(self.view(b)["drafts"][r.task_key(SECOND,"A-01","SIM-001",self.view(b)["role"])],[])
        self.qr(b,SECOND,"A-01","SIM-001","00000001,000101,4")
        self.qr(b,SECOND,"A-01","SIM-001","00000001,000102,6")
        self.act(b,"submit",SECOND,"A-01","SIM-001",complete=True)
        for address,payload in [("A-02","00000001,000101,3"),("B-01","00000003,000301,4"),("B-02","")]:
            self.act(a,"open",address=address)
            if payload:
                self.qr(a,FIRST,address,"",payload)
            self.act(a,"submit",FIRST,address,empty=not payload,complete=True)
        self.act(c,"close")
        p=self.view(c)["pilot"]
        self.assertEqual(p.totals()[0][6:],(0,0))
        self.assertEqual([(item[2],item[7]) for item in p.lot_discrepancies()],[("000101",-2),("000102",2)])

    def test_recount_with_third_lot_distribution_goes_to_audit(self):
        c,(a,b,u) = self.free_room()
        self.act(a,"open",address="A-01")
        for payload in ("00000001,000101,4","00000001,000102,6","00000002,000201,5"):
            self.qr(a,FIRST,"A-01","",payload)
        self.act(a,"submit",FIRST,"A-01",complete=True)
        for payload in ("00000001,000101,5","00000001,000102,5"):
            self.qr(b,SECOND,"A-01","SIM-001",payload)
        self.act(b,"submit",SECOND,"A-01","SIM-001",complete=True)
        self.assertEqual(self.view(u)["tasks"][AUDIT],[("A-01","SIM-001")])
        for payload in ("00000001,000101,6","00000001,000102,4"):
            self.qr(u,AUDIT,"A-01","SIM-001",payload)
        self.act(u,"submit",AUDIT,"A-01","SIM-001",complete=True,note="Conferidos os dois lotes.")
        row=self.view(c)["pilot"].positions["A-01"]["SIM-001"]
        self.assertEqual((row.final,row.final_lots,row.audit_note),(10,{"000101":6,"000102":4},"Conferidos os dois lotes."))
