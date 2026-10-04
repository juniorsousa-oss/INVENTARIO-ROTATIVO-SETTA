"""Autenticação central SETTA para o Inventário Rotativo.

O login é validado pelo OperaHub através da setta-data-api. A API retorna
uma sessão temporária do Inventário, usada para autorizar ações sensíveis.
"""

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


def _inventory_action(key, action, payload=None, timeout=20):
    response = HTTP_SESSION.post(
        f"{SUPABASE_PROJECT_URL}/functions/v1/setta-data-api",
        headers=_headers(key),
        json={"action": action, "payload": payload or {}},
        timeout=timeout,
    )
    try:
        data = response.json()
    except Exception:
        data = {"ok": False, "error": response.text}

    if not response.ok or not isinstance(data, dict) or not data.get("ok"):
        error = data.get("error") if isinstance(data, dict) else None
        if response.status_code == 401 and error in {
            "USUARIO_OU_SENHA_INVALIDOS",
            "SESSION_INVALID_OR_EXPIRED",
        }:
            return None
        raise RuntimeError(error or f"Erro HTTP {response.status_code}")

    result = data.get("data")
    return result if isinstance(result, dict) else {}


def bootstrap(key, timeout=15):
    data = _rpc(key, "operahub_bootstrap", timeout=timeout)
    if isinstance(data, list) and data:
        data = data[0]
    return data if isinstance(data, dict) else {}


def authenticate(key, login, password, timeout=20):
    data = _inventory_action(
        key,
        "inventory_login",
        {
            "login": str(login or "").strip(),
            "password": str(password or ""),
        },
        timeout=timeout,
    )
    if not data:
        return None

    row = data.get("user") if isinstance(data.get("user"), dict) else None
    if not row:
        return None

    return {
        "id": str(row.get("id") or ""),
        "username": str(row.get("username") or ""),
        "full_name": str(row.get("full_name") or ""),
        "email": str(row.get("email") or ""),
        "role": str(row.get("role") or ""),
        "has_avatar": bool(row.get("has_avatar", False)),
        "inventory_token": str(data.get("token") or ""),
        "session_expires_at": str(data.get("expires_at") or ""),
    }


def logout(key, auth_token, timeout=15):
    token = str(auth_token or "").strip()
    if not token:
        return True
    _inventory_action(
        key,
        "inventory_logout",
        {"auth_token": token},
        timeout=timeout,
    )
    return True
