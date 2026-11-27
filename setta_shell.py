"""Padrão visual do MRP Setta, adaptado aos fluxos do Inventário."""
from base64 import b64encode
from functools import lru_cache
from html import escape
from pathlib import Path

_ASSETS = Path(__file__).with_name("assets")

_ROUTES = {
    "Dashboard": ("Gestão de estoque", "Painel geral", "Acompanhe os indicadores, a acurácia e o andamento das contagens.", "grid_view"),
    "Inventário Rotativo": ("Gestão de estoque", "Inventário rotativo", "Acompanhe os lotes, registre contagens e trate divergências.", "inventory_2"),
    "Inventário Anual": ("Gestão de estoque", "Inventário anual", "", "calendar_month"),
    "Banco de Dados": ("Gestão de estoque", "Banco de dados", "Consulte o estoque e os relatórios de conferência.", "database"),
    "Registro": ("Gestão de estoque", "Registro", "Consulte o histórico das contagens e acompanhe os ajustes.", "assignment"),
    "Reportar Inconsistências": ("Gestão de estoque", "Reportar inconsistências", "Registre e acompanhe as inconsistências de estoque.", "fact_check"),
    "Retornos de Produção": ("Gestão de estoque", "Retornos de produção", "Acompanhe os retornos de materiais da produção.", "factory"),
    "Configurações": ("Administração", "Configurações", "Consulte as configurações e o status das fontes do Inventário.", "settings"),
}


def route_title(page):
    return _ROUTES[page][1]


def route_icon(page):
    return f":material/{_ROUTES[page][3]}:"


@lru_cache(maxsize=2)
def _encoded(name):
    return b64encode((_ASSETS / name).read_bytes()).decode("ascii")


def _stylesheet():
    # A produção pode atualizar o CSS sem reiniciar o processo Streamlit.
    return (_ASSETS / "setta-inventory.css").read_text(encoding="utf-8")


def render_shell(st, sidebar_open):
    """Emite a moldura sem ler nem alterar o estado operacional."""
    # SETTA UI — Layout padrão Streamlit
    font = _encoded("outfit-latin.woff2")
    drawer = "setta-drawer-open" if sidebar_open else "setta-drawer-closed"
    st.html(
        f'<style id="setta-inv-shell-style">@font-face{{font-family:Outfit;'
        f'src:url(data:font/woff2;base64,{font}) format("woff2");font-weight:100 900;'
        f'font-display:swap}}{_stylesheet()}</style>'
        f'<span class="setta-shell-marker {drawer}" aria-hidden="true"></span>'
    )


def render_top(st):
    try:
        navigation = (_ASSETS / "setta-inventory-navigation.js").read_text(encoding="utf-8")
    except OSError:
        navigation = ""
    st.html(
        '<header class="setta-inv-top" aria-label="Gestão de Estoque Setta">'
        '<span class="setta-inv-mark">'
        f'<img src="data:image/svg+xml;base64,{_encoded("setta-logo-oficial.svg")}" alt="Setta">'
        '</span><b>Inventário</b><small>Gestão de estoque</small></header>'
        '<div class="setta-inv-route-loader" role="status" aria-live="polite">'
        'Carregando aba…</div>'
        + (f'<script>{navigation}</script>' if navigation else ""),
        unsafe_allow_javascript=bool(navigation),
    )


def render_page(st, page):
    section, label, description, _icon = _ROUTES[page]
    summary = f'<p>{escape(description)}</p>' if description else ""
    st.html(
        '<div class="setta-inv-intro">'
        f'<div class="setta-inv-breadcrumb">{escape(section)} / {escape(label)}</div>'
        f'<h1>{escape(label)}</h1>{summary}</div>'
    )


def status_badge(status):
    status = str(status or "")
    tones = {"EM CONTAGEM": "count", "FECHADO": "closed", "AGUARDANDO ANÁLISE": "review"}
    tone = tones.get(status, "review")
    return f'<span class="inv-lot-badge inv-status-{tone}">{escape(status.capitalize())}</span>'


def render_summary(st, cycle, open_count, closed_count):
    icons = (
        '<path d="M20 7v-4m0 4h-4m4 0a9 9 0 0 0-15 1M4 17v4m0-4h4m-4 0a9 9 0 0 0 15-1"/>',
        '<path d="M4 7l8-4 8 4v10l-8 4-8-4zM4 7l8 4 8-4m-8 4v10"/>',
        '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    )
    labels = ("Ciclo atual", "Lotes em aberto", "Lotes fechados")
    markup = ['<div class="setta-inv-summary">']
    for icon, label, value in zip(icons, labels, (cycle, open_count, closed_count)):
        markup.append(
            '<div class="setta-inv-stat"><svg viewBox="0 0 24 24" aria-hidden="true" '
            f'fill="none" stroke="currentColor" stroke-width="1.6">{icon}</svg>'
            f'<div>{label}<b>{int(value)}</b></div></div>'
        )
    st.html(''.join(markup) + '</div>')


def lot_count(value, singular, plural):
    value = int(value)
    label = escape(singular if value == 1 else plural)
    return f'<div class="inv-lot-num" aria-label="{value} {label}">{value} <span>{label}</span></div>'
