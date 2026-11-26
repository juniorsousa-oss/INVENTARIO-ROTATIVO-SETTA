(() => {
  // O HTML do topo é reemitido pelo Streamlit; o listener é único por página.
  if (window.__settaInventoryNavigation) return;
  window.__settaInventoryNavigation = true;
  const root = document.documentElement;
  const bodySelector = '[data-testid="stMainBlockContainer"]';
  const title = () => document.querySelector('.setta-inv-intro h1')?.textContent.trim();
  const busy = new Set(['running', 'rerunRequested', 'stopRequested']);
  let pending = null;
  let frame = 0;

  function finish() {
    pending = null;
    delete root.dataset.settaInventoryNavigating;
  }

  function watch() {
    if (frame || !pending) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (!pending) return;
      const work = document.querySelector(bodySelector);
      const state = document.querySelector('[data-testid="stApp"]')?.dataset.testScriptState;
      const running = busy.has(state);
      const stale = !!work?.querySelector('[data-stale="true"]');
      const elapsed = performance.now() - pending.start;
      if (running || stale) pending.sawRender = true;
      // O novo título pode ser entregue antes do corpo da tela. Não abre a
      // máscara antes de o Streamlit terminar e remover os elementos antigos.
      if ((!running && !stale &&
            (title() === pending.target || (pending.sawRender && elapsed > 2200) ||
             (!pending.sawRender && elapsed > 1500))) ||
          state === 'compilationError' || elapsed > 25_000) {
        finish();
        return;
      }
      watch();
    });
  }

  document.addEventListener('click', event => {
    const button = event.target instanceof Element
      ? event.target.closest('.st-key-setta_route_list button') : null;
    if (!button || button.disabled || !title()) return;
    const target = button.querySelector('[data-testid="stMarkdownContainer"] p')?.textContent.trim();
    if (!target || target === pending?.target || (!pending && target === title())) return;
    pending = { target, start: performance.now(), sawRender: false };
    root.dataset.settaInventoryNavigating = 'true';
    watch();
  }, true);
})();
