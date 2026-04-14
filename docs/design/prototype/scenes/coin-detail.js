/* scenes/coin-detail.js — sidecar for coin-detail.html
 *
 * Paramétré via :
 *   params.eurioId        – id canonique
 *   query.ctx             – 'scan' | 'owned' | 'reference'  (default: 'owned')
 *
 * Récupère le coin via data.getCoin(id) (fallback data.randomCoin() pour
 * robustesse). Rendu déterministe : tous les prix mockés dérivent d'un
 * hash stable de l'eurioId pour éviter les sauts entre deux mounts.
 */

// ───────── Utilities ─────────

const EUROZONE_21 = [
  'AT','BE','BG','CY','DE','EE','ES','FI','FR','GR','HR','IE','IT',
  'LT','LU','LV','MT','NL','PT','SI','SK',
];

const COUNTRY_NAMES = {
  AT: 'Autriche', BE: 'Belgique', BG: 'Bulgarie', CY: 'Chypre', DE: 'Allemagne',
  EE: 'Estonie', ES: 'Espagne', FI: 'Finlande', FR: 'France', GR: 'Grèce',
  HR: 'Croatie', IE: 'Irlande', IT: 'Italie', LT: 'Lituanie', LU: 'Luxembourg',
  LV: 'Lettonie', MT: 'Malte', NL: 'Pays-Bas', PT: 'Portugal', SI: 'Slovénie',
  SK: 'Slovaquie', AD: 'Andorre', MC: 'Monaco', SM: 'Saint-Marin',
  VA: 'Vatican', EU: 'Union européenne',
};

const RARITY_SCALE = [
  { key: 'commune',    label: 'Commune',      gold: false },
  { key: 'peu',        label: 'Peu courante', gold: false },
  { key: 'rare',       label: 'Rare',         gold: true  },
  { key: 'tres-rare',  label: 'Très rare',    gold: true  },
];

function hashInt(str) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function seeded(seed) {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s ^ (s >>> 15), 2246822507) ^ Math.imul(s ^ (s >>> 13), 3266489909)) >>> 0;
    return (s & 0xffffffff) / 0x100000000;
  };
}

function euro(v) {
  if (v == null) return '—';
  if (v < 10) return v.toFixed(2).replace('.', ',') + ' €';
  return v.toFixed(1).replace('.', ',') + ' €';
}

function pct(v) {
  const sign = v >= 0 ? '+' : '';
  return `${sign}${v.toFixed(1).replace('.', ',')} %`;
}

function fmtInt(n) {
  if (n == null) return '—';
  return n.toLocaleString('fr-FR');
}

function fmtDate(ts) {
  try {
    return new Date(ts).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
  } catch { return '—'; }
}

// ───────── Mock market data (stable from eurioId) ─────────

/**
 * Returns mock market state for a coin, or null if it's a plain circulation
 * coin that effectively trades at face value (empty state).
 */
function mockMarket(coin) {
  const faceEur = coin.faceValue || 0;
  const rng = seeded(hashInt(coin.eurioId));
  const hasMarket = coin.isCommemorative || faceEur >= 2;
  if (!hasMarket) return null;

  // Base price : commemo 2€ → 3-15€, other commemo similar, high denom → face * 1.5
  let p50;
  if (coin.isCommemorative) {
    p50 = 3 + rng() * 12;
  } else {
    p50 = faceEur * (1.2 + rng() * 0.6);
  }
  const spread = 0.22 + rng() * 0.15;
  const p25 = p50 * (1 - spread);
  const p75 = p50 * (1 + spread);
  const deltaVsFace = faceEur > 0 ? ((p50 - faceEur) / faceEur) * 100 : 0;

  // 12 monthly points (popular commemos only). Circulation-looking = no history.
  const historyPoints = (coin.isCommemorative && rng() > 0.25) ? 12 : 0;
  let history = [];
  if (historyPoints >= 6) {
    let v = p50 * (0.75 + rng() * 0.15);
    for (let i = 0; i < historyPoints; i++) {
      const drift = (rng() - 0.4) * 0.08;
      v = Math.max(0.5, v * (1 + drift));
      history.push(v);
    }
    // Pin last point near p50
    history[history.length - 1] = p50;
  }

  const delta3m = history.length >= 3
    ? ((history[history.length - 1] - history[history.length - 4]) / history[history.length - 4]) * 100
    : null;

  // Rarity tier from p50 vs face
  let rarityIdx = 0;
  if (p50 / Math.max(faceEur, 1) > 6) rarityIdx = 3;
  else if (p50 / Math.max(faceEur, 1) > 3.5) rarityIdx = 2;
  else if (p50 / Math.max(faceEur, 1) > 1.8) rarityIdx = 1;

  // 5y projection
  const projLow = p50 * (1.1 + rng() * 0.2);
  const projHigh = projLow * (1.3 + rng() * 0.4);

  return {
    p25, p50, p75, deltaVsFace, history, delta3m,
    rarity: RARITY_SCALE[rarityIdx],
    projLow, projHigh,
  };
}

