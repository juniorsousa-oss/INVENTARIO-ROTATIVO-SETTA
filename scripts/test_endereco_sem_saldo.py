"""Testa filtragem de posições inativas no carregamento do Inventário SETTA."""
import pandas as pd
from central_inventory_data import filtrar_enderecos_zerados
from pathlib import Path

def source(*values):
    return pd.DataFrame([
        ["001", "S2", "", "R01", "", "", "", "0"],
        ["001", "S2", "", "R01", "", "", "", "2"],
        ["002", "S2", "", "R02", "", "", "", "-1"],
        ["003", "S2", "", "R03", "", "", "", "0,000"],
        ["004", "S2", "", "R04", "", "", "", "1,25"],
        ["005", "S2", "", "R05", "", "", "", "INVALIDO"],
    ], columns=["Produto", "Armazem", "Prioridade", "Endereco",
                "Num de Serie", "Lote", "Sub-Lote", "Quantidade"])

def run():
    raw=source()
    filtered=filtrar_enderecos_zerados(raw,"endereco")
    assert len(raw)==6 and len(filtered)==4
    assert "R03" not in filtered["Endereco"].to_list()
    assert filtered["Endereco"].to_list()==["R01","R02","R04","R05"]
    assert filtrar_enderecos_zerados(raw,"analitico").equals(raw)
    app=Path("app.py").read_text(encoding="utf-8")
    assert "pos.quantidade.gt(0)" in app
    assert "e=e[e.quantidade.ne(0)]" in app
    print("INVENTARIO_ENDERECOS_ZERO_IGNORADOS_OK")

if __name__=="__main__":
    run()
