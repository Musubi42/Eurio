// Scene : scan-transition-3d
// ===========================
// The diégetic camera→3D transition. Reuses the REAL coin renderer (_coin3d.js)
// and layers a hand-tuned physics state machine on top :
//
//   morph  — the 3D coin emerges from the detected-coin ghost (scale-in).
//   spin   — an impulse (auto, or a thumb flick) spins it; speed decays.
//   settle — it snaps obverse-forward; at the STOP we fire the peak :
//            scale-pop + gold halo + haptic (~400ms window) + "clink".
//   posed  — gentle idle float; drag to re-spin; CTAs appear.
//
// Garde-fous incarnés : ~0.8–1.2s, tap = skip to settle, ?light=1 + reduced-
// motion = settle quasi-direct. Zéro hasard : the only uncertainty is epistemic
// (which coin), never a gamble — there is no near-miss branch.

import {
  createStage, buildCoinFromUrls, buildProceduralEdgeTexture,
  disposeCoin, R_OUT,
} from './_coin3d.js';
import * as data from '../_shared/data.js';

// ───────── Feel constants (audit-tunable) ─────────
const MORPH_DUR = 0.24;        // s, ghost → hero scale-in
const MORPH_DUR_LIGHT = 0.14;
const AUTO_IMPULSE = 18;       // rad/s, default spin when the user doesn't flick
const SPIN_DAMP = 3.4;         // exponential decay /s
const SETTLE_OMEGA = 2.2;      // rad/s threshold → begin the snap
const SNAP_DUR = 0.32;         // s, ease to obverse-forward
const POP_DUR = 0.24;          // s, scale-pop at the stop
const DRAG_K = 0.011;          // rad per px dragged
const FLICK_MAX = 30;          // clamp flick speed
const TAP_PX = 7;              // movement under this = a tap
const HERO_SCALE = 1;          // morph target multiplier (fit handled by camera distance)
const HERO_FILL = 0.72;        // coin fills this fraction of the canvas's tight dimension

let active = null;

