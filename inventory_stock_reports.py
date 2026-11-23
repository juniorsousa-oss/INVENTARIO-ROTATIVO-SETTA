"""Relatórios gerenciais independentes da operação de inventário S2.

Origem oficial: Estoque Tratado (por produto) + Analítico (código/armazém/custo)
+ Endereço (código/armazém/endereço/lote). Não modifica o estado operacional.

Regra NÃO ENDEREÇADOS: por produto/armazém, diferença POSITIVA entre
saldo disponível calculado com a mesma regra da Central e posições reais
disponíveis. Excesso de endereçamento é divergência, nunca saldo negativo
fictício. Números e classificação são recalculados após filtrar armazém.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from io import BytesIO
from typing import Any, Mapping

import pandas as pd

NAO_ENDERECADOS = "NÃO ENDEREÇADOS"
NUM = '#,##0.000;[Red](#,##0.000);–'
MONEY = 'R$ #,##0.00;[Red](R$ #,##0.00);R$ 0.00'
GERAL_CONFERENCIA = [
    "Código", "Armazém", "Descrição", "Saldo em Estoque",
    "Saldo Não Disponível", "Saldo Disponível", "Valor Unitário",
    "Valor em Estoque", "Quantidade de Contagens",
    "Classificação por Valor Unitário", "Classificação por Valor Agregado",
    "Data da Última Contagem",
]
GERAL_AUDITORIA = [
    "Código", "Armazém", "Descrição", "Saldo Disponível",
    "Valor Unitário", "Valor em Estoque",
]
ENDERECOS_COLS = [
    "Código", "Armazém", "Descrição", "Endereço",
    "Quantidade no Endereço", "Valor no Endereço",
    "Classificação por Valor Unitário", "Classificação por Valor Agregado",
]


def _code(v: object) -> str:
    if v is None or pd.isna(v):
        return ""
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s.zfill(8) if s.isdigit() and len(s) <= 8 else ""


def _armz(v: object) -> str:
    if v is None or pd.isna(v):
        return ""
    return str(v).strip().upper().replace(".0", "")


def _addr(v: object) -> str:
    if v is None or pd.isna(v):
        return ""
    return " ".join(str(v).strip().upper().split())


def _number(v: object) -> float:
    if v is None or pd.isna(v):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("R$", "").replace(" ", "").strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except (ValueError, OverflowError):
        raise ValueError(f"Estoque: número inválido na origem: {s[:32]!r}")


def _required(frame: pd.DataFrame, count: int, label: str) -> None:
    if frame is None or frame.shape[1] < count:
        raise ValueError(f"Fonte {label} sem as {count} colunas esperadas do Protheus.")


def _counts(inventories: Mapping[str, Any]) -> dict[tuple[str, str], tuple[int, str]]:
    result: dict[tuple[str, str], list] = defaultdict(lambda: [0, pd.NaT])
    for inventory in (inventories or {}).values():
        if not isinstance(inventory, dict):
            continue
        for item in inventory.get("rows") or []:
            if not isinstance(item, dict):
                continue
            code = _code(item.get("codigo"))
            warehouse = _armz(item.get("armazem") or "S2")
            if not code or not warehouse:
                continue
            for count in item.get("contagens") or []:
                if not isinstance(count, dict):
                    continue
                key = (code, warehouse)
                result[key][0] += 1
                raw = count.get("timestamp") or count.get("data")
                if raw:
                    parsed = pd.to_datetime(raw, dayfirst=not str(raw).startswith("20"), errors="coerce", utc=True)
                    if pd.notna(parsed) and (pd.isna(result[key][1]) or parsed > result[key][1]):
                        result[key][1] = parsed
    return {
        key: (n, dt.tz_convert("America/Sao_Paulo").strftime("%d/%m/%Y") if pd.notna(dt) else "")
        for key, (n, dt) in result.items()
    }


def _rank(frame: pd.DataFrame, column: str) -> list[str]:
    # Empates recebem mesma posição (ranking denso 1º, 2º, ...).
    return (
        pd.to_numeric(frame[column], errors="coerce").fillna(0)
        .rank(method="dense", ascending=False)
        .astype(int).map(lambda i: f"{i}º").tolist()
    )


def build_stock_reports(
    tratado: pd.DataFrame,
    analitico: pd.DataFrame,
    endereco: pd.DataFrame,
    inventories: Mapping[str, Any] | None,
    indisponiveis: set[str] | list[str],
    armazem: str = "TODOS",
) -> dict[str, Any]:
    """Retorna as quatro visões (conferência/auditoria + posições).

    A disponibilidade oficial da Central é por código, não armazém.
    Sua abertura é reconstruída pela mesma fórmula da Central (Analítico -
    endereços não disponíveis) em cada código/armazém, e conciliada ao total
    do tratado. Em caso de divergência, EXIBE ALERTA sem redistribuir saldo.
    """
    _required(analitico, 11, "ANALÍTICO")
    _required(endereco, 8, "ENDEREÇO")
    if tratado is None or not {
        "COD_MATERIAL", "SALDO_EM_ESTOQUE",
        "SALDO_NAO_DISPONIVEL", "SALDO_DISPONIVEL",
    }.issubset(tratado.columns):
        raise ValueError("Estoque Tratado da Central sem colunas oficiais.")
    blocked = {_addr(x) for x in indisponiveis}

    a = analitico.iloc[:, [0, 3, 6, 7, 10]].copy()
    a.columns = ["Código", "Descrição", "Armazém", "qtd", "valor"]
    a["Código"] = a["Código"].map(_code)
    a["Armazém"] = a["Armazém"].map(_armz)
    a["Descrição"] = a["Descrição"].fillna("").astype(str).str.strip()
    a["qtd"] = a["qtd"].map(_number)
    a["valor"] = a["valor"].map(_number)
    a = a[(a["Código"] != "") & (a["Armazém"] != "")]
    a = a.groupby(["Código", "Armazém"], sort=False, as_index=False).agg(
        **{"Descrição": ("Descrição", "first"),
           "Saldo em Estoque": ("qtd", "sum"), "_valor_contabil": ("valor", "sum")}
    )

    e = endereco.iloc[:, [0, 1, 3, 7]].copy()
    e.columns = ["Código", "Armazém", "Endereço", "quantidade"]
    e["Código"] = e["Código"].map(_code)
    e["Armazém"] = e["Armazém"].map(_armz)
    e["Endereço"] = e["Endereço"].map(_addr)
    e["quantidade"] = e["quantidade"].map(_number)
    e = e[(e["Código"] != "") & (e["Armazém"] != "") & (e["Endereço"] != "")]
    e = e.groupby(["Código", "Armazém", "Endereço"], sort=False, as_index=False)["quantidade"].sum()
    e = e[e["quantidade"].ne(0)].copy()
    e["_bloqueado"] = e["Endereço"].isin(blocked)

    grp = ["Código", "Armazém"]
    nao_disp = e.loc[e["_bloqueado"]].groupby(grp)["quantidade"].sum()
    a = a.merge(
        nao_disp.rename("Saldo Não Disponível").reset_index(),
        on=grp, how="left", validate="one_to_one",
    )
    a["Saldo Não Disponível"] = a["Saldo Não Disponível"].fillna(0).astype(float)
    a["Saldo Disponível"] = (a["Saldo em Estoque"] - a["Saldo Não Disponível"]).clip(lower=0)
    divisor = a["Saldo em Estoque"].where(a["Saldo em Estoque"].abs() > 1e-12)
    a["Valor Unitário"] = (a["_valor_contabil"] / divisor).fillna(0)
    a["Valor em Estoque"] = a["Saldo Disponível"] * a["Valor Unitário"]

    # Auditoria do subtotal por código contra a fonte oficial publicada.
    official = tratado[["COD_MATERIAL", "SALDO_EM_ESTOQUE", "SALDO_NAO_DISPONIVEL", "SALDO_DISPONIVEL"]].copy()
    official["COD_MATERIAL"] = official["COD_MATERIAL"].map(_code)
    for col in ("SALDO_EM_ESTOQUE", "SALDO_NAO_DISPONIVEL", "SALDO_DISPONIVEL"):
        official[col] = official[col].map(_number)
    official = official.groupby("COD_MATERIAL", as_index=True)[
        ["SALDO_EM_ESTOQUE", "SALDO_NAO_DISPONIVEL", "SALDO_DISPONIVEL"]
    ].sum()
    calculated = a.groupby("Código")[
        ["Saldo em Estoque", "Saldo Não Disponível", "Saldo Disponível"]
    ].sum()
    joined = official.join(calculated, how="outer").fillna(0)
    diffs = (
        (joined["SALDO_EM_ESTOQUE"] - joined["Saldo em Estoque"]).abs().gt(.001)
        | (joined["SALDO_NAO_DISPONIVEL"] - joined["Saldo Não Disponível"]).abs().gt(.001)
        | (joined["SALDO_DISPONIVEL"] - joined["Saldo Disponível"]).abs().gt(.001)
    )
    avisos = []
    if diffs.any():
        avisos.append(
            f"{int(diffs.sum())} produto(s) com divergência entre o Estoque Tratado "
            "oficial e a abertura por armazém. Não houve ajuste automático; "
            "confira se ANALÍTICO/ENDEREÇO estão na mesma versão de origem."
        )

    invalid = e[~e["_bloqueado"] & e["quantidade"].lt(0)]
    if not invalid.empty:
        avisos.append(
            f"{len(invalid)} posição(ões) disponíveis com saldo negativo "
            "na origem ENDEREÇO, exibidas como divergência, sem criar saldos artificiais."
        )

    # Só endereços disponíveis com saldo positivo entram no relatório.
    # Endereços bloqueados não são subtraídos novamente.
    akey = a.set_index(grp)
    address_rows = e[(~e["_bloqueado"]) & e["quantidade"].gt(0)].copy()
    address_rows = address_rows.merge(
        a[grp + ["Descrição", "Valor Unitário"]], on=grp, how="left",
        validate="many_to_one",
    )
    orfa = address_rows["Descrição"].isna()
    if orfa.any():
        avisos.append(
            f"{int(orfa.sum())} posição(ões) do ENDEREÇO sem produto/armazém "
            "correspondente no Analítico foram excluídas do relatório financeiro."
        )
    address_rows = address_rows[~orfa].copy()
    address_rows["Valor no Endereço"] = address_rows["quantidade"] * address_rows["Valor Unitário"]

    pos_sum = address_rows.groupby(grp)["quantidade"].sum()
    available_idx = a.set_index(grp)
    discrepancy = (available_idx["Saldo Disponível"] - pos_sum.reindex(available_idx.index, fill_value=0)).astype(float)
    positive_missing = discrepancy[discrepancy > .001]
    negative_missing = discrepancy[discrepancy < -.001]
    if not negative_missing.empty:
        avisos.append(
            f"{len(negative_missing)} produto(s)/armazém(ns) com soma dos endereços "
            "MAIOR que saldo disponível oficial: exibidos para auditoria, sem "
            "criar linha negativa NÃO ENDEREÇADOS."
        )
    if not positive_missing.empty:
        virtual = positive_missing.rename("quantidade").reset_index()
        virtual["Endereço"] = NAO_ENDERECADOS
        virtual = virtual.merge(
            a[grp + ["Descrição", "Valor Unitário"]], on=grp, how="left",
            validate="many_to_one",
        )
        virtual["Valor no Endereço"] = virtual["quantidade"] * virtual["Valor Unitário"]
        address_rows = pd.concat([address_rows, virtual], ignore_index=True)
    positions = address_rows.rename(columns={"quantidade": "Quantidade no Endereço"})

    ware = _armz(armazem)
    options = sorted(a["Armazém"].unique().tolist())
    if ware not in ("", "TODOS") and ware not in options:
        raise ValueError(f"Armazém não encontrado no Analítico: {ware}")
    if ware not in ("", "TODOS"):
        a = a[a["Armazém"].eq(ware)].copy()
        positions = positions[positions["Armazém"].eq(ware)].copy()

    hist = _counts(inventories or {})
    a["Quantidade de Contagens"] = [
        hist.get((c, arm), (0 if arm == "S2" else None, ""))[0]
        for c, arm in zip(a["Código"], a["Armazém"])
    ]
    a["Data da Última Contagem"] = [
        hist.get((c, arm), (0, ""))[1]
        for c, arm in zip(a["Código"], a["Armazém"])
    ]
    a["Classificação por Valor Unitário"] = _rank(a, "Valor Unitário")
    a["Classificação por Valor Agregado"] = _rank(a, "Valor em Estoque")
    positions["Classificação por Valor Unitário"] = _rank(positions, "Valor Unitário")
    positions["Classificação por Valor Agregado"] = _rank(positions, "Valor no Endereço")

    a = a.sort_values(["Valor em Estoque", "Código", "Armazém"], ascending=[False, True, True])
    positions = positions.sort_values(
        ["Valor no Endereço", "Código", "Armazém", "Endereço"],
        ascending=[False, True, True, True],
    )
    return {
        "conferencia": a.reindex(columns=GERAL_CONFERENCIA).reset_index(drop=True),
        "auditoria": a.reindex(columns=GERAL_AUDITORIA).reset_index(drop=True),
        "enderecos": positions.reindex(columns=ENDERECOS_COLS).reset_index(drop=True),
        "armazens": options,
        "avisos": avisos,
        "nao_enderecados": len(positive_missing),
        "divergencias_enderecos": len(negative_missing),
        "divergencias_central": int(diffs.sum()),
        "saldo_disponivel_total": float(a["Saldo Disponível"].sum()),
    }


def exportar_excel(geral: pd.DataFrame, posicoes: pd.DataFrame, modelo: str, armazem: str) -> bytes:
    """Duas abas no padrão tabular Protheus: cabeçalhos, filtros e números nativos."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    if modelo not in ("Conferência", "Auditoria"):
        raise ValueError("Modelo de estoque inválido.")
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        for name, frame in (("Estoque Geral", geral), ("Estoque por Endereço", posicoes)):
            frame.to_excel(writer, sheet_name=name, index=False)
            ws = writer.sheets[name]
            ws.freeze_panes = "D2"
            ws.auto_filter.ref = ws.dimensions
            ws.sheet_view.showGridLines = False
            ws.oddHeader.center.text = f"SETTA | ESTOQUE | {modelo.upper()} | ARMZ: {armazem}"
            ws.oddFooter.center.text = "Página &P de &N"
            ws.print_title_rows = "1:1"
            ws.sheet_properties.pageSetUpPr.fitToPage = True
            ws.page_setup.fitToWidth = 1
            for cell in ws[1]:
                cell.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="172033")
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            ws.row_dimensions[1].height = 30
            for i, label in enumerate(frame.columns, start=1):
                letter = get_column_letter(i)
                width = 60 if label == "Descrição" else 28 if label in ("Endereço", "Data da Última Contagem") else 23
                if label in ("Código", "Armazém"):
                    width = 16
                ws.column_dimensions[letter].width = width
                for row in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                    cell = row[0]
                    if label in ("Código", "Armazém", "Endereço"):
                        cell.number_format = "@"
                    elif "Valor" in label and "Classificação" not in label:
                        cell.number_format = MONEY
                    elif label in (
                        "Saldo em Estoque", "Saldo Não Disponível", "Saldo Disponível",
                        "Quantidade no Endereço",
                    ):
                        cell.number_format = NUM
                    elif label == "Quantidade de Contagens":
                        cell.number_format = "0"
                    if cell.row % 2 == 0:
                        cell.fill = PatternFill("solid", fgColor="F4F6FA")
            if not frame.empty:
                total_row = len(frame) + 2
                ws.cell(total_row, 1, "TOTAL")
                for col_name in ("Saldo Disponível", "Valor em Estoque",
                                 "Quantidade no Endereço", "Valor no Endereço"):
                    if col_name in frame.columns:
                        col_idx = list(frame.columns).index(col_name) + 1
                        letter = get_column_letter(col_idx)
                        cell = ws.cell(total_row, col_idx)
                        cell.value = f"=SUM({letter}2:{letter}{total_row - 1})"
                        cell.number_format = MONEY if "Valor" in col_name else NUM
                for cell in ws[total_row]:
                    cell.font = Font(name="Arial", bold=True, color="172033")
                    cell.fill = PatternFill("solid", fgColor="FFE36A")
    return out.getvalue()
