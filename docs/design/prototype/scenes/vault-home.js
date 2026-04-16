/* scenes/vault-home.js — sidecar for vault-home.html
 *
 * Responsibilities
 *   1. Decide empty vs populated (data-empty attribute on the root).
 *   2. Compute total value, delta %, stats (pièces / pays / séries).
 *   3. Render grid OR list with monthly group headers.
 *   4. Wire toolbar : search → #/vault/search, filters → #/vault/filters,
 *      grid/list toggle persisted in state.prefs.vaultView.
 *   5. Tap tile → #/coin/:eurioId?ctx=owned
 *   6. ⋯ button → open vault-remove-confirm overlay.
 *
 * Value computation
 *   - entry.valueAtAddCents (mock) is the reference price at add time.
 *   - Current reference price = entry.valueAtAddCents if set, else coin.faceValueCents.
 *     (data.js does not expose p50 prices so we silently fall back.)
 *   - Total = Σ currentCents.
 *   - Delta = (current - initial) / initial where initial = Σ valueAtAddCents.
 *     Hidden if initial is zero or total < 50 cents.
 *
 * Mock seed : if state.collection is empty AND sessionStorage.vaultDemo === 'on'
 * we populate 10 random coins just for preview (dev-friendly).
 */

const VIEW_KEY = 'vaultView';     // state.prefs[VIEW_KEY] = 'grid' | 'list'
const SORT_KEY = 'vaultSort';     // 'country' (default) | 'face' | 'price' | 'month'
export function mount(ctx) {
  const { state, data, navigate } = ctx;
  const root = document.querySelector('[data-scene="vault-home"]');
  if (!root) return;

  const collection = state.state.collection;
  const isEmpty = collection.length === 0;
  root.dataset.empty = isEmpty ? 'true' : 'false';

  // Empty state CTA
  const emptyCta = root.querySelector('.vault-home-empty__cta');
  emptyCta?.addEventListener('click', () => navigate('#/scan'));

  if (isEmpty) return;

  // Populated state
  state.state.prefs[VIEW_KEY] = state.state.prefs[VIEW_KEY] || 'grid';
  state.state.prefs[SORT_KEY] = state.state.prefs[SORT_KEY] || 'country';
  const view = state.state.prefs[VIEW_KEY];
  const sort = state.state.prefs[SORT_KEY];

  renderHeader(root, collection, data);
  renderSparkline(root, collection, data);
  renderStats(root, collection, data);
  renderGroups(root, collection, data, view, sort, navigate);
  wireToolbar(root, state, navigate);
  wireCoffreTabs(root, navigate);
}

/* ───────── Coffre segmented tabs ─────────
 * Routes the user to the Sets / Catalogue sub-views. The "Mes pièces"
 * tab is already the current scene (noop). Each scene hosts its own
 * copy of this segmented control — see coffre-header pattern.
 */
function wireCoffreTabs(root, navigate) {
  const tabs = root.querySelectorAll('[data-coffre-tab]');
  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      const id = tab.dataset.coffreTab;
      if (id === 'sets')    return navigate('#/vault/sets');
      if (id === 'catalog') return navigate('#/vault/catalog');
    });
  });
}

/* ───────── Header : value total + delta ───────── */

