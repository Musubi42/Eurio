/* lib/celebration.ts — « juice » partagé des célébrations (port de _celebration.js).
 * Haptique + son + confettis DOM. Aléatoire = cosmétique uniquement (pull éthique). */

const prefersReduced = (): boolean =>
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

export function haptic(pattern: number[]): void {
  if (prefersReduced()) return
  try {
    navigator.vibrate?.(pattern)
  } catch {
    /* non supporté */
  }
}

let audioCtx: AudioContext | null = null
export function chime(freqs: number[], opts: { gain?: number; stagger?: number } = {}): void {
  const { gain = 0.12, stagger = 0.09 } = opts
  if (prefersReduced() || !freqs.length) return
  try {
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    audioCtx = audioCtx ?? new Ctor()
    if (audioCtx.state === 'suspended') void audioCtx.resume()
    const now = audioCtx.currentTime
    const master = audioCtx.createGain()
    master.gain.value = gain
    master.connect(audioCtx.destination)
    freqs.forEach((f, i) => {
      const t = now + i * stagger
      const osc = audioCtx!.createOscillator()
      osc.type = 'triangle'
      osc.frequency.value = f
      const g = audioCtx!.createGain()
      g.gain.setValueAtTime(0.0001, t)
      g.gain.exponentialRampToValueAtTime(1, t + 0.012)
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.5)
      osc.connect(g)
      g.connect(master)
      osc.start(t)
      osc.stop(t + 0.55)
    })
  } catch {
    /* audio bloqué — l'haptique + le visuel prennent le relais */
  }
}

/** Confettis DOM dans `layer`. Couleurs via classes token-backed. */
export function confetti(layer: HTMLElement | null, opts: { count?: number } = {}): () => void {
  const { count = 28 } = opts
  if (prefersReduced() || !layer) return () => {}
  const mods = ['gold', 'gold', 'gold', 'indigo', 'paper']
  layer.style.setProperty('--cel-fall', `${(layer.clientHeight || 700) + 48}px`)
  const pieces: HTMLElement[] = []
  for (let i = 0; i < count; i++) {
    const p = document.createElement('span')
    p.className = `cel-confetti__piece cel-confetti__piece--${mods[i % mods.length]}`
    p.style.left = `${Math.random() * 100}%`
    p.style.setProperty('--drift', `${(Math.random() * 2 - 1) * 64}px`)
    p.style.setProperty('--rot', `${(Math.random() * 2 - 1) * 540}deg`)
    p.style.width = `${5 + Math.random() * 5}px`
    p.style.height = `${8 + Math.random() * 7}px`
    p.style.animationDuration = `${1.6 + Math.random() * 1.4}s`
    p.style.animationDelay = `${Math.random() * 0.45}s`
    layer.appendChild(p)
    pieces.push(p)
  }
  const stop = () => pieces.forEach((p) => p.remove())
  setTimeout(stop, 3600)
  return stop
}
