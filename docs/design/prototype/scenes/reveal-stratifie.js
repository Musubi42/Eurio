// Scene : reveal-stratifie
// =========================
// Stratified post-scan reveal — "bottom sheet à 2 crans" model.
//   • 3D hero (rotatable) via the shared engine (_coin3d.js), stays visible.
//   • Draggable bottom sheet with a handle :
//       peek      → Découverte summary (≤3 drives) + CTAs
//       expanded  → pull the handle up → Histoire / Rareté / Valeur / Complétion
//   Vertical pull = depth ; "Voir la fiche" = ultimate depth (page pièce).
//
// Proto note : lens CONTENT is mocked deterministically from the manifest entry;
// the real data contract is wired later — here we validate the *design*.

import {
  createStage, buildCoinFromUrls, buildProceduralEdgeTexture,
  disposeCoin, R_OUT,
} from './_coin3d.js';
import * as data from '../_shared/data.js';
import { confetti, chime, haptic } from './_celebration.js';

const HERO_FILL = 0.78;
const IDLE_SPD = 0.2;
const DRAG_K = 0.011;
const TILT_K = 0.006;
const TILT_MAX = 0.55;

// Sheet detents. peek is MEASURED (handle + summary + pinned CTAs + nav clearance)
// so the summary always fits; expanded is capped so the coin stays fully visible.
const NAV_PAD = 88;        // bottom padding reserved for the nav (matches CSS)
const EXPANDED_FRAC = 0.60; // expanded sheet height → top ≈ 40% = coin band bottom

let active = null;

