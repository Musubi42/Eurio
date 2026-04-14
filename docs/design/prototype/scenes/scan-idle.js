/* scenes/scan-idle.js — sidecar for scan-idle.html
 *
 * The router imports this module via `await import('../scenes/scan-idle.js')`
 * AFTER the scene HTML has been injected. It exports `mount({ params, query,
 * state, data, navigate })` which is called once. Always idempotent and
 * cleanup-safe : listeners are scoped to elements that disappear on nav.
 */

const AUTO_MATCH_DELAY_MS = 2000;

export function mount(ctx) {
  const { data, navigate } = ctx;
  const root = document.querySelector('[data-scene="scan-idle"]');
  if (!root) return;

  // Debug button visibility
  const debugBtn = root.querySelector('.scan-idle-debug');
  const debugOn = document.querySelector('.version-badge')?.dataset.debug === 'on';
  if (debugBtn) debugBtn.dataset.debug = debugOn ? 'on' : 'off';

  // Force-match button picks a random coin
  debugBtn?.addEventListener('click', () => {
    const coin = data.randomCoin();
    if (coin) navigate(`#/scan/matched?id=${coin.eurioId}`);
  });

  // Auto-advance timer (mock ML inference)
  const timer = setTimeout(() => {
    const coin = data.randomCoin();
    if (coin) navigate(`#/scan/matched?id=${coin.eurioId}`);
  }, AUTO_MATCH_DELAY_MS);

  // Cancel the timer as soon as the user navigates elsewhere
  const onLeave = () => {
    clearTimeout(timer);
    window.removeEventListener('scene:mounted', onLeave);
    window.removeEventListener('hashchange', onLeave);
  };
  window.addEventListener('scene:mounted', onLeave, { once: true });
  window.addEventListener('hashchange', onLeave, { once: true });
}