// ───────── Renderers ─────────

function renderHero({ coin, ctx, data, state }) {
  const svg = data.coinSvg(coin, { size: 200 });
  if (ctx === 'reference') {
    return `
      <div class="coin-detail-hero__photos">
        <div class="coin-detail-photo coin-detail-photo--reference">
          <span class="coin-detail-photo__label">Référence</span>
          ${svg}
        </div>
      </div>
      <div class="coin-detail-face-toggle" role="tablist">
        <button type="button" aria-selected="true">Avers</button>
        <button type="button" aria-selected="false" disabled title="Revers indisponible">Revers</button>
      </div>
    `;
  }

  const goldBadge = ctx === 'scan'
    ? `<div class="coin-detail-hero__gold-badge"><span>✦</span> Nouvelle pièce</div>`
    : '';

  const photos = `
    <div class="coin-detail-hero__photos">
      <div class="coin-detail-photo coin-detail-photo--user">
        <span class="coin-detail-photo__label">${ctx === 'scan' ? 'Ta capture' : 'Ta photo'}</span>
        ${svg}
      </div>
      <div class="coin-detail-photo coin-detail-photo--reference">
        <span class="coin-detail-photo__label">Référence</span>
        ${svg}
      </div>
    </div>
  `;

  let ownershipStrip = '';
  if (ctx === 'owned') {
    const entry = state.state.collection.find(c => c.eurioId === coin.eurioId);
    const addedAt = entry ? fmtDate(entry.addedAt) : fmtDate(Date.now() - 86400000 * 12);
    const valueAtAdd = entry?.valueAtAddCents ?? null;
    const market = mockMarket(coin);
    let deltaLabel = '—';
    let deltaClass = '';
    if (market && valueAtAdd != null) {
      const delta = market.p50 - (valueAtAdd / 100);
      deltaLabel = (delta >= 0 ? '+' : '') + euro(Math.abs(delta)).replace(' €', ' €');
      deltaClass = delta >= 0 ? 'stat-value--delta-up' : 'stat-value--delta-down';
    } else if (market) {
      deltaLabel = euro(market.p50);
    }
    ownershipStrip = `
      <div class="coin-detail-ownership">
        <div class="stat">
          <div class="stat-label">Ajoutée</div>
          <div class="stat-value">${addedAt}</div>
        </div>
        <div class="stat">
          <div class="stat-label">Condition</div>
          <div class="stat-value">${entry?.condition || 'Non renseignée'}</div>
        </div>
        <div class="stat">
          <div class="stat-label">Valeur actuelle</div>
          <div class="stat-value ${deltaClass}">${deltaLabel}</div>
        </div>
      </div>
    `;
  }

  return `
    ${goldBadge}
    ${photos}
    ${ownershipStrip}
    <div class="coin-detail-face-toggle" role="tablist">
      <button type="button" aria-selected="true">Avers</button>
      <button type="button" aria-selected="false" disabled title="Revers indisponible">Revers</button>
    </div>
  `;
}

