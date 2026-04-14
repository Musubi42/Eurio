/* scenes/vault-empty.js — sidecar for vault-empty.html
 *
 * Hooks the "Scanner ma première pièce" CTA to #/scan and adapts the
 * footer eyebrow text depending on whether this is a true first run or
 * an emptied vault.
 */

export function mount(ctx) {
  const { state, navigate } = ctx;
  const root = document.querySelector('[data-scene="vault-empty"]');
  if (!root) return;

  const cta = root.querySelector('[data-action="scan"]');
  cta?.addEventListener('click', () => navigate('#/scan'));

  const hint = root.querySelector('[data-role="first-run-hint"]');
  if (hint) {
    hint.textContent = state.state.firstRun
      ? 'Bienvenue sur Eurio'
      : 'Coffre vidé · recommence quand tu veux';
  }
}