export async function mount({ query, navigate }) {
  if (active) { active.dispose(); active = null; }

  const root = document.querySelector('[data-scene="reveal-stratifie"]');
  if (!root) return;
  const canvasWrap = root.querySelector('[data-slot="canvas-wrap"]');
  const statusEl = root.querySelector('[data-slot="status"]');
  const sheet = root.querySelector('[data-slot="sheet"]');
  const handle = root.querySelector('.reveal-sheet__handle');

  const owned = query?.owned === '1';
  root.dataset.owned = owned ? '1' : '0';

  // Jalon (démo déterministe) : ?milestone=set|feat → le reveal passe en mode fête
  // SANS changer d'écran : un overlay (banderole + confettis + rayons) se superpose
  // et on ré-accentue ce qui est déjà là (héros, complétion/rareté). L'intensité
  // monte avec le type (économie des célébrations : set < feat = le pic). En vrai,
  // le jalon est détecté côté données. (country = chunk D, enchaîne carte à gratter.)
  const milestone = owned ? '' : (query?.milestone || '').toLowerCase();
  const MILESTONE = {
    set:     { label: 'Série complète', confetti: 24, chime: [523.25, 659.25, 783.99],          toast: 'Série complétée ✓' },
    country: { label: 'Pays complété',  confetti: 32, chime: [523.25, 659.25, 783.99, 880.00],  toast: 'Pays complété ✓' },
    feat:    { label: 'Légendaire',     confetti: 44, chime: [523.25, 659.25, 783.99, 1046.50], toast: 'Pièce légendaire ajoutée ✓' },
  };
  const ms = MILESTONE[milestone] || null;
  if (ms) {
    root.dataset.milestone = milestone;
    const label = root.querySelector('[data-slot="cel-label"]');
    if (label) label.textContent = ms.label;
  }

  // ───────── 3D hero ─────────
  const stage = createStage(canvasWrap);
  function frameCoin() {
    const w = canvasWrap.clientWidth || 1;
    const h = canvasWrap.clientHeight || 1;
    const tanHalfV = Math.tan((35 * Math.PI / 180) / 2);
    const halfNeeded = R_OUT / HERO_FILL;
    const dist = Math.max(halfNeeded / tanHalfV, halfNeeded / (tanHalfV * (w / h)));
    stage.camera.position.set(0, dist * 0.05, dist);
    stage.camera.lookAt(0, 0, 0);
  }
  frameCoin();

  const ctx = {
    stage, coin: null, leaveOff: null,
    dispose() {
      if (this.leaveOff) this.leaveOff();
      if (this.coin) { stage.scene.remove(this.coin.group); disposeCoin(this.coin); }
      stage.dispose();
    },
  };
  active = ctx;
  const onLeave = () => { if (active === ctx) { ctx.dispose(); active = null; } };
  window.addEventListener('hashchange', onLeave, { once: true });
  ctx.leaveOff = () => window.removeEventListener('hashchange', onLeave);

  let group = null;
  let omega = IDLE_SPD;
  let dragging = false;
  stage.onFrame((dt) => {
    frameCoin();
    if (!group) return;
    if (!dragging) {
      group.rotation.y += omega * dt;
      omega += (IDLE_SPD - omega) * Math.min(1, dt * 2.5);
      group.rotation.x += (0 - group.rotation.x) * Math.min(1, dt * 4);
    }
  });
  stage.start();

  let hdown = null;
  function heroDown(ev) {
    if (!group) return;
    canvasWrap.querySelector('canvas')?.setPointerCapture?.(ev.pointerId);
    dragging = true;
    hdown = { lastX: ev.clientX, lastY: ev.clientY, lastT: performance.now(), vel: 0 };
    root.dataset.rotated = '1';
  }
  function heroMove(ev) {
    if (!hdown || !group) return;
    const dx = ev.clientX - hdown.lastX;
    const dy = ev.clientY - hdown.lastY;
    const dt = Math.max((performance.now() - hdown.lastT) / 1000, 1 / 240);
    group.rotation.y += dx * DRAG_K;
    group.rotation.x = Math.max(-TILT_MAX, Math.min(TILT_MAX, group.rotation.x + dy * TILT_K));
    hdown.vel = hdown.vel * 0.7 + ((dx * DRAG_K) / dt) * 0.3;
    hdown.lastX = ev.clientX; hdown.lastY = ev.clientY; hdown.lastT = performance.now();
  }
  function heroUp() {
    if (!hdown) return;
    dragging = false;
    omega = Math.max(-12, Math.min(12, hdown.vel || IDLE_SPD));
    hdown = null;
  }
  canvasWrap.addEventListener('pointerdown', heroDown);
  canvasWrap.addEventListener('pointermove', heroMove);
  canvasWrap.addEventListener('pointerup', heroUp);
  canvasWrap.addEventListener('pointercancel', heroUp);

  // ───────── Bottom sheet (2 detents : peek / expanded) ─────────
  const summaryEl = root.querySelector('[data-slot="summary"]');
  const ctaEl = root.querySelector('.reveal-cta');
  let peekH = 0, expandedH = 0;
  let sdown = null;

  function relayout() {
    const rootH = root.clientHeight || 1;
    expandedH = Math.round(rootH * EXPANDED_FRAC);          // top ≈ 40% → coin stays full
    const handleH = handle.offsetHeight || 30;
    const sumH = summaryEl.offsetHeight || 180;
    const ctaH = ctaEl.offsetHeight || 52;
    peekH = handleH + sumH + ctaH + NAV_PAD + 16;           // fit summary + pinned CTAs
    peekH = Math.max(Math.round(rootH * 0.30), Math.min(peekH, Math.round(rootH * 0.56)));
    if (expandedH < peekH + 80) expandedH = peekH + 80;     // always a real expand
    if (!sdown) applyHeight(false);
  }
  function applyHeight(animate = true) {
    sheet.style.transition = animate ? '' : 'none';
    sheet.style.height = `${root.dataset.state === 'expanded' ? expandedH : peekH}px`;
    if (!animate) requestAnimationFrame(() => { sheet.style.transition = ''; });
  }
  function setSheet(state) { root.dataset.state = state; applyHeight(true); }

  relayout();
  applyHeight(false);

  const ro = new ResizeObserver(() => relayout());
  ro.observe(root);
  ctx.leaveOff = ((prev) => () => { prev(); ro.disconnect(); })(ctx.leaveOff);

  ctx.relayout = relayout;   // boot re-runs this once content is filled

  // Handle drag (up = grow) + tap-to-toggle
  function curHeight() { return parseFloat(sheet.style.height) || peekH; }
  handle.addEventListener('pointerdown', (ev) => {
    handle.setPointerCapture?.(ev.pointerId);
    sdown = { startY: ev.clientY, base: curHeight(), moved: 0 };
    sheet.style.transition = 'none';
  });
  handle.addEventListener('pointermove', (ev) => {
    if (!sdown) return;
    const dy = sdown.startY - ev.clientY;
    sdown.moved += Math.abs(dy);
    sheet.style.height = `${Math.max(peekH, Math.min(expandedH, sdown.base + dy))}px`;
  });
  function endSheetDrag() {
    if (!sdown) return;
    sheet.style.transition = '';
    if (sdown.moved < 6) {
      setSheet(root.dataset.state === 'expanded' ? 'peek' : 'expanded');
    } else {
      setSheet(curHeight() > (peekH + expandedH) / 2 ? 'expanded' : 'peek');
    }
    sdown = null;
  }
  handle.addEventListener('pointerup', endSheetDrag);
  handle.addEventListener('pointercancel', endSheetDrag);

  // ───────── actions ─────────
  function toast(msg) {
    const t = document.createElement('div');
    t.className = 'toast toast--on-dark';
    t.textContent = msg;
    document.querySelector('.screen')?.appendChild(t);
    requestAnimationFrame(() => t.setAttribute('data-visible', 'true'));
    setTimeout(() => { t.removeAttribute('data-visible'); setTimeout(() => t.remove(), 300); }, 2400);
  }
  root.querySelectorAll('[data-action]').forEach((el) => {
    if (el.dataset.action === 'toggle') return;   // handled by the drag logic
    el.addEventListener('click', (ev) => {
      ev.stopPropagation();
      const a = el.dataset.action;
      if (a === 'close') navigate('#/scan');
      else if (a === 'details') navigate(`#/coin/${ctx.coinId || ''}`);
      else if (a === 'vault') navigate('#/vault');
      else if (a === 'add') {
        toast(ms ? ms.toast : 'Ajoutée au coffre ✓');
        if (milestone === 'country') {
          // pays complété → le payoff est le grattage de la carte
          el.textContent = 'Gratter la carte 🪙';
          el.dataset.action = 'scratch';
        } else {
          el.setAttribute('disabled', ''); el.textContent = 'Ajoutée ✓';
        }
      }
      else if (a === 'scratch') { navigate('#/vault/catalog?scratch=1'); }
    });
  });

  // ───────── boot ─────────
  try {
    await data.init();
    const list = data.allCoins().filter((c) => data.coinTextures(c));
    if (!list?.length) throw new Error('app_core: aucune pièce avec textures');
    const rec = list.find((c) => c.eurioId === (query?.id || '').toString())
      || list[Math.floor(Math.random() * list.length)];
    // Legacy display shim so fillContent() keeps its country/year/name contract.
    const entry = {
      eurioId: rec.eurioId, numista_id: rec.eurioId, country: rec.countryName,
      year: rec.year, name: rec.theme || rec.designDescription || '',
    };
    ctx.coinId = rec.eurioId;

    fillContent(root, entry, owned, milestone);
    ctx.relayout?.();   // size the peek detent to the real summary height

    const edgeTex = buildProceduralEdgeTexture();
    const coin = await buildCoinFromUrls(data.coinTextures(rec), { edgeTex });
    if (active !== ctx) { disposeCoin(coin); return; }
    group = coin.group;
    ctx.coin = coin;
    stage.scene.add(group);
    statusEl?.classList.add('is-hidden');

    // Jalon : la fête se joue PAR-DESSUS le reveal (overlay déjà visible via le
    // data-milestone) — on ajoute juste le juice après le settle de la pièce.
    if (ms) {
      const layer = root.querySelector('[data-slot="cel-confetti"]');
      setTimeout(() => {
        if (active !== ctx) return;
        haptic([0, 35, 30, 80]);
        chime(ms.chime);
        if (layer) confetti(layer, { count: ms.confetti });
      }, 650);
    }

    if (owned) {
      toast("Tu l'as déjà — le scan continue");
      const addBtn = root.querySelector('[data-action="add"]');
      if (addBtn) { addBtn.textContent = 'Voir au coffre'; addBtn.dataset.action = 'vault'; }
    }
  } catch (err) {
    console.error('[reveal-stratifie] init failed', err);
    if (statusEl) statusEl.textContent = `Erreur : ${err.message || err}`;
  }
}

