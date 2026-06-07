/* scenes/scan-failure.js
 * After ~3s, auto-retry by navigating back to #/scan.
 * A user tap anywhere in the scene short-circuits the timer.
 */

const AUTO_RETRY_MS = 3000;

export function mount(ctx) {
  const { navigate } = ctx;
  const root = document.querySelector('[data-scene="scan-failure"]');
  if (!root) return;

  const retry = () => navigate('#/scan');

  const timer = setTimeout(retry, AUTO_RETRY_MS);

  root.addEventListener('click', () => {
    clearTimeout(timer);
    retry();
  }, { once: true });

  const cancel = () => {
    clearTimeout(timer);
    window.removeEventListener('scene:mounted', cancel);
    window.removeEventListener('hashchange', cancel);
  };
  window.addEventListener('scene:mounted', cancel, { once: true });
  window.addEventListener('hashchange', cancel, { once: true });
}
