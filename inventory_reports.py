"""Conferência de contagens independente da autorização de ajustes no Protheus.

Este relatório pode mostrar inventários em andamento, mas nunca os transforma em
lançamentos autorizados. A carga do ERP é montada separadamente no Registro.
"""

from __future__ import annotations

from typing import Any, Mapping


def _numero(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_count_rows(inventories: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Uma linha por material/endereço com pelo menos uma contagem registrada."""
    rows: list[dict[str, Any]] = []
    for document, inventory in sorted((inventories or {}).items(), reverse=True):
        if not isinstance(inventory, dict):
            continue
        status = str(inventory.get("status") or "").strip().upper()
        for item in inventory.get("rows") or []:
            if not isinstance(item, dict):
                continue
            counts = [c for c in (item.get("contagens") or []) if isinstance(c, dict)]
            if not counts:
                continue

            first = _numero(counts[0].get("quantidade"))
            last = _numero(counts[-1].get("quantidade"))
            system = _numero(item.get("qtd_sistema"))
            final = _numero(item.get("contagem_final"))
            physical = final if final is not None else last
            divergence = (physical - system) if physical is not None and system is not None else None
            authorized = item.get("ajuste_autorizado") is True
            executed = str(item.get("ajuste_status") or "").upper() == "REALIZADO"
            ready = status == "FECHADO" and authorized and not executed

            if ready:
                situation = "AJUSTE AUTORIZADO / PENDENTE"
            elif executed:
                situation = "AJUSTE REALIZADO"
            elif status != "FECHADO":
                situation = "INVENTÁRIO EM APURAÇÃO"
            else:
                situation = "ENCERRADO SEM AJUSTE"

            history = " | ".join(
                f'{c.get("etapa") or "CONTAGEM"}: {c.get("quantidade")} '
                f'({c.get("comentario") or "SC"})'
                for c in counts
            )

            rows.append({
                "Documento": str(inventory.get("documento") or document),
                "Situação Inventário": status,
                "Código": str(item.get("codigo") or ""),
                "Descrição": str(item.get("descricao") or ""),
                "Endereço": str(item.get("endereco") or ""),
                "Qtd. Sistema": system,
                "1ª Contagem": first,
                "Última Contagem": last,
                "Contagem Final": final,
                "Saldo Físico para Conferência": physical,
                "Diferença de Quantidade": divergence,
                "Nº de Contagens": len(counts),
                "Histórico de Contagens": history,
                "Status Item": str(item.get("status") or ""),
                "Tratativa": str(item.get("tratativa_divergencia") or ""),
                "Ajuste Autorizado": "SIM" if authorized else "NÃO",
                "Situação Protheus": situation,
            })
    return rows
