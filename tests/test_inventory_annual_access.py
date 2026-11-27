import unittest
from functools import partial
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from pathlib import Path
from tempfile import TemporaryDirectory

import inventory_annual_rooms as r
from inventory_annual_pilot import FIRST, INDEPENDENT


class AnnualAccessTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'annual.sqlite3'
        token = r.create_room({}, True, people=2, mode=r.INDIVIDUAL, participants='Equipe A\nEquipe B', path=self.path)
        self.id = r.view(token, path=self.path)['room_id']
        self.gestor = r.RoomAccess(self.id, r.COORD, True)
        self.guest = r.RoomAccess(self.id, 'EQ-000001')

    def test_release_guest_blind_and_revocation_without_codes(self):
        self.assertFalse(r.list_rooms(path=self.path))
        self.assertEqual(len(r.list_rooms(manager=True, path=self.path)), 1)
        with self.assertRaises(ValueError):
            r.view(self.guest, path=self.path)
        r.action(self.gestor, 'publish', path=self.path)
        rooms = r.list_rooms(path=self.path)
        self.assertEqual(rooms[0]['teams'], [('EQ-000001', 'Equipe A'), ('EQ-000002', 'Equipe B')])
        r.action(self.guest, 'open', address='A-01', path=self.path)
        r.action(self.guest, 'add', FIRST, 'A-01', item=r.parse_demo_label('00000001,000101,3', 'A-01'), path=self.path)
        self.assertNotIn('pilot', r.view(self.guest, path=self.path))
        other = r.view(r.RoomAccess(self.id, 'EQ-000002'), path=self.path)
        self.assertFalse(other['drafts'])
        for role in (r.COORD, r.AUDITOR, 'UNKNOWN', INDEPENDENT):
            with self.subTest(role=role), self.assertRaises(ValueError):
                r.view(r.RoomAccess(self.id, role), path=self.path)
        self.assertIn('tasks', r.view(r.RoomAccess(self.id, r.AUDITOR, True), path=self.path))
        for event in ('close', 'hide', 'publish'):
            with self.assertRaises(ValueError):
                r.action(self.guest, event, path=self.path)
        r.action(self.gestor, 'hide', path=self.path)
        with self.assertRaises(ValueError):
            r.action(self.guest, 'open', address='A-02', path=self.path)
        r.action(self.gestor, 'publish', path=self.path)
        self.assertTrue(r.view(self.guest, path=self.path)['drafts'])

    def test_invalid_room_and_snapshot_catalog(self):
        with self.assertRaises(ValueError):
            r.view(r.RoomAccess('missing', r.COORD, True), path=self.path)
        item = r.parse_demo_label('00000001,L01,3', 'A-01', catalog={'00000001': 'Descrição'})
        self.assertEqual(item.product, '00000001')
        r.action(self.gestor, 'publish', path=self.path)
        r.action(self.guest, 'open', address='A-01', path=self.path)
        with self.assertRaisesRegex(ValueError, 'catálogo'):
            r.action(self.guest, 'add', FIRST, 'A-01', item=item, path=self.path)


    def test_ui_access_does_not_prompt_for_team_code(self):
        def click(app, label):
            [button] = [b for b in app.button if b.label == label]
            app = button.click().run()
            self.assertFalse(app.exception)
            return app

        entry = "import streamlit as st\nfrom inventory_annual_ui import render\n"
        with patch.object(r, "list_rooms", partial(r.list_rooms, path=self.path)), \
             patch.object(r, "view", partial(r.view, path=self.path)), \
             patch.object(r, "action", partial(r.action, path=self.path)):
            guest = AppTest.from_string(entry + "render(st, manager=False)").run()
            self.assertFalse(guest.exception)
            self.assertTrue(guest.info)
            self.assertFalse(guest.text_input)
            self.assertEqual([c.value for c in guest.caption], ["Piloto S2 · Dados fictícios"])
            manager = AppTest.from_string(entry + "render(st, manager=True)").run()
            manager = click(manager, "Acompanhar inventário")
            manager = click(manager, "Liberar na visão padrão")
            guest = click(guest.run(), "Equipe A")
            self.assertTrue(any("Acesso: Equipe A" == x.value for x in guest.text))
            self.assertFalse(any("Código de acesso" in x.label for x in guest.text_input))
            self.assertFalse(any(x.label == "Abrir auditoria" for x in guest.button))
            other = r.RoomAccess(self.id, "EQ-000002")
            r.action(self.guest, "open", address="A-01")
            r.action(other, "open", address="A-01", confirm_owner=self.guest.role)
            r.action(other, "add", r.EXTRA, "A-01",
                     item=r.parse_demo_label("00000001,000101,3", "A-01"))
            r.action(other, "submit", r.EXTRA, "A-01", complete=True)
            manager = manager.run()
            self.assertFalse(manager.exception)
            self.assertTrue(any("Parafuso" in f.value["Descrição"].tolist()
                                for f in manager.dataframe if "Descrição" in f.value))
            click(manager, "Retirar da visão padrão")
            self.assertTrue(guest.run().info)


