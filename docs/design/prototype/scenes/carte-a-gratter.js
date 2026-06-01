/* scenes/carte-a-gratter.js — sidecar de la « belle carte » (Chunk D)
 *
 * Géométrie = vraie carte (paths réels Natural Earth, domaine public) injectée
 * depuis _eurozone-geo.js. Chaque pays : 3 états lisibles (gravé / en cours /
 * complété) + label ISO2 + compteur. Micro-états (LU/MT/CY) en pastilles à
 * leader. Le pays complété (Slovénie) est coiffé d'une feuille d'or à gratter
 * (D1 statique ; D2 = canvas scratch). Tap pays → liste inline sous la carte (D-next).
 */

import { VIEWBOX, GEO, CONTEXT } from './_eurozone-geo.js';
import { EUROZONE, isComplete } from './_eurozone.js';
import { confetti, chime, haptic } from './_celebration.js';

const VBW = 400, VBH = 511;   // viewBox de la carte (cf. _eurozone-geo.js)

const SVGNS = 'http://www.w3.org/2000/svg';
const MICRO = new Set(['LU', 'MT', 'CY']);          // dessinés en pastilles, pas en paths
// ancres des pastilles dans les marges « mer » + leader vers le centroïde réel
const MICRO_ANCHOR = { LU: { x: 34, y: 250 }, MT: { x: 256, y: 504 }, CY: { x: 384, y: 452 } };

const entryOf = (iso) => EUROZONE.find(c => c.iso === iso);
const stateOf = (c) => (c.owned === 0 ? 'empty' : (isComplete(c) ? 'complete' : 'progress'));

export function mount(ctx) {
  const { navigate, data, query } = ctx;
  const root = document.querySelector('[data-scene="carte-a-gratter"]');
  if (!root) return;
  const svg = root.querySelector('.cag-map svg');   // PAS le 1er svg (icône header)
  if (!svg) return;
  svg.setAttribute('viewBox', VIEWBOX);

  // arrivée depuis le reveal « pays complété » → on met le grattage en avant
  const fromReveal = query?.scratch === '1';

  buildContext(svg);
  buildCountries(svg);
  buildMicro(svg);
  buildLabels(svg);
  setupScratch(svg, root, fromReveal);
  renderStats(root);

  // tap (carte OU liste) → détail inline du pays, jamais de redirection
  const select = (iso) => selectCountry(root, svg, iso, data, navigate);
  renderList(root, select);
  wireCoffreTabs(root, navigate);
  wireModeToggle(root);
  wireCountryTaps(root, svg, select);

  // défaut : pays partiel ; arrivée scratch → le pays complété (cible du grattage)
  const startIso = (fromReveal && EUROZONE.find(isComplete)?.iso) || 'FR';
  select(startIso);
  if (fromReveal) root.querySelector('.cag-mapcard')?.scrollIntoView({ block: 'center' });
}

/* ───────── Géométrie (paths réels + pastilles + labels) ───────── */

function buildContext(svg) {
  const g = svg.querySelector('[data-role="context"]');
  if (!g) return;
  for (const iso of Object.keys(CONTEXT)) {
    g.appendChild(el('path', { class: 'cag-context', d: CONTEXT[iso] }));
  }
}

function buildCountries(svg) {
  const g = svg.querySelector('[data-role="countries"]');
  for (const iso of Object.keys(GEO)) {
    if (MICRO.has(iso)) continue;
    const c = entryOf(iso);
    if (!c) continue;
    const p = document.createElementNS(SVGNS, 'path');
    p.setAttribute('class', 'cag-country');
    p.setAttribute('data-iso', iso);
    p.setAttribute('d', GEO[iso].d);
    p.setAttribute('data-state', stateOf(c));
    g.appendChild(p);
  }
}

