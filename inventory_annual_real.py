"""Prepare a private cut from selected real addresses, never the company-wide close."""
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import BytesIO
import re

import pandas as pd

from inventory_annual_addresses import WAREHOUSE_COLUMNS, address_book_from_report, canonical_address
from inventory_scope import code, column, norm


@dataclass(frozen=True)
class Sample:
    addresses: dict
    stock: dict
    totals: dict
    catalog: dict
    lots: dict
    tracked: set


def _fields(frame, *fields):
    cols = [column(frame, *aliases) for aliases in fields]
    if any(c is None for c in cols):
        raise ValueError("Confira as colunas obrigatórias dos relatórios ENDEREÇO e ANALÍTICO.")
    return frame[cols].fillna("").itertuples(index=False, name=None)


def _number(raw):
    text = str(raw).strip().replace("R$", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        value = Decimal(text)
        if not value.is_finite() or abs(value) > 1_000_000_000_000:
            raise InvalidOperation
        return value
    except InvalidOperation:
        raise ValueError("Um dos relatórios contém quantidade ou valor inválido.") from None


def _material(raw):
    key = code(raw)
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{0,31}", key):
        raise ValueError("Um dos relatórios contém um código de produto inválido.")
    return key


def read_export(upload, kind):
    try:
        return pd.read_excel(BytesIO(upload), dtype=str, header=1, engine="openpyxl")
    except Exception:
        raise ValueError(f"Não consegui ler o relatório {kind}. Use a exportação XLSX ou XLTX do sistema.") from None


def sample(end, analytic, selected, *, excluded=()):
    chosen = tuple(dict.fromkeys(canonical_address(line) for line in selected.splitlines() if line.strip()))
    if not 1 <= len(chosen) <= 30:
        raise ValueError("Informe de 1 a 30 endereços para a validação privada.")
    book = address_book_from_report(end, analytic=analytic, excluded=excluded)
    for a in chosen:
        if a not in book or not book[a][1]:
            raise ValueError(f"{a}: endereço inexistente ou não apto no relatório ENDEREÇO.")

    products = {}
    for raw, warehouse, desc, saldo, valor in _fields(
        analytic, ("CODIGO", "PRODUTO"), WAREHOUSE_COLUMNS, ("DESCRICAO",),
        ("SALDO EM ESTOQUE",), ("VALOR EM ESTOQUE",)
    ):
        if norm(warehouse) != "S2":
            continue
        k = _material(raw)
        previous_desc, previous_q, previous_v = products.get(k, ("", Decimal(0), Decimal(0)))
        products[k] = (previous_desc or desc.strip(), previous_q + _number(saldo), previous_v + _number(valor))
    if not products:
        raise ValueError("O relatório ANALÍTICO não tem produtos no estoque.")
    stock = {a: defaultdict(Decimal) for a in chosen}
    totals = defaultdict(Decimal)
    lots = {a: defaultdict(lambda: defaultdict(Decimal)) for a in chosen}
    has_lot = set()
    for raw, location, warehouse, lot, qtd in _fields(
        end, ("PRODUTO", "CODIGO"), ("ENDERECO", "ENDERECO FISICO", "COD ENDERECO", "LOCALIZACAO"),
        WAREHOUSE_COLUMNS, ("LOTE",), ("QUANTIDADE",)
    ):
        if norm(warehouse) != "S2" or not location.strip():
            continue
        a = canonical_address(location)
        if a not in stock:
            continue
        q = _number(qtd)
        if q < 0:
            raise ValueError(f"{a}: há saldo negativo por endereço. Corrija o relatório ou selecione outro endereço.")
        if not q:
            continue
        k = _material(raw)
        if k not in products or not products[k][0]:
            raise ValueError(f"{a}: produto {k} sem cadastro ou descrição no ANALÍTICO.")
        lot = lot.strip().upper()
        if lot:
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{0,31}", lot) or lot == "SEM-LOTE":
                raise ValueError(f"{a}: há um código de lote inválido no relatório.")
            has_lot.add(k)
        stock[a][k] += q
        totals[k] += q
        lots[a][k][lot or "SEM-LOTE"] += q
    catalog = {k: (desc, v / q if q > 0 else Decimal(0)) for k, (desc, q, v) in products.items() if desc}
    clean_lots = {a: {k: dict(ls) for k, ls in ks.items() if k in has_lot} for a, ks in lots.items()}
    return Sample({a: book[a] for a in chosen}, {a: dict(ks) for a, ks in stock.items()},
                  dict(totals), catalog, clean_lots, has_lot)
