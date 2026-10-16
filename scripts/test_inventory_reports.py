"""Regressões: novas contagens visíveis, carga Protheus sempre autorizada."""

from inventory_reports import build_count_rows


def item(code, address, system, count, *, final=None, status="CONTADO", authorized=False, adjustment_status=""):
    return {
        "codigo": code,
        "descricao": "MATERIAL DE TESTE",
        "endereco": address,
        "qtd_sistema": system,
        "status": status,
        "contagens": [{"etapa": "1ª CONTAGEM", "quantidade": count, "comentario": "SC"}],
        "contagem_final": final,
        "ajuste_autorizado": authorized,
        "ajuste_status": adjustment_status,
        "tratativa_divergencia": "AJUSTAR ESTOQUE" if authorized else "ENCERRAR SEM AJUSTE",
    }


documents = {
    "15102026-002": {"documento": "15102026-002", "status": "EM CONTAGEM", "rows": [
        item("001", "A-01", 2, 3), item("001", "A-02", 1, 1),
        {"codigo": "002", "endereco": "B-01", "contagens": []},
    ]},
    "15102026-001": {"documento": "15102026-001", "status": "AGUARDANDO ANÁLISE", "rows": [
        item("003", "C-01", 8, 9),
    ]},
    "14102026-001": {"documento": "14102026-001", "status": "FECHADO", "rows": [
        item("004", "D-01", 10, 12, final=12, status="FINALIZADO"),
    ]},
    "08102026-001": {"documento": "08102026-001", "status": "FECHADO", "rows": [
        item("005", "E-01", 1, 4, final=4, status="FINALIZADO", authorized=True),
        item("006", "E-02", 2, 5, final=5, status="FINALIZADO", authorized=True, adjustment_status="REALIZADO"),
    ]},
}

rows = build_count_rows(documents)
assert len(rows) == 6, rows
assert {r["Documento"] for r in rows} == {"15102026-002", "15102026-001", "14102026-001", "08102026-001"}
assert [r for r in rows if r["Documento"] == "15102026-002" and r["Código"] == "001"].__len__() == 2
assert all(r["Situação Protheus"] == "INVENTÁRIO EM APURAÇÃO" for r in rows if r["Documento"].startswith("15102026"))
assert any(r["Documento"] == "14102026-001" and r["Situação Protheus"] == "ENCERRADO SEM AJUSTE" for r in rows)
assert sum(r["Situação Protheus"] == "AJUSTE AUTORIZADO / PENDENTE" for r in rows) == 1
assert sum(r["Situação Protheus"] == "AJUSTE REALIZADO" for r in rows) == 1
assert next(r for r in rows if r["Documento"] == "15102026-001")["Contagem Final"] is None
assert next(r for r in rows if r["Documento"] == "15102026-001")["Última Contagem"] == 9
print("INVENTORY_REPORTS_OK", len(rows))
