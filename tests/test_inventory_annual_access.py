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