function renderHeader(root, collection, data) {
  let currentCents = 0;
  let initialCents = 0;
  for (const entry of collection) {
    const coin = data.getCoin(entry.eurioId);
    const reference = entry.valueAtAddCents ?? (coin ? coin.faceValueCents : 0);
    currentCents += reference;
    initialCents += entry.valueAtAddCents ?? reference;
  }

  const euros = Math.floor(currentCents / 100);
  const intEl = root.querySelector('[data-role="value-int"]');
  if (intEl) intEl.textContent = euros.toLocaleString('fr-FR');

  // Delta display
  const chip    = root.querySelector('[data-role="delta-chip"]');
  const pctEl   = root.querySelector('[data-role="delta-pct"]');
  const arrow   = root.querySelector('[data-role="delta-arrow"]');
  const caption = root.querySelector('[data-role="delta-caption"]');
  const row     = root.querySelector('[data-role="delta-row"]');

  if (initialCents <= 0 || currentCents < 50) {
    if (row) row.style.visibility = 'hidden';
    return;
  }

  const delta = (currentCents - initialCents) / initialCents;
  const pct   = Math.round(delta * 100);
  const isNeg = pct < 0;
  if (pctEl) pctEl.textContent = `${isNeg ? '' : '+'}${pct}%`;
  if (chip) {
    chip.classList.toggle('vault-home-delta-chip--down', isNeg);
  }
  if (arrow) {
    // Flip arrow path for down variant
    arrow.innerHTML = isNeg
      ? '<path d="M7 10l5 5 5-5" />'
      : '<path d="M7 14l5-5 5 5" />';
  }
  if (caption) {
    caption.textContent = 'depuis tes premiers ajouts';
  }
}

/* ───────── Stats strip ───────── */

function renderStats(root, collection, data) {
  const coins = collection.length;
  const countries = new Set();
  for (const entry of collection) {
    const coin = data.getCoin(entry.eurioId);
    if (coin?.country) countries.add(coin.country);
  }
  const series = countries.size; // proxy : 1 pays = 1 série représentée

  setText(root, '[data-role="stat-coins"]', coins.toString());
  setText(root, '[data-role="stat-countries"]', countries.size.toString());
  setText(root, '[data-role="stat-series"]', `${series}/21`);
}

/* ───────── Groups + grid/list ───────── */

function renderGroups(root, collection, data, view, sort, navigate) {
  const host = root.querySelector('[data-role="groups"]');
  if (!host) return;
  host.innerHTML = '';

  // Compute multiplicity per eurioId (global, used by tile/row badges)
  const multi = new Map();
  for (const e of collection) {
    multi.set(e.eurioId, (multi.get(e.eurioId) || 0) + 1);
  }

  // Build ordered list of { label, entries } buckets according to the active sort.
  const groups = bucketCollection(collection, data, sort);

  for (const { label, entries } of groups) {
    host.insertAdjacentHTML('beforeend', `
      <div class="vault-home-group">
        <span class="vault-home-group__label">${escapeHtml(label)}</span>
        <span class="vault-home-group__line"></span>
      </div>
    `);

    // Group dedup : when multiple same-eurioId in same bucket, show once + ×N
    const seen = new Set();
    const deduped = entries.filter(e => {
      if (seen.has(e.eurioId)) return false;
      seen.add(e.eurioId);
      return true;
    });

    if (view === 'list') {
      const list = document.createElement('div');
      list.className = 'vault-home-list';
      for (const entry of deduped) {
        list.appendChild(buildRow(entry, data, multi));
      }
      host.appendChild(list);
    } else {
      const grid = document.createElement('div');
      grid.className = 'vault-home-grid';
      for (const entry of deduped) {
        grid.appendChild(buildTile(entry, data, multi));
      }
      host.appendChild(grid);
    }
  }

  // Tap handlers (delegated)
  host.addEventListener('click', (ev) => {
    const moreBtn = ev.target.closest('[data-action="more"]');
    if (moreBtn) {
      ev.stopPropagation();
      const id = moreBtn.dataset.eurioId;
      openRemoveOverlay(id, data, navigate);
      return;
    }
    const tile = ev.target.closest('[data-eurio-id]');
    if (tile && !moreBtn) {
      const id = tile.dataset.eurioId;
      navigate(`#/coin/${encodeURIComponent(id)}?ctx=owned`);
    }
  });
}

