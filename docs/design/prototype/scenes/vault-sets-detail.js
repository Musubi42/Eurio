/* scenes/vault-sets-detail.js — sidecar for vault-sets-detail.html
 *
 * Renders a mocked set detail. Picks the mock by ?setId or falls back
 * to 'it-circulation'. Contract when wired to Android :
 *
 *   type SetDetail = {
 *     id, title, description,
 *     category, kind,
 *     completedAt: string | null,
 *     coins: Array<{
 *       eurioId: string,
 *       metal: 'copper'|'nordic'|'silver'|'bimetal',
 *       val: string,
 *       owned: boolean,
 *       scannedAt: string | null,
 *     }>
 *   }
 */

const MOCK_DETAILS = {
  'it-circulation': {
    title: 'Italie — <em>circulation</em>',
    kindLabel: 'structural',
    description:
      "La série complète des 8 pièces euro italiennes en circulation, du cent de cuivre à la bimétallique de 2€.",
    chips: ['country', 'italie 🇮🇹', 'depuis 2002'],
    completedAt: null,
    rewardTitle: 'Badge « Botte complète »',
    coins: [
      { eurioId: 'it-001', metal: 'copper',  val: '1c',  owned: true,  scannedAt: '2026-03-12' },
      { eurioId: 'it-002', metal: 'copper',  val: '2c',  owned: true,  scannedAt: '2026-03-12' },
      { eurioId: 'it-005', metal: 'copper',  val: '5c',  owned: true,  scannedAt: '2026-03-18' },
      { eurioId: 'it-010', metal: 'nordic',  val: '10c', owned: true,  scannedAt: '2026-03-29' },
      { eurioId: 'it-020', metal: 'nordic',  val: '20c', owned: true,  scannedAt: '2026-04-02' },
      { eurioId: 'it-050', metal: 'nordic',  val: '50c', owned: false, scannedAt: null },
      { eurioId: 'it-100', metal: 'silver',  val: '1€',  owned: false, scannedAt: null },
      { eurioId: 'it-200', metal: 'bimetal', val: '2€',  owned: false, scannedAt: null },
    ],
  },
  'starter-ie': {
    title: 'Starter kit Irlande <em>2002</em>',
    kindLabel: 'curated',
    description:
      'Les 8 pièces du starter kit irlandais distribué à la veille du passage à l\'euro en 2002.',
    chips: ['country', 'irlande 🇮🇪', 'starter 2002'],
    completedAt: '2026-04-03',
    rewardTitle: 'Badge « Pionnier d\'Éire »',
    coins: [
      { eurioId: 'ie-001', metal: 'copper',  val: '1c',  owned: true, scannedAt: '2026-02-08' },
      { eurioId: 'ie-002', metal: 'copper',  val: '2c',  owned: true, scannedAt: '2026-02-14' },
      { eurioId: 'ie-005', metal: 'copper',  val: '5c',  owned: true, scannedAt: '2026-02-18' },
      { eurioId: 'ie-010', metal: 'nordic',  val: '10c', owned: true, scannedAt: '2026-03-01' },
      { eurioId: 'ie-020', metal: 'nordic',  val: '20c', owned: true, scannedAt: '2026-03-11' },
      { eurioId: 'ie-050', metal: 'nordic',  val: '50c', owned: true, scannedAt: '2026-03-20' },
      { eurioId: 'ie-100', metal: 'silver',  val: '1€',  owned: true, scannedAt: '2026-03-29' },
      { eurioId: 'ie-200', metal: 'bimetal', val: '2€',  owned: true, scannedAt: '2026-04-03' },
    ],
  },
};

/* Pick 4 discs for the fan hero. Prefer the most "representative" :
 * 1c (copper), 10c or 20c (nordic), 1€ (silver), 2€ (bimetal). */
function pickFanDiscs(coins) {
  const picks = [];
  const byMetal = (metal) => coins.find(c => c.metal === metal);
  ['copper', 'nordic', 'silver', 'bimetal'].forEach((m) => {
    const c = byMetal(m);
    if (c) picks.push(c);
  });
  while (picks.length < 4 && coins.length) picks.push(coins[picks.length % coins.length]);
  return picks.slice(0, 4);
}

