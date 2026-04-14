/* scenes/onboarding-2.js — vault preview step 2/3 */

export function mount(ctx) {
  const { navigate, state } = ctx;
  const root = document.querySelector('[data-scene="onboarding-2"]');
  if (!root) return;

  root.querySelector('[data-action="next"]')?.addEventListener('click', () => {
    navigate('#/onboarding/3');
  });
  root.querySelector('[data-action="back"]')?.addEventListener('click', () => {
    navigate('#/onboarding/1');
  });
  root.querySelector('[data-action="skip"]')?.addEventListener('click', () => {
    state.completeOnboarding?.();
    navigate('#/scan');
  });
}
