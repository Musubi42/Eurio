/* api/parity.ts — seam de déterminisme pour la capture parité (web).
 *
 * En mode parité, l'horloge est FIGÉE sur PARITY_NOW : la collection seedée,
 * les buckets « mois » et la sparkline « 12 derniers mois » deviennent stables
 * entre deux runs. C'est LE mécanisme partagé web↔android — Android lira la
 * même constante PARITY_NOW (C2 la hoiste dans shared/fixtures/parity/).
 *
 * Activation = flag RUNTIME, pas un build dédié : le MÊME dist sert l'audit
 * humain (horloge réelle) et la capture (Playwright injecte `__eurioParity`
 * via addInitScript avant boot). `?parity` en query marche aussi pour un
 * debug manuel. Aucune scène/store ne lit Date.now() directement pour du
 * rendu : tout passe par `now()`.
 */

// Instant figé unique (UTC). Mi-année → « 12 derniers mois » couvre un seed
// réparti sur l'année écoulée.
export const PARITY_NOW = Date.parse('2026-06-01T12:00:00Z')

export function isParity(): boolean {
  if (typeof window === 'undefined') return false
  const w = window as Window & { __eurioParity?: boolean }
  if (w.__eurioParity === true) return true
  return new URLSearchParams(window.location.search).has('parity')
}

/** Horloge : figée en parité, réelle sinon. Remplace tout Date.now() *rendu*. */
export function now(): number {
  return isParity() ? PARITY_NOW : Date.now()
}

// Pose figée du coin 3D en capture parité (radians). Léger tilt → relief +
// anneau bimétal lisibles, sans dépendre du moment où le clip est pris. Les
// scènes 3D (reveal, transition) sautent leur animation temporelle vers cette
// pose quand isParity().
export const PARITY_COIN_POSE = { x: 0.12, y: -0.4, z: 0 }
