/* scenes/vault-remove-confirm.js — overlay sidecar
 *
 * Unlike normal scenes, this module is mounted manually by
 * vault-home.js openRemoveOverlay(). It does NOT rely on router.js
 * auto-import (filename lookup would fail for non-routed scenes anyway).
 *
 * ctx shape : { eurioId, overlay, data, state, navigate }
 */

const UNDO_TIMEOUT_MS = 5000;

export function mount(ctx) {
  const { eurioId, overlay, data, state } = ctx;
  if (!overlay) return;

  const coin = data.getCoin(eurioId);
  const metaEl = overlay.querySelector('[data-role="coin-meta"]');
  if (metaEl && coin) {
    metaEl.textContent =
      `${coin.countryName} · ${formatFaceValue(coin.faceValueCents)}${coin.year ? ' · ' + coin.year : ''}`;
  }

  // Mock "set broken" warning for commemoratives
  const warning = overlay.querySelector('[data-role="warning"]');
  const warningText = overlay.querySelector('[data-role="warning-text"]');
  if (coin?.isCommemorative && warning && warningText) {
    warning.hidden = false;
    warningText.textContent = `Cela brisera la série ${coin.countryName} commémorative.`;
  }

  const close = () => overlay.remove();

  overlay.addEventListener('click', (ev) => {
    if (ev.target === overlay) close();
  });

  overlay.querySelector('[data-action="cancel"]')
    ?.addEventListener('click', close);

  overlay.querySelector('[data-action="confirm"]')
    ?.addEventListener('click', () => {
      // Snapshot for undo
      const entry = state.state.collection.find(e => e.eurioId === eurioId);
      const snapshot = entry ? { ...entry } : null;

      state.removeCoin(eurioId);
      close();
      showUndoToast(snapshot, state, ctx);

      // Re-render vault-home to reflect removal
      if (location.hash.startsWith('#/vault')) {
        import('./vault-home.js')
          .then(mod => mod.mount && mod.mount({
            state, data,
            navigate: ctx.navigate,
            params: {}, query: {},
          }))
          .catch(() => {});
      }
    });
}

function showUndoToast(snapshot, state, ctx) {
  const host = document.querySelector('.screen');
  if (!host) return;

  const toast = document.createElement('div');
  toast.className = 'vault-remove-toast';
  toast.innerHTML = `
    <span>Pièce retirée</span>
    <button type="button" class="vault-remove-toast__undo" data-action="undo">Annuler</button>
  `;
  host.appendChild(toast);

  const timer = setTimeout(() => toast.remove(), UNDO_TIMEOUT_MS);

  toast.querySelector('[data-action="undo"]').addEventListener('click', () => {
    clearTimeout(timer);
    if (snapshot) {
      state.addCoin(snapshot.eurioId, {
        valueAtAddCents: snapshot.valueAtAddCents,
        condition: snapshot.condition,
        note: snapshot.note,
      });
    }
    toast.remove();
    // Re-render vault-home
    if (location.hash.startsWith('#/vault')) {
      import('./vault-home.js')
        .then(mod => mod.mount && mod.mount({
          state,
          data: ctx.data,
          navigate: ctx.navigate,
          params: {}, query: {},
        }))
        .catch(() => {});
    }
  });
}

function formatFaceValue(cents) {
  if (cents >= 100) {
    const eur = cents / 100;
    return Number.isInteger(eur) ? `${eur} €` : `${eur.toFixed(2).replace('.', ',')} €`;
  }
  return `${cents} c`;
}
