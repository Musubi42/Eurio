/* scenes/scan-debug.js
 * Fake tool handlers — each shows a monospace toast. "Force" actually
 * navigates to scan-matched with a random coin so the debug path is usable.
 */

const TOOL_MESSAGES = {
  dump:   'frame.jpg + meta.json written to /dumps',
  dumps:  '42 dumps (218 MB) on device',
  replay: 'replaying last 30 frames…',
  freeze: 'frame frozen · tap again to resume',
  force:  'forcing top-1 match…',
  embed:  'embed cached · 128-D · 2.1 kB',
  stats:  'session: 17 scans · 14 match · 2 fail',
};

export function mount(ctx) {
  const { data, navigate } = ctx;
  const root = document.querySelector('[data-scene="scan-debug"]');
  if (!root) return;

  const toast = root.querySelector('[data-slot="toast"]');
  const show = (msg) => {
    if (!toast) return;
    toast.textContent = msg;
    toast.dataset.visible = 'true';
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { toast.dataset.visible = 'false'; }, 1800);
  };

  root.querySelectorAll('[data-tool]').forEach(btn => {
    btn.addEventListener('click', () => {
      const tool = btn.dataset.tool;
      show(TOOL_MESSAGES[tool] || tool);
      if (tool === 'force') {
        const coin = data.randomCoin();
        setTimeout(() => {
          if (coin) navigate(`#/scan/matched?id=${coin.eurioId}`);
        }, 500);
      }
    });
  });
}
