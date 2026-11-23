"""Smoke read-only de relatório por armazém na Central real.

Não imprime dados financeiros, códigos ou nomes de materiais.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from central_inventory_data import download_source_frame, derived_status, download_derived, operational_state
from inventory_stock_reports import build_stock_reports

BLOCKED = {
 "ALMOX. N.C.I", "ALMOX. N.C.R", "ASTEC", "G9-PROD", "G9-SEPA",
 "PROD. BARRAS", "PROD. CHAPAS", "PROD. PROC", "PROD. SUCATA",
 "PROD. TCTP", "QUALIDADE", "SETTA FIOS",
}
an, _ = download_source_frame("analitico", "inventory-report-live", header=1)
en, _ = download_source_frame("endereco", "inventory-report-live", header=1)
state = derived_status(["estoque_tratado"])["estoque_tratado"]
tratado, _ = download_derived("estoque_tratado", f"v{state.get('version') or 0}")
history = operational_state(["inventories"]).get("inventories") or {}
result = build_stock_reports(tratado, an, en, history, BLOCKED)
assert len(result["conferencia"]) > 4000
assert len(result["enderecos"]) > 0
assert {"S2", "EP", "E2", "T1"}.issubset(set(result["armazens"]))
assert result["saldo_disponivel_total"] >= 0
print("ESTOQUE_RELATORIOS_LIVE_OK", {
    "geral": len(result["conferencia"]),
    "posicoes": len(result["enderecos"]),
    "armazens": len(result["armazens"]),
    "nao_enderecados": result["nao_enderecados"],
    "divergencias_central": result["divergencias_central"],
    "divergencias_enderecos": result["divergencias_enderecos"],
})
