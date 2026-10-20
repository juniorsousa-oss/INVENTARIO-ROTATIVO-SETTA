"""Teste de regressão: decisão final após recontagem conciliada.

Executa funções reais do app via AST sem abrir interface Streamlit ou gravar
em Supabase. Protege dados históricos e impede fechamento prematuro.
"""
import ast
from copy import deepcopy
from datetime import datetime
from pathlib import Path

app = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
module = ast.parse(app)
names = {
    "last", "diff", "_decision_candidates",
    "_confirm_system_recount", "_pending_inventory_message",
}
nodes = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name in names]
assert {n.name for n in nodes} == names, "Rotinas de análise não encontradas"
ctx = {"now_local": lambda: datetime.fromisoformat("2026-10-20T07:50:00-03:00")}
exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), ctx)

# Situação real observada em 19102026-002: a segunda contagem eliminou a divergência.
r = {
    "id": "47b3c445b202", "codigo": "52700375", "endereco": "ALMOX. P.A",
    "status": "RECONTADA", "qtd_sistema": 1, "contagem_final": None,
    "ajuste_autorizado": False, "resultado_final": "",
    "contagens": [
        {"etapa": "1ª CONTAGEM", "quantidade": 2, "comentario": "SC"},
        {"etapa": "2ª CONTAGEM", "quantidade": 1, "comentario": "SC"},
    ],
}
done = {"codigo": "00090083", "status": "FINALIZADO",
        "contagens": [{"etapa": "1ª CONTAGEM", "quantidade": 155}],
        "qtd_sistema": 155}
inv = {"documento": "19102026-002", "status": "AGUARDANDO DECISÃO",
       "rows": [done, r]}
original_counts = deepcopy(r["contagens"])

candidate = ctx["_decision_candidates"](inv)
assert candidate == [r], "Recontagem conciliada precisa aparecer na análise"
assert "52700375" in ctx["_pending_inventory_message"](inv)
assert ctx["_confirm_system_recount"](r, "Operador Almoxarifado")
assert r["status"] == "FINALIZADO"
assert r["resultado_final"] == "SISTEMA CONFIRMADO"
assert r["contagem_final"] == 1
assert r["ajuste_autorizado"] is False
assert r["contagens"] == original_counts, "Nunca sobrescrever a história de contagens"
assert r["confirmado_por"] == "Operador Almoxarifado"
assert ctx["_decision_candidates"](inv) == []
assert ctx["_pending_inventory_message"](inv) == ""

# Não repetir confirmação nem autorizar silenciosamente ajuste existente.
assert ctx["_confirm_system_recount"](r, "outro") is False
other = deepcopy(r)
other["status"] = "RECONTADA"
other["resultado_final"] = ""
other["ajuste_autorizado"] = True
assert ctx["_confirm_system_recount"](other, "outro") is False
assert other["status"] == "RECONTADA"

# Divergência persistente deve seguir o fluxo de tratativa e permanecer pendente.
mismatch = deepcopy(r)
mismatch["status"] = "RECONTADA"
mismatch["contagem_final"] = None
mismatch["contagens"][-1]["quantidade"] = 3
mismatch["qtd_sistema"] = 1
assert ctx["_confirm_system_recount"](mismatch, "outro") is False
assert mismatch["status"] == "RECONTADA"
assert ctx["_decision_candidates"]({"rows": [mismatch]}) == [mismatch]

# Uma contagem inexistente nunca pode ser convertida em confirmação.
missing = deepcopy(r)
missing["status"] = "PENDENTE"
missing["contagens"] = []
assert ctx["_confirm_system_recount"](missing, "outro") is False
assert ctx["_decision_candidates"]({"rows": [missing]}) == []
assert "PENDENTE" in ctx["_pending_inventory_message"]({"rows": [missing]})
print("INVENTORY_WORKFLOW_OK")
