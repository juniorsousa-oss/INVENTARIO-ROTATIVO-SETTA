"""Extract a quantity-free address catalog from the ENDEREÇO report layout."""
from collections import defaultdict
import re
import unicodedata

import pandas as pd

from inventory_scope import code, column, norm

WAREHOUSE_COLUMNS = ("ARMZ", "ARMAZEM", "ARMAZÉM", "COD ARMAZEM", "CODIGO ARMAZEM")
UNKNOWN_WAREHOUSE = "INDEFINIDO"


def canonical_address(value):
    text = unicodedata.normalize("NFKC", str(value or "")).upper()
    text = re.sub(r"[‐‑‒–—−]", "-", text)
    text = re.sub(r"\s*([-./])\s*", r"\1", " ".join(text.split()))
    if not re.fullmatch(r"[^\W_][\w ./()-]{0,59}", text):
        raise ValueError("Informe um endereço válido do S2.")
    return text


def _warehouse(text):
    return norm(text) or UNKNOWN_WAREHOUSE


def address_book_from_report(report, *, analytic=None, excluded=()):
    """Keep only address, warehouse and eligibility; never retain report quantities.

    Presence is based on the original report, even for rows with zero stock.
    If ENDEREÇO has no ARMZ, an address is eligible only with unambiguous
    warehouse evidence from ANALÍTICO. Mixed or incomplete evidence fails closed.
    """
    if not isinstance(report, pd.DataFrame) or report.empty:
        raise ValueError("Relatório ENDEREÇO indisponível. Não foi possível validar o cadastro.")
    addr = column(report, "ENDERECO", "ENDERECO FISICO", "COD ENDERECO", "LOCALIZACAO")
    if addr is None:
        raise ValueError("Coluna de endereço não localizada no relatório ENDEREÇO.")
    armz = column(report, *WAREHOUSE_COLUMNS)
    by_material = defaultdict(set)
    if armz is None and isinstance(analytic, pd.DataFrame) and not analytic.empty:
        analytic_armz = column(analytic, *WAREHOUSE_COLUMNS)
        if analytic_armz is not None:
            for k, w in zip(analytic.iloc[:, 0].fillna(""), analytic[analytic_armz].fillna("")):
                if material := code(k):
                    by_material[material].add(_warehouse(w))
    warehouse_values = report[armz].fillna("") if armz is not None else [""] * len(report)
    addresses = defaultdict(set)
    for raw, material, warehouse in zip(report[addr].fillna(""), report.iloc[:, 0].fillna(""), warehouse_values):
        if not str(raw).strip():
            continue
        address = canonical_address(raw)
        candidates = by_material.get(code(material), set())
        proof = _warehouse(warehouse) if armz is not None else next(iter(candidates)) if len(candidates) == 1 else UNKNOWN_WAREHOUSE
        addresses[address].add(proof)
    blocked = {canonical_address(value) for value in excluded}
    book = {}
    for address, values in sorted(addresses.items()):
        warehouse = next(iter(values)) if len(values) == 1 else UNKNOWN_WAREHOUSE
        book[address] = (warehouse, warehouse == "S2" and address not in blocked)
    if not any(eligible for _, eligible in book.values()):
        raise ValueError("O relatório ENDEREÇO não confirmou nenhum endereço apto do S2.")
    return book


def pilot_address_report():
    """Synthetic equivalent of the columns consumed from ENDEREÇO."""
    return pd.DataFrame(
        [("00000001", "S2", "A-01", 10),
         ("00000002", "S2", "a – 01", 5),
         ("00000001", "S2", "A-02", 3),
         ("00000003", "S2", "B-01", 4),
         ("00000003", "S2", "B-02", 0),
         ("00000001", "S2", "X-01", 2),
         ("00000002", "E2", "E2-01", 1)],
        columns=("CODIGO", "ARMZ", "Endereço", "Quantidade"),
    )