// ───────── mock lens content (deterministic from numista_id) ─────────

function fillContent(root, entry, owned, milestone) {
  const set = (slot, txt) => { const el = root.querySelector(`[data-slot="${slot}"]`); if (el) el.textContent = txt; };
  const m = mockReveal(entry);

  // Jalon actif : l'overlay ré-accentue l'élément qui porte la fête.
  // set  → complétion à l'état FINAL (la pièce boucle la série).
  // feat → l'accent porte l'exploit de rareté (le pic), sans toucher la complétion.
  if (milestone === 'set')     { m.owned = m.total; m.accent = 'Série complète 🎉'; }
  if (milestone === 'country') { m.accent = '🗺️ Pays complété'; }
  if (milestone === 'feat')    { m.accent = '★ Légendaire · 2% la détiennent'; }

  set('kicker', owned ? 'Doublon' : 'Nouvelle pièce');
  set('cap-country', entry.country);
  set('cap-year', String(entry.year));

  set('d-title', entry.name);
  set('d-history', m.historyLine);
  set('d-new', owned ? 'Déjà' : 'Nouvelle');
  set('d-comp', `${entry.country} · ${m.owned}/${m.total}`);
  set('d-accent', m.accent);

  set('h-1', m.historyLine);
  set('h-2', m.historyLong);

  set('r-tier', m.tier);
  set('r-mintage', `Tirage ${m.mintage.toLocaleString('fr-FR')} ex.`);
  set('r-neffect', m.nEffect);

  set('v-headline', `≈ ${m.value.ttb} € en TTB`);
  set('v-unc', `${m.value.unc} €`);
  set('v-ttb', `${m.value.ttb} €`);
  set('v-tb', `${m.value.tb} €`);

  set('c-owned', String(m.owned));
  set('c-total', `/ ${m.total}`);
  set('c-missing', m.owned >= m.total ? 'Série complète 🎉' : `Il te manque ${m.total - m.owned} pièce(s)`);
  const fill = root.querySelector('[data-slot="c-fill"]');
  if (fill) fill.style.width = `${Math.round((m.owned / m.total) * 100)}%`;
}

