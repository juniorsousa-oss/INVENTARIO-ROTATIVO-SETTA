"""Smoke test opcional da Central de Dados para validar os cabeçalhos reais.

Invocado na integração contínua; usa apenas a chave pública já
configurada no aplicativo e não exibe itens/códigos do estoque.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from central_inventory_data import download_source_frame, inventory_scope_catalog
from inventory_scope import catalog_exclusions, filter_s2_sources
an,_=download_source_frame("analitico","s2-smoke",header=1)
en,_=download_source_frame("endereco","s2-smoke",header=1)
scope=inventory_scope_catalog()
exclusions=catalog_exclusions(scope["excluded_codes"])
s2_an,s2_en,info=filter_s2_sources(an,en,exclusions)
assert not s2_an.empty, "Analítico S2 vazio"
assert not s2_en.empty, "Endereço S2 vazio"
assert info["eligible_codes"]>0
print("LIVE_S2_SCOPE_OK", {**info, "analitico_rows":len(an),"endereco_rows":len(en)})
