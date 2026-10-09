"""Testes comportamentais da regra de ciclos (funções extraídas do app real)."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
source = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
names = {
    "_counted_cycles", "_open_inventory_codes", "_eligible_priority_frame",
    "select_products", "cycle",
}
nodes = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names]
assert {x.name for x in nodes} == names, "Funções de prioridade ausentes"
mock_state = SimpleNamespace(cycles={}, inventories={}, db=None)
env = {"st": SimpleNamespace(session_state=mock_state), "pd": pd}
exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), env)

db = pd.DataFrame({
    "codigo": ["00000001", "00000002", "00000003", "00000004", "00000005"],
    "descricao": ["A", "B", "C", "D", "E"],
    "saldo_apto": [1, 2, 3, 4, 5],
    "valor_unitario": [10, 20, 30, 40, 50],
    "classificacao_r_un": [5, 4, 3, 2, 1],
    "classificacao_r_total": [5, 4, 3, 2, 1],
})

def selected(n, urgencies=None):
    return set(env["select_products"](db, n, urgencies)["codigo"].tolist())

mock_state.db = db
mock_state.cycles = {"00000001": 0, "00000002": 0, "00000003": 1, "00000004": 1, "00000005": 2}
assert selected(1) <= {"00000001", "00000002"}, "Contagens 0 devem sair primeiro"
assert selected(3) == {"00000001", "00000002", "00000003"} or selected(3) == {"00000001", "00000002", "00000004"}, "Deve completar a quantidade na próxima faixa"
assert env["cycle"]() == 1

urgency_result = selected(2, ["00000005"])
assert "00000005" in urgency_result, "Constatação de inconsistência deve antecipar o item"
assert {"00000001", "00000002"} <= urgency_result, "Urgência não pode consumir vagas regulares"

mock_state.inventories = {
    "in-progress": {"status": "EM CONTAGEM", "rows": [{"codigo": "00000001"}]},
}
assert "00000001" not in selected(3), "Não duplicar material de inventário em aberto"
mock_state.inventories = {}

mock_state.cycles = dict.fromkeys(db["codigo"].tolist(), 1)
assert env["cycle"]() == 2, "Novo ciclo após todos atingirem uma contagem"
mock_state.cycles["00000005"] = 0
assert selected(1) == {"00000005"}, "Item com 0 contagens volta à frente"

print("INVENTORY_CYCLE_PRIORITY_OK")
