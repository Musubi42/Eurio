/* scenes/onboarding-lentille.js — question-lentille (Chunk E)
 * Choix unique réversible ; « Plus tard » = Découverte. Persiste state.lens. */

export function mount(ctx) {
  const { navigate, state } = ctx;
  const root = document.querySelector('[data-scene="onboarding-lentille"]');
  if (!root) return;

  const opts = [...root.querySelectorAll('.onb-lens-opt')];
  // pré-sélectionne le choix existant (réversible)
  const current = state?.state?.lens;
  let selected = current && current !== 'discovery' ? current : null;
  const paint = () => opts.forEach(o => o.setAttribute('aria-pressed', o.dataset.lens === selected ? 'true' : 'false'));
  paint();

  opts.forEach((o) => o.addEventListener('click', () => {
    selected = (selected === o.dataset.lens) ? null : o.dataset.lens;  // re-tap = désélection
    paint();
  }));

  const persist = (lens) => {
    if (state?.state) { state.state.lens = lens; state.save?.(); }
  };

  root.querySelector('[data-action="next"]')?.addEventListener('click', () => {
    persist(selected || 'discovery');
    navigate('#/onboarding/permission');
  });
  root.querySelector('[data-action="skip"]')?.addEventListener('click', () => {
    persist('discovery');
    navigate('#/onboarding/permission');
  });
  root.querySelector('[data-action="back"]')?.addEventListener('click', () => {
    navigate('#/onboarding/3');
  });
}
