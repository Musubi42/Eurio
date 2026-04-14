/* scenes/onboarding-3.js — achievements step 3/3 */

export function mount(ctx) {
  const { navigate, state } = ctx;
  const root = document.querySelector('[data-scene="onboarding-3"]');
  if (!root) return;

  root.querySelector('[data-action="next"]')?.addEventListener('click', () => {
    navigate('#/onboarding/permission');
  });
  root.querySelector('[data-action="back"]')?.addEventListener('click', () => {
    navigate('#/onboarding/2');
  });
  root.querySelector('[data-action="skip"]')?.addEventListener('click', () => {
    state.completeOnboarding?.();
    navigate('#/scan');
  });
}
