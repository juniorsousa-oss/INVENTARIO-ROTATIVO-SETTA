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

  // Remove somente as instruções de teclado, sem alterar os eventos dos
  // campos nem os contadores de caracteres que o Streamlit exibe junto.
  const inputHint = '[data-testid="InputInstructions"]';
  const keyboardHint = /^Press (?:⌘\+|Ctrl\+)?Enter to (?:apply|submit(?: form)?)$/;
  function updateInputHint(group) {
    for (const child of group.children) {
      child.toggleAttribute('data-setta-keyboard-hint', keyboardHint.test(child.textContent.trim()));
    }
  }
  function inspectInputHints(node) {
    const element = node instanceof Element ? node : node.parentElement;
    if (!element) return;
    const group = element.closest(inputHint);
    if (group) updateInputHint(group);
    if (node instanceof Element) node.querySelectorAll(inputHint).forEach(updateInputHint);
  }
  document.querySelectorAll(inputHint).forEach(updateInputHint);
  new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'characterData') inspectInputHints(record.target);
      else {
        const group = record.target instanceof Element && record.target.closest(inputHint);
        if (group) updateInputHint(group);
        for (const node of record.addedNodes) {
          if (node instanceof Element) inspectInputHints(node);
        }
      }
    }
  }).observe(document.body, {subtree: true, childList: true, characterData: true});

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
