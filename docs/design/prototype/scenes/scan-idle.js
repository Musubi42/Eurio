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

  // Force-match → the diégetic transition (it picks a random 3D coin itself).
  debugBtn?.addEventListener('click', () => {
    navigate('#/scan/transition');
  });

  // Auto-advance timer (mock ML inference)
  // The 3.6 MB referential fetch can outrun the 2s delay on a cold cache,
  // so we await data.init() (idempotent) before arming the timer.
  let timer = null;
  let cancelled = false;

  // Cancel the pending auto-advance only when the user actually LEAVES the scene
  // (any hash navigation). NOT on `scene:mounted` — the router fires that for
  // scan-idle's OWN mount, which would self-cancel the timer before it can run.
  const onLeave = () => {
    cancelled = true;
    if (timer) clearTimeout(timer);
    window.removeEventListener('hashchange', onLeave);
  };
  window.addEventListener('hashchange', onLeave, { once: true });

  data.init().then(() => {
    if (cancelled) return;
    timer = setTimeout(() => {
      // Mock ML inference resolved → play the diégetic transition → reveal.
      navigate('#/scan/transition');
    }, AUTO_MATCH_DELAY_MS);
  });
}
