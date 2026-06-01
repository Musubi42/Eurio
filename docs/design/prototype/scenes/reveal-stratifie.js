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
  createStage, loadCoinsManifest, buildCoinFromEntry, buildProceduralEdgeTexture,
  disposeCoin, R_OUT,
} from './_coin3d.js';

const HERO_FILL = 0.78;
const IDLE_SPD = 0.2;
const DRAG_K = 0.011;
const TILT_K = 0.006;
const TILT_MAX = 0.55;

// Sheet detents, as fractions of the scene height.
const SHEET_FRAC = 0.80;   // total sheet height (= expanded extent)
const PEEK_FRAC = 0.56;    // how much of the sheet shows in peek (clears the nav)

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

  // ───────── Bottom sheet (2 detents) ─────────
  let sheetH = 0, peekTranslate = 0;
  function measure() {
    const rootH = root.clientHeight || 1;
    sheetH = Math.round(rootH * SHEET_FRAC);
    peekTranslate = Math.round(rootH * (SHEET_FRAC - PEEK_FRAC));
    sheet.style.height = `${sheetH}px`;
  }
  function applyState(animate = true) {
    sheet.style.transition = animate ? '' : 'none';
    sheet.style.transform = `translateY(${root.dataset.state === 'expanded' ? 0 : peekTranslate}px)`;
    if (!animate) requestAnimationFrame(() => { sheet.style.transition = ''; });
  }
  function setSheet(state, animate = true) { root.dataset.state = state; applyState(animate); }
  measure();
  setSheet('peek', false);

  const ro = new ResizeObserver(() => { measure(); if (!sdown) applyState(false); });
  ro.observe(root);
  ctx.leaveOff = ((prev) => () => { prev(); ro.disconnect(); })(ctx.leaveOff);

  // Handle drag + tap-to-toggle
  let sdown = null;
  function curTranslate() {
    const m = /translateY\(([-\d.]+)px\)/.exec(sheet.style.transform || '');
    return m ? parseFloat(m[1]) : (root.dataset.state === 'expanded' ? 0 : peekTranslate);
  }
  handle.addEventListener('pointerdown', (ev) => {
    handle.setPointerCapture?.(ev.pointerId);
    sdown = { startY: ev.clientY, base: curTranslate(), moved: 0 };
    sheet.style.transition = 'none';
  });
  handle.addEventListener('pointermove', (ev) => {
    if (!sdown) return;
    const dy = ev.clientY - sdown.startY;
    sdown.moved += Math.abs(dy);
    const ty = Math.max(0, Math.min(peekTranslate, sdown.base + dy));
    sheet.style.transform = `translateY(${ty}px)`;
  });
  function endSheetDrag(ev) {
    if (!sdown) return;
    sheet.style.transition = '';
    const ty = curTranslate();
    if (sdown.moved < 6) {
      setSheet(root.dataset.state === 'expanded' ? 'peek' : 'expanded');
    } else {
      setSheet(ty < peekTranslate * 0.5 ? 'expanded' : 'peek');
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
      else if (a === 'add') { toast('Ajoutée au coffre ✓'); el.setAttribute('disabled', ''); el.textContent = 'Ajoutée ✓'; }
    });
  });

  // ───────── boot ─────────
  try {
    const manifest = await loadCoinsManifest();
    const list = manifest.coins;
    if (!list?.length) throw new Error('coins.json vide');
    const entry = list.find((c) => c.numista_id === (query?.id || '').toString())
      || list[Math.floor(Math.random() * list.length)];
    ctx.coinId = entry.numista_id;

    fillContent(root, entry, owned);

    const edgeTex = buildProceduralEdgeTexture();
    const coin = await buildCoinFromEntry(entry, { edgeTex });
    if (active !== ctx) { disposeCoin(coin); return; }
    group = coin.group;
    ctx.coin = coin;
    stage.scene.add(group);
    statusEl?.classList.add('is-hidden');

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

function fillContent(root, entry, owned) {
  const set = (slot, txt) => { const el = root.querySelector(`[data-slot="${slot}"]`); if (el) el.textContent = txt; };
  const m = mockReveal(entry);

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
