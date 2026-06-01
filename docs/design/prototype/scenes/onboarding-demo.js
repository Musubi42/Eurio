/* scenes/onboarding-demo.js — scan guidé sans pièce (Chunk E)
 * On « prête » une pièce-échantillon (coins.json) ; le tap lance la vraie
 * transition 3D → reveal célébré (cat. 1). Skip = on file vers le scan réel. */

export function mount(ctx) {
  const { navigate, state } = ctx;
  const root = document.querySelector('[data-scene="onboarding-demo"]');
  if (!root) return;

  // pièce-échantillon déterministe (1ʳᵉ du manifeste 3D) — sans bloquer l'UI
  let sampleId = '';
  fetch('data/coin-3d/coins.json')
    .then((r) => r.json())
    .then((m) => { sampleId = (m.coins && m.coins[0] && m.coins[0].numista_id) || ''; })
    .catch(() => { /* tap → transition choisira une pièce au hasard */ });

  const done = () => state?.completeOnboarding?.();

  root.querySelector('[data-action="skip"]')?.addEventListener('click', (e) => {
    e.stopPropagation();
    done();
    navigate('#/scan');
  });

  // tap n'importe où = scanner la pièce prêtée → transition diégétique → reveal
  root.addEventListener('click', () => {
    done();
    navigate(`#/scan/transition?id=${sampleId}`);
  });
}
