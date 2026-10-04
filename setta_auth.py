"""Autenticação central SETTA baseada no cadastro do OperaHub."""

import requests

SUPABASE_PROJECT_URL = "https://cuixazpxkvniqldmmnth.supabase.co"
HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({"Connection": "keep-alive"})


def _headers(key):
    if not key:
        raise RuntimeError("SUPABASE_ANON_KEY não configurada.")
    return {
        "Authorization": f"Bearer {key}",
        "apikey": key,
        "Content-Type": "application/json",
    }


def _rpc(key, name, payload=None, timeout=20):
    response = HTTP_SESSION.post(
        f"{SUPABASE_PROJECT_URL}/rest/v1/rpc/{name}",
        headers=_headers(key),
        json=payload or {},
        timeout=timeout,
    )
    try:
        data = response.json()
    except Exception:
        data = {"error": response.text}
    if not response.ok:
        message = data.get("message") if isinstance(data, dict) else None
        error = data.get("error") if isinstance(data, dict) else None
        raise RuntimeError(message or error or f"Erro HTTP {response.status_code}")
    return data


def bootstrap(key, timeout=15):
    data = _rpc(key, "operahub_bootstrap", timeout=timeout)
    if isinstance(data, list) and data:
        data = data[0]
    return data if isinstance(data, dict) else {}


def authenticate(key, login, password, timeout=20):
    data = _rpc(
        key,
        "operahub_auth_user",
        {"p_login": str(login or "").strip(), "p_password": str(password or "")},
        timeout=timeout,
    )
    if not isinstance(data, list) or not data:
        return None
    row = data[0] if isinstance(data[0], dict) else None
    if not row:
        return None
    return {
        "id": str(row.get("id") or ""),
        "username": str(row.get("username") or ""),
        "full_name": str(row.get("full_name") or ""),
        "email": str(row.get("email") or ""),
        "role": str(row.get("role") or ""),
        "has_avatar": bool(row.get("has_avatar", False)),
    }
