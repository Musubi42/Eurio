/* scenes/onboarding-demo.js — scan guidé sans pièce (Chunk E)
 * On « prête » une pièce-échantillon (app_core) ; le tap lance la vraie
 * transition 3D → reveal célébré (cat. 1). Skip = on file vers le scan réel. */

import * as data from '../_shared/data.js';

export function mount(ctx) {
  const { navigate, state } = ctx;
  const root = document.querySelector('[data-scene="onboarding-demo"]');
  if (!root) return;

  // pièce-échantillon déterministe (1ʳᵉ avec textures) — sans bloquer l'UI
  let sampleId = '';
  data.init()
    .then(() => { sampleId = (data.allCoins().find((c) => data.coinTextures(c)) || {}).eurioId || ''; })
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