function mockReveal(entry) {
  const h = [...String(entry.numista_id)].reduce((a, c) => a + c.charCodeAt(0), 0);
  const tierIdx = h % 5;
  const tiers = ['Courante', 'Peu commune', 'Recherchée', 'Rare', 'Très rare'];
  const mintages = [12_400_000, 1_480_000, 470_000, 92_000, 28_500];
  const ttb = [3, 6, 12, 30, 75][tierIdx];
  const pctOwn = [42, 18, 9, 4, 2][tierIdx];
  const nth = (h % 6) + 2;

  const total = 12 + (h % 16);
  const owned = Math.max(1, total - (1 + (h % 5)));

  const accent = tierIdx >= 3
    ? `${pctOwn}% la détiennent`
    : (owned >= total ? 'Série complète' : `${nth}ᵉ à la scanner ce mois`);

  return {
    tier: tiers[tierIdx],
    mintage: mintages[tierIdx],
    value: { unc: Math.round(ttb * 2.2), ttb, tb: Math.max(2, Math.round(ttb * 0.55)) },
    nEffect: tierIdx >= 2 ? `Tu es le ${nth}ᵉ à la scanner ce mois-ci` : `${pctOwn}% des collectionneurs la détiennent`,
    owned, total, accent,
    historyLine: `${entry.name} — frappe de ${entry.country}, millésime ${entry.year}.`,
    historyLong: `Une fenêtre sur un fragment d'Europe : son dessin, son atelier et l'événement qu'elle commémore racontent une histoire que peu de gens prennent le temps de lire.`,
  };
}
