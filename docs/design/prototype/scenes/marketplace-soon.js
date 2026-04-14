/* scenes/marketplace-soon.js — sidecar for marketplace-soon.html (Agent B5-bis)
 *
 * Wires the close button and the "Me prévenir" mock CTA.
 */

function showToast(root, text) {
  const el = root.querySelector('[data-bind="toast"]');
  if (!el) return;
  el.textContent = text;
  el.classList.add('is-on');
  setTimeout(() => el.classList.remove('is-on'), 1800);
}

export function mount(ctx) {
  const { navigate } = ctx;
  const root = document.querySelector('[data-scene="marketplace-soon"]');
  if (!root) return;

  const goBack = () => {
    if (window.history.length > 1) {
      window.history.back();
    } else if (navigate) {
      navigate('#/scan');
    }
  };

  root.querySelector('[data-action="close"]')?.addEventListener('click', (ev) => {
    ev.preventDefault();
    goBack();
  });

  // Click on the backdrop also closes (matches the modal intent).
  root.querySelector('.marketplace-backdrop')?.addEventListener('click', () => {
    goBack();
  });

  root.querySelector('[data-action="notify"]')?.addEventListener('click', (ev) => {
    ev.preventDefault();
    showToast(root, 'Merci — on te notifiera au lancement');
  });
}
