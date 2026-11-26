"""Camera for the Annual pilot. Decode on-device; send only the QR text."""
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).with_name("assets")
HTML = """
<button type="button" data-open>Abrir câmera para ler QR</button>
<button type="button" data-close hidden>Fechar câmera</button>
<video playsinline muted autoplay hidden aria-label="Imagem da câmera"></video>
<div role="status" aria-live="polite"></div>
"""
CSS = """
[hidden] { display: none !important; }
button { font: inherit; color: var(--st-text-color); background: var(--st-background-color);
    border: 1px solid var(--st-text-color); border-radius: .5rem; padding: .45rem .8rem;
    min-height: 44px; cursor: pointer; }
button:hover, button:focus-visible { outline: 2px solid var(--st-primary-color); outline-offset: 2px; }
video { display: block; width: min(100%, 420px); max-height: 45vh; margin-top: .6rem;
    background: #111; border-radius: .5rem; object-fit: contain; }
[role=status]:not(:empty) { margin-top: .45rem; font-size: .875rem; }
"""


@lru_cache(maxsize=1)
def _component():
    import streamlit as st

    js = "\n".join((ASSETS / name).read_text(encoding="utf-8")
                   for name in ("jsqr-1.4.0.js", "annual-camera.js"))
    return st.components.v2.component("annual_pilot_camera", html=HTML, css=CSS, js=js)


def scan_qr(key):
    result = _component()(key=key, on_scanned_change=lambda: None)
    value = getattr(result, "scanned", None)
    return value if isinstance(value, str) and len(value) <= 180 else None
