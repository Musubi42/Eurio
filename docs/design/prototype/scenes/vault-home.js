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
const DEMO_KEY = 'eurio.proto.v1.vaultDemo';

export function mount(ctx) {
  const { state, data, navigate } = ctx;
  const root = document.querySelector('[data-scene="vault-home"]');
  if (!root) return;

  // Optional demo seed (non-destructive, session-scoped)
  maybeSeedDemo(state, data);

  const collection = state.state.collection;
  const isEmpty = collection.length === 0;
  root.dataset.empty = isEmpty ? 'true' : 'false';

  // Empty state CTA
  const emptyCta = root.querySelector('.vault-home-empty__cta');
  emptyCta?.addEventListener('click', () => navigate('#/scan'));

  if (isEmpty) return;

  // Populated state
  state.state.prefs[VIEW_KEY] = state.state.prefs[VIEW_KEY] || 'grid';
  const view = state.state.prefs[VIEW_KEY];

  renderHeader(root, collection, data);
  renderStats(root, collection, data);
  renderGroups(root, collection, data, view, navigate);
  wireToolbar(root, state, navigate);
}

/* ───────── Mock demo seed ───────── */

function maybeSeedDemo(state, data) {
  if (sessionStorage.getItem(DEMO_KEY) !== 'on') return;
  if (state.state.collection.length > 0) return;
  if (!data.isReady()) return;
  // Pick 10 random referential coins
  for (let i = 0; i < 10; i++) {
    const coin = data.randomCoin();
    if (!coin) break;
    // Mock a small +/- variation on initial value
    const base = coin.faceValueCents || 10;
    const jitter = Math.round(base * (0.85 + Math.random() * 0.2));
    state.addCoin(coin.eurioId, { valueAtAddCents: jitter });
  }
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

function renderGroups(root, collection, data, view, navigate) {
  const host = root.querySelector('[data-role="groups"]');
  if (!host) return;
  host.innerHTML = '';

  // Bucket by addedAt month
  const buckets = new Map();
  for (const entry of collection) {
    const d = new Date(entry.addedAt || Date.now());
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    if (!buckets.has(key)) buckets.set(key, { label: formatMonth(d), entries: [] });
    buckets.get(key).entries.push(entry);
  }

  // Sorted newest first
  const keys = Array.from(buckets.keys()).sort().reverse();

  // Compute multiplicity per eurioId (global)
  const multi = new Map();
  for (const e of collection) {
    multi.set(e.eurioId, (multi.get(e.eurioId) || 0) + 1);
  }

  for (const key of keys) {
    const { label, entries } = buckets.get(key);
    host.insertAdjacentHTML('beforeend', `
      <div class="vault-home-group">
        <span class="vault-home-group__label">${escapeHtml(label)}</span>
        <span class="vault-home-group__line"></span>
      </div>
    `);

    // Group dedup : when multiple same-eurioId in same month, show once + ×N
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

  // View toggle
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
    // Re-render groups area
    import('./vault-home.js').then(mod => {
      // Remount cleanly by re-reading groups (not full mount).
      const ctx = window.eurio;
      const groupsHost = root.querySelector('[data-role="groups"]');
      if (groupsHost) groupsHost.innerHTML = '';
      // re-render inline (reuse same fn)
      renderGroups(root, ctx.state.state.collection, ctx.data, view, navigate);
    });
  });

  // Set initial selection from persisted pref
  const active = state.state.prefs[VIEW_KEY] || 'grid';
  toggle?.querySelectorAll('button').forEach(b => {
    b.setAttribute('aria-selected', b.dataset.view === active ? 'true' : 'false');
  });
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
