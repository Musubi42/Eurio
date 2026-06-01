// Scene : scan-coin-3d
// Three.js bimetal coin lab — render-quality validation + tune sliders.
//
// The heavy lifting (renderer, studio lighting, bimetal mesh, texture/normal-map
// pipeline) lives in the shared engine ./_coin3d.js so scan-transition-3d.js can
// reuse the exact same coin. This file owns only the *lab* interaction model :
// OrbitControls (drag/zoom), the country carousel, and the debug tune panel.

import { OrbitControls } from 'https://esm.sh/three@0.160.0/examples/jsm/controls/OrbitControls.js';
import {
  createStage, loadCoinsManifest, buildCoinFromEntry, buildProceduralEdgeTexture,
  disposeCoin, DEFAULT_NORMAL_STRENGTH, DEFAULT_METALNESS, DEFAULT_ROUGHNESS,
  DEFAULT_EXPOSURE, REVERSE_RELIEF_BOOST,
} from './_coin3d.js';

let activeContext = null;

export async function mount({ state, query }) {
  if (activeContext) { activeContext.dispose(); activeContext = null; }

  const root = document.querySelector('[data-scene="scan-coin-3d"]');
  if (!root) return;
  const canvasWrap = root.querySelector('[data-slot="canvas-wrap"]');
  const statusEl = root.querySelector('[data-slot="status"]');
  const labelEl = root.querySelector('[data-slot="label"]');

  const stage = createStage(canvasWrap);
  const controls = new OrbitControls(stage.camera, stage.renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 22;
  controls.maxDistance = 80;
  controls.target.set(0, 0, 0);
  controls.autoRotateSpeed = 1.2;
  stage.onFrame(() => controls.update());
  stage.start();

  const ctx = {
    stage, controls, coin: null, tune: null,
    statusEl, labelEl, root, debugListener: null,
    // Edge texture is built once and reused across coin swaps — it doesn't depend
    // on the photo and rebuilding it would just churn GPU memory for no win.
    edgeTex: buildProceduralEdgeTexture(),
    dispose() {
      if (this.debugListener) window.removeEventListener('debug:toggle', this.debugListener);
      controls.dispose();
      stage.dispose();
    },
  };
  activeContext = ctx;

  root.querySelectorAll('[data-action]').forEach((el) => {
    el.addEventListener('click', () => onChipClick(el, ctx));
  });

  const tuneChip = root.querySelector('.coin3d-tune-toggle');
  const syncTuneVisibility = () => {
    if (tuneChip) tuneChip.classList.toggle('is-hidden', !state.state.debugMode);
  };
  syncTuneVisibility();
  window.addEventListener('debug:toggle', syncTuneVisibility);
  ctx.debugListener = syncTuneVisibility;

  try {
    setStatus(statusEl, 'Chargement du catalogue…');
    const manifest = await loadCoinsManifest();
    const list = manifest.coins;
    if (!list?.length) throw new Error('coins.json: empty list');

    const requestedId = (query?.id || '').toString();
    let idx = list.findIndex((c) => c.numista_id === requestedId);
    if (idx < 0) idx = 0;
    ctx.coinIndex = idx;
    ctx.coinList = list;

    wireSliders(root, ctx);
    await loadAndBuildCoin(ctx, list[idx]);
  } catch (err) {
    console.error('[scan-coin-3d] init failed', err);
    setStatus(statusEl, `Erreur : ${err.message || err}`);
  }
}

// ───────── Coin swapping ─────────

async function loadAndBuildCoin(ctx, entry) {
  setStatus(ctx.statusEl, `Chargement ${entry.country} ${entry.year}…`);
  if (ctx.labelEl) {
    ctx.labelEl.textContent = `${entry.country} · ${entry.year} · ${entry.name}`;
  }

  if (ctx.coin) {
    ctx.stage.scene.remove(ctx.coin.group);
    disposeCoin(ctx.coin);
    ctx.coin = null;
  }

  const coin = await buildCoinFromEntry(entry, { edgeTex: ctx.edgeTex });
  ctx.stage.scene.add(coin.group);
  ctx.coin = coin;

  // Re-apply current slider state to the freshly-built materials so tuning
  // persists across coin swaps.
  if (ctx.tune) {
    Object.entries(ctx.tune).forEach(([k, v]) => applyTune(ctx, k, v));
  }

  // Reflect the current coin in the URL without firing the router.
  history.replaceState({}, '', `#/scan/coin-3d?id=${entry.numista_id}`);

  setStatus(ctx.statusEl, '', { fadeOut: true });
}

function swapCoin(ctx, direction) {
  if (!ctx.coinList) return;
  const N = ctx.coinList.length;
  ctx.coinIndex = (ctx.coinIndex + direction + N) % N;
  loadAndBuildCoin(ctx, ctx.coinList[ctx.coinIndex]);
}

// ───────── UI handlers ─────────

function onChipClick(chip, ctx) {
  const action = chip.dataset.action;
  if (action === 'toggle-normal') {
    const on = chip.getAttribute('aria-pressed') !== 'true';
    chip.setAttribute('aria-pressed', String(on));
    const s = on ? (ctx.tune?.relief ?? DEFAULT_NORMAL_STRENGTH) : 0;
    setReliefStrength(ctx, s);
  } else if (action === 'toggle-rotate') {
    const on = chip.getAttribute('aria-pressed') !== 'true';
    chip.setAttribute('aria-pressed', String(on));
    ctx.controls.autoRotate = on;
  } else if (action === 'reset-view') {
    ctx.controls.reset();
    ctx.stage.camera.position.set(0, 6, 38);
    ctx.controls.target.set(0, 0, 0);
  } else if (action === 'prev') {
    swapCoin(ctx, -1);
  } else if (action === 'next') {
    swapCoin(ctx, +1);
  } else if (action === 'toggle-tune') {
    const panel = document.querySelector('[data-slot="tune"]');
    if (!panel) return;
    const willOpen = panel.dataset.open !== 'true';
    panel.dataset.open = String(willOpen);
    const tuneChip = document.querySelector('.coin3d-tune-toggle');
    if (tuneChip) tuneChip.setAttribute('aria-pressed', String(willOpen));
  }
}

function wireSliders(root, ctx) {
  ctx.tune = {
    relief: DEFAULT_NORMAL_STRENGTH,
    metalness: DEFAULT_METALNESS,
    roughness: DEFAULT_ROUGHNESS,
    exposure: DEFAULT_EXPOSURE,
  };
  Object.entries(ctx.tune).forEach(([k, v]) => {
    const input = root.querySelector(`[data-tune="${k}"]`);
    const label = root.querySelector(`[data-val="${k}"]`);
    if (input) input.value = String(v);
    if (label) label.textContent = formatVal(v);
  });
  root.querySelectorAll('[data-tune]').forEach((input) => {
    const key = input.dataset.tune;
    const label = root.querySelector(`[data-val="${key}"]`);
    input.addEventListener('input', () => {
      const v = parseFloat(input.value);
      ctx.tune[key] = v;
      if (label) label.textContent = formatVal(v);
      applyTune(ctx, key, v);
    });
  });
}

function applyTune(ctx, key, v) {
  if (!ctx.coin) return;
  const faces = [ctx.coin.matSilver, ctx.coin.matGold, ctx.coin.matSilverBack, ctx.coin.matGoldBack];
  const allMetal = [...faces, ctx.coin.matRim, ctx.coin.matEdge];
  if (key === 'relief') {
    setReliefStrength(ctx, v);
    const chip = document.querySelector('[data-action="toggle-normal"]');
    if (chip) chip.setAttribute('aria-pressed', String(v > 0));
  } else if (key === 'metalness') {
    allMetal.forEach((m) => { m.metalness = v; });
  } else if (key === 'roughness') {
    allMetal.forEach((m) => { m.roughness = v; });
  } else if (key === 'exposure') {
    ctx.stage.setExposure(v);
  }
}

function setReliefStrength(ctx, v) {
  if (!ctx.coin) return;
  const back = v * REVERSE_RELIEF_BOOST;
  ctx.coin.matSilver.normalScale.set(v, v);
  ctx.coin.matGold.normalScale.set(v, v);
  ctx.coin.matSilverBack.normalScale.set(back, back);
  ctx.coin.matGoldBack.normalScale.set(back, back);
}

function formatVal(v) {
  return Math.abs(v) < 1 ? v.toFixed(2) : v.toFixed(1);
}

function setStatus(el, text, opts = {}) {
  if (!el) return;
  el.textContent = text;
  el.classList.remove('is-hidden');
  if (opts.fadeOut) setTimeout(() => el.classList.add('is-hidden'), 1200);
}
