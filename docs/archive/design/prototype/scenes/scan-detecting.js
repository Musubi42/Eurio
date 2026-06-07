/* scenes/scan-detecting.js
 * Auto-advance to scan-matched after the fake embedding completes.
 */

const ADVANCE_MS = 1600;

export function mount(ctx) {
  const { data, navigate } = ctx;

  const timer = setTimeout(() => {
    const coin = data.randomCoin();
    if (coin) navigate(`#/scan/matched?id=${coin.eurioId}`);
    else navigate('#/scan');
  }, ADVANCE_MS);

  const cancel = () => {
    clearTimeout(timer);
    window.removeEventListener('scene:mounted', cancel);
    window.removeEventListener('hashchange', cancel);
  };
  window.addEventListener('scene:mounted', cancel, { once: true });
  window.addEventListener('hashchange', cancel, { once: true });
}
