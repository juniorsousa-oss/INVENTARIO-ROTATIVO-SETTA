"""Regras do escopo do Inventário Rotativo: exclusivamente S2.

Não interpreta o endereço físico como armazém contábil. A fonte oficial é
ANALÍTICO (ARMZ) e o cadastro de chapas/barras vem do Fechamento Mensal.
Se não for possível confirmar o armazém, não libera o item para contagem.
"""
from __future__ import annotations

import unicodedata
import re
from typing import Iterable
import pandas as pd


def norm(text: object) -> str:
    v = unicodedata.normalize("NFKD", str(text or ""))
    v = "".join(x for x in v if not unicodedata.combining(x))
    return re.sub(r"\s+", " ", v.upper().strip())


def code(value: object) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"\d+\.0", raw):
        raw = raw[:-2]
    return raw.zfill(8) if raw.isdigit() and len(raw) <= 8 else raw


def column(frame: pd.DataFrame, *aliases: str) -> str | None:
    names = {norm(name): name for name in frame.columns}
    for alias in aliases:
        if norm(alias) in names:
            return names[norm(alias)]
    return None


def catalog_exclusions(rows: Iterable[dict]) -> set[str]:
    return {
        code(row.get("codigo"))
        for row in rows
        if str(row.get("categoria") or "").upper() in {"CHAPA", "BARRA_COBRE"}
        and code(row.get("codigo"))
    }


def filter_s2_sources(
    analytic: pd.DataFrame,
    addresses: pd.DataFrame,
    excluded: Iterable[str],
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Retorna apenas linhas vinculáveis com segurança ao armazém S2.

    Quando ENDEREÇO não contém ARMZ, só são aceitos códigos exclusivos de S2
    no ANALÍTICO. Códigos multi-armazém ficam bloqueados, pois não seria
    possível atribuir posições a S2 sem inventar vínculo.
    """
    if analytic is None or analytic.empty or addresses is None or addresses.empty:
        raise ValueError("FONTES ANALÍTICO/ENDEREÇO NÃO DISPONÍVEIS PARA VALIDAR O S2.")
    if len(analytic.columns) < 11 or len(addresses.columns) < 8:
        raise ValueError("LAYOUT DAS FONTES INCOMPATÍVEL COM O INVENTÁRIO S2.")
    warehouse_col = column(analytic, "ARMZ", "ARMAZEM", "ARMAZÉM", "COD ARMAZEM", "CODIGO ARMAZEM")
    type_col = column(analytic, "TP", "TIPO", "TIPO PRODUTO", "TIPO DE PRODUTO")
    if warehouse_col is None:
        raise ValueError("COLUNA ARMZ NÃO LOCALIZADA NO ANALÍTICO. INVENTÁRIO S2 BLOQUEADO PARA EVITAR CONTAGEM DE OUTROS ARMAZÉNS.")
    # Não inferir tipo apenas pela descrição ou local: bloquear PA quando TP existe.
    if type_col is None:
        raise ValueError("COLUNA TP NÃO LOCALIZADA NO ANALÍTICO. NÃO É POSSÍVEL EXCLUIR PRODUTOS ACABADOS COM SEGURANÇA.")

    excluded_codes = {code(x) for x in excluded}
    all_analytic = analytic.copy()
    all_analytic["_inv_codigo"] = all_analytic.iloc[:, 0].map(code)
    all_analytic["_inv_armz"] = all_analytic[warehouse_col].astype(str).map(norm)
    all_analytic["_inv_tp"] = all_analytic[type_col].astype(str).map(norm)

    s2 = all_analytic[
        all_analytic["_inv_armz"].eq("S2")
        & ~all_analytic["_inv_tp"].eq("PA")
        & ~all_analytic["_inv_codigo"].isin(excluded_codes)
    ].copy()
    address_warehouse = column(addresses, "ARMZ", "ARMAZEM", "ARMAZÉM", "COD ARMAZEM", "CODIGO ARMAZEM")
    source_codes = set(s2["_inv_codigo"])
    ambiguous_codes = set()
    if address_warehouse is None:
        other_warehouse_codes = set(all_analytic.loc[
            ~all_analytic["_inv_armz"].eq("S2"), "_inv_codigo"
        ])
        ambiguous_codes = source_codes & other_warehouse_codes
        source_codes -= ambiguous_codes
        s2 = s2[s2["_inv_codigo"].isin(source_codes)]
    pos = addresses.copy()
    pos["_inv_codigo"] = pos.iloc[:, 0].map(code)
    pos = pos[pos["_inv_codigo"].isin(source_codes)].copy()
    if address_warehouse is not None:
        pos = pos[pos[address_warehouse].astype(str).map(norm).eq("S2")].copy()
    analytic_s2 = s2.drop(columns=["_inv_codigo", "_inv_armz", "_inv_tp"])
    position_s2 = pos.drop(columns=["_inv_codigo"])
    result = {
        "warehouse": "S2",
        "catalog_excluded": len(excluded_codes),
        "eligible_codes": len(source_codes),
        "blocked_ambiguous_codes": len(ambiguous_codes),
        "has_address_warehouse": address_warehouse is not None,
        "eligible_positions": len(position_s2),
    }
    return analytic_s2, position_s2, result


def classify_past_row(
    row: dict, excluded: set[str], s2_codes: set[str], known_non_s2: set[str]
) -> str:
    """Classificação não destrutiva de posição já salva no histórico."""
    material = code(row.get("codigo"))
    if material in excluded:
        return "FECHAMENTO CHAPAS/BARRAS"
    if material in known_non_s2:
        return "FORA DO S2"
    if material not in s2_codes:
        return "S2 NÃO COMPROVADO"
    return "S2"


def is_in_scope(row: dict, excluded: set[str], s2_codes: set[str], known_non_s2: set[str]) -> bool:
    return classify_past_row(row, excluded, s2_codes, known_non_s2) == "S2"