function renderIdentity({ coin }) {
  const faceLabel = coin.faceValueCents >= 100
    ? (coin.faceValueCents % 100 === 0 ? `${coin.faceValueCents/100} €` : `${(coin.faceValueCents/100).toFixed(2).replace('.',',')} €`)
    : `${coin.faceValueCents} c`;
  const market = mockMarket(coin);
  const rarity = market?.rarity ?? RARITY_SCALE[0];
  const badgeClass = rarity.gold ? 'badge badge--gold' : 'badge';
  return `
    <div class="coin-detail-identity__value">${faceLabel}</div>
    <div class="coin-detail-identity__meta">
      <span>${coin.countryName}</span>
      <span>·</span>
      <span class="u-mono tabular">${coin.year ?? '—'}</span>
      ${coin.isCommemorative ? '<span>·</span><span>Commémorative</span>' : ''}
    </div>
    ${coin.theme ? `<div class="coin-detail-identity__theme">${coin.theme}</div>` : ''}
    <div class="coin-detail-identity__rarity">
      <span class="${badgeClass}">${rarity.label}</span>
    </div>
  `;
}

function renderValuation({ coin }) {
  const market = mockMarket(coin);
  if (!market) {
    return `<div class="coin-detail-empty">Pas encore de données de marché<br><span class="eyebrow">Pièce de circulation, valeur faciale</span></div>`;
  }
  const deltaClass = market.deltaVsFace >= 0
    ? 'coin-detail-valuation__delta--up'
    : 'coin-detail-valuation__delta--down';
  return `
    <div class="coin-detail-valuation">
      <div class="coin-detail-pct">
        <div class="coin-detail-pct__label">P25</div>
        <div class="coin-detail-pct__value">${euro(market.p25)}</div>
      </div>
      <div class="coin-detail-pct coin-detail-pct--median">
        <div class="coin-detail-pct__label">P50 · médiane</div>
        <div class="coin-detail-pct__value">${euro(market.p50)}</div>
      </div>
      <div class="coin-detail-pct">
        <div class="coin-detail-pct__label">P75</div>
        <div class="coin-detail-pct__value">${euro(market.p75)}</div>
      </div>
    </div>
    <div class="coin-detail-valuation__delta ${deltaClass}">
      ${pct(market.deltaVsFace)} vs valeur faciale (${euro(coin.faceValue)})
    </div>
  `;
}

function renderSparkline(points) {
  if (!points || points.length < 2) return '';
  const w = 320, h = 90, pad = 4;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const step = (w - pad * 2) / (points.length - 1);
  const coords = points.map((v, i) => {
    const x = pad + i * step;
    const y = pad + (h - pad * 2) * (1 - (v - min) / span);
    return [x, y];
  });
  const line = coords.map(([x,y], i) => (i === 0 ? `M${x},${y}` : `L${x},${y}`)).join(' ');
  const fill = `${line} L${coords[coords.length-1][0]},${h-pad} L${coords[0][0]},${h-pad} Z`;
  const [lx, ly] = coords[coords.length - 1];
  return `
    <svg class="coin-detail-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
      <path class="fill" d="${fill}"/>
      <path class="line" d="${line}"/>
      <circle class="point" cx="${lx}" cy="${ly}" r="4"/>
    </svg>
  `;
}

function renderHistory({ coin }) {
  const market = mockMarket(coin);
  if (!market || market.history.length < 6) {
    return `<div class="coin-detail-empty">Historique insuffisant pour tracer une tendance</div>`;
  }
  const deltaClass = market.delta3m >= 0 ? 'coin-detail-valuation__delta--up' : 'coin-detail-valuation__delta--down';
  return `
    ${renderSparkline(market.history)}
    <div class="coin-detail-history__stats">
      <div class="stat">
        <div class="stat-label">3 mois</div>
        <div class="stat-value u-mono tabular ${deltaClass}">${pct(market.delta3m)}</div>
      </div>
      <div class="stat">
        <div class="stat-label">12 mois</div>
        <div class="stat-value u-mono tabular">${market.history.length} pts</div>
      </div>
    </div>
    <button type="button" class="coin-detail-history__extend" data-action="extend-history">
      Étendre sur 5 ans
    </button>
  `;
}

