/* scenes/vault-catalog-map.js — sidecar for vault-catalog-map.html
 *
 * - Sets the fill intensity of each country path from mock progress data
 *   by writing a CSS custom property `--p` (0..1).
 * - Wires tap on country paths + micro-state pastilles → updates the peek
 *   card and navigates to /vault/catalog/:iso on subsequent tap.
 * - Toggles between map and list mode.
 */

const EUROZONE = [
  { iso: 'AT', name: 'Autriche',    flag: '🇦🇹', owned: 18, total: 42 },
  { iso: 'BE', name: 'Belgique',    flag: '🇧🇪', owned: 22, total: 38 },
  { iso: 'BG', name: 'Bulgarie',    flag: '🇧🇬', owned:  2, total: 24 },
  { iso: 'CY', name: 'Chypre',      flag: '🇨🇾', owned:  4, total: 26 },
  { iso: 'DE', name: 'Allemagne',   flag: '🇩🇪', owned: 38, total: 62 },
  { iso: 'EE', name: 'Estonie',     flag: '🇪🇪', owned:  5, total: 28 },
  { iso: 'ES', name: 'Espagne',     flag: '🇪🇸', owned: 26, total: 58 },
  { iso: 'FI', name: 'Finlande',    flag: '🇫🇮', owned: 14, total: 42 },
  { iso: 'FR', name: 'France',      flag: '🇫🇷', owned: 45, total: 68 },
  { iso: 'GR', name: 'Grèce',       flag: '🇬🇷', owned:  9, total: 38 },
  { iso: 'HR', name: 'Croatie',     flag: '🇭🇷', owned:  3, total: 26 },
  { iso: 'IE', name: 'Irlande',     flag: '🇮🇪', owned: 12, total: 34 },
  { iso: 'IT', name: 'Italie',      flag: '🇮🇹', owned: 28, total: 58 },
  { iso: 'LT', name: 'Lituanie',    flag: '🇱🇹', owned:  6, total: 28 },
  { iso: 'LU', name: 'Luxembourg',  flag: '🇱🇺', owned: 19, total: 36 },
  { iso: 'LV', name: 'Lettonie',    flag: '🇱🇻', owned:  5, total: 28 },
  { iso: 'MT', name: 'Malte',       flag: '🇲🇹', owned:  8, total: 30 },
  { iso: 'NL', name: 'Pays-Bas',    flag: '🇳🇱', owned: 20, total: 38 },
  { iso: 'PT', name: 'Portugal',    flag: '🇵🇹', owned: 16, total: 42 },
  { iso: 'SI', name: 'Slovénie',    flag: '🇸🇮', owned:  4, total: 30 },
  { iso: 'SK', name: 'Slovaquie',   flag: '🇸🇰', owned:  8, total: 34 },
];

/* Centers for the big-5 overlay labels — rough visual centroid of each
 * country's path in viewBox coordinates. */
const LABEL_CENTERS = {
  FR: { x: 155, y: 278 },
  DE: { x: 226, y: 238 },
  IT: { x: 244, y: 336 },
  ES: { x: 108, y: 350 },
  PT: { x:  44, y: 338 },
};

export function mount(ctx) {
  const { navigate } = ctx;
  const root = document.querySelector('[data-scene="vault-catalog-map"]');
  if (!root) return;

  const svg = root.querySelector('svg');
  if (!svg) return;

  applyFills(svg);
  renderLabels(svg);
  renderStats(root);
  renderList(root, navigate);

  wireCoffreTabs(root, navigate);
  wireModeToggle(root);
  wireCountryTaps(root, svg, navigate);
  wirePeek(root, navigate);
}

/* ───────── Fill each country path from --p ───────── */

function applyFills(svg) {
  svg.querySelectorAll('[data-iso]').forEach((el) => {
    const iso = el.dataset.iso;
    const entry = EUROZONE.find(c => c.iso === iso);
    if (!entry) return;
    const p = entry.owned / entry.total;
    el.style.setProperty('--p', p.toFixed(3));

    // Also tint micro pastilles by progress
    if (el.tagName.toLowerCase() === 'circle') {
      const alpha = 0.2 + p * 0.8;
      el.style.fill = `rgba(200, 168, 100, ${alpha.toFixed(2)})`;
    }
  });
}

