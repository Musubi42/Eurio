/* scenes/onboarding-permission.js — pre-prompt camera permission */

const FADE_MS = 400;

export function mount(ctx) {
  const { navigate, state } = ctx;
  const root = document.querySelector('[data-scene="onboarding-permission"]');
  if (!root) return;

  const finish = () => {
    state.completeOnboarding?.();
    root.dataset.state = 'accepting';
    setTimeout(() => navigate('#/scan'), FADE_MS);
  };

  root.querySelector('[data-action="allow"]')?.addEventListener('click', finish);

  root.querySelector('[data-action="later"]')?.addEventListener('click', () => {
    state.completeOnboarding?.();
    navigate('#/scan');
  });

  root.querySelector('[data-action="back"]')?.addEventListener('click', () => {
    navigate('#/onboarding/3');
  });
}