function buildTile(entry, data, multi) {
  const coin = data.getCoin(entry.eurioId);
  if (!coin) return document.createElement('div');
  const count = multi.get(entry.eurioId) || 1;
  const isSetComplete = coin.isCommemorative && (count >= 2);
  // Heuristic : we don't have set data in the referential, so any commemorative
  // owned in duplicate mock-acts as "set complete" for visual variety.

  const tile = document.createElement('button');
  tile.type = 'button';
  tile.className = `vault-home-tile${isSetComplete ? ' vault-home-tile--set-complete' : ''}`;
  tile.dataset.eurioId = coin.eurioId;
  tile.innerHTML = `
    ${count > 1 ? `<span class="vault-home-tile__mult">×${count}</span>` : ''}
    <span class="vault-home-tile__more" data-action="more"
          data-eurio-id="${escapeHtml(coin.eurioId)}" aria-label="Plus d'options">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" aria-hidden="true">
        <circle cx="5"  cy="12" r="1.2" fill="currentColor" stroke="none"/>
        <circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none"/>
        <circle cx="19" cy="12" r="1.2" fill="currentColor" stroke="none"/>
      </svg>
    </span>
    <div class="vault-home-tile__coin">${data.coinSvg(coin, { size: 120, showLabel: true })}</div>
    <div class="vault-home-tile__meta">
      <span>${escapeHtml(coin.country.toUpperCase())}</span>
      <span>${coin.year ?? ''}</span>
    </div>
  `;
  return tile;
}

function buildRow(entry, data, multi) {
  const coin = data.getCoin(entry.eurioId);
  if (!coin) return document.createElement('div');
  const count = multi.get(coin.eurioId) || 1;
  const current = entry.valueAtAddCents ?? coin.faceValueCents;
  const initial = entry.valueAtAddCents ?? current;

  const row = document.createElement('button');
  row.type = 'button';
  row.className = 'vault-home-row';
  row.dataset.eurioId = coin.eurioId;

  const hasDelta = initial > 0 && current !== initial;
  const deltaPct = hasDelta ? Math.round(((current - initial) / initial) * 100) : null;
  const deltaClass = deltaPct == null
    ? 'vault-home-row__delta--neutral'
    : deltaPct < 0 ? 'vault-home-row__delta--down' : '';
  const deltaText = deltaPct == null
    ? '—'
    : `${deltaPct >= 0 ? '+' : ''}${deltaPct}%`;

  row.innerHTML = `
    <div class="vault-home-row__coin">${data.coinSvg(coin, { size: 44, showLabel: false })}</div>
    <div class="vault-home-row__meta">
      <span class="vault-home-row__title">${escapeHtml(coin.countryName)}${count > 1 ? ` ×${count}` : ''}</span>
      <span class="vault-home-row__sub">
        ${escapeHtml(formatFaceValue(coin.faceValueCents))} · ${coin.year ?? '—'}
      </span>
    </div>
    <div class="vault-home-row__value tabular">
      <span class="vault-home-row__price">${formatEuros(current)}</span>
      <span class="vault-home-row__delta ${deltaClass}">${deltaText}</span>
    </div>
  `;
  return row;
}

/* ───────── Toolbar wiring ───────── */

