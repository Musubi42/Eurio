/* scenes/onboarding-1.js — welcome step 1/3 */

export function mount(ctx) {
  const { navigate, state } = ctx;
  const root = document.querySelector('[data-scene="onboarding-1"]');
  if (!root) return;

  root.querySelector('[data-action="next"]')?.addEventListener('click', () => {
    navigate('#/onboarding/2');
  });

  root.querySelector('[data-action="skip"]')?.addEventListener('click', () => {
    state.completeOnboarding?.();
    navigate('#/scan');
  });
}