export async function mount({ query, navigate }) {
  if (active) { active.dispose(); active = null; }

  const root = document.querySelector('[data-scene="scan-transition-3d"]');
  if (!root) return;

  const canvasWrap = root.querySelector('[data-slot="canvas-wrap"]');
  const statusEl = root.querySelector('[data-slot="status"]');
  const titleEl = root.querySelector('[data-slot="title"]');
  const flashEl = root.querySelector('[data-slot="flash"]');
  const haloEl = root.querySelector('[data-slot="halo"]');

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const light = query?.light === '1' || reduced;

  const stage = createStage(canvasWrap);
  // Hero framing — fit-to-view. Distance is derived from the canvas aspect so the
  // coin is ALWAYS centred and fully visible whatever the device. The vertical
  // placement (upper part of the screen) is handled in CSS by the 3D band height,
  // not the camera → device-robust. A tiny y offset keeps a subtle 3D tilt.
  function frameCoin() {
    const w = canvasWrap.clientWidth || 1;
    const h = canvasWrap.clientHeight || 1;
    const tanHalfV = Math.tan((35 * Math.PI / 180) / 2);
    const halfNeeded = R_OUT / HERO_FILL;
    const dist = Math.max(halfNeeded / tanHalfV, halfNeeded / (tanHalfV * (w / h)));
    stage.camera.position.set(0, dist * 0.06, dist);
    stage.camera.lookAt(0, 0, 0);
  }
  frameCoin();
  let audioCtx = null;

  // ── teardown : stop RAF + WebGL when leaving (proper, unlike the lab scene) ──
  const ctx = {
    stage, coin: null, leaveOff: null,
    dispose() {
      if (this.leaveOff) this.leaveOff();
      if (this.coin) { stage.scene.remove(this.coin.group); disposeCoin(this.coin); }
      try { audioCtx?.close(); } catch (_) { /* already closed */ }
      stage.dispose();
    },
  };
  active = ctx;
  const onLeave = () => { if (active === ctx) { ctx.dispose(); active = null; } };
  window.addEventListener('hashchange', onLeave, { once: true });
  ctx.leaveOff = () => window.removeEventListener('hashchange', onLeave);

  // ───────── animation state ─────────
  let phase = 'loading';      // loading | morph | spin | settle | posed
  let omega = 0;              // spin angular velocity (rad/s)
  let idleT = 0;
  let group = null;
  const tweens = [];

  const setScale = (m) => { if (group) group.scale.setScalar(HERO_SCALE * m); };
  const setPhase = (p) => { phase = p; root.dataset.phase = p; };
  const easeOut = (t) => 1 - Math.pow(1 - t, 3);

  function addTween(o) { tweens.push({ t: 0, from: 0, to: 1, ...o }); }
  function clearTweens() { tweens.length = 0; }
  function advanceTweens(dt) {
    for (let i = tweens.length - 1; i >= 0; i--) {
      const tw = tweens[i];
      tw.t += dt;
      const p = tw.dur > 0 ? Math.min(tw.t / tw.dur, 1) : 1;
      const e = tw.ease ? tw.ease(p) : p;
      tw.onUpdate?.(tw.from + (tw.to - tw.from) * e, p);
      if (p >= 1) { tweens.splice(i, 1); tw.onDone?.(); }
    }
  }

  // ───────── the frame step ─────────
  let dragging = false;
  stage.onFrame((dt) => {
    frameCoin();   // cheap; keeps the fit correct across resizes / late layout
    advanceTweens(dt);
    if (!group) return;
    if (phase === 'spin' && !dragging) {
      group.rotation.y += omega * dt;
      omega *= Math.exp(-SPIN_DAMP * dt);
      if (Math.abs(omega) < SETTLE_OMEGA) enterSettle();
    } else if (phase === 'posed') {
      idleT += dt;
      group.position.y = Math.sin(idleT * 1.1) * 0.25;
      if (!dragging && Math.abs(omega) > 0.002) {
        group.rotation.y += omega * dt;
        omega *= Math.exp(-SPIN_DAMP * dt);
      }
    }
  });
  stage.start();

  // ───────── play / settle ─────────
  function play() {
    clearTweens();
    omega = 0;
    group.rotation.set(0, 0, 0);
    group.position.set(0, 0, 0);
    setScale(0.18);
    if (titleEl) titleEl.textContent = 'Identification…';
    setPhase('morph');
    addTween({
      dur: light ? MORPH_DUR_LIGHT : MORPH_DUR,
      ease: easeOut,
      onUpdate: (v) => setScale(0.18 + 0.82 * v),
      onDone: () => {
        setScale(1);
        if (light) { settleStop(); }
        else { setPhase('spin'); omega = AUTO_IMPULSE; }
      },
    });
  }

  function enterSettle() {
    if (phase === 'settle') return;
    setPhase('settle');
    const start = group.rotation.y;
    const target = Math.round(start / (Math.PI * 2)) * (Math.PI * 2);
    addTween({
      dur: SNAP_DUR, from: start, to: target, ease: easeOut,
      onUpdate: (v) => { group.rotation.y = v; },
      onDone: settleStop,
    });
  }

  // The STOP — the memorised peak (peak-end). FX synced to the landing.
  function settleStop() {
    omega = 0;
    setScale(1);
    addTween({
      dur: POP_DUR,
      onUpdate: (_v, p) => setScale(1 + 0.07 * Math.sin(Math.PI * p)),
      onDone: () => setScale(1),
    });
    fireSettleFX();
    if (titleEl) titleEl.textContent = 'Identifiée';
    setPhase('posed');
    idleT = 0;
  }

  function forceSettle() {
    if (phase === 'settle' || phase === 'posed' || phase === 'loading') return;
    clearTweens();
    omega = 0;
    setScale(1);
    enterSettle();
  }

  // ───────── settle FX ─────────
  function burst(el) {
    if (!el) return;
    el.classList.remove('is-burst');
    void el.offsetWidth;            // reflow → restart the keyframes
    el.classList.add('is-burst');
  }
  function fireSettleFX() {
    burst(flashEl);
    burst(haloEl);
    try { navigator.vibrate?.([0, 45, 35, 120]); } catch (_) { /* unsupported */ }
    playClink();
  }

  // Synthesised metallic "clink" — two detuned partials with a fast decay.
  function playClink() {
    if (reduced) return;
    try {
      if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === 'suspended') audioCtx.resume();
      const now = audioCtx.currentTime;
      const master = audioCtx.createGain();
      master.gain.value = 0.16;
      master.connect(audioCtx.destination);
      [2280, 3160].forEach((freq, i) => {
        const osc = audioCtx.createOscillator();
        osc.type = i === 0 ? 'triangle' : 'sine';
        osc.frequency.value = freq;
        const g = audioCtx.createGain();
        g.gain.setValueAtTime(0.0001, now);
        g.gain.exponentialRampToValueAtTime(i === 0 ? 1 : 0.5, now + 0.006);
        g.gain.exponentialRampToValueAtTime(0.0001, now + (i === 0 ? 0.22 : 0.14));
        osc.connect(g); g.connect(master);
        osc.start(now); osc.stop(now + 0.26);
      });
    } catch (_) { /* audio blocked — haptic + visual carry the peak */ }
  }

  // ───────── pointer : flick / drag / tap ─────────
  let down = null;  // { x, y, t, moved, lastX, lastT, vel }
  const canvasEl = () => stage.renderer.domElement;

  function onPointerDown(ev) {
    if (phase === 'loading') return;
    canvasEl().setPointerCapture?.(ev.pointerId);
    dragging = true;
    down = { x: ev.clientX, y: ev.clientY, t: performance.now(), moved: 0,
             lastX: ev.clientX, lastT: performance.now(), vel: 0 };
    if (audioCtx?.state === 'suspended') audioCtx.resume();
  }
  function onPointerMove(ev) {
    if (!down || !group) return;
    const dx = ev.clientX - down.lastX;
    const dt = Math.max((performance.now() - down.lastT) / 1000, 1 / 240);
    down.moved += Math.abs(dx);
    if (phase === 'spin' || phase === 'posed' || phase === 'settle') {
      group.rotation.y += dx * DRAG_K;
      const inst = (dx * DRAG_K) / dt;
      down.vel = down.vel * 0.7 + inst * 0.3;
    }
    down.lastX = ev.clientX;
    down.lastT = performance.now();
  }
  function onPointerUp() {
    if (!down) return;
    const wasTap = down.moved < TAP_PX;
    dragging = false;
    if (wasTap) {
      forceSettle();
    } else {
      omega = Math.max(-FLICK_MAX, Math.min(FLICK_MAX, down.vel));
      if (Math.abs(omega) > SETTLE_OMEGA) setPhase('spin');
      else enterSettle();
    }
    down = null;
  }

  const cw = canvasWrap;
  cw.addEventListener('pointerdown', onPointerDown);
  cw.addEventListener('pointermove', onPointerMove);
  cw.addEventListener('pointerup', onPointerUp);
  cw.addEventListener('pointercancel', onPointerUp);

  // ───────── chrome buttons ─────────
  root.querySelectorAll('[data-action]').forEach((el) => {
    el.addEventListener('click', (ev) => {
      ev.stopPropagation();
      const a = el.dataset.action;
      if (a === 'skip') forceSettle();
      else if (a === 'replay') play();
      else if (a === 'continue') navigate(`#/scan/reveal?id=${ctx.coinId || ''}`);
    });
  });

  // ───────── boot ─────────
  try {
    await data.init();
    const list = data.allCoins().filter((c) => data.coinTextures(c));
    if (!list?.length) throw new Error('app_core: aucune pièce avec textures');
    const requestedId = (query?.id || '').toString();
    // No id → a random coin so each scan reveals something different (demo
    // liveliness only; the act itself is never a gamble — see garde-fous).
    const rec = list.find((c) => c.eurioId === requestedId)
      || list[Math.floor(Math.random() * list.length)];
    // Legacy display shim so fillDone() keeps its country/year/name contract.
    const entry = {
      eurioId: rec.eurioId, numista_id: rec.eurioId, country: rec.countryName,
      year: rec.year, name: rec.theme || rec.designDescription || '',
    };
    ctx.coinId = rec.eurioId;

    const edgeTex = buildProceduralEdgeTexture();
    const coin = await buildCoinFromUrls(data.coinTextures(rec), { edgeTex });
    if (active !== ctx) { disposeCoin(coin); return; }  // left during async load
    group = coin.group;
    ctx.coin = coin;
    stage.scene.add(group);

    fillDone(root, entry);
    if (statusEl) { statusEl.classList.add('is-hidden'); }
    play();
  } catch (err) {
    console.error('[scan-transition-3d] init failed', err);
    if (statusEl) statusEl.textContent = `Erreur : ${err.message || err}`;
  }
}

function fillDone(root, entry) {
  const set = (slot, txt) => {
    const el = root.querySelector(`[data-slot="${slot}"]`);
    if (el) el.textContent = txt;
  };
  set('done-country', entry.country);
  set('done-year', String(entry.year));
  set('done-title', entry.name);
}
