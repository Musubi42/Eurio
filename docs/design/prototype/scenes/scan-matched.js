/* scenes/scan-matched.js
 * Populates the bottom sheet with a real coin and wires the CTAs.
 *
 * - "Ajouter au coffre"  -> state.addCoin(eurioId), navigate('#/scan')
 * - "Voir la fiche"      -> navigate('#/coin/:id?ctx=scan')
 * - Close (X)            -> navigate('#/scan')
 */

// Deterministic pseudo-random P25/P75 valuation (cents) from the eurioId hash.
function mockValuation(coin) {
  const faceCents = coin.faceValueCents || 100;
  let h = 0;
  for (let i = 0; i < coin.eurioId.length; i++) {
    h = (h * 31 + coin.eurioId.charCodeAt(i)) >>> 0;
  }
  // Commemoratives & higher denominations get bigger multiples.
  const base = coin.isCommemorative ? faceCents * 2.5 : faceCents * 1.15;
  const jitter = (h % 40) / 100; // 0..0.4
  const p25 = Math.max(1, base * (1 - jitter * 0.5));
  const p75 = base * (1 + jitter);
  return { p25, p75, faceCents };
}

function formatEur(cents) {
  const eur = cents / 100;
  if (eur >= 10) return `${eur.toFixed(0)} €`;
  return `${eur.toFixed(2).replace('.', ',')} €`;
}

function rarityLabel(coin) {
  if (coin.isCommemorative) return 'Commémorative';
  if (coin.faceValueCents >= 200) return 'Courante · 2€';
  if (coin.faceValueCents >= 100) return 'Courante · 1€';
  return 'Courante';
}

export function mount(ctx) {
  const { data, state, navigate, query } = ctx;
  const root = document.querySelector('[data-scene="scan-matched"]');
  if (!root) return;

  const coin = (query && query.id && data.getCoin(query.id)) || data.randomCoin();
  if (!coin) return;

  // ── Populate slots ──
  const q = (sel) => root.querySelector(sel);

  const thumb = q('[data-slot="thumb"]');
  if (thumb) thumb.innerHTML = data.coinSvg(coin, { size: 200 });

  const countryLabel = coin.countryName || '?';
  q('[data-slot="country"]').textContent = countryLabel;

  const faceValStr = coin.faceValueCents >= 100
    ? `${(coin.faceValueCents / 100).toFixed(coin.faceValueCents % 100 === 0 ? 0 : 2).replace('.', ',')} €`
    : `${coin.faceValueCents} c`;
  q('[data-slot="face-value"]').textContent = faceValStr;

  q('[data-slot="title"]').textContent = coin.theme || `${coin.countryName} ${faceValStr}`;

  const subParts = [];
  if (coin.year) subParts.push(coin.year);
  if (coin.isCommemorative) subParts.push('Commémorative');
  subParts.push(`Réf. ${coin.eurioId}`);
  q('[data-slot="sub"]').textContent = subParts.join(' · ');

  q('[data-slot="rarity"]').textContent = rarityLabel(coin);
  q('[data-slot="kind"]').textContent = coin.isCommemorative ? 'Commémo' : 'Circulation';

  // Fake confidence — deterministic from eurioId
  let h = 0;
  for (let i = 0; i < coin.eurioId.length; i++) h = (h * 31 + coin.eurioId.charCodeAt(i)) >>> 0;
  const confidence = 87 + (h % 120) / 10; // 87.0 .. 99.0
  q('[data-slot="confidence"]').textContent = `${confidence.toFixed(1)} %`;

  const { p25, p75 } = mockValuation(coin);
  q('[data-slot="price-range"]').textContent = `${formatEur(p25)} – ${formatEur(p75)}`;

  // ── Actions ──
  root.querySelector('[data-action="add"]')?.addEventListener('click', () => {
    if (!state.hasCoin(coin.eurioId)) {
      state.addCoin(coin.eurioId, { valueAtAddCents: Math.round((p25 + p75) / 2) });
    }
    navigate('#/scan');
  });

  root.querySelector('[data-action="details"]')?.addEventListener('click', () => {
    navigate(`#/coin/${coin.eurioId}?ctx=scan`);
  });

  root.querySelector('[data-action="close"]')?.addEventListener('click', () => {
    navigate('#/scan');
  });
}