function renderProjection({ coin }) {
  const market = mockMarket(coin);
  if (!market || market.history.length < 6) return { html: '', show: false };
  return {
    html: `
      <div class="coin-detail-projection">
        <div class="coin-detail-projection__label">Dans 5 ans</div>
        <div class="coin-detail-projection__range u-display-it">${euro(market.projLow)} – ${euro(market.projHigh)}</div>
        <div class="coin-detail-projection__disclaimer">Estimation indicative basée sur la tendance historique.</div>
      </div>
    `,
    show: true,
  };
}

function renderSets({ coin }) {
  const country = (coin.country || '').toUpperCase();
  const cName = COUNTRY_NAMES[country] || coin.countryName;
  const sets = [];
  if (!coin.isCommemorative) {
    sets.push({ name: `Série circulation ${cName}`, done: 6, total: 8 });
  } else {
    sets.push({ name: `Commémoratives ${cName}`, done: 2, total: 15 });
    if (coin.nationalVariants && coin.nationalVariants.length > 0) {
      sets.push({ name: `Émission commune ${coin.year}`, done: 1, total: coin.nationalVariants.length });
    }
  }
  return sets.map(s => {
    const pctVal = Math.round((s.done / s.total) * 100);
    return `
      <div class="coin-detail-set">
        <div class="coin-detail-set__head">
          <div class="coin-detail-set__name">${s.name}</div>
          <div class="coin-detail-set__count tabular">${s.done}/${s.total}</div>
        </div>
        <div class="progress-bar"><div class="progress-track"><div class="progress-fill" style="width:${pctVal}%"></div></div></div>
      </div>
    `;
  }).join('');
}

function renderDetails({ coin }) {
  const mintage = coin.raw?.observations?.wikipedia?.mintage_total ?? null;
  const sources = coin.raw?.provenance?.sources_used || [];
  const updated = coin.raw?.provenance?.last_updated || '—';
  const desc = coin.designDescription;

  let common = '';
  if (coin.nationalVariants && coin.nationalVariants.length > 0) {
    const flags = EUROZONE_21.map(cc => {
      const participating = coin.nationalVariants.includes(cc);
      return `<span class="coin-detail-common__flag" style="${participating ? '' : 'opacity:0.35;'}">${cc}</span>`;
    }).join('');
    common = `
      <div class="coin-detail-common">
        <div class="coin-detail-common__title">Émission commune zone euro</div>
        <div class="eyebrow">${coin.nationalVariants.length} pays participants · frappe nationale</div>
        <div class="coin-detail-common__flags">${flags}</div>
      </div>
    `;
  }

  return `
    <dl class="coin-detail-dl">
      <dt>Tirage total</dt>
      <dd>${fmtInt(mintage)}</dd>
      <dt>Métal</dt>
      <dd>${coin.faceValueCents >= 100 ? 'Bimétal' : coin.faceValueCents >= 10 ? 'Or nordique' : 'Acier cuivré'}</dd>
      <dt>Sources</dt>
      <dd>${sources.join(', ') || '—'}</dd>
      <dt>Dernière MAJ</dt>
      <dd>${updated}</dd>
    </dl>
    ${desc ? `<p class="coin-detail-description">${desc}</p>` : ''}
    ${common}
  `;
}

function renderCta({ coin, ctx }) {
  if (ctx === 'scan') {
    return `
      <button type="button" class="btn btn-gold" data-action="add-scan">
        Ajouter au coffre
      </button>
    `;
  }
  if (ctx === 'owned') {
    return `
      <div class="coin-detail-cta__confirm" data-confirm>
        <span>Retirer cette pièce de ton coffre ?</span>
        <div class="coin-detail-cta__confirm-actions">
          <button type="button" class="btn btn-ghost" data-action="cancel-remove">Annuler</button>
          <button type="button" class="btn btn-primary" data-action="confirm-remove">Confirmer</button>
        </div>
      </div>
      <button type="button" class="btn btn-ghost" data-action="ask-remove">
        Retirer du coffre
      </button>
    `;
  }
  // reference
  return `
    <button type="button" class="btn btn-gold" data-action="add-manual">
      Ajouter au coffre manuellement
    </button>
  `;
}

