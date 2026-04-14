/* scenes/scan-not-identified.js
 * - Renders 5 fake suggestions (decreasing scores) from data.randomCoin()
 * - Face-value chips select a degraded coin to add manually
 * - "Envoyer pour analyse" / "Ajouter en mode dégradé" show a toast
 */

const SUGG_SCORES = [0.714, 0.682, 0.651, 0.618, 0.589];

function formatFace(cents) {
  if (cents >= 100) {
    const eur = cents / 100;
    return Number.isInteger(eur) ? `${eur} €` : `${eur.toFixed(2).replace('.', ',')} €`;
  }
  return `${cents} c`;
}

export function mount(ctx) {
  const { data, state, navigate } = ctx;
  const root = document.querySelector('[data-scene="scan-not-identified"]');
  if (!root) return;

  // ── Suggestions ──
  const suggBox = root.querySelector('[data-slot="suggestions"]');
  const picks = [];
  for (let i = 0; i < 5 && i < 50; i++) {
    const c = data.randomCoin();
    if (c && !picks.find(p => p.eurioId === c.eurioId)) picks.push(c);
    if (picks.length >= 5) break;
  }
  while (picks.length < 5) {
    const c = data.randomCoin();
    if (c) picks.push(c);
    else break;
  }
  suggBox.innerHTML = picks.map((c, i) => {
    const name = c.theme || `${c.countryName} · ${formatFace(c.faceValueCents)}`;
    const year = c.year ? ` (${c.year})` : '';
    return `
      <div class="scan-ni-suggestion">
        <span class="scan-ni-suggestion__rank">${i + 1}.</span>
        <span class="scan-ni-suggestion__name">${name}${year}</span>
        <span class="scan-ni-suggestion__score">${SUGG_SCORES[i].toFixed(3)}</span>
      </div>
    `;
  }).join('');

  // ── Toast helper ──
  const toast = root.querySelector('[data-slot="toast"]');
  const showToast = (msg) => {
    if (!toast) return;
    toast.textContent = msg;
    toast.dataset.visible = 'true';
    setTimeout(() => { toast.dataset.visible = 'false'; }, 1800);
  };

  // ── Chips + manual add enablement ──
  let selectedCents = null;
  const addBtn = root.querySelector('[data-action="manual-add"]');
  root.querySelectorAll('.scan-ni-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      root.querySelectorAll('.scan-ni-chip').forEach(c => c.setAttribute('aria-pressed', 'false'));
      chip.setAttribute('aria-pressed', 'true');
      selectedCents = parseInt(chip.dataset.cents, 10);
      if (addBtn) addBtn.removeAttribute('disabled');
    });
  });

  // ── Actions ──
  root.querySelector('[data-action="retry"]')?.addEventListener('click', () => {
    navigate('#/scan');
  });

  root.querySelector('[data-action="send"]')?.addEventListener('click', () => {
    showToast('Merci, enregistré pour analyse.');
  });

  addBtn?.addEventListener('click', () => {
    if (selectedCents == null) return;
    // Grab any coin of that face value for a degraded manual entry.
    const pool = data.allCoins().filter(c => c.faceValueCents === selectedCents && !c.isCommemorative);
    const pick = pool[Math.floor(Math.random() * pool.length)];
    if (pick && !state.hasCoin(pick.eurioId)) {
      state.addCoin(pick.eurioId, { note: 'manual-degraded' });
      showToast(`Ajoutée en mode dégradé (${formatFace(selectedCents)}).`);
      setTimeout(() => navigate('#/scan'), 900);
    } else {
      showToast('Déjà dans ton coffre.');
    }
  });
}
