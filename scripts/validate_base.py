from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def fail(message):
    raise AssertionError(message)


app = read("app.py")
shell = read("setta_shell.py")
auth = read("setta_auth.py")
central = read("central_inventory_data.py")
requirements = read("requirements.txt")
config = read(".streamlit/config.toml")

for rel in [
    "app.py",
    "setta_shell.py",
    "setta_auth.py",
    "central_inventory_data.py",
    ".streamlit/config.toml",
]:
    if not (ROOT / rel).exists():
        fail(f"Arquivo obrigatório ausente: {rel}")

for rel in [
    ".github/inspect_sidebar.py",
    ".github/workflows/firebase_auth_patch.yml",
    ".github/workflows/inspect_sidebar.yml",
]:
    if (ROOT / rel).exists():
        fail(f"Arquivo legado retornou: {rel}")

expected_pages = [
    "Dashboard",
    "Inventário Rotativo",
    "Banco de Dados",
    "Registro",
    "Reportar Inconsistências",
    "Configurações",
]
match = re.search(r"_INV_NAV_PAGES\s*=\s*\[(.*?)\]", app, re.S)
if not match:
    fail("Lista de páginas não encontrada.")
pages = re.findall(r"'([^']+)'", match.group(1))
if pages != expected_pages:
    fail(f"Páginas divergentes: {pages}")

for page in expected_pages:
    if page == "Dashboard":
        token = "if active=='Dashboard':"
    else:
        token = f"elif active=='{page}':"
    if token not in app:
        fail(f"Renderização ausente: {page}")

for token in [
    "SETTA UI — App Shell Rounded V1",
    "max-width:1680px!important",
    "width:260px!important",
    "border-radius:24px!important",
    "top:18px!important",
    "left:44px!important",
    "@media(max-width:900px)",
]:
    if token not in shell:
        fail(f"Contrato SETTA ausente: {token}")

for token in [
    "setta_shell.render_shell(",
    "setta_drawer_toggle",
    "_setta_close_sidebar()",
    "_render_setta_auth_gate()",
]:
    if token not in app:
        fail(f"Integração SETTA ausente: {token}")

if "SIDEBAR SETTA V1" in app:
    fail("CSS legado da sidebar voltou ao app.py.")
if app.count("<style>") != 1:
    fail(f"Quantidade inesperada de blocos CSS internos: {app.count('<style>')}")

for token in ["operahub_bootstrap", "operahub_auth_user"]:
    if token not in auth:
        fail(f"Contrato de autenticação ausente: {token}")

if "return True" not in app or "_setta_auth_policy_error" not in app:
    fail("Política fail-closed da autenticação não identificada.")

central_contract = [
    "bundle_state",
    "source_normalized_download",
    "consumer_sync_status",
    "consumer_sync_commit",
    "inventory_state_get",
    "inventory_state_set",
    "derived_status",
    "derived_download",
    "visual_get",
    '"ui_config": row.get("ui_config") or {}',
]
for token in central_contract:
    if token not in central:
        fail(f"Contrato da Central ausente: {token}")

for token in [
    "def sync_central_inventory",
    "eligible_addresses_from_frame",
    "ESTOQUE_ENDERECOS_NAO_DISPONIVEIS",
    "download_derived('estoque_tratado'",
    "save_operational_state",
    "operational_state",
]:
    if token not in app:
        fail(f"Regra operacional ausente: {token}")

for token in [
    "def _cached_inventory_snapshot",
    "_central_inventory_session_token",
    "def _load_inventory_fallback",
    "def _save_local_inventory_snapshot",
]:
    if token not in app:
        fail(f"Otimização de carregamento ausente: {token}")

if "_fsdb=firestore_load_db()" in app:
    fail("Firestore voltou ao caminho crítico de inicialização.")
if "if sync_central_inventory(force=False):\n st.rerun()" in app:
    fail("Rerun extra após sincronização retornou.")

expected_requirements = {
    "streamlit==1.65.0",
    "pandas==3.0.6",
    "openpyxl==3.1.5",
    "xlrd==2.0.2",
    "firebase-admin==7.7.0",
    "requests==2.34.2",
    "Pillow==11.3.0",
    "altair==6.3.0",
}
actual = {
    line.strip()
    for line in requirements.splitlines()
    if line.strip() and not line.lstrip().startswith("#")
}
if actual != expected_requirements:
    fail(f"requirements divergente: {sorted(actual)}")

for token in [
    'base = "light"',
    'primaryColor = "#111827"',
    'backgroundColor = "#F4F7FB"',
    'toolbarMode = "minimal"',
]:
    if token not in config:
        fail(f"Configuração Streamlit ausente: {token}")

if "AUTH_REQUIRED = False" in app:
    fail("Bypass fixo de autenticação retornou.")

build = re.search(r"BUILD_DIAGNOSTICO\s*=\s*'([^']+)'", app)
if not build:
    fail("BUILD_DIAGNOSTICO ausente.")

print(
    "BASE_INVENTARIO_ROTATIVO_OK",
    {
        "build": build.group(1),
        "pages": len(expected_pages),
        "app_lines": len(app.splitlines()),
    },
)
