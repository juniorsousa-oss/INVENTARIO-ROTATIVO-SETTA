"""Testes do escopo contábil do Inventário Rotativo."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from inventory_scope import catalog_exclusions, filter_s2_sources, classify_past_row

an = pd.DataFrame([
 ["00000001","MP","S2","PARAFUSO",10],
 ["00000002","MP","E2","ITEM E2",20],
 ["06000218","MP","S2","CHAPA",50],
 ["00000003","PA","S2","PAINEL",1],
 ["00000004","MP","S2","MULTI",2],
 ["00000004","MP","E2","MULTI",2],
 ["00000005","MP","S2","MATERIAL S2 NOVO",7],
],columns=["CODIGO","TP","ARMZ","DESCRICAO","QNT"])
# Completar 11 colunas para preservar o contrato com o ANALÍTICO.
for i in range(6): an[f"C{i}"] = 0
en = pd.DataFrame([
 ["00000001","S2","A","G9-A",1,2,3,10],
 ["00000002","E2","A","PA",1,2,3,20],
 ["06000218","S2","A","G9-B",1,2,3,50],
 ["00000003","S2","A","ALMOX. P.A",1,2,3,1],
 ["00000004","S2","A","G9-C",1,2,3,2],
 ["00000004","E2","A","E2",1,2,3,2],
 ["00000005","S2","A","DOCA",1,2,3,7],
],columns=["COD","ARMZ","X","ENDERECO","a","b","c","QTD"])
exc=catalog_exclusions([{"codigo":"06000218","categoria":"CHAPA"}])
a,e,stats=filter_s2_sources(an,en,exc)
assert set(a.iloc[:,0])=={"00000001","00000004","00000005"}
assert set(e.iloc[:,0])=={"00000001","00000004","00000005"}
assert all(e["ARMZ"]=="S2")
assert stats["has_address_warehouse"]
# Endereços sem ARMZ deixam itens multi-armazém em quarentena.
en_no_armz=en.drop(columns=["ARMZ"]).copy()
en_no_armz["XTRA"]=0
a2,e2,stats2=filter_s2_sources(an,en_no_armz,exc)
assert set(a2.iloc[:,0])=={"00000001","00000005"}
assert set(e2.iloc[:,0])=={"00000001","00000005"}
assert stats2["blocked_ambiguous_codes"]==1
assert classify_past_row({"codigo":"06000218"},exc,{"06000218"},set())=="FECHAMENTO CHAPAS/BARRAS"
assert classify_past_row({"codigo":"00000002"},exc,{"00000001"},{"00000002"})=="FORA DO S2"
assert classify_past_row({"codigo":"00000006"},exc,{"00000001"},set())=="S2 NÃO COMPROVADO"
assert classify_past_row({"codigo":"00000001"},exc,{"00000001"},set())=="S2"
try:
 an_missing_armz=an.drop(columns=["ARMZ"]).copy()
 an_missing_armz["OTHER"]=0
 filter_s2_sources(an_missing_armz,en,exc)
except ValueError as e:
 assert "ARMZ" in str(e)
else:
 raise AssertionError("Sem ARMZ deve bloquear a geração")
print("S2_SCOPE_OK")