function wireToolbar(root, state, navigate) {
  root.querySelector('[data-action="search"]')
      ?.addEventListener('click', () => navigate('#/vault/search'));
  root.querySelector('[data-action="filters"]')
      ?.addEventListener('click', () => navigate('#/vault/filters'));
  root.querySelector('[data-action="export"]')
      ?.addEventListener('click', () => {
        // no-op for prototype
        console.info('[vault-home] export clicked (no-op mock)');
      });
  root.querySelector('[data-action="more"]')
      ?.addEventListener('click', () => {
        console.info('[vault-home] more clicked (no-op mock)');
      });

  const rerender = () => {
    const ctx = window.eurio;
    const groupsHost = root.querySelector('[data-role="groups"]');
    if (groupsHost) groupsHost.innerHTML = '';
    const currentView = ctx.state.state.prefs[VIEW_KEY] || 'grid';
    const currentSort = ctx.state.state.prefs[SORT_KEY] || 'country';
    renderGroups(root, ctx.state.state.collection, ctx.data, currentView, currentSort, navigate);
  };

  // View toggle (grid/list)
  const toggle = root.querySelector('.vault-home-toggle');
  toggle?.addEventListener('click', (ev) => {
    const btn = ev.target.closest('button[data-view]');
    if (!btn) return;
    const view = btn.dataset.view;
    toggle.querySelectorAll('button').forEach(b => {
      b.setAttribute('aria-selected', b.dataset.view === view ? 'true' : 'false');
    });
    state.state.prefs[VIEW_KEY] = view;
    state.save();
    rerender();
  });

  // Set initial selection from persisted pref
  const activeView = state.state.prefs[VIEW_KEY] || 'grid';
  toggle?.querySelectorAll('button').forEach(b => {
    b.setAttribute('aria-selected', b.dataset.view === activeView ? 'true' : 'false');
  });

  // Sort chips (country / face / price / month)
  const sortBar = root.querySelector('.vault-home-sort');
  sortBar?.addEventListener('click', (ev) => {
    const chip = ev.target.closest('button[data-sort]');
    if (!chip) return;
    const sort = chip.dataset.sort;
    sortBar.querySelectorAll('button[data-sort]').forEach(b => {
      b.setAttribute('aria-pressed', b.dataset.sort === sort ? 'true' : 'false');
    });
    state.state.prefs[SORT_KEY] = sort;
    state.save();
    rerender();
  });

  const activeSort = state.state.prefs[SORT_KEY] || 'country';
  sortBar?.querySelectorAll('button[data-sort]').forEach(b => {
    b.setAttribute('aria-pressed', b.dataset.sort === activeSort ? 'true' : 'false');
  });
}

/* ───────── Bucketing (sort modes) ───────── */

/**
 * Returns an ordered array of { label, entries } buckets. The ordering
 * reflects the chosen sort mode. Within each bucket, entries keep their
 * collection order (month-sort reverses by recency inside groups).
 */
function bucketCollection(collection, data, sort) {
  switch (sort) {
    case 'face':       return bucketByFaceValue(collection, data);
    case 'price':      return bucketByPrice(collection, data);
    case 'month':      return bucketByMonth(collection);
    case 'country':
    default:           return bucketByCountry(collection, data);
  }
}

function bucketByCountry(collection, data) {
  const buckets = new Map();
  for (const entry of collection) {
    const coin = data.getCoin(entry.eurioId);
    const label = coin?.countryName || '?';
    if (!buckets.has(label)) buckets.set(label, { label, entries: [] });
    buckets.get(label).entries.push(entry);
  }
  return Array.from(buckets.values())
    .sort((a, b) => a.label.localeCompare(b.label, 'fr'));
}

function bucketByFaceValue(collection, data) {
  const buckets = new Map();
  for (const entry of collection) {
    const coin = data.getCoin(entry.eurioId);
    const cents = coin?.faceValueCents ?? 0;
    if (!buckets.has(cents)) {
      buckets.set(cents, { cents, label: formatFaceValue(cents), entries: [] });
    }
    buckets.get(cents).entries.push(entry);
  }
  // Descending : 2 € → 1 c
  return Array.from(buckets.values())
    .sort((a, b) => b.cents - a.cents)
    .map(({ label, entries }) => ({ label, entries }));
}

function bucketByMonth(collection) {
  const buckets = new Map();
  for (const entry of collection) {
    const d = new Date(entry.addedAt || Date.now());
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    if (!buckets.has(key)) buckets.set(key, { key, label: formatMonth(d), entries: [] });
    buckets.get(key).entries.push(entry);
  }
  return Array.from(buckets.values())
    .sort((a, b) => b.key.localeCompare(a.key))
    .map(({ label, entries }) => ({ label, entries }));
}

function bucketByPrice(collection, data) {
  // Single bucket, entries sorted by value descending.
  const sorted = [...collection].sort((a, b) => {
    const av = a.valueAtAddCents ?? (data.getCoin(a.eurioId)?.faceValueCents ?? 0);
    const bv = b.valueAtAddCents ?? (data.getCoin(b.eurioId)?.faceValueCents ?? 0);
    return bv - av;
  });
  return [{ label: 'Trié par prix', entries: sorted }];
}

