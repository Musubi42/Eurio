/* scenes/profile.js — sidecar for profile.html (Agent B5 · Phase 2)
 *
 * Binds state.collection + state.level to the profile hero + stats + chases.
 * Level math lives in state.js (recomputeLevel). We just read the resulting
 * tier + progressPct and pick a ladder index. Same threshold table duplicated
 * locally to resolve labels and compute "Encore N pièces" without leaking
 * into state.js.
 */

const TIERS = [
  { name: 'Découvreur', min: 0,   nextAt: 5,   caption: '« Ton aventure commence »' },
  { name: 'Passionné',  min: 5,   nextAt: 30,  caption: '« Tu prends goût à la collection »' },
  { name: 'Expert',     min: 30,  nextAt: 100, caption: '« La collection devient une discipline »' },
  { name: 'Maître',     min: 100, nextAt: null, caption: '« Tu as atteint le rang le plus élevé »' },
];

// A tiny hand-written set of achievement definitions. Progress is derived
// from state.collection, no backend needed. Each returns a "hot" flag if it
// sits above 75%.
function computeAchievements(collection) {
  const ids = new Set(collection.map(c => c.eurioId));
  const countByCountry = {};
  collection.forEach(c => {
    const cc = (c.eurioId || '').slice(0, 2).toUpperCase();
    countByCountry[cc] = (countByCountry[cc] || 0) + 1;
  });

  // Série France 2020 — 8 pièces nominalement "fr-2020-*-standard"
  const FR_SET = [
    'fr-2020-1c-standard',  'fr-2020-2c-standard',
    'fr-2020-5c-standard',  'fr-2020-10c-standard',
    'fr-2020-20c-standard', 'fr-2020-50c-standard',
    'fr-2020-1eur-standard','fr-2020-2eur-standard',
  ];
  const frHave = FR_SET.filter(id => ids.has(id)).length;

  // Eurozone founding (12 pays)
  const FOUNDING = ['BE','DE','ES','FI','FR','GR','IE','IT','LU','NL','AT','PT'];
  const foundHave = FOUNDING.filter(cc => countByCountry[cc]).length;

  // Grande chasse — 21 pays zone euro
  const ALL_EZ = ['AT','BE','BG','CY','DE','EE','ES','FI','FR','GR','HR','IE','IT','LT','LU','LV','MT','NL','PT','SI','SK'];
  const ezHave = ALL_EZ.filter(cc => countByCountry[cc]).length;

  const list = [
    {
      id: 'circulation-fr',
      title: 'Série complète France',
      difficulty: 'Facile',
      icon: '★',
      have: frHave, total: FR_SET.length,
      unlocked: frHave >= FR_SET.length,
    },
    {
      id: 'eurozone-founding',
      title: 'Eurozone founding',
      difficulty: 'Moyen',
      icon: '◎',
      have: foundHave, total: FOUNDING.length,
      unlocked: foundHave >= FOUNDING.length,
    },
    {
      id: 'grande-chasse',
      title: 'Grande chasse',
      difficulty: 'Difficile',
      icon: '◐',
      have: ezHave, total: ALL_EZ.length,
      unlocked: ezHave >= ALL_EZ.length,
    },
  ];
  return list.map(a => ({
    ...a,
    pct: Math.round((a.have / a.total) * 100),
    hot: (a.have / a.total) >= 0.75 && a.have < a.total,
  }));
}

function tierIndexFor(tierName) {
  return Math.max(0, TIERS.findIndex(t => t.name === tierName));
}

function totalValueCents(collection) {
  return collection.reduce((acc, c) => acc + (c.valueAtAddCents ?? 0), 0);
}

function countDistinctCountries(collection) {
  const set = new Set();
  collection.forEach(c => set.add((c.eurioId || '').slice(0, 2).toUpperCase()));
  return set.size;
}

function setText(root, key, value) {
  const el = root.querySelector(`[data-bind="${key}"]`);
  if (el) el.textContent = value;
}

function setHTML(root, key, html) {
  const el = root.querySelector(`[data-bind="${key}"]`);
  if (el) el.innerHTML = html;
}

function renderChases(chases) {
  if (!chases.length) return '';
  return chases.map(a => {
    const dim = a.pct < 10 ? 'is-dim' : '';
    const goldClass = a.hot ? 'is-gold' : '';
    return `
      <a href="#/profile/set/${a.id}" class="profile-home-ach" style="color:inherit">
        <div class="profile-home-medal ${dim}"><span>${a.icon}</span></div>
        <div class="profile-home-ach__body">
          <div class="profile-home-ach__title">${a.title}</div>
          <div class="profile-home-ach__meta"><b>${a.difficulty}</b> · ${a.have} / ${a.total} acquises</div>
          <div class="profile-home-ach__bar">
            <div class="profile-home-ach__fill ${goldClass}" style="width:${a.pct}%"></div>
          </div>
        </div>
        <div class="profile-home-ach__count"><b>${a.have}</b>/${a.total}</div>
      </a>`;
  }).join('');
}

function renderEmpty() {
  return `
    <div class="profile-home-empty">
      <div class="profile-home-medal is-dim"><span>◐</span></div>
      <p>Les chasses apparaîtront dès ta première pièce scannée.</p>
    </div>`;
}

