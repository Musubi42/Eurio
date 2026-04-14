/* scenes/vault-filters.js — sidecar for vault-filters.html
 *
 * Persistence : state.prefs.vaultFilters (object) — survives reload because
 * state.save() hits localStorage.
 *
 * Filter shape :
 *   {
 *     countries: string[],       // iso codes lowercase
 *     faceValueCents: number[],  // e.g. [100, 200]
 *     types: string[],           // 'circulation' | 'commemorative' | 'common'
 *     rarities: string[],
 *     conditions: string[],
 *     yearMin: number,
 *     yearMax: number,
 *   }
 *
 * Count in CTA = number of coins in state.collection that match.
 */

const DEFAULT = {
  countries: [],
  faceValueCents: [],
  types: [],
  rarities: [],
  conditions: [],
  yearMin: 1999,
  yearMax: 2026,
};

export function mount(ctx) {
  const { state, data, navigate } = ctx;
  const root = document.querySelector('[data-scene="vault-filters"]');
  if (!root) return;

  state.state.prefs.vaultFilters = state.state.prefs.vaultFilters || structuredClone(DEFAULT);
  const filters = state.state.prefs.vaultFilters;

  renderCountries(root, data, filters);
  hydrateChips(root, filters);
  hydrateYear(root, filters);
  wire(root, state, data, filters, navigate);
  updateCount(root, state, data, filters);
}

function renderCountries(root, data, filters) {
  const host = root.querySelector('[data-role="countries"]');
  if (!host) return;
  const countries = data.allCountries();
  host.innerHTML = countries.map(c => `
    <button type="button" class="vault-filters-chip" data-value="${c}"
            aria-pressed="${filters.countries.includes(c) ? 'true' : 'false'}">
      ${c.toUpperCase()}
    </button>
  `).join('');
}

function hydrateChips(root, filters) {
  const map = [
    ['[data-role="face-values"] .vault-filters-chip', filters.faceValueCents, v => Number(v)],
    ['[data-role="types"] .vault-filters-chip',       filters.types,          v => v],
    ['[data-role="rarity"] .vault-filters-chip',      filters.rarities,       v => v],
    ['[data-role="condition"] .vault-filters-chip',   filters.conditions,     v => v],
  ];
  for (const [sel, list, cast] of map) {
    root.querySelectorAll(sel).forEach(btn => {
      const raw = cast(btn.dataset.value);
      btn.setAttribute('aria-pressed', list.includes(raw) ? 'true' : 'false');
    });
  }
}

function hydrateYear(root, filters) {
  const min = root.querySelector('[data-role="year-min"]');
  const max = root.querySelector('[data-role="year-max"]');
  if (min) min.value = filters.yearMin;
  if (max) max.value = filters.yearMax;
}

function wire(root, state, data, filters, navigate) {
  // Chip toggles
  const onChip = (listKey, cast) => (ev) => {
    const btn = ev.target.closest('.vault-filters-chip');
    if (!btn) return;
    const value = cast(btn.dataset.value);
    const arr = filters[listKey];
    const idx = arr.indexOf(value);
    if (idx >= 0) arr.splice(idx, 1); else arr.push(value);
    btn.setAttribute('aria-pressed', idx >= 0 ? 'false' : 'true');
    state.save();
    updateCount(root, state, data, filters);
  };

  root.querySelector('[data-role="countries"]')
      ?.addEventListener('click', onChip('countries', v => v));
  root.querySelector('[data-role="face-values"]')
      ?.addEventListener('click', onChip('faceValueCents', v => Number(v)));
  root.querySelector('[data-role="types"]')
      ?.addEventListener('click', onChip('types', v => v));
  root.querySelector('[data-role="rarity"]')
      ?.addEventListener('click', onChip('rarities', v => v));
  root.querySelector('[data-role="condition"]')
      ?.addEventListener('click', onChip('conditions', v => v));

  // Year inputs
  const yearMin = root.querySelector('[data-role="year-min"]');
  const yearMax = root.querySelector('[data-role="year-max"]');
  yearMin?.addEventListener('change', () => {
    filters.yearMin = clampYear(Number(yearMin.value));
    yearMin.value = filters.yearMin;
    state.save();
    updateCount(root, state, data, filters);
  });
  yearMax?.addEventListener('change', () => {
    filters.yearMax = clampYear(Number(yearMax.value));
    yearMax.value = filters.yearMax;
    state.save();
    updateCount(root, state, data, filters);
  });

  // Close / apply / reset
  root.querySelector('[data-action="close"]')
      ?.addEventListener('click', () => navigate('#/vault'));
  root.querySelector('[data-action="apply"]')
      ?.addEventListener('click', () => navigate('#/vault'));
  root.querySelector('[data-action="reset"]')
      ?.addEventListener('click', () => {
        Object.assign(filters, structuredClone(DEFAULT_MUT()));
        state.save();
        hydrateChips(root, filters);
        hydrateYear(root, filters);
        // Reset country chips too
        root.querySelectorAll('[data-role="countries"] .vault-filters-chip')
            .forEach(b => b.setAttribute('aria-pressed', 'false'));
        updateCount(root, state, data, filters);
      });
}

function DEFAULT_MUT() {
  return {
    countries: [],
    faceValueCents: [],
    types: [],
    rarities: [],
    conditions: [],
    yearMin: 1999,
    yearMax: 2026,
  };
}

function clampYear(y) {
  if (Number.isNaN(y)) return 1999;
  return Math.max(1999, Math.min(2026, Math.round(y)));
}

/* Count how many coins in the vault match the current filters. */
function updateCount(root, state, data, filters) {
  const collection = state.state.collection;
  let n = 0;
  for (const entry of collection) {
    if (matches(entry, filters, data)) n++;
  }
  const el = root.querySelector('[data-role="count"]');
  if (el) el.textContent = String(n);
}

function matches(entry, filters, data) {
  const coin = data.getCoin(entry.eurioId);
  if (!coin) return false;

  if (filters.countries.length && !filters.countries.includes(coin.country)) return false;

  if (filters.faceValueCents.length && !filters.faceValueCents.includes(coin.faceValueCents)) return false;

  if (filters.yearMin && coin.year && coin.year < filters.yearMin) return false;
  if (filters.yearMax && coin.year && coin.year > filters.yearMax) return false;

  if (filters.types.length) {
    const t = coin.isCommemorative ? 'commemorative' : 'circulation';
    if (!filters.types.includes(t)) return false;
  }

  // Rarity & condition are mock-only (not in referential) — if user selects any,
  // we don't eliminate any coin because we cannot know.
  return true;
}