class MixedTeamsTests(unittest.TestCase):
    @staticmethod
    def participant(name, role=r.PRINCIPAL):
        return {"Participante": name, "Classe": role}

    def test_even_total_can_make_a_pair_and_two_solos(self):
        rows = [self.participant("Aux 1", r.ASSISTANT), self.participant("Principal 1"),
                self.participant("Principal 2"), self.participant("Principal 3")]
        info = r.formation(4, r.MIXED, rows, "Teste")
        self.assertEqual([x["name"] for x in info["teams"].values()],
                         ["Principal 1 / Aux 1", "Principal 2", "Principal 3"])
        with TemporaryDirectory() as temp:
            path = Path(temp) / "test.sqlite3"
            token = r.create_room({}, True, people=4, mode=r.MIXED, participants=rows, path=path)
            rid = r.view(token, path=path)["room_id"]
            r.action(r.RoomAccess(rid, r.COORD, True), "publish", path=path)
            listing = r.list_rooms(path=path)[0]
            self.assertEqual([name for _, name in listing["teams"]],
                             ["Principal 1 / Aux 1", "Principal 2", "Principal 3"])

    def test_odd_total_and_no_fixed_limit(self):
        rows = [self.participant(f"P{i}") for i in range(19)]
        rows += [self.participant(f"A{i}", r.ASSISTANT) for i in range(12)]
        teams = list(r.formation(31, r.MIXED, rows, "Teste")["teams"].values())
        self.assertEqual(len(teams), 19)
        self.assertEqual([pair["assistant"] for pair in teams[:12]], [f"A{i}" for i in range(12)])
        self.assertTrue(all(not pair["assistant"] for pair in teams[12:]))

    def test_invalid_mixed_formation(self):
        with self.assertRaisesRegex(ValueError, "principal"):
            r.formation(3, r.MIXED, [self.participant("P"), self.participant("A", r.ASSISTANT),
                                     self.participant("B", r.ASSISTANT)], "Teste")
        with self.assertRaisesRegex(ValueError, "uma vez"):
            r.formation(2, r.MIXED, [self.participant("P"), self.participant("p", r.ASSISTANT)], "Teste")
        with self.assertRaisesRegex(ValueError, "classe"):
            r.formation(2, r.MIXED, [self.participant("P")], "Teste")
        with self.assertRaisesRegex(ValueError, "Principal ou Auxiliar"):
            r.formation(1, r.MIXED, [self.participant("P", "Outra")], "Teste")
        with self.assertRaisesRegex(ValueError, "nome de cada"):
            r.formation(1, r.MIXED, [self.participant("")], "Teste")

    def test_manager_can_render_mixed_entry_and_correct_missing_names(self):
        entry = "import streamlit as st\nfrom inventory_annual_ui import _setup\n_setup(st)"
        app = AppTest.from_string(entry).run()
        app = app.radio[0].set_value(r.MIXED).run()
        app = app.number_input[0].set_value(4).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[0].value.shape, (4, 2))
        self.assertEqual(app.dataframe[0].value["Classe"].tolist(), [r.PRINCIPAL]*4)
        app = app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertIn("nome de cada participante", app.error[0].value)


class AuxiliaryExchangeTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"Participante": name, "Classe": role} for name, role in
                     (("Ana", r.PRINCIPAL), ("Bia", r.PRINCIPAL), ("Caio", r.PRINCIPAL),
                      ("Luz", r.ASSISTANT), ("Sol", r.ASSISTANT))]
        self.plan = r.formation(5, r.MIXED, self.rows, "Piloto de teste")
        self.a, self.b, self.c = list(self.plan["teams"])

    def test_move_and_swap(self):
        teams = self.plan["teams"]
        moved = r.move_auxiliary(teams, self.a, self.c)
        self.assertEqual([x["name"] for x in moved.values()], ["Ana", "Bia / Sol", "Caio / Luz"])
        both = r.move_auxiliary(moved, self.c, self.b)
        self.assertEqual([x["name"] for x in both.values()], ["Ana", "Bia / Luz", "Caio / Sol"])
        with self.assertRaisesRegex(ValueError, "outro principal"):
            r.move_auxiliary(both, self.a, self.b)
        with self.assertRaisesRegex(ValueError, "única equipe"):
            r.assign_auxiliaries(teams, {self.a:"Luz", self.b:"Luz", self.c:""})
        with self.assertRaisesRegex(ValueError, "única equipe"):
            r.assign_auxiliaries(teams, {self.a:"Luz", self.b:"Não cadastrado", self.c:""})
        with self.assertRaisesRegex(ValueError, "formação mudou"):
            r.assign_auxiliaries(teams, {self.a:"Luz", self.b:"Sol"})

    def test_preview_edit_and_started_room_uses_reviewed_teams(self):
        from inventory_annual_ui import PREP, STATE
        entry = "import streamlit as st\nfrom inventory_annual_ui import _setup\n_setup(st)"
        app = AppTest.from_string(entry)
        app.session_state[PREP] = {**self.plan, "people":5, "participants":self.rows, "ready":True}
        def by_label(items, label):
            return next(x for x in items if x.label == label)
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/"rooms.sqlite3"
            with patch.object(r, "create_room", partial(r.create_room, path=path)), \
                 patch.object(r, "view", partial(r.view, path=path)):
                app.run()
                app = by_label(app.selectbox, "Auxiliar").set_value(self.a).run()
                app = by_label(app.selectbox, "Novo principal").set_value(self.c).run()
                app = by_label(app.button, "Aplicar troca").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.dataframe[0].value["Equipe"].tolist(), ["Ana", "Bia / Sol", "Caio / Luz"])
                self.assertFalse(path.exists())
                self.assertFalse(app.checkbox)
                app = by_label(app.button, "Iniciar piloto").click().run()
                self.assertFalse(app.exception)
                room = r.view(app.session_state[STATE])
                self.assertEqual([x["name"] for x in room["teams"].values()], ["Ana", "Bia / Sol", "Caio / Luz"])
                self.assertIsNotNone(room["pilot"].started_at)
                self.assertFalse(r.list_rooms(path=path))
                r.action(app.session_state[STATE], "publish", path=path)
                self.assertEqual([name for _, name in r.list_rooms(path=path)[0]["teams"]],
                                 ["Ana", "Bia / Sol", "Caio / Luz"])
