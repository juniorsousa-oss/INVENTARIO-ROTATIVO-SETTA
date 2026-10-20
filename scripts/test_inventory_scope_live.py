"""Smoke test opcional da Central de Dados para validar os cabeçalhos reais.

Invocado na integração contínua; usa apenas a chave pública já
configurada no aplicativo e não exibe itens/códigos do estoque.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from collections import Counter
from central_inventory_data import download_source_frame, inventory_scope_catalog, operational_state
from inventory_scope import catalog_exclusions, filter_s2_sources, classify_past_row, code
an,_=download_source_frame("analitico","s2-smoke",header=1)
en,_=download_source_frame("endereco","s2-smoke",header=1)
scope=inventory_scope_catalog()
assert len(scope.get("historical_s2_codes") or []) >= 4000, "Catálogo S2 histórico foi truncado"
assert len(scope.get("historical_non_s2_codes") or []) >= 100, "Outros armazéns não foram carregados por completo"
exclusions=catalog_exclusions(scope["excluded_codes"])
s2_an,s2_en,info=filter_s2_sources(an,en,exclusions)
assert not s2_an.empty, "Analítico S2 vazio"
assert not s2_en.empty, "Endereço S2 vazio"
assert info["eligible_codes"]>0
print("LIVE_S2_SCOPE_OK", {**info, "analitico_rows":len(an),"endereco_rows":len(en)})

# Classificar histórico, preservando dados originais e sem efetuar ajustes.
state=operational_state(["inventories"])
docs=state.get("inventories") or {}
s2_codes=set(scope.get("historical_s2_codes") or []) | {code(x) for x in s2_an.iloc[:,0]}
non_s2=set(scope.get("historical_non_s2_codes") or []) - {code(x) for x in s2_an.iloc[:,0]}
statuses=Counter()
executed_out_scope=0
for doc in docs.values():
 for item in doc.get("rows") or []:
  reason=classify_past_row(item,exclusions,s2_codes,non_s2)
  statuses[reason]+=1
  if reason!="S2" and str(item.get("ajuste_status") or "").upper()=="REALIZADO":
   executed_out_scope+=1
print("S2_HISTORICAL_AUDIT_OK",dict(statuses),"executed_out_scope",executed_out_scope)
