/* scenes/profile-achievements.js — sidecar (Agent B5 · Phase 2)
 *
 * Tabs : En cours / Débloqués / Verrouillés.
 * Computes the same achievement list as profile.js from state.collection.
 * Missing-coin chips come from the same FR / EZ tables.
 */

const FR_SET = [
  { id: 'fr-2020-1c-standard',   label: '1 c'  },
  { id: 'fr-2020-2c-standard',   label: '2 c'  },
  { id: 'fr-2020-5c-standard',   label: '5 c'  },
  { id: 'fr-2020-10c-standard',  label: '10 c' },
  { id: 'fr-2020-20c-standard',  label: '20 c' },
  { id: 'fr-2020-50c-standard',  label: '50 c' },
  { id: 'fr-2020-1eur-standard', label: '1 €'  },
  { id: 'fr-2020-2eur-standard', label: '2 €'  },
];

const FOUNDING = ['BE','DE','ES','FI','FR','GR','IE','IT','LU','NL','AT','PT'];
const ALL_EZ = ['AT','BE','BG','CY','DE','EE','ES','FI','FR','GR','HR','IE','IT','LT','LU','LV','MT','NL','PT','SI','SK'];

const ACHIEVEMENTS = [
  { id: 'circulation-fr',    title: 'Série complète France', difficulty: 'Facile',    icon: '★', kind: 'fr' },
  { id: 'eurozone-founding', title: 'Eurozone founding',     difficulty: 'Moyen',     icon: '◎', kind: 'founding' },
  { id: 'grande-chasse',     title: 'Grande chasse',         difficulty: 'Difficile', icon: '◐', kind: 'grande' },
  { id: 'circulation-de',    title: 'Série complète Allemagne', difficulty: 'Facile', icon: '✦', kind: 'de' },
  { id: 'commemoratives-2e', title: 'Dix 2€ commémoratives', difficulty: 'Moyen',     icon: '◇', kind: 'commem' },
];

function computeProgress(ach, ids, byCountry) {
  if (ach.kind === 'fr') {
    const have = FR_SET.filter(c => ids.has(c.id));
    const missing = FR_SET.filter(c => !ids.has(c.id));
    return { have: have.length, total: FR_SET.length, missing: missing.map(m => m.label) };
  }
  if (ach.kind === 'founding') {
    const have = FOUNDING.filter(cc => byCountry[cc]);
    const missing = FOUNDING.filter(cc => !byCountry[cc]);
    return { have: have.length, total: FOUNDING.length, missing };
  }
  if (ach.kind === 'grande') {
    const have = ALL_EZ.filter(cc => byCountry[cc]);
    const missing = ALL_EZ.filter(cc => !byCountry[cc]);
    return { have: have.length, total: ALL_EZ.length, missing };
  }
  if (ach.kind === 'de') {
    const have = [...ids].filter(id => id.startsWith('de-') && id.includes('-standard'));
    return { have: Math.min(8, have.length), total: 8, missing: [] };
  }
  if (ach.kind === 'commem') {
    const have = [...ids].filter(id => id.includes('-2eur-') && !id.endsWith('-standard'));
    return { have: Math.min(10, have.length), total: 10, missing: [] };
  }
  return { have: 0, total: 1, missing: [] };
}

function buildList(collection) {
  const ids = new Set(collection.map(c => c.eurioId));
  const byCountry = {};
  collection.forEach(c => {
    const cc = (c.eurioId || '').slice(0, 2).toUpperCase();
    byCountry[cc] = (byCountry[cc] || 0) + 1;
  });
  return ACHIEVEMENTS.map(a => {
    const p = computeProgress(a, ids, byCountry);
    const pct = Math.round((p.have / p.total) * 100);
    return {
      ...a,
      have: p.have,
      total: p.total,
      missing: p.missing,
      pct,
      unlocked: p.have >= p.total,
      hot: pct >= 75 && p.have < p.total,
      started: p.have > 0,
    };
  });
}

function renderHot(a) {
  const chips = (a.missing || []).slice(0, 6)
    .map(m => `<span class="chip">${m}</span>`).join('');
  return `
    <a class="profile-ach-hot" href="#/profile/set/${a.id}" style="display:block;color:inherit">
      <div class="profile-ach-hot__head">
        <div class="profile-ach-hot__medal"></div>
        <div>
          <div class="profile-ach-hot__title">${a.title}</div>
          <div class="profile-ach-hot__sub">Plus que ${a.total - a.have} pièce${a.total - a.have > 1 ? 's' : ''}</div>
        </div>
      </div>
      <div class="profile-ach-hot__bar"><div class="profile-ach-hot__fill" style="width:${a.pct}%"></div></div>
      ${chips ? `<div class="profile-ach-hot__missing-lbl">À trouver</div><div class="profile-ach-chips">${chips}</div>` : ''}
    </a>`;
}

