// _celebration.js — shared "juice" for the celebration scenes (Chunk C).
// =======================================================================
// Économie des célébrations : l'intensité est une ÉCHELLE délibérée
//   1 nouvelle pièce  <  2 set complété  ≈  3 pays complété  <  4 exploit rareté
// Ce module ne fait que la mécanique commune (haptique, son, confettis,
// câblage des CTA) ; chaque scène règle son intensité + son habillage.
//
// Zéro hasard côté produit : l'aléatoire ici n'est QUE cosmétique (trajectoire
// des confettis), jamais une récompense — cf. pull éthique.

const prefersReduced = () =>
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

export function haptic(pattern) {
  if (prefersReduced()) return;
  try { navigator.vibrate?.(pattern); } catch (_) { /* unsupported */ }
}

// Soft warm arpeggio — gentler than the scan "clink", scaled by note count.
let audioCtx = null;
export function chime(freqs, { gain = 0.12, stagger = 0.09 } = {}) {
  if (prefersReduced() || !freqs?.length) return;
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();
    const now = audioCtx.currentTime;
    const master = audioCtx.createGain();
    master.gain.value = gain;
    master.connect(audioCtx.destination);
    freqs.forEach((f, i) => {
      const t = now + i * stagger;
      const osc = audioCtx.createOscillator();
      osc.type = 'triangle';
      osc.frequency.value = f;
      const g = audioCtx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(1, t + 0.012);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.5);
      osc.connect(g); g.connect(master);
      osc.start(t); osc.stop(t + 0.55);
    });
  } catch (_) { /* audio blocked — haptic + visual carry it */ }
}

// DOM confetti. Colours come from token-backed CSS classes (no hardcoded hex).
// Random trajectory only — purely cosmetic.
export function confetti(layer, { count = 28 } = {}) {
  if (prefersReduced() || !layer) return () => {};
  const mods = ['gold', 'gold', 'gold', 'indigo', 'paper'];
  layer.style.setProperty('--cel-fall', `${(layer.clientHeight || 700) + 48}px`);
  const pieces = [];
  for (let i = 0; i < count; i++) {
    const p = document.createElement('span');
    p.className = `cel-confetti__piece cel-confetti__piece--${mods[i % mods.length]}`;
    p.style.left = `${Math.random() * 100}%`;
    p.style.setProperty('--drift', `${(Math.random() * 2 - 1) * 64}px`);
    p.style.setProperty('--rot', `${(Math.random() * 2 - 1) * 540}deg`);
    p.style.width = `${5 + Math.random() * 5}px`;
    p.style.height = `${8 + Math.random() * 7}px`;
    p.style.animationDuration = `${1.6 + Math.random() * 1.4}s`;
    p.style.animationDelay = `${Math.random() * 0.45}s`;
    layer.appendChild(p);
    pieces.push(p);
  }
  const stop = () => pieces.forEach((p) => p.remove());
  setTimeout(stop, 3600);
  return stop;
}

// Orchestrator : fire the juice after the entrance, then wire the CTAs.
// Buttons declare their destination with `data-href="#/…"` ; anything without
// one falls back to `opts.continueTo` (default the scan loop).
export function playCelebration({ root, navigate }, opts = {}) {
  if (!root) return () => {};
  const layer = root.querySelector('[data-slot="confetti"]');
  const t = setTimeout(() => {
    haptic(opts.haptic || [0, 30]);
    if (opts.chime) chime(opts.chime);
    if (opts.confetti && layer) confetti(layer, { count: opts.confetti });
  }, opts.delay ?? 200);

  root.querySelectorAll('[data-action]').forEach((el) => {
    el.addEventListener('click', (ev) => {
      ev.preventDefault();
      navigate(el.dataset.href || opts.continueTo || '#/scan');
    });
  });

  return () => clearTimeout(t);
}