/* ───────── mount() ───────── */

export function mount(ctx) {
  const { params, query, navigate } = ctx;
  const root = document.querySelector('[data-scene="vault-sets-detail"]');
  if (!root) return;

  const setId = (params && params.setId) || (query && query.setId) || 'it-circulation';
  const detail = MOCK_DETAILS[setId] || MOCK_DETAILS['it-circulation'];

  renderFan(root, detail);
  renderMeta(root, detail);
  renderProgress(root, detail);
  renderPlanche(root, detail, navigate);

  // Long-press on missing cell (mock)
  wireLongPress(root);

  // Back button respects a custom history hint if present
  const back = root.querySelector('.scene-vsd-back');
  if (back) {
    back.addEventListener('click', (e) => {
      e.preventDefault();
      navigate('#/vault/sets');
    });
  }
}

function renderFan(root, detail) {
  const fan = root.querySelector('[data-role="fan"]');
  if (!fan) return;
  const picks = pickFanDiscs(detail.coins);
  fan.innerHTML = picks.map((c, i) => `
    <div class="scene-vsd-fan__disc disc--${c.metal} scene-vsd-fan__disc--${i + 1}">
      <span class="scene-vsd-fan__val">${escapeHtml(c.val)}</span>
    </div>
  `).join('');
}

function renderMeta(root, detail) {
  const titleEl = root.querySelector('[data-role="title"]');
  const descEl = root.querySelector('[data-role="desc"]');
  const kindEl = root.querySelector('[data-role="kind"]');
  const chipsEl = root.querySelector('.scene-vsd-hero__chips');

  if (titleEl) titleEl.innerHTML = detail.title;
  if (descEl)  descEl.textContent = detail.description;
  if (kindEl)  kindEl.textContent = detail.kindLabel;
  if (chipsEl) {
    chipsEl.innerHTML = detail.chips
      .map(c => `<span class="chip">${escapeHtml(c)}</span>`).join('');
  }

  // Reward title
  const rewardTitle = root.querySelector('.scene-vsd-reward__title');
  if (rewardTitle) rewardTitle.textContent = detail.rewardTitle;

  // Completed state
  const owned = detail.coins.filter(c => c.owned).length;
  const isComplete = owned === detail.coins.length;
  root.dataset.completed = isComplete ? 'true' : 'false';
  if (isComplete && detail.completedAt) {
    const noteDate = root.querySelector('[data-role="completed-date"]');
    if (noteDate) noteDate.textContent = formatDate(detail.completedAt);
  }
}

function renderProgress(root, detail) {
  const owned = detail.coins.filter(c => c.owned).length;
  const total = detail.coins.length;
  const pct = Math.round((owned / total) * 100);

  const pctEl = root.querySelector('[data-role="pct"]');
  const ratioEl = root.querySelector('[data-role="ratio"]');
  const fillEl = root.querySelector('[data-role="fill"]');

  if (pctEl) pctEl.textContent = pct;
  if (ratioEl) ratioEl.textContent = `${owned} / ${total}`;
  if (fillEl) fillEl.style.width = `${pct}%`;
}

function renderPlanche(root, detail, navigate) {
  const grid = root.querySelector('[data-role="planche-grid"]');
  if (!grid) return;

  grid.innerHTML = detail.coins.map((coin) => {
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
}

function wireLongPress(root) {
  let timer = null;
  const LONG_MS = 550;
  root.querySelectorAll('[data-owned="false"]').forEach((cell) => {
    const start = () => {
      timer = setTimeout(() => {
        showToast(root, `Marquer ${cell.dataset.coinId} comme possédée ?`);
        timer = null;
      }, LONG_MS);
    };
    const cancel = () => {
      if (timer) { clearTimeout(timer); timer = null; }
    };
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

/* ───────── Helpers ───────── */

function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDate(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' });
  } catch (_) {
    return iso;
  }
}
function formatDateShort(iso) {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    const dd = String(d.getDate()).padStart(2, '0');
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const yy = String(d.getFullYear()).slice(2);
    return `${dd}·${mm}·${yy}`;
  } catch (_) {
    return null;
  }
}
