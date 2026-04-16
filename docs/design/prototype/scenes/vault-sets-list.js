/* scenes/vault-sets-list.js — sidecar for vault-sets-list.html
 *
 * Renders a mocked list of sets with mini-planche previews and progress.
 * Wires :
 *   - segmented tabs → /vault (Mes pièces) or /vault/catalog (Catalogue)
 *   - filter chips (category / state) → local filtering
 *   - card tap → /vault/sets/:setId (detail scene)
 *
 * Mock data lives in this file for the proto. When the Android app uses
 * this pattern, the shape documented here is the contract the repository
 * should return :
 *
 *   type SetPreview = {
 *     id: string,
 *     title: string,
 *     description: string,
 *     category: 'country' | 'theme' | 'tier' | 'personal' | 'hunt',
 *     kind: 'structural' | 'curated' | 'parametric',
 *     owned: number,
 *     total: number,
 *     completedAt: string | null,
 *     preview: Array<{ metal: 'nordic'|'copper'|'silver'|'bimetal'|'missing', val: string }>
 *   }
 */

const CATEGORY_LABEL = {
  country:  'Pays',
  theme:    'Thème',
  tier:     'Tier',
  personal: 'Perso',
  hunt:     'Chasse',
};

/* ───────── Mock sets ───────── */

const MOCK_SETS = [
  {
    id: 'it-circulation',
    title: 'Italie — circulation',
    description: 'Les 8 pièces euro de circulation italienne, de 1c à 2€.',
    category: 'country',
    kind: 'structural',
    owned: 5, total: 8,
    completedAt: null,
    preview: [
      { metal: 'copper',  val: '1c'  },
      { metal: 'copper',  val: '2c'  },
      { metal: 'copper',  val: '5c'  },
      { metal: 'nordic',  val: '10c' },
      { metal: 'nordic',  val: '20c' },
      { metal: 'missing', val: '50c' },
      { metal: 'missing', val: '1€'  },
      { metal: 'missing', val: '2€'  },
    ],
  },
  {
    id: 'fr-commemo-2024',
    title: 'Commémoratives France 2024',
    description: 'Les 2€ commémoratives françaises émises en 2024.',
    category: 'country',
    kind: 'curated',
    owned: 2, total: 4,
    completedAt: null,
    preview: [
      { metal: 'bimetal', val: '2€' },
      { metal: 'bimetal', val: '2€' },
      { metal: 'missing', val: '2€' },
      { metal: 'missing', val: '2€' },
      { metal: null,      val: ''   },
      { metal: null,      val: ''   },
      { metal: null,      val: ''   },
      { metal: null,      val: ''   },
    ],
  },
  {
    id: 'vatican-benoit',
    title: 'Vatican — Benoît XVI',
    description: 'La série complète des pièces émises sous Benoît XVI (2005–2013).',
    category: 'theme',
    kind: 'curated',
    owned: 3, total: 16,
    completedAt: null,
    preview: [
      { metal: 'nordic',  val: '1€' },
      { metal: 'bimetal', val: '2€' },
      { metal: 'copper',  val: '5c' },
      { metal: 'missing', val: '1c' },
      { metal: 'missing', val: '2c' },
      { metal: 'missing', val: '10c'},
      { metal: 'missing', val: '20c'},
      { metal: 'missing', val: '50c'},
    ],
  },
  {
    id: 'tier-2-euro-all',
    title: 'Toutes les 2€ courantes',
    description: 'Une 2€ face nationale de chaque pays eurozone.',
    category: 'tier',
    kind: 'parametric',
    owned: 14, total: 21,
    completedAt: null,
    preview: [
      { metal: 'bimetal', val: '2€' },
      { metal: 'bimetal', val: '2€' },
      { metal: 'bimetal', val: '2€' },
      { metal: 'bimetal', val: '2€' },
      { metal: 'bimetal', val: '2€' },
      { metal: 'bimetal', val: '2€' },
      { metal: 'missing', val: '2€' },
      { metal: 'missing', val: '2€' },
    ],
  },
  {
    id: 'hunt-rare-2007',
    title: 'Chasse — Traité de Rome 2007',
    description: '13 pays, un design commun, un seul millésime. Le Graal européen.',
    category: 'hunt',
    kind: 'curated',
    owned: 0, total: 13,
    completedAt: null,
    preview: Array.from({ length: 8 }, () => ({ metal: 'missing', val: '2€' })),
  },
  {
    id: 'starter-ie',
    title: 'Starter kit Irlande 2002',
    description: 'Les 8 pièces du starter kit distribué en 2002.',
    category: 'country',
    kind: 'curated',
    owned: 8, total: 8,
    completedAt: '2026-04-03',
    preview: [
      { metal: 'copper',  val: '1c'  },
      { metal: 'copper',  val: '2c'  },
      { metal: 'copper',  val: '5c'  },
      { metal: 'nordic',  val: '10c' },
      { metal: 'nordic',  val: '20c' },
      { metal: 'nordic',  val: '50c' },
      { metal: 'silver',  val: '1€'  },
      { metal: 'bimetal', val: '2€'  },
    ],
  },
];

/* ───────── mount() ───────── */

export function mount(ctx) {
  const { navigate } = ctx;
  const root = document.querySelector('[data-scene="vault-sets-list"]');
  if (!root) return;

  wireCoffreTabs(root, navigate);
  wireFilters(root);
  render(root, navigate);
}

