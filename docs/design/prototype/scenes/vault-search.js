/* scenes/vault-search.js — sidecar for vault-search.html
 *
 * Live search against data.searchCoins(). Splits results into
 * "owned" (present in state.collection) and "hunt" (not).
 */

const MAX_PER_SECTION = 20;

export function mount(ctx) {
  const { state, data, navigate } = ctx;
  const root = document.querySelector('[data-scene="vault-search"]');
  if (!root) return;

  const input = root.querySelector('[data-role="input"]');
  const emptyBox = root.querySelector('[data-role="empty"]');
  const results  = root.querySelector('[data-role="results"]');

  input?.focus();

  const ownedIds = new Set(state.state.collection.map(e => e.eurioId));

  const run = (q) => {
    const query = (q || '').trim();
    if (query.length === 0) {
      emptyBox.hidden = false;
      results.hidden = true;
      return;
    }
    const matches = data.searchCoins(query);
    const owned = [];
    const hunt = [];
    for (const c of matches) {
      if (ownedIds.has(c.eurioId)) owned.push(c); else hunt.push(c);
      if (owned.length + hunt.length > MAX_PER_SECTION * 2) break;
    }

    emptyBox.hidden = true;
    results.hidden = false;

    renderList(root, '[data-role="list-owned"]',
               '[data-role="count-owned"]', '[data-role="section-owned"]',
               owned.slice(0, MAX_PER_SECTION), query, data, navigate, 'owned');
    renderList(root, '[data-role="list-hunt"]',
               '[data-role="count-hunt"]', '[data-role="section-hunt"]',
               hunt.slice(0, MAX_PER_SECTION), query, data, navigate, 'reference');
  };

  input?.addEventListener('input', (ev) => run(ev.target.value));

  // Suggestion buttons
  root.querySelectorAll('[data-suggest]').forEach(btn => {
    btn.addEventListener('click', () => {
      input.value = btn.dataset.suggest;
      run(input.value);
    });
  });

  // Close
  root.querySelector('[data-action="close"]')
      ?.addEventListener('click', () => navigate('#/vault'));
}

function renderList(root, listSel, countSel, sectionSel, coins, query, data, navigate, ctx) {
  const list = root.querySelector(listSel);
  const count = root.querySelector(countSel);
  const section = root.querySelector(sectionSel);
  if (!list || !count || !section) return;

  count.textContent = String(coins.length);
  section.hidden = coins.length === 0;

  list.innerHTML = coins.map(coin => `
    <button type="button" class="vault-search-row" data-eurio-id="${escapeHtml(coin.eurioId)}">
      <div class="vault-search-row__coin">${data.coinSvg(coin, { size: 44, showLabel: false })}</div>
      <div class="vault-search-row__meta">
        <span class="vault-search-row__title">${highlight(coin.countryName, query)}</span>
        <span class="vault-search-row__sub">${formatFaceValue(coin.faceValueCents)} · ${coin.year ?? '—'}${
          coin.theme ? ' · ' + highlight(coin.theme, query) : ''
        }</span>
      </div>
      ${ctx === 'reference' ? '<span class="vault-search-row__cta">à chasser</span>' : ''}
    </button>
  `).join('');

  list.querySelectorAll('[data-eurio-id]').forEach(el => {
    el.addEventListener('click', () => {
      navigate(`#/coin/${encodeURIComponent(el.dataset.eurioId)}?ctx=${ctx}`);
    });
  });
}

function highlight(text, query) {
  if (!text || !query) return escapeHtml(text);
  const escText = escapeHtml(text);
  const safeQ = query.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&');
  try {
    const re = new RegExp(`(${safeQ})`, 'ig');
    return escText.replace(re, '<mark>$1</mark>');
  } catch (_) {
    return escText;
  }
}

function formatFaceValue(cents) {
  if (cents >= 100) {
    const eur = cents / 100;
    return Number.isInteger(eur) ? `${eur} €` : `${eur.toFixed(2).replace('.', ',')} €`;
  }
  return `${cents} c`;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}
