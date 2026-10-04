from __future__ import annotations

import base64
import gzip
import io
import json
import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

DEFAULT_SUPABASE_URL = "https://cuixazpxkvniqldmmnth.supabase.co"
DEFAULT_SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImN1aXhhenB4a3ZuaXFsZG1tbnRoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1MTYwNTMsImV4cCI6MjEwMzA5MjA1M30.jNFaIG1FcDYnMAoVaI23UYMuRL1BpZmuqu_LPEYb88E"
CONSUMER_KEY = "inventario_rotativo"
TZ = ZoneInfo("America/Sao_Paulo")

SESSION = requests.Session()
SESSION.headers.update({"Connection": "keep-alive"})


def _secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name)
        if value:
            return str(value).strip()
    except Exception:
        pass
    return str(os.getenv(name, default) or "").strip()


def supabase_url() -> str:
    return _secret("SUPABASE_URL", DEFAULT_SUPABASE_URL).rstrip("/")


def supabase_key() -> str:
    return (
        _secret("SETTA_SUPABASE_ANON_KEY")
        or _secret("SUPABASE_ANON_KEY")
        or _secret("SUPABASE_KEY")
        or DEFAULT_SUPABASE_ANON_KEY
    )


def _headers() -> dict[str, str]:
    key = supabase_key()
    return {
        "Authorization": f"Bearer {key}",
        "apikey": key,
        "Content-Type": "application/json",
    }


def api_call(action: str, payload: dict | None = None, timeout: int = 45) -> dict:
    response = SESSION.post(
        f"{supabase_url()}/functions/v1/setta-data-api",
        headers=_headers(),
        json={"action": action, "payload": payload or {}},
        timeout=timeout,
    )
    try:
        data = response.json()
    except Exception:
        data = {"ok": False, "error": response.text}
    if not response.ok or not data.get("ok"):
        raise RuntimeError(data.get("error") or f"HTTP {response.status_code}")
    return data


@st.cache_data(show_spinner=False, ttl=30, max_entries=3)
def bundle_state() -> dict[str, dict]:
    payload = api_call(
        "bundle_state",
        {"source_keys": ["analitico", "endereco"], "derived_keys": []},
        timeout=30,
    ).get("data") or {}
    return {
        str(row.get("source_key")): row
        for row in (payload.get("sources") or [])
        if isinstance(row, dict)
    }


def source_token(meta: dict) -> str:
    return f"v{int(meta.get('version') or 0)}|{meta.get('last_update_at') or ''}"

def operational_state(keys: list[str] | None = None) -> dict[str, Any]:
    """Carrega o estado operacional persistente do Inventário no Supabase."""
    requested = keys or ["cfg", "inventories", "cycles", "reports"]
    data = api_call(
        "inventory_state_get",
        {"keys": requested},
        timeout=30,
    ).get("data") or {}
    state = data.get("state") or {}
    return state if isinstance(state, dict) else {}


def save_operational_state(state_key: str, value: Any) -> dict:
    """Persiste uma seção do estado operacional via Edge Function."""
    return api_call(
        "inventory_state_set",
        {"state_key": state_key, "value": value},
        timeout=45,
    ).get("data") or {}


def next_inventory_document() -> str:
    data = api_call("inventory_next_document", timeout=20).get("data") or {}
    documento = str(data.get("documento") or "").strip()
    if not documento:
        raise RuntimeError("DOCUMENTO_NAO_GERADO")
    return documento


def save_inventory_document(documento: str, document: dict) -> dict:
    return api_call(
        "inventory_document_upsert",
        {"documento": str(documento), "document": document or {}},
        timeout=45,
    ).get("data") or {}


def save_inventory_report(report_id: str, report: dict) -> dict:
    return api_call(
        "inventory_report_upsert",
        {"report_id": str(report_id), "report": report or {}},
        timeout=45,
    ).get("data") or {}


def merge_inventory_cycles(values: dict) -> dict:
    return api_call(
        "inventory_cycles_merge",
        {"values": values or {}},
        timeout=45,
    ).get("data") or {}


def close_inventory_atomic(
    documento: str,
    document: dict,
    cycle_codes: list[str],
    reports: dict,
) -> dict:
    return api_call(
        "inventory_close_atomic",
        {
            "documento": str(documento),
            "document": document or {},
            "cycle_codes": [str(x) for x in (cycle_codes or [])],
            "reports": reports or {},
        },
        timeout=60,
    ).get("data") or {}


def derived_status(keys: list[str]) -> dict[str, dict]:
    rows = api_call("derived_status", {"keys": keys}, timeout=30).get("data") or []
    return {
        str(row.get("base_key")): row
        for row in rows
        if isinstance(row, dict)
    }


@st.cache_data(show_spinner=False, ttl=300, max_entries=3)
def download_derived(base_key: str, version_token: str = "") -> tuple[pd.DataFrame, dict]:
    del version_token
    meta = api_call("derived_download", {"base_key": base_key}, timeout=30).get("data") or {}
    signed_url = str(meta.get("signed_url") or "")
    if not signed_url:
        raise RuntimeError(f"Base {base_key} sem URL de leitura.")
    response = SESSION.get(signed_url, timeout=120)
    response.raise_for_status()
    raw = gzip.decompress(response.content)
    frame = pd.read_json(io.BytesIO(raw), orient="table")
    return frame, meta



