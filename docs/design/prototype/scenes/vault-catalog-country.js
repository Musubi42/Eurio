/* scenes/vault-catalog-country.js — sidecar for vault-catalog-country.html
 *
 * Renders the planche of all coins for a given country (mock data).
 * Route : /vault/catalog/:iso — falls back to FR for unknown isos.
 */

const COUNTRIES = {
  FR: {
    name: 'France',
    flag: '🇫🇷',
    coins: [
      // circulation (8)
      { eurioId: 'fr-001', type: 'circulation', metal: 'copper',  val: '1c',  owned: true,  scannedAt: '2026-02-22' },
      { eurioId: 'fr-002', type: 'circulation', metal: 'copper',  val: '2c',  owned: true,  scannedAt: '2026-02-22' },
      { eurioId: 'fr-005', type: 'circulation', metal: 'copper',  val: '5c',  owned: true,  scannedAt: '2026-02-28' },
      { eurioId: 'fr-010', type: 'circulation', metal: 'nordic',  val: '10c', owned: true,  scannedAt: '2026-03-05' },
      { eurioId: 'fr-020', type: 'circulation', metal: 'nordic',  val: '20c', owned: true,  scannedAt: '2026-03-12' },
      { eurioId: 'fr-050', type: 'circulation', metal: 'nordic',  val: '50c', owned: true,  scannedAt: '2026-03-18' },
      { eurioId: 'fr-100', type: 'circulation', metal: 'silver',  val: '1€',  owned: true,  scannedAt: '2026-03-25' },
      { eurioId: 'fr-200', type: 'circulation', metal: 'bimetal', val: '2€',  owned: true,  scannedAt: '2026-03-30' },
      // commemos (10)
      { eurioId: 'fr-c01', type: 'commemo', metal: 'bimetal', val: '2€', owned: true,  scannedAt: '2026-04-02' },
      { eurioId: 'fr-c02', type: 'commemo', metal: 'bimetal', val: '2€', owned: true,  scannedAt: '2026-04-04' },
      { eurioId: 'fr-c03', type: 'commemo', metal: 'bimetal', val: '2€', owned: true,  scannedAt: '2026-04-08' },
      { eurioId: 'fr-c04', type: 'commemo', metal: 'bimetal', val: '2€', owned: true,  scannedAt: '2026-04-12' },
      { eurioId: 'fr-c05', type: 'commemo', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
      { eurioId: 'fr-c06', type: 'commemo', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
      { eurioId: 'fr-c07', type: 'commemo', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
      { eurioId: 'fr-c08', type: 'commemo', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
      { eurioId: 'fr-c09', type: 'commemo', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
      { eurioId: 'fr-c10', type: 'commemo', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
    ],
  },
  IT: {
    name: 'Italie',
    flag: '🇮🇹',
    coins: [
      { eurioId: 'it-001', type: 'circulation', metal: 'copper',  val: '1c',  owned: true,  scannedAt: '2026-03-12' },
      { eurioId: 'it-002', type: 'circulation', metal: 'copper',  val: '2c',  owned: true,  scannedAt: '2026-03-12' },
      { eurioId: 'it-005', type: 'circulation', metal: 'copper',  val: '5c',  owned: true,  scannedAt: '2026-03-18' },
      { eurioId: 'it-010', type: 'circulation', metal: 'nordic',  val: '10c', owned: true,  scannedAt: '2026-03-29' },
      { eurioId: 'it-020', type: 'circulation', metal: 'nordic',  val: '20c', owned: true,  scannedAt: '2026-04-02' },
      { eurioId: 'it-050', type: 'circulation', metal: 'nordic',  val: '50c', owned: false, scannedAt: null },
      { eurioId: 'it-100', type: 'circulation', metal: 'silver',  val: '1€',  owned: false, scannedAt: null },
      { eurioId: 'it-200', type: 'circulation', metal: 'bimetal', val: '2€',  owned: false, scannedAt: null },
      { eurioId: 'it-c01', type: 'commemo', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
      { eurioId: 'it-c02', type: 'commemo', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
    ],
  },
};

export function mount(ctx) {
  const { params, navigate } = ctx;
  const root = document.querySelector('[data-scene="vault-catalog-country"]');
  if (!root) return;

  const iso = (params && params.iso) ? String(params.iso).toUpperCase() : 'FR';
  const country = COUNTRIES[iso] || COUNTRIES.FR;

  renderHero(root, country);
  renderPlanche(root, country, navigate);
  wireFilters(root, country, navigate);

  // Back button
  const back = root.querySelector('.scene-vcc-back');
  if (back) {
    back.addEventListener('click', (e) => {
      e.preventDefault();
      navigate('#/vault/catalog');
    });
  }
}

function renderHero(root, country) {
  const owned = country.coins.filter(c => c.owned).length;
  const total = country.coins.length;
  const pct = Math.round((owned / total) * 100);

  const flag = root.querySelector('[data-role="flag"]');
  const name = root.querySelector('[data-role="name"]');
  const ratio = root.querySelector('[data-role="ratio"]');
  const pctEl = root.querySelector('[data-role="pct"]');
  const fill = root.querySelector('[data-role="fill"]');

  if (flag) flag.textContent = country.flag;
  if (name) name.textContent = country.name;
  if (ratio) ratio.textContent = `${owned} / ${total}`;
  if (pctEl) pctEl.textContent = `${pct}%`;
  if (fill) fill.style.width = `${pct}%`;
}

function renderPlanche(root, country, navigate, filter = 'all') {
  const grid = root.querySelector('[data-role="planche-grid"]');
  const count = root.querySelector('[data-role="planche-count"]');
  if (!grid) return;

  const coins = filter === 'all'
    ? country.coins
    : country.coins.filter(c => c.type === filter);

  if (count) count.textContent = `${coins.length} pièces`;

  grid.innerHTML = coins.map((coin) => {
    if (!coin.owned) {
      return `
        <div class="planche__cell planche__cell--missing"
             data-coin-id="${escapeHtml(coin.eurioId)}"
             data-owned="false">
          <div class="disc disc--missing">
            <span class="disc__val">${escapeHtml(coin.val)}</span>
          </div>
        </div>
      `;
    }
    const dateLabel = formatDateShort(coin.scannedAt);
    return `
      <div class="planche__cell"
           data-coin-id="${escapeHtml(coin.eurioId)}"
           data-owned="true">
        <div class="disc disc--${coin.metal}">
          <span class="disc__val">${escapeHtml(coin.val)}</span>
        </div>
        ${dateLabel ? `<span class="planche__cell__date">${escapeHtml(dateLabel)}</span>` : ''}
      </div>
    `;
  }).join('');

  grid.querySelectorAll('[data-coin-id]').forEach((cell) => {
    cell.addEventListener('click', () => {
      navigate(`#/coin/${encodeURIComponent(cell.dataset.coinId)}`);
    });
  });

  wireLongPress(grid, root);
}

function wireFilters(root, country, navigate) {
  const buttons = root.querySelectorAll('.scene-vcc-filter-row button[data-filter]');
  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      buttons.forEach(b => b.setAttribute('aria-selected', b === btn ? 'true' : 'false'));
      renderPlanche(root, country, navigate, btn.dataset.filter);
    });
  });
}

function wireLongPress(grid, root) {
  let timer = null;
  const LONG_MS = 550;
  grid.querySelectorAll('[data-owned="false"]').forEach((cell) => {
    const start = () => {
      timer = setTimeout(() => {
        showToast(root, `Marquer ${cell.dataset.coinId} comme possédée ?`);
        timer = null;
      }, LONG_MS);
    };
    const cancel = () => { if (timer) { clearTimeout(timer); timer = null; } };
    cell.addEventListener('pointerdown', start);
    cell.addEventListener('pointerup', cancel);
    cell.addEventListener('pointerleave', cancel);
    cell.addEventListener('pointercancel', cancel);
  });
}

function showToast(root, msg) {
  let toast = root.querySelector('[data-role="toast"]');
  if (!toast) {
    toast = document.createElement('div');
    toast.className = 'toast';
    toast.dataset.role = 'toast';
    root.appendChild(toast);
  }
  toast.textContent = msg;
  toast.dataset.visible = 'true';
  setTimeout(() => { toast.dataset.visible = 'false'; }, 1800);
}

function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
function formatDateShort(iso) {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    const dd = String(d.getDate()).padStart(2, '0');
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const yy = String(d.getFullYear()).slice(2);
    return `${dd}·${mm}·${yy}`;
  } catch (_) { return null; }
}
