"""Exercita as rotinas reais sem importar o app nem abrir uma Central."""
import ast
import copy
from datetime import datetime
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import central_inventory_data as central


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class InventoryPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.base = {
            "documento": "TESTE-A", "status": "AGUARDANDO ANÁLISE", "rows": [
                {"id": "1", "codigo": "001", "endereco": "A1", "status": "FINALIZADO",
                 "contagem_final": 7, "contagens": [{"quantidade": 7}], "resultado_final": "CONFIRMADO"},
            ],
        }
        self.state = State(inventories={"TESTE-A": copy.deepcopy(self.base)}, cycles={"001": 4}, reports={})
        self.state["_inventory_scope_ready"] = True
        self.save = Mock()
        self.remote = Mock()
        self.remote.save_inventory_document.return_value = {"ok": True, "protected": True}
        self.remote.close_inventory_atomic.return_value = {"ok": True, "protected": True}
        names = {"persist_inv", "_save_confirmed_inventory_cache", "_inventory_write_error",
                 "_commit_inventory_action", "close_inv"}
        nodes = [node for node in ast.parse(Path(__file__).resolve().parents[1].joinpath("app.py").read_text()).body
                 if isinstance(node, ast.FunctionDef) and node.name in names]
        self.assertEqual(names, {node.name for node in nodes})
        self.st = SimpleNamespace(session_state=self.state, error=Mock(), rerun=Mock(), stop=Mock())
        self.ctx = {"st": self.st, "central_data": self.remote, "copy": copy, "sqlite3": sqlite3,
                    "save": self.save, "_valid_inventory_rows": lambda doc: doc["rows"],
                    "_can_manage_inventory": lambda: True, "_session_auth_token": lambda: "fixture",
                    "_session_operator": lambda: "Operador de teste",
                    "now_local": lambda: datetime.fromisoformat("2026-11-26T12:00:00-03:00"),
                    "last": lambda row: row["contagens"][-1]["quantidade"]}
        exec(compile(ast.Module(nodes, []), "app.py", "exec"), self.ctx)

    def test_failure_keeps_confirmed_document_and_does_not_rerun(self):
        proposed = copy.deepcopy(self.base)
        proposed["status"] = "AGUARDANDO DECISÃO"
        self.remote.save_inventory_document.side_effect = TimeoutError()
        self.ctx["_commit_inventory_action"](proposed)
        self.assertEqual(self.state.inventories["TESTE-A"], self.base)
        self.save.assert_not_called()
        self.st.rerun.assert_not_called()
        self.st.stop.assert_called_once()
        self.st.error.assert_called_once()

    def test_confirmed_write_uses_previous_document_and_updates_after_commit(self):
        proposed = copy.deepcopy(self.base)
        proposed["status"] = "AGUARDANDO DECISÃO"

        def validate(documento, document, *, expected):
            self.assertEqual(self.state.inventories[documento], self.base)
            self.assertEqual(expected, self.base)
            self.assertEqual(document, proposed)
            self.save.assert_not_called()

        self.remote.save_inventory_document.side_effect = validate
        self.assertTrue(self.ctx["persist_inv"](proposed))
        self.assertEqual(self.state.inventories["TESTE-A"], proposed)
        self.save.assert_called_once()

    def test_conflict_blocks_retry_until_refresh(self):
        proposed = copy.deepcopy(self.base)
        self.remote.save_inventory_document.side_effect = RuntimeError("INVENTARIO_CONFLITO_DE_VERSAO")
        self.assertFalse(self.ctx["persist_inv"](proposed))
        self.assertEqual(self.state["_inventory_conflict_document"], "TESTE-A")
        self.assertFalse(self.ctx["persist_inv"](proposed))
        self.remote.save_inventory_document.assert_called_once()
        self.assertEqual(self.state.inventories["TESTE-A"], self.base)

    def test_close_failure_leaves_document_cycles_reports_unchanged(self):
        self.state.reports = {"r": {"status": "ABERTO", "codigo": "001", "endereco": "A1"}}
        old = copy.deepcopy(dict(self.state))
        self.remote.close_inventory_atomic.side_effect = RuntimeError("INVENTARIO_CONFLITO_DE_VERSAO")
        self.assertFalse(self.ctx["close_inv"](copy.deepcopy(self.base)))
        for k in ("inventories", "cycles", "reports"):
            self.assertEqual(self.state[k], old[k])
        self.save.assert_not_called()

    def test_guarded_api_requires_explicit_confirmation_and_separates_snapshot(self):
        proposed = copy.deepcopy(self.base)
        proposed["status"] = "AGUARDANDO DECISÃO"
        with patch.object(central, "api_call", return_value={"data": {"ok": True}}) as api:
            with self.assertRaisesRegex(RuntimeError, "CONFIRMACAO"):
                central.save_inventory_document("TESTE-A", proposed, expected=self.base)
        wire = api.call_args.args[1]["document"]
        self.assertEqual(wire["_setta_expected_document"], self.base)
        self.assertNotIn("_setta_expected_document", proposed)
        with patch.object(central, "api_call", return_value={"data": {"ok": True, "protected": True}}):
            self.assertTrue(central.save_inventory_document("TESTE-A", proposed, expected=self.base)["ok"])