function renderRow(a) {
  const dim = a.pct < 10 ? 'is-dim' : '';
  return `
    <a class="profile-ach-row" href="#/profile/set/${a.id}" style="color:inherit;text-decoration:none">
      <div class="profile-ach-row__medal ${dim}">${a.icon}</div>
      <div style="flex:1;min-width:0">
        <div class="profile-ach-row__title">${a.title}</div>
        <div class="profile-ach-row__meta"><b>${a.difficulty}</b> · ${a.have} / ${a.total}</div>
        <div class="profile-ach-row__bar"><div class="profile-ach-row__fill" style="width:${a.pct}%"></div></div>
      </div>
      <div class="profile-ach-row__count"><b>${a.have}</b>/${a.total}</div>
    </a>`;
}

function renderUnlocked(list) {
  if (!list.length) {
    return `<div class="profile-ach-empty"><p>Aucune médaille débloquée pour l'instant — continue à collectionner.</p></div>`;
  }
  const [featured, ...rest] = list;
  const tiles = rest.map(a => `
    <div class="profile-ach-tile">
      <div class="profile-ach-tile__medal"></div>
      <div class="profile-ach-tile__title">${a.title}</div>
      <div class="profile-ach-tile__date">Débloqué</div>
    </div>`).join('');
  return `
    <div class="profile-ach-featured">
      <div class="profile-ach-featured__medal"></div>
      <div class="profile-ach-featured__title">${featured.title}</div>
      <div class="profile-ach-featured__sub">Dernière médaille débloquée</div>
    </div>
    ${rest.length ? `<div class="profile-ach-grid">${tiles}</div>` : ''}`;
}

function renderLocked(list) {
  if (!list.length) {
    return `<div class="profile-ach-empty"><p>Tu as déjà démarré toutes les chasses disponibles.</p></div>`;
  }
  return `<div>${list.map(a => `
    <div class="profile-ach-row" style="opacity:0.55;border-style:dashed">
      <div class="profile-ach-row__medal is-dim">${a.icon}</div>
      <div style="flex:1;min-width:0">
        <div class="profile-ach-row__title">${a.title}</div>
        <div class="profile-ach-row__meta">${a.difficulty} · ${a.total} pièces</div>
      </div>
      <div class="profile-ach-row__count">0/${a.total}</div>
    </div>`).join('')}</div>`;
}

export function mount(ctx) {
  const { state } = ctx;
  const root = document.querySelector('[data-scene="profile-achievements"]');
  if (!root) return;
  const col = state.state.collection || [];
  const list = buildList(col);

  const inProgress = list.filter(a => a.started && !a.unlocked).sort((a, b) => b.pct - a.pct);
  const unlocked = list.filter(a => a.unlocked);
  const locked = list.filter(a => !a.started);

  // Tab counters
  const set = (key, text) => {
    const el = root.querySelector(`[data-bind="${key}"]`);
    if (el) el.textContent = text;
  };
  set('ach-count', `${unlocked.length} / ${list.length}`);
  set('tab-c-in-progress', String(inProgress.length));
  set('tab-c-unlocked',    String(unlocked.length));
  set('tab-c-locked',      String(locked.length));

  // Panes
  const paneIP = root.querySelector('[data-bind="pane-in-progress"]');
  if (paneIP) {
    const hots = inProgress.filter(a => a.hot);
    const rest = inProgress.filter(a => !a.hot);
    paneIP.innerHTML = (hots.length ? `<div class="eyebrow eyebrow--gold profile-ach-section-eyebrow">Presque complètes</div>${hots.map(renderHot).join('')}` : '')
                     + (rest.length ? `<div class="eyebrow profile-ach-section-eyebrow" style="margin-top:${hots.length ? 'var(--space-6)' : '0'}">Autres chasses</div>${rest.map(renderRow).join('')}` : '')
                     + (!inProgress.length ? `<div class="profile-ach-empty"><p>Les chasses apparaîtront dès ta première pièce scannée.</p></div>` : '');
  }

  const paneU = root.querySelector('[data-bind="pane-unlocked"]');
  if (paneU) paneU.innerHTML = renderUnlocked(unlocked);

  const paneL = root.querySelector('[data-bind="pane-locked"]');
  if (paneL) paneL.innerHTML = renderLocked(locked);

  // Tab switching
  const tabs = root.querySelectorAll('.profile-ach-tab');
  const panes = root.querySelectorAll('.profile-ach-pane');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.setAttribute('aria-selected', t === tab ? 'true' : 'false'));
      panes.forEach(p => p.classList.toggle('is-active', p.dataset.pane === tab.dataset.tab));
    });
  });
}