function buildMicro(svg) {
  const g = svg.querySelector('[data-role="micro"]');
  for (const iso of MICRO) {
    const c = entryOf(iso); const geo = GEO[iso]; const a = MICRO_ANCHOR[iso];
    if (!c || !geo || !a) continue;
    const line = el('line', { class: 'cag-leader', x1: a.x, y1: a.y, x2: geo.cx, y2: geo.cy });
    const dot = el('circle', { class: 'cag-micro-dot', 'data-iso': iso, cx: a.x, cy: a.y, r: 12 });
    dot.style.fill = `rgba(200,168,100,${(0.2 + (c.owned / c.total) * 0.8).toFixed(2)})`;
    const lab = el('text', { class: 'cag-micro-label', x: a.x, y: a.y });
    lab.textContent = iso;
    const rat = el('text', { class: 'cag-micro-ratio', x: a.x, y: a.y + 19 });
    rat.textContent = `${c.owned}/${c.total}`;
    g.append(line, dot, lab, rat);
  }
}

function buildLabels(svg) {
  const g = svg.querySelector('[data-role="labels"]');
  const frag = [];
  for (const iso of Object.keys(GEO)) {
    if (MICRO.has(iso)) continue;
    const c = entryOf(iso); const geo = GEO[iso];
    if (!c) continue;
    frag.push(`<text class="cag-label" x="${geo.cx}" y="${geo.cy - 3}">${iso}</text>`);
    frag.push(`<text class="cag-ratio" x="${geo.cx}" y="${geo.cy + 6}">${c.owned}/${c.total}</text>`);
  }
  g.innerHTML = frag.join('');
}

/* ───────── Scratch-reveal (D2) — feuille d'or grattable sur le pays complété ─────────
   Un <canvas> posé sur la bbox du pays complété, foil clippé à sa silhouette,
   effacé au doigt (destination-out). Au seuil → on dévoile le pays (déjà en or
   dessous) + célébration « pays complété » (overlay sur la carte). Réservé au
   pays complété → le geste garde sa valeur (garde-fou). */
function setupScratch(svg, root, pulse) {
  const complete = EUROZONE.find(isComplete);
  if (!complete || MICRO.has(complete.iso)) return;
  const path = svg.querySelector(`.cag-country[data-iso="${complete.iso}"]`);
  const mapEl = root.querySelector('.cag-map');
  if (!path || !mapEl) return;
  const bbox = path.getBBox();

  const build = () => {
    const rect = mapEl.getBoundingClientRect();
    if (!rect.width) { requestAnimationFrame(build); return; }
    const sx = rect.width / VBW, sy = rect.height / VBH;
    const dpr = window.devicePixelRatio || 1;
    const pad = 3;                                   // marge en unités viewBox
    const bx = bbox.x - pad, by = bbox.y - pad, bw = bbox.width + 2 * pad, bh = bbox.height + 2 * pad;

    const canvas = document.createElement('canvas');
    canvas.className = 'cag-scratch';
    canvas.style.left = `${bx * sx}px`; canvas.style.top = `${by * sy}px`;
    canvas.style.width = `${bw * sx}px`; canvas.style.height = `${bh * sy}px`;
    canvas.width = Math.round(bw * sx * dpr); canvas.height = Math.round(bh * sy * dpr);
    canvas.setAttribute('aria-label', `Gratter pour révéler ${complete.name} complété`);
    if (pulse) canvas.classList.add('cag-scratch--pulse');   // attire l'œil à l'arrivée depuis le reveal
    mapEl.appendChild(canvas);

    const ctx = canvas.getContext('2d');
    ctx.setTransform(sx * dpr, 0, 0, sy * dpr, -bx * sx * dpr, -by * sy * dpr);  // dessine en unités viewBox
    const p2d = new Path2D(path.getAttribute('d'));
    ctx.save();
    ctx.clip(p2d);
    const g = ctx.createLinearGradient(bx, by, bx + bw, by + bh);
    g.addColorStop(0, '#F5EBD3'); g.addColorStop(0.35, '#E7CB8B');
    g.addColorStop(0.6, '#C8A864'); g.addColorStop(0.85, '#8F7637'); g.addColorStop(1, '#E7CB8B');
    ctx.fillStyle = g; ctx.fillRect(bx, by, bw, bh);
    ctx.fillStyle = 'rgba(20,20,46,0.62)';
    ctx.font = '700 7px ui-monospace, monospace';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText('GRATTE', bbox.x + bbox.width / 2, bbox.y + bbox.height / 2);
    ctx.restore();

    // échantillons de base = pixels initialement opaques (intérieur du pays)
    const base = [];
    const img0 = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    for (let i = 3; i < img0.length; i += 4 * 30) if (img0[i] > 200) base.push(i);

    let scratching = false, done = false, moves = 0;
    const toVB = (ev) => {
      const r = mapEl.getBoundingClientRect();
      return [(ev.clientX - r.left) / r.width * VBW, (ev.clientY - r.top) / r.height * VBH];
    };
    const erase = (x, y) => {
      ctx.save();
      ctx.globalCompositeOperation = 'destination-out';
      ctx.beginPath(); ctx.arc(x, y, 12, 0, Math.PI * 2); ctx.fill();
      ctx.restore();
    };
    const cleared = () => {
      const d = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      let c = 0; for (const i of base) if (d[i] < 30) c++;
      return base.length ? c / base.length : 0;
    };
    const finish = () => {
      if (done) return;
      done = true;
      canvas.style.transition = 'opacity 0.5s var(--ease-out)';
      canvas.style.opacity = '0';
      setTimeout(() => canvas.remove(), 540);
      celebrateCountry(root, complete);
    };
    canvas.addEventListener('pointerdown', (e) => { try { canvas.setPointerCapture(e.pointerId); } catch (_) { /* synthetic */ } scratching = true; erase(...toVB(e)); });
    canvas.addEventListener('pointermove', (e) => { if (!scratching) return; erase(...toVB(e)); if (++moves % 6 === 0 && cleared() > 0.5) finish(); });
    canvas.addEventListener('pointerup', () => { scratching = false; if (cleared() > 0.5) finish(); });
    canvas.addEventListener('pointercancel', () => { scratching = false; });
  };
  requestAnimationFrame(build);
}