function wireCoffreTabs(root, navigate) {
  root.querySelectorAll('[data-coffre-tab]').forEach((tab) => {
    tab.addEventListener('click', () => {
      const id = tab.dataset.coffreTab;
      if (id === 'coins')   return navigate('#/vault');
      if (id === 'catalog') return navigate('#/vault/catalog');
      // 'sets' is already here — noop
    });
  });
}

function wireFilters(root) {
  const state = { cat: 'all', stateFilter: 'all' };

  root.querySelectorAll('[data-filter-cat]').forEach((chip) => {
    chip.addEventListener('click', () => {
      state.cat = chip.dataset.filterCat;
      root.querySelectorAll('[data-filter-cat]').forEach(c =>
        c.setAttribute('aria-pressed', c === chip ? 'true' : 'false'));
      applyFilters(root, state);
    });
  });

  root.querySelectorAll('[data-filter-state]').forEach((chip) => {
    chip.addEventListener('click', () => {
      state.stateFilter = chip.dataset.filterState;
      root.querySelectorAll('[data-filter-state]').forEach(c =>
        c.setAttribute('aria-pressed', c === chip ? 'true' : 'false'));
      applyFilters(root, state);
    });
  });
}

function applyFilters(root, { cat, stateFilter }) {
  const all = root.querySelectorAll('.scene-vsl-card');
  all.forEach((card) => {
    const cardCat = card.dataset.cat;
    const cardState = card.dataset.state;
    const catOk   = cat === 'all' || cardCat === cat;
    const stateOk = stateFilter === 'all' || cardState === stateFilter;
    card.style.display = (catOk && stateOk) ? '' : 'none';
  });
  // Hide the divider if nothing below it is visible.
  const divider = root.querySelector('[data-role="divider"]');
  const anyDone = Array.from(all).some(c =>
    c.dataset.state === 'done' && c.style.display !== 'none');
  if (divider) divider.style.display = anyDone ? '' : 'none';
}

function render(root, navigate) {
  const list = root.querySelector('[data-role="list"]');
  if (!list) return;

  const inProgress = MOCK_SETS.filter(s => s.completedAt == null && s.owned > 0);
  const idle = MOCK_SETS.filter(s => s.owned === 0);
  const done = MOCK_SETS.filter(s => s.completedAt != null);

  // Sort in-progress descending by %
  inProgress.sort((a, b) => (b.owned / b.total) - (a.owned / a.total));

  list.innerHTML = '';

  [...inProgress, ...idle].forEach(set => list.appendChild(cardEl(set, navigate)));

  if (done.length > 0) {
    const divider = document.createElement('div');
    divider.className = 'scene-vsl-divider';
    divider.dataset.role = 'divider';
    divider.innerHTML = `
      <span class="scene-vsl-divider__label">Complétés</span>
      <span class="scene-vsl-divider__line"></span>
    `;
    list.appendChild(divider);
    done.forEach(set => list.appendChild(cardEl(set, navigate)));
  }
}

function cardEl(set, navigate) {
  const card = document.createElement('article');
  const isDone = set.completedAt != null;
  const stateAttr = isDone ? 'done' : (set.owned === 0 ? 'idle' : 'progress');

  card.className = 'scene-vsl-card' + (isDone ? ' scene-vsl-card--done' : '');
  card.dataset.setId = set.id;
  card.dataset.cat = set.category;
  card.dataset.state = stateAttr;

  const pct = Math.round((set.owned / set.total) * 100);
  const catLabel = CATEGORY_LABEL[set.category] || set.category;

  card.innerHTML = `
    <div class="scene-vsl-card__head">
      <div class="scene-vsl-card__titles">
        <h3 class="scene-vsl-card__title">${escapeHtml(set.title)}</h3>
        <p class="scene-vsl-card__sub">${escapeHtml(set.description)}</p>
      </div>
      ${isDone ? `
        <div class="scene-vsl-card__crown" aria-label="Complété">
          <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M3 8l4.5 3L12 4l4.5 7L21 8l-1.5 10h-15z"/>
          </svg>
        </div>
      ` : ''}
    </div>

    <div class="scene-vsl-card__chips">
      <span class="scene-vsl-card__kind scene-vsl-card__kind--${set.category}">${catLabel}</span>
      <span class="chip">${set.kind}</span>
    </div>

    <div class="scene-vsl-card__preview">
      <div class="planche planche--compact">
        <div class="planche__grid">
          ${set.preview.map(slot => cellMarkup(slot)).join('')}
        </div>
      </div>
    </div>

    <div class="scene-vsl-card__progress">
      <div class="scene-vsl-card__progress__bar progress-bar">
        <div class="progress-track">
          <div class="progress-fill" style="width: ${pct}%;"></div>
        </div>
      </div>
      <div class="scene-vsl-card__progress__label">${set.owned} / ${set.total}</div>
      <div class="scene-vsl-card__progress__pct tabular">${pct}%</div>
    </div>
  `;

  card.addEventListener('click', () => {
    navigate(`#/vault/sets/${encodeURIComponent(set.id)}`);
  });

  return card;
}

function cellMarkup(slot) {
  if (slot.metal == null) {
    // Padding cell — show an empty cavity with no disc inside.
    return `<div class="planche__cell planche__cell--missing" aria-hidden="true"></div>`;
  }
  if (slot.metal === 'missing') {
    return `
      <div class="planche__cell planche__cell--missing">
        <div class="disc disc--missing disc--xs">
          <span class="disc__val">${escapeHtml(slot.val)}</span>
        </div>
      </div>
    `;
  }
  return `
    <div class="planche__cell">
      <div class="disc disc--${slot.metal} disc--xs">
        <span class="disc__val">${escapeHtml(slot.val)}</span>
      </div>
    </div>
  `;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
