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
    ".gitignore",
    "supabase/migrations/20261004_inventory_atomic_state.sql",
    "supabase/migrations/20261004_inventory_auth_sessions.sql",
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
    "SETTA UI — Layout padrão Streamlit",
    "max-width:none!important",
    "width:260px!important",
    "border-radius:0!important",
    "top:18px!important",
    "left:44px!important",
    "@media(max-width:900px)",
    "if not sidebar_open:",
    "if sidebar_open:",
    'section[data-testid="stSidebar"][aria-expanded="false"]',
    "display:flex!important",
    "display:block!important",
    "visibility:visible!important",
    "transform:none!important",
    "height:auto!important",
    "max-height:none!important",
]:
    if token not in shell:
        fail(f"Contrato SETTA ausente: {token}")

for forbidden in [
    "SETTA UI — App Shell Rounded V1",
    "max-width:1680px!important",
    "max-width:1780px!important",
    "border-radius:24px!important",
    "box-shadow:0 24px 70px",
    "height:calc(100vh - 36px)!important;\n  min-height:0!important;max-height:calc(100vh - 36px)!important;",
    "overflow:hidden!important;background:#F8FAFD!important;",
]:
    if forbidden in shell:
        fail(f"Shell fixo/cortado retornou: {forbidden}")

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
for forbidden in [
    "INVENTÁRIO SETTA — LAYOUT FLUIDO FINAL MRP V1",
    "GESTÃO DE ESTOQUE — REMOVE DEFINITIVAMENTE A BORDA EXTERNA ARREDONDADA",
]:
    if forbidden in app:
        fail(f"Override estrutural paralelo voltou ao app.py: {forbidden}")
if 'style id="inventory-component-style"' not in app:
    fail("CSS operacional do Inventário não está isolado do shell canônico.")
if ":has(#inventory-component-style){display:none!important" not in app:
    fail("Bloco CSS operacional pode voltar a criar espaçamento antes do header.")
if "sidebar_auth_form" in app:
    fail("Formulário anônimo voltou a deformar a sidebar padrão.")
if "settings_auth_form" not in app:
    fail("Login administrativo não foi preservado em Configurações.")
if "BUILD DE DIAGNÓSTICO" in app:
    fail("Legenda de diagnóstico voltou ao cabeçalho principal.")
if app.count("<style") != 1:
    fail(f"Quantidade inesperada de CSS operacional no app.py: {app.count('<style')}")

for token in ["operahub_bootstrap", "inventory_login", "inventory_logout"]:
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
    "altair==6.3.0",
    "Pillow==11.3.0",
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

for token in [
    "next_inventory_document",
    "save_inventory_document",
    "save_inventory_report",
    "close_inventory_atomic",
    "merge_inventory_cycles",
]:
    if token not in central:
        fail(f"Operação atômica ausente: {token}")

for token in [
    "def _global_browser_icon",
    "central_data.favicon_bytes",
    "INVENTORY_DATA_EPOCH",
    "dashboard-chart-grid",
    "SITUAÇÃO DAS POSIÇÕES CONTADAS",
    "ACURÁCIA DOS ÚLTIMOS INVENTÁRIOS",
]:
    if token not in app:
        fail(f"Dashboard/favicon/reset ausente: {token}")

for token in [
    "DIVERGENCE_REASONS",
    "DIVERGENCE_TREATMENTS",
    "def register_divergence_treatment",
    "def _render_divergence_treatment",
    "AJUSTAR ESTOQUE",
    "ENCERRAR SEM AJUSTE",
    "Ajustes Protheus · Excel",
    "Ajustes Protheus · CSV",
    "Seleção de materiais",
    "AUTOMÁTICA",
    "MANUAL",
]:
    if token not in app:
        fail(f"Tratativa/seleção de inventário ausente: {token}")

if "pendentes=[r for r in inv.get('rows',[]) if r.get('status')!='FINALIZADO']" not in app:
    fail("Proteção contra encerramento com item pendente ausente.")

for token in [
    "_session_profile()",
    "_session_operator()",
    "America/Sao_Paulo",
    "inventory_close_atomic",
]:
    if token not in app and token not in central:
        fail(f"Segurança/rastreabilidade ausente: {token}")

for token in [
    "radio('MODO OPERACIONAL'",
    "session_state.profile",
    "def persist_all(",
    "def persist_db(",
    "def persist_eligible(",
    "def persist_reports(",
    "def readxls(",
    "def css(",
]:
    if token in app:
        fail(f"Legado operacional retornou: {token}")

if "tempfile.gettempdir()" not in app:
    fail("SQLite de contingência voltou para o diretório do projeto.")

for token in [
    "inventory_login",
    "inventory_logout",
    "inventory_token",
]:
    if token not in auth:
        fail(f"Sessão administrativa ausente: {token}")

if "visual_get" not in central:
    fail("Identidade visual global do Monitor não está sendo utilizada.")

# Proteções contra regressões desta revisão.
for token in [
    "def delete_open_inventory(",
    "delete_inventory_document(doc,_session_auth_token())",
    "inventory_delete_confirmation",
    "CONFIRMAR EXCLUSÃO",
    "if _session_profile()!='Gestor' or not inv or inv.get('status')=='FECHADO'",
    "if x.get('status')=='FECHADO'",
]:
    if token not in app:
        fail(f"Exclusão ou histórico alterado indevidamente: {token}")

for token in ["inventory_document_delete", "def delete_inventory_document("]:
    if token not in central:
        fail(f"Contrato de exclusão ausente: {token}")

if "O perfil Gestor é liberado somente" in app or "MODO OPERACIONAL:**" in app:
    fail("Textos explicativos removidos voltaram.")

if '[data-testid="stVerticalBlock"]{{gap:0!important;row-gap:0!important}}' in shell:
    fail("Sidebar voltou a eliminar o espaçamento de todas as seções.")

migration = read("supabase/migrations/20261008_inventory_delete_open.sql")
for token in [
    "inventario_delete_open_document", "inventario_deleted_documents",
    "INVENTARIO_FECHADO_NAO_PODE_EXCLUIR", "INVENTARIO_EXCLUIDO",
    "grant execute on function public.inventario_delete_open_document",
]:
    if token not in migration:
        fail(f"Proteção da exclusão ausente: {token}")

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