/* ───────── Sparkline : value over time ───────── */

function renderSparkline(root, collection, data) {
  const host = root.querySelector('[data-role="spark"]');
  if (!host || collection.length === 0) {
    if (host) host.style.display = 'none';
    return;
  }

  // Chronologically sorted cumulative value, 12 monthly samples.
  const sorted = [...collection].sort((a, b) => (a.addedAt || 0) - (b.addedAt || 0));
  const now = Date.now();
  const monthMs = 30 * 24 * 60 * 60 * 1000;
  const samples = 12;
  const points = [];

  for (let i = samples - 1; i >= 0; i--) {
    const cutoff = now - i * monthMs;
    let total = 0;
    for (const entry of sorted) {
      if ((entry.addedAt || now) > cutoff) continue;
      const coin = data.getCoin(entry.eurioId);
      total += entry.valueAtAddCents ?? (coin?.faceValueCents ?? 0);
    }
    points.push(total);
  }

  const max = Math.max(...points, 1);
  const min = Math.min(...points);
  const range = Math.max(max - min, 1);

  // Map to SVG 0–300 × 2–50 space (leaving padding top/bottom)
  const W = 300;
  const H = 52;
  const PAD = 6;
  const coords = points.map((v, i) => {
    const x = (i / (samples - 1)) * W;
    const y = H - PAD - ((v - min) / range) * (H - PAD * 2);
    return [x, y];
  });

  const linePath = coords
    .map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`)
    .join(' ');
  const fillPath = `${linePath} L${W},${H} L0,${H} Z`;

  const lineEl = host.querySelector('[data-role="spark-line"]');
  const fillEl = host.querySelector('[data-role="spark-fill"]');
  const dotEl  = host.querySelector('[data-role="spark-dot"]');
  if (lineEl) lineEl.setAttribute('d', linePath);
  if (fillEl) fillEl.setAttribute('d', fillPath);
  if (dotEl && coords.length) {
    const [lx, ly] = coords[coords.length - 1];
    dotEl.setAttribute('cx', lx.toFixed(1));
    dotEl.setAttribute('cy', ly.toFixed(1));
  }
}

/* ───────── Remove confirm overlay ───────── */

function openRemoveOverlay(eurioId, data, navigate) {
  // Fetch the overlay HTML and inject above the scene
  fetch('scenes/vault-remove-confirm.html')
    .then(r => r.ok ? r.text() : null)
    .then(html => {
      if (!html) return;
      const host = document.getElementById('view');
      if (!host) return;
      // Append to view (non-routed overlay)
      const wrap = document.createElement('div');
      wrap.innerHTML = html;
      const overlay = wrap.firstElementChild;
      host.appendChild(overlay);

      // Lazy import overlay sidecar
      import('./vault-remove-confirm.js')
        .then(mod => mod.mount && mod.mount({
          eurioId,
          overlay,
          data,
          state: window.eurio.state,
          navigate,
        }))
        .catch(err => console.warn('[vault-home] overlay mount failed', err));
    });
}

/* ───────── Utils ───────── */

const MONTHS_FR = [
  'Janvier','Février','Mars','Avril','Mai','Juin',
  'Juillet','Août','Septembre','Octobre','Novembre','Décembre',
];
function formatMonth(d) {
  return `${MONTHS_FR[d.getMonth()]} ${d.getFullYear()}`;
}

function formatEuros(cents) {
  const eur = cents / 100;
  return Number.isInteger(eur)
    ? `${eur} €`
    : `${eur.toFixed(2).replace('.', ',')} €`;
}

function formatFaceValue(cents) {
  if (cents >= 100) {
    const eur = cents / 100;
    return Number.isInteger(eur) ? `${eur} €` : `${eur.toFixed(2).replace('.', ',')} €`;
  }
  return `${cents} c`;
}

function setText(root, selector, value) {
  const el = root.querySelector(selector);
  if (el) el.textContent = value;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}
