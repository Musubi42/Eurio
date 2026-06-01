// Scene : reveal-stratifie
// =========================
// The stratified post-scan reveal. Reuses the shared 3D engine (_coin3d.js) for
// a rotatable hero, and a horizontally-snapping lens carousel for progressive
// disclosure (Découverte default · Histoire · Rareté · Valeur · Complétion).
//
// Proto note : lens CONTENT is mocked deterministically from the 3D manifest
// entry (numista_id → stable values). The real data contract (referential +
// cote + completion) is wired later — here we validate the *design*.

import {
  createStage, loadCoinsManifest, buildCoinFromEntry, buildProceduralEdgeTexture,
  disposeCoin, R_OUT,
} from './_coin3d.js';

const HERO_FILL = 0.82;
const IDLE_SPD = 0.2;      // rad/s gentle idle auto-rotation (calm, lets you read the design)
const DRAG_K = 0.011;
const TILT_K = 0.006;
const TILT_MAX = 0.55;

const LENS_ORDER = ['decouverte', 'histoire', 'rarete', 'valeur', 'completion'];
const PIN_KEY = 'eurio.reveal.pin';
const LENS_PREF_KEY = 'eurio.lens';   // set by onboarding-lentille (chunk E)

let active = null;

export async function mount({ query, navigate }) {
  if (active) { active.dispose(); active = null; }

  const root = document.querySelector('[data-scene="reveal-stratifie"]');
  if (!root) return;
  const canvasWrap = root.querySelector('[data-slot="canvas-wrap"]');
  const statusEl = root.querySelector('[data-slot="status"]');
  const lensesEl = root.querySelector('[data-slot="lenses"]');

  const owned = query?.owned === '1';
  root.dataset.owned = owned ? '1' : '0';

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

  // ── teardown ──
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

  // ── hero rotation (drag + inertia decaying into a gentle idle) ──
  let group = null;
  let omega = IDLE_SPD;
  let dragging = false;
  stage.onFrame((dt) => {
    frameCoin();
    if (!group) return;
    if (!dragging) {
      group.rotation.y += omega * dt;
      omega += (IDLE_SPD - omega) * Math.min(1, dt * 2.5);
      group.rotation.x += (0 - group.rotation.x) * Math.min(1, dt * 4); // ease tilt back
    }
  });
  stage.start();

  let down = null;
  function onDown(ev) {
    if (!group) return;
    canvasWrap.querySelector('canvas')?.setPointerCapture?.(ev.pointerId);
    dragging = true;
    down = { lastX: ev.clientX, lastY: ev.clientY, lastT: performance.now(), vel: 0 };
    root.dataset.rotated = '1';
  }
  function onMove(ev) {
    if (!down || !group) return;
    const dx = ev.clientX - down.lastX;
    const dy = ev.clientY - down.lastY;
    const dt = Math.max((performance.now() - down.lastT) / 1000, 1 / 240);
    group.rotation.y += dx * DRAG_K;
    group.rotation.x = Math.max(-TILT_MAX, Math.min(TILT_MAX, group.rotation.x + dy * TILT_K));
    down.vel = down.vel * 0.7 + ((dx * DRAG_K) / dt) * 0.3;
    down.lastX = ev.clientX;
    down.lastY = ev.clientY;
    down.lastT = performance.now();
  }
  function onUp() {
    if (!down) return;
    dragging = false;
    omega = Math.max(-12, Math.min(12, down.vel || IDLE_SPD));
    down = null;
  }
  canvasWrap.addEventListener('pointerdown', onDown);
  canvasWrap.addEventListener('pointermove', onMove);
  canvasWrap.addEventListener('pointerup', onUp);
  canvasWrap.addEventListener('pointercancel', onUp);

  // ── lens carousel : dots sync + click-to-scroll ──
  const dots = [...root.querySelectorAll('[data-dot]')];
  const lensEls = [...lensesEl.querySelectorAll('.reveal-lens')];
  let scrollRAF = 0;
  function activeLensIndex() {
    const mid = lensesEl.scrollLeft + lensesEl.clientWidth / 2;
    let best = 0, bestD = Infinity;
    lensEls.forEach((el, i) => {
      const c = el.offsetLeft + el.clientWidth / 2;
      const d = Math.abs(c - mid);
      if (d < bestD) { bestD = d; best = i; }
    });
    return best;
  }
  function syncDots() {
    const i = activeLensIndex();
    dots.forEach((d, k) => d.setAttribute('aria-current', String(k === i)));
  }
  lensesEl.addEventListener('scroll', () => {
    cancelAnimationFrame(scrollRAF);
    scrollRAF = requestAnimationFrame(syncDots);
  });
  function scrollToLens(i, smooth = true) {
    const el = lensEls[i];
    if (!el) return;
    const left = el.offsetLeft - (lensesEl.clientWidth - el.clientWidth) / 2;
    lensesEl.scrollTo({ left, behavior: smooth ? 'smooth' : 'auto' });
  }
  dots.forEach((d, i) => d.addEventListener('click', () => scrollToLens(i)));

  // ── pin (declared default lens) ──
  const pins = [...root.querySelectorAll('[data-pin]')];
  function readPin() { try { return localStorage.getItem(PIN_KEY); } catch (_) { return null; } }
  function paintPins() {
    const pinned = readPin();
    pins.forEach((p) => p.setAttribute('aria-pressed', String(p.dataset.pin === pinned)));
  }
  pins.forEach((p) => p.addEventListener('click', (ev) => {
    ev.stopPropagation();
    const key = p.dataset.pin;
    const next = readPin() === key ? null : key;
    try { next ? localStorage.setItem(PIN_KEY, next) : localStorage.removeItem(PIN_KEY); } catch (_) {}
    paintPins();
  }));
  paintPins();

  // ── actions ──
  function toast(msg) {
    const t = document.createElement('div');
    t.className = 'toast toast--on-dark';
    t.textContent = msg;
    t.style.zIndex = 'var(--z-toast)';
    document.querySelector('.screen')?.appendChild(t);
    requestAnimationFrame(() => t.setAttribute('data-visible', 'true'));
    setTimeout(() => { t.removeAttribute('data-visible'); setTimeout(() => t.remove(), 300); }, 2400);
  }
  root.querySelectorAll('[data-action]').forEach((el) => {
    el.addEventListener('click', (ev) => {
      ev.stopPropagation();
      const a = el.dataset.action;
      if (a === 'close') navigate('#/scan');
      else if (a === 'details') navigate(`#/coin/${ctx.coinId || ''}`);
      else if (a === 'vault') navigate('#/vault');
      else if (a === 'add') {
        toast('Ajoutée au coffre ✓');
        el.setAttribute('disabled', '');
        el.textContent = 'Ajoutée ✓';
      }
    });
  });

  // ── boot ──
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

    // Default lens : pin > onboarding preference > Découverte.
    let startKey = readPin();
    if (!startKey) { try { startKey = localStorage.getItem(LENS_PREF_KEY); } catch (_) {} }
    const startIdx = Math.max(0, LENS_ORDER.indexOf(startKey));
    requestAnimationFrame(() => { scrollToLens(startIdx, false); syncDots(); });
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

  // Découverte
  set('d-title', entry.name);
  set('d-history', m.historyLine);
  set('d-new', owned ? 'Déjà' : 'Nouvelle');
  set('d-comp', `${entry.country} · ${m.owned}/${m.total}`);
  set('d-accent', m.accent);

  // Histoire
  set('h-1', m.historyLine);
  set('h-2', m.historyLong);

  // Rareté
  set('r-tier', m.tier);
  set('r-mintage', `Tirage ${m.mintage.toLocaleString('fr-FR')} ex.`);
  set('r-neffect', m.nEffect);

  // Valeur
  set('v-headline', `≈ ${m.value.ttb} € en TTB`);
  set('v-unc', `${m.value.unc} €`);
  set('v-ttb', `${m.value.ttb} €`);
  set('v-tb', `${m.value.tb} €`);

  // Complétion
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