/* Célébration « pays complété » : overlay sur la carte (confettis + banderole),
   cohérent avec la philosophie overlay. (D3 reliera le reveal ?milestone=country.) */
function celebrateCountry(root, entry) {
  const card = root.querySelector('.cag-mapcard');
  if (!card) return;
  const layer = document.createElement('div');
  layer.className = 'cel-confetti';
  card.appendChild(layer);
  const banner = document.createElement('div');
  banner.className = 'cag-cel-banner';
  banner.textContent = `${entry.name} complété`;
  card.appendChild(banner);
  haptic([0, 35, 30, 80]);
  chime([523.25, 659.25, 783.99, 1046.50]);
  confetti(layer, { count: 40 });
  setTimeout(() => { banner.classList.add('is-out'); }, 2800);
  setTimeout(() => { banner.remove(); layer.remove(); }, 3600);
}

function el(tag, attrs) {
  const n = document.createElementNS(SVGNS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  return n;
}

/* ───────── Stats + liste ───────── */

function renderStats(root) {
  const total = EUROZONE.reduce((s, c) => s + c.total, 0);
  const owned = EUROZONE.reduce((s, c) => s + c.owned, 0);
  const s1 = root.querySelector('[data-role="stat-coins"]');
  const s2 = root.querySelector('[data-role="stat-total"]');
  if (s1) s1.textContent = owned;
  if (s2) s2.textContent = total;
}

function renderList(root, select) {
  const list = root.querySelector('[data-role="list"]');
  if (!list) return;
  const sorted = [...EUROZONE].sort((a, b) => (b.owned / b.total) - (a.owned / a.total));
  list.innerHTML = sorted.map((c) => {
    const pct = Math.round((c.owned / c.total) * 100);
    const done = isComplete(c) ? ' <span>✓ complet</span>' : '';
    return `
      <button type="button" class="cag-listrow" data-iso="${c.iso}">
        <div class="cag-listrow__flag">${c.flag}</div>
        <div class="cag-listrow__name">${c.name}${done}</div>
        <div class="cag-listrow__bar progress-bar"><div class="progress-track"><div class="progress-fill" style="width:${pct}%;"></div></div></div>
        <div class="cag-listrow__ratio">${c.owned}/${c.total}</div>
      </button>`;
  }).join('');
  // depuis la liste : revenir en mode carte + sélectionner le pays inline
  list.querySelectorAll('[data-iso]').forEach((row) => {
    row.addEventListener('click', () => {
      setMode(root, 'map');
      select(row.dataset.iso);
      root.querySelector('[data-role="detail"]')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
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

function setMode(root, mode) {
  root.dataset.mode = mode;
  root.querySelectorAll('[data-mode]').forEach(x => x.setAttribute('aria-selected', x.dataset.mode === mode ? 'true' : 'false'));
}
function wireModeToggle(root) {
  root.querySelectorAll('[data-mode]').forEach((b) => {
    b.addEventListener('click', () => setMode(root, b.dataset.mode));
  });
}

function wireCountryTaps(root, svg, select) {
  svg.querySelectorAll('[data-iso]').forEach((elm) => {
    elm.addEventListener('click', () => select(elm.dataset.iso));
  });
}

/* tap pays → son détail (pièces) directement sous la carte — pas de redirection */
function selectCountry(root, svg, iso, data, navigate) {
  const entry = entryOf(iso);
  if (!entry) return;
  svg.querySelectorAll('[data-selected]').forEach(s => s.removeAttribute('data-selected'));
  svg.querySelector(`.cag-country[data-iso="${iso}"], .cag-micro-dot[data-iso="${iso}"]`)?.setAttribute('data-selected', '1');

  const pct = Math.round((entry.owned / entry.total) * 100);
  const detail = root.querySelector('[data-role="detail"]');
  if (detail) detail.dataset.complete = isComplete(entry) ? '1' : '0';
  setText(root, 'd-flag', entry.flag);
  setText(root, 'd-name', entry.name);
  setText(root, 'd-ratio', `${entry.owned} / ${entry.total}`);
  setText(root, 'd-pct', `${pct}%`);
  const fill = root.querySelector('[data-role="d-fill"]');
  if (fill) fill.style.width = `${pct}%`;

  // pièces réelles du pays (eurio_referential via data.js), cadrées au total mock
  let coins = (data?.filterCoins?.({ country: iso }) || []).slice();
  coins.sort((a, b) => (a.year || 0) - (b.year || 0) || (a.faceValueCents || 0) - (b.faceValueCents || 0));
  const set = coins.slice(0, entry.total);
  const ownedN = isComplete(entry) ? set.length : Math.min(entry.owned, set.length);

  const grid = root.querySelector('[data-role="d-grid"]');
  grid.innerHTML = set.length
    ? set.map((c, i) => coinCell(c, i < ownedN, data)).join('')
    : `<p class="cag-detail__empty">Pas de pièces au catalogue pour ce pays (données proto).</p>`;
  grid.querySelectorAll('[data-eurio]').forEach((btn) => {
    btn.addEventListener('click', () => navigate(`#/coin/${btn.dataset.eurio}`));
  });
}

function coinCell(c, owned, data) {
  const svg = data?.coinSvg ? data.coinSvg(c, { size: 46, showLabel: false }) : '';
  const fv = c.faceValue >= 1 ? `${c.faceValue} €` : `${Math.round((c.faceValue || 0) * 100)} c`;
  const yr = c.year ? ` · ${c.year}` : '';
  return `<button type="button" class="cag-coin" data-eurio="${c.eurioId}" data-owned="${owned ? 1 : 0}" aria-label="${fv} ${c.year || ''} ${owned ? '— possédée' : '— manquante'}">
    <span class="cag-coin__disc">${svg}</span>
    <span class="cag-coin__label">${fv}${yr}</span>
  </button>`;
}

function setText(root, role, txt) {
  const e = root.querySelector(`[data-role="${role}"]`);
  if (e) e.textContent = txt;
}