@st.cache_data(show_spinner=False, ttl=3600, max_entries=4)
def download_source(source_key: str, version_token: str) -> tuple[bytes, dict]:
    del version_token
    meta = api_call("source_download", {"source_key": source_key}, timeout=30).get("data") or {}
    signed_url = str(meta.get("signed_url") or "")
    if not signed_url:
        raise RuntimeError(f"Fonte {source_key} sem URL de leitura.")
    response = SESSION.get(signed_url, timeout=120)
    response.raise_for_status()
    return response.content, meta


@st.cache_data(show_spinner=False, ttl=3600, max_entries=4)
def download_source_frame(
    source_key: str,
    version_token: str,
    *,
    header: int = 1,
) -> tuple[pd.DataFrame, dict]:
    """Lê a fonte técnica normalizada; Excel é contingência para versões antigas."""
    del version_token
    try:
        meta = api_call(
            "source_normalized_download",
            {"source_key": source_key},
            timeout=30,
        ).get("data") or {}
        signed_url = str(meta.get("signed_url") or "")
        if not signed_url:
            raise RuntimeError("Fonte normalizada sem URL.")
        response = SESSION.get(signed_url, timeout=120)
        response.raise_for_status()
        pack = json.loads(gzip.decompress(response.content).decode("utf-8"))
        if str(pack.get("format") or "") != "SETTA_SOURCE_V1":
            raise RuntimeError("Formato normalizado inválido.")
        sheets = [
            row for row in (pack.get("sheets") or [])
            if isinstance(row, dict)
        ]
        if not sheets:
            raise RuntimeError("Fonte normalizada sem planilha.")
        raw = pd.DataFrame(sheets[0].get("rows") or [])
        if len(raw) <= header:
            return pd.DataFrame(), meta

        values = raw.iloc[header].tolist()
        used: dict[str, int] = {}
        columns = []
        for idx, value in enumerate(values):
            base = (
                f"Unnamed: {idx}"
                if value is None or str(value).strip() == ""
                else str(value)
            )
            count = used.get(base, 0)
            used[base] = count + 1
            columns.append(base if count == 0 else f"{base}.{count}")

        frame = raw.iloc[header + 1 :].reset_index(drop=True).copy()
        frame.columns = columns
        return frame, meta
    except Exception:
        raw, meta = download_source(source_key, "")
        return (
            pd.read_excel(
                io.BytesIO(raw),
                sheet_name=0,
                header=header,
                dtype=str,
            ),
            meta,
        )


@st.cache_data(show_spinner=False, ttl=30, max_entries=2)
def sync_state() -> dict[str, dict]:
    rows = api_call(
        "consumer_sync_status",
        {"consumer_key": CONSUMER_KEY},
        timeout=30,
    ).get("data") or []
    return {
        str(row.get("source_key")): row
        for row in rows
        if isinstance(row, dict)
    }


def commit_sync(
    source_key: str,
    version_token: str,
    source_updated_at: Any,
    rows_count: int,
    *,
    status: str = "ATUALIZADO",
    error_message: str | None = None,
) -> None:
    api_call(
        "consumer_sync_commit",
        {
            "consumer_key": CONSUMER_KEY,
            "source_key": source_key,
            "version_token": version_token,
            "source_updated_at": source_updated_at,
            "rows_count": int(rows_count or 0),
            "status": status,
            "error_message": error_message,
        },
        timeout=30,
    )
    sync_state.clear()


@st.cache_data(show_spinner=False, ttl=900, max_entries=2)
def load_visual_config() -> dict:
    # A identidade visual é opcional. Se a API estiver indisponível ou a ação
    # visual_get ainda não estiver publicada, o aplicativo deve continuar
    # funcionando com o logo/configuração local em vez de cair na inicialização.
    try:
        row = api_call(
            "visual_get",
            {"app_key": "setta_global"},
            timeout=30,
        ).get("data") or {}
    except Exception:
        row = {}
    return {
        "logo_data": row.get("logo_data") or "",
        "logo_mime": row.get("logo_mime") or "image/png",
        "favicon_data": row.get("favicon_data") or "",
        "favicon_mime": row.get("favicon_mime") or "image/png",
        "ui_config": row.get("ui_config") or {},
    }


def logo_data_uri(config: dict | None = None) -> str:
    # Um dict vazio é uma configuração válida de fallback. Não repetir a
    # chamada remota quando o carregamento inicial já falhou.
    cfg = config if config is not None else load_visual_config()
    raw = str(cfg.get("logo_data") or "").strip()
    if not raw:
        return ""
    mime = str(cfg.get("logo_mime") or "image/png")
    return f"data:{mime};base64,{raw}"


def favicon_bytes(config: dict | None = None) -> bytes:
    cfg = config if config is not None else load_visual_config()
    raw = str(cfg.get("favicon_data") or "").strip()
    if not raw:
        return b""
    try:
        return base64.b64decode(raw, validate=True)
    except Exception:
        return b""


def format_dt(value: Any) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(value)