// ───────── Toast helper ─────────

function showToast(root, text) {
  const toast = root.querySelector('[data-slot="toast"]');
  if (!toast) return;
  toast.textContent = text;
  toast.dataset.open = 'true';
  setTimeout(() => { toast.dataset.open = 'false'; }, 2200);
}

// ───────── Mount ─────────

export function mount(ctx) {
  const { params, query, data, state, navigate } = ctx;
  const root = document.querySelector('[data-scene="coin-detail"]');
  if (!root) return;

  // Resolve coin with fallback
  let coin = data.getCoin(params.eurioId);
  if (!coin) {
    coin = data.randomCoin();
    if (!coin) return;
    console.warn(`[coin-detail] unknown eurioId "${params.eurioId}", fallback → ${coin.eurioId}`);
  }

  const scanctx = (query.ctx || 'owned').toLowerCase();
  const validCtx = ['scan', 'owned', 'reference'].includes(scanctx) ? scanctx : 'owned';

  // Populate slots
  const hero = root.querySelector('[data-slot="hero"]');
  hero.dataset.ctx = validCtx;
  hero.innerHTML = renderHero({ coin, ctx: validCtx, data, state });

  root.querySelector('[data-slot="identity"]').innerHTML = renderIdentity({ coin });
  root.querySelector('[data-slot="valuation"]').innerHTML = renderValuation({ coin });
  root.querySelector('[data-slot="history"]').innerHTML = renderHistory({ coin });

  const proj = renderProjection({ coin });
  const projWrap = root.querySelector('[data-slot-wrap="projection"]');
  if (proj.show) {
    root.querySelector('[data-slot="projection"]').innerHTML = proj.html;
  } else {
    projWrap.style.display = 'none';
  }

  root.querySelector('[data-slot="sets"]').innerHTML = renderSets({ coin });
  root.querySelector('[data-slot="details"]').innerHTML = renderDetails({ coin });
  root.querySelector('[data-slot="cta"]').innerHTML = renderCta({ coin, ctx: validCtx });

  const title = root.querySelector('[data-slot="topbar-title"]');
  if (title) {
    title.textContent = validCtx === 'scan'
      ? 'Résultat du scan'
      : validCtx === 'owned' ? 'Dans ton coffre' : 'Référence';
  }

  // ───── Wire actions ─────
  root.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;

    if (action === 'back') {
      if (validCtx === 'scan') navigate('#/scan');
      else if (validCtx === 'owned') navigate('#/vault');
      else history.length > 1 ? history.back() : navigate('#/vault');
      return;
    }

    if (action === 'add-scan') {
      state.addCoin(coin.eurioId, { valueAtAddCents: Math.round((mockMarket(coin)?.p50 ?? coin.faceValue) * 100) });
      showToast(root, 'Ajoutée au coffre');
      setTimeout(() => navigate('#/scan'), 700);
      return;
    }

    if (action === 'add-manual') {
      state.addCoin(coin.eurioId, { valueAtAddCents: Math.round((mockMarket(coin)?.p50 ?? coin.faceValue) * 100) });
      showToast(root, 'Ajoutée au coffre');
      return;
    }

    if (action === 'ask-remove') {
      root.querySelector('[data-confirm]').dataset.open = 'true';
      return;
    }
    if (action === 'cancel-remove') {
      root.querySelector('[data-confirm]').dataset.open = 'false';
      return;
    }
    if (action === 'confirm-remove') {
      state.removeCoin(coin.eurioId);
      showToast(root, 'Retirée du coffre');
      setTimeout(() => navigate('#/vault'), 700);
      return;
    }

    if (action === 'extend-history') {
      showToast(root, 'Vue 5 ans · bientôt');
      return;
    }
  });
}
