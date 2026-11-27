import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from inventory_annual_pilot import FIRST
import inventory_annual_rooms as r


class PilotBackupTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.source = Path(temp.name) / "source.sqlite3"
        self.target = Path(temp.name) / "fresh.sqlite3"
        auth = r.create_room({}, True, title="Piloto de validação", people=2, mode=r.INDIVIDUAL,
                             participants="Ana\nJoão", path=self.source)
        rid = r.view(auth, path=self.source)["room_id"]
        self.manager = r.RoomAccess(rid, r.COORD, True)
        self.ana = r.RoomAccess(rid, "EQ-000001")
        self.joao = r.RoomAccess(rid, "EQ-000002")
        r.action(self.manager, "publish", path=self.source)
        for access, address, commit in ((self.ana, "A-01", True), (self.joao, "A-02", False)):
            item = r.parse_demo_label("00000001,000101,3", address)
            r.action(access, "open", address=address, path=self.source)
            r.action(access, "add", FIRST, address, item=item, path=self.source)
            if commit:
                r.action(access, "submit", FIRST, address, complete=True, path=self.source)

    def test_restore_teams_drafts_and_submitted_from_a_fresh_database(self):
        data = r.backup_room(self.manager, path=self.source)
        access = r.restore_room(data, manager=True, path=self.target)
        self.assertEqual(access, self.manager)
        self.assertFalse(r.list_rooms(path=self.target))
        dest = r.view(access, path=self.target)
        source = r.view(self.manager, path=self.source)
        self.assertEqual(dest["title"], "Piloto de validação")
        self.assertEqual(dest["teams"], source["teams"])
        self.assertEqual(dest["pilot"].positions, source["pilot"].positions)
        self.assertEqual(dest["queue"], source["queue"])
        payload = json.loads(json.loads(data)["payload"])
        self.assertTrue(payload["state"]["evidence"])
        self.assertEqual(set(payload), {"id", "state"})
        self.assertNotIn("token_hash", data.decode())
        r.action(access, "publish", path=self.target)
        self.assertEqual(r.view(self.joao, path=self.target)["drafts"],
                         r.view(self.joao, path=self.source)["drafts"])

    def test_does_not_overwrite_live_data_or_accept_non_manager_and_tampering(self):
        with self.assertRaisesRegex(ValueError, "Somente a gestão"):
            r.backup_room(self.ana, path=self.source)
        data = r.backup_room(self.manager, path=self.source)
        with self.assertRaisesRegex(ValueError, "Somente a gestão"):
            r.restore_room(data, path=self.target)
        with self.assertRaisesRegex(ValueError, "Cópia inválida"):
            r.restore_room(data.replace(b"valida", b"XXXXXX"), manager=True, path=self.target)
        with self.assertRaisesRegex(ValueError, "Nenhum dado foi substituído"):
            r.restore_room(data, manager=True, path=self.source)
        self.assertEqual(r.backup_room(self.manager, path=self.source), data)
