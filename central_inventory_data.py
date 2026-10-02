from __future__ import annotations

import base64
import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

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


@st.cache_data(show_spinner=False, ttl=60, max_entries=2)
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
