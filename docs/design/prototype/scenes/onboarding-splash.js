/* scenes/onboarding-splash.js — auto-advance to onboarding/1 after ~1.4s */

const AUTO_ADVANCE_MS = 1400;

export function mount(ctx) {
  const { navigate } = ctx;
  const root = document.querySelector('[data-scene="onboarding-splash"]');
  if (!root) return;

  const timer = setTimeout(() => navigate('#/onboarding/1'), AUTO_ADVANCE_MS);

  // Tap anywhere = skip splash
  root.addEventListener('click', () => {
    clearTimeout(timer);
    navigate('#/onboarding/1');
  }, { once: true });

  const cleanup = () => {
    clearTimeout(timer);
    window.removeEventListener('hashchange', cleanup);
  };
  window.addEventListener('hashchange', cleanup, { once: true });
}