function renderUnlockBanner(lastUnlock) {
  if (!lastUnlock) return '';
  return `
    <div class="profile-home-unlock">
      <div class="profile-home-medal"><span>${lastUnlock.icon || '✦'}</span></div>
      <div class="profile-home-unlock__txt">
        <div class="eyebrow eyebrow--gold">Débloqué · ${lastUnlock.when || 'récemment'}</div>
        <div class="profile-home-unlock__title">${lastUnlock.title}</div>
        <div class="profile-home-unlock__sub">${lastUnlock.sub || ''}</div>
      </div>
    </div>`;
}

export function mount(ctx) {
  const { state, navigate } = ctx;
  const root = document.querySelector('[data-scene="profile"]');
  if (!root) return;

  // ── Auto-unlock celebration : if a set was just completed (flagged by
  //    state.addCoin → checkSetCompletions), redirect to the unlock scene
  //    once. consumePendingUnlock clears the flag so we don't loop.
  if (state.state.level && state.state.level.pendingUnlock) {
    const setId = state.consumePendingUnlock();
    if (setId) {
      navigate(`#/profile/unlock?setId=${encodeURIComponent(setId)}`);
      return;
    }
  }

  const col = state.state.collection || [];
  const count = col.length;
  const tierIdx = tierIndexFor(state.state.level.tier);
  const tier = TIERS[tierIdx];
  const pct = state.state.level.progressPct || 0;
  const ord = ['I','II','III','IV'][tierIdx] || 'I';

  // Hero eyebrow + level
  setText(root, 'level-eyebrow', `Niveau · rang ${ord} de IV`);
  setText(root, 'level-name', tier.name);
  setText(root, 'level-ord', `${ord} / IV`);
  setText(root, 'level-caption', tier.caption);

  // Ladder
  const labels = root.querySelector('[data-bind="ladder-labels"]');
  if (labels) {
    [...labels.querySelectorAll('span')].forEach((span, i) => {
      span.classList.remove('is-done', 'is-current');
      if (i < tierIdx) span.classList.add('is-done');
      else if (i === tierIdx) span.classList.add('is-current');
    });
  }
  // Each tier owns a 1/3 slice of the bar. The fill covers all done tiers
  // plus the current slice's progress.
  const segmentWidth = 100 / 3;
  const fillPct = Math.min(100, tierIdx * segmentWidth + (pct / 100) * segmentWidth);
  const fillEl = root.querySelector('[data-bind="ladder-fill"]');
  if (fillEl) fillEl.style.width = `${fillPct}%`;

  // Node states
  for (let i = 0; i < 4; i++) {
    const node = root.querySelector(`[data-bind="node-${i}"]`);
    if (!node) continue;
    node.classList.remove('is-done', 'is-current');
    if (i < tierIdx) node.classList.add('is-done');
    else if (i === tierIdx) node.classList.add('is-current');
  }

  // Hint
  let hintHtml = state.state.level.nextThresholdHint;
  if (tier.nextAt != null) {
    const remaining = Math.max(0, tier.nextAt - count);
    const nextName = TIERS[tierIdx + 1]?.name || '';
    hintHtml = remaining === 0
      ? `Tu peux passer <b>${nextName}</b>`
      : `Encore <b>${remaining} pièce${remaining > 1 ? 's' : ''}</b> pour devenir ${nextName}`;
  } else {
    hintHtml = 'Tu as atteint le rang le plus élevé.';
  }
  setHTML(root, 'ladder-hint', hintHtml);
  setText(root, 'ladder-pct', `${pct}%`);

  // Stats
  setText(root, 'stat-coins', String(count));
  const coinsSub = root.querySelector('[data-bind="stat-coins-sub"]');
  if (coinsSub) {
    if (count === 0) {
      coinsSub.textContent = 'Aucune encore';
    } else {
      coinsSub.innerHTML = `<span class="up">+${count}</span> ce mois`;
    }
  }

  setText(root, 'stat-countries', String(countDistinctCountries(col)));

  const valCents = totalValueCents(col);
  const valEl = root.querySelector('[data-bind="stat-value"]');
  const valSub = root.querySelector('[data-bind="stat-value-sub"]');
  if (valCents > 0) {
    if (valEl) valEl.textContent = Math.round(valCents / 100);
    if (valSub) valSub.innerHTML = `<span class="up">↑ 34%</span>`;
  } else {
    if (valEl) valEl.textContent = '—';
    setText(root, 'stat-value-unit', '');
    if (valSub) valSub.textContent = 'Coffre vide';
  }

  // Achievements
  const chases = computeAchievements(col).filter(a => !a.unlocked && a.have > 0);
  const chasesContainer = root.querySelector('[data-bind="chases-container"]');
  if (chasesContainer) {
    chasesContainer.className = 'profile-home-chases';
    chasesContainer.innerHTML = chases.length ? renderChases(chases) : renderEmpty();
  }

  // Last unlock banner (if lastUnlock set in state.level, else synthesize one
  // when a chase just finished; here we only show the banner if lastUnlock
  // exists on state.level).
  const lastUnlock = state.state.level.lastUnlock || null;
  setHTML(root, 'unlock-banner', renderUnlockBanner(lastUnlock));

  // Settings button wiring
  root.querySelectorAll('[data-action="open-settings"]').forEach(el => {
    el.addEventListener('click', ev => {
      ev.preventDefault();
      navigate('#/profile/settings');
    });
  });
}