function renderLabels(svg) {
  const g = svg.querySelector('[data-role="labels"]');
  if (!g) return;
  const frag = [];
  for (const iso of Object.keys(LABEL_CENTERS)) {
    const entry = EUROZONE.find(c => c.iso === iso);
    if (!entry) continue;
    const { x, y } = LABEL_CENTERS[iso];
    const pct = Math.round((entry.owned / entry.total) * 100);
    frag.push(`<text class="ez-label" x="${x}" y="${y - 4}">${iso}</text>`);
    frag.push(`<text class="ez-ratio" x="${x}" y="${y + 6}">${entry.owned}/${entry.total}</text>`);
  }
  g.innerHTML = frag.join('');
}

/* ───────── Stats + list ───────── */

function renderStats(root) {
  const total = EUROZONE.reduce((s, c) => s + c.total, 0);
  const owned = EUROZONE.reduce((s, c) => s + c.owned, 0);
  const s1 = root.querySelector('[data-role="stat-coins"]');
  const s2 = root.querySelector('[data-role="stat-total"]');
  if (s1) s1.textContent = owned;
  if (s2) s2.textContent = total;
}

function renderList(root, navigate) {
  const list = root.querySelector('[data-role="list"]');
  if (!list) return;
  const sorted = [...EUROZONE].sort((a, b) =>
    (b.owned / b.total) - (a.owned / a.total));

  list.innerHTML = sorted.map((c) => {
    const pct = Math.round((c.owned / c.total) * 100);
    return `
      <a class="scene-vcm-listrow" href="#/vault/catalog/${c.iso}">
        <div class="scene-vcm-listrow__flag">${c.flag}</div>
        <div class="scene-vcm-listrow__name">${c.name}</div>
        <div class="scene-vcm-listrow__bar progress-bar">
          <div class="progress-track"><div class="progress-fill" style="width: ${pct}%;"></div></div>
        </div>
        <div class="scene-vcm-listrow__ratio">${c.owned}/${c.total}</div>
      </a>
    `;
  }).join('');

  list.querySelectorAll('[href]').forEach((row) => {
    row.addEventListener('click', (e) => {
      e.preventDefault();
      const iso = row.getAttribute('href').split('/').pop();
      navigate(`#/vault/catalog/${iso}`);
    });
  });
}

/* ───────── Wiring ───────── */

function wireCoffreTabs(root, navigate) {
  root.querySelectorAll('[data-coffre-tab]').forEach((tab) => {
    tab.addEventListener('click', () => {
      const id = tab.dataset.coffreTab;
      if (id === 'coins') return navigate('#/vault');
      if (id === 'sets')  return navigate('#/vault/sets');
    });
  });
}

function wireModeToggle(root) {
  const buttons = root.querySelectorAll('[data-mode]');
  buttons.forEach((b) => {
    b.addEventListener('click', () => {
      const mode = b.dataset.mode;
      root.dataset.mode = mode;
      buttons.forEach(x => x.setAttribute('aria-selected', x === b ? 'true' : 'false'));
    });
  });
}

function wireCountryTaps(root, svg, navigate) {
  let lastTappedIso = null;
  svg.querySelectorAll('[data-iso]').forEach((el) => {
    el.addEventListener('click', () => {
      const iso = el.dataset.iso;
      if (lastTappedIso === iso) {
        navigate(`#/vault/catalog/${iso}`);
      } else {
        lastTappedIso = iso;
        updatePeek(root, iso);
      }
    });
  });
}

function wirePeek(root, navigate) {
  const peek = root.querySelector('[data-role="peek"]');
  if (!peek) return;
  peek.addEventListener('click', (e) => {
    e.preventDefault();
    const iso = peek.dataset.iso || 'FR';
    navigate(`#/vault/catalog/${iso}`);
  });
  updatePeek(root, 'FR');
}

function updatePeek(root, iso) {
  const peek = root.querySelector('[data-role="peek"]');
  const entry = EUROZONE.find(c => c.iso === iso);
  if (!peek || !entry) return;

  const pct = Math.round((entry.owned / entry.total) * 100);
  peek.dataset.iso = iso;
  peek.setAttribute('href', `#/vault/catalog/${iso}`);
  peek.querySelector('.scene-vcm-peek__flag').textContent = entry.flag;
  peek.querySelector('[data-role="peek-name"]').textContent = entry.name;
  peek.querySelector('[data-role="peek-ratio"]').textContent = `${entry.owned} / ${entry.total}`;
  peek.querySelector('[data-role="peek-fill"]').style.width = `${pct}%`;
  peek.querySelector('[data-role="peek-pct"]').textContent = `${pct}%`;
}
