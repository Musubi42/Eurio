/* api/market.ts — dérivations marché & reveal, déterministes par eurio_id.
 *
 * Tant qu'on est en fixtures, prix/rareté/tirage sont seedés (stables entre deux
 * mounts). En live, ces méthodes seront backées par coin_market_quotes / prices.
 * Portage de mockMarket (coin-detail) + mockReveal (reveal-stratifie), unifiés
 * autour du type Grades.
 */

import type { Coin, Grades, Market, Reveal } from './types'
import { hashInt, seeded } from './util'

/** Marché bâti sur les COTES RÉELLES (coin.prices, cents) si présentes.
 *  Pas de série temporelle réelle → history/projection restent null (on ne
 *  fabrique pas de tendance). null si aucune cote exploitable. */
function marketFromPrices(coin: Coin): Market | null {
  if (!coin.prices.length) return null
  const byGrade = new Map(coin.prices.map((p) => [p.grade?.toUpperCase(), p]))
  const eur = (cents: number | null | undefined): number | null =>
    cents == null ? null : Math.round(cents) / 100
  const ttb = byGrade.get('TTB') ?? coin.prices[0]
  const p50 = eur(ttb.pMid ?? ttb.pHigh ?? ttb.pLow)
  if (p50 == null) return null
  const p25 = eur(ttb.pLow) ?? p50 * 0.8
  const p75 = eur(ttb.pHigh) ?? p50 * 1.2
  const faceEur = coin.faceValue || 0
  const grades: Grades = {
    unc: eur(byGrade.get('UNC')?.pMid) ?? Math.round(p50 * 1.8 * 100) / 100,
    ttb: eur(ttb.pMid) ?? p50,
    tb: eur(byGrade.get('TB')?.pMid) ?? Math.round(Math.max(2, p50 * 0.5) * 100) / 100,
  }
  const ratio = p50 / Math.max(faceEur, 1)
  const rarityIdx = ratio > 6 ? 3 : ratio > 3.5 ? 2 : ratio > 1.8 ? 1 : 0
  return {
    p25,
    p50,
    p75,
    deltaVsFace: faceEur > 0 ? ((p50 - faceEur) / faceEur) * 100 : 0,
    history: [],
    delta3m: null,
    projection: null,
    rarity: RARITY_SCALE[rarityIdx],
    grades,
  }
}

const RARITY_SCALE = [
  { key: 'commune', label: 'Commune', gold: false },
  { key: 'peu', label: 'Peu courante', gold: false },
  { key: 'rare', label: 'Rare', gold: true },
  { key: 'tres-rare', label: 'Très rare', gold: true },
]

/** Grades (UNC/TTB/TB) dérivés d'un prix médian. */
function gradesFromP50(p50: number): Grades {
  return {
    unc: Math.round(p50 * 1.8 * 100) / 100,
    ttb: Math.round(p50 * 100) / 100,
    tb: Math.round(Math.max(2, p50 * 0.5) * 100) / 100,
  }
}

/** Marché d'une pièce, ou null si elle s'échange à la faciale (circulation). */
export function deriveMarket(coin: Coin): Market | null {
  // Cotes RÉELLES d'abord (dump QA / live). Fallback synthétique seedé sinon.
  const real = marketFromPrices(coin)
  if (real) return real

  const faceEur = coin.faceValue || 0
  const rng = seeded(hashInt(coin.eurioId))
  const hasMarket = coin.isCommemorative || faceEur >= 2
  if (!hasMarket) return null

  let p50: number
  if (coin.isCommemorative) {
    p50 = 3 + rng() * 12
  } else {
    p50 = faceEur * (1.2 + rng() * 0.6)
  }
  const spread = 0.22 + rng() * 0.15
  const p25 = p50 * (1 - spread)
  const p75 = p50 * (1 + spread)
  const deltaVsFace = faceEur > 0 ? ((p50 - faceEur) / faceEur) * 100 : 0

  const historyPoints = coin.isCommemorative && rng() > 0.25 ? 12 : 0
  const history: number[] = []
  if (historyPoints >= 6) {
    let v = p50 * (0.75 + rng() * 0.15)
    for (let i = 0; i < historyPoints; i++) {
      const drift = (rng() - 0.4) * 0.08
      v = Math.max(0.5, v * (1 + drift))
      history.push(v)
    }
    history[history.length - 1] = p50
  }

  const delta3m =
    history.length >= 4
      ? ((history[history.length - 1] - history[history.length - 4]) / history[history.length - 4]) * 100
      : null

  let rarityIdx = 0
  const ratio = p50 / Math.max(faceEur, 1)
  if (ratio > 6) rarityIdx = 3
  else if (ratio > 3.5) rarityIdx = 2
  else if (ratio > 1.8) rarityIdx = 1

  const projection =
    history.length >= 6
      ? { low: p50 * (1.1 + rng() * 0.2), high: p50 * (1.1 + rng() * 0.2) * (1.3 + rng() * 0.4) }
      : null

  return {
    p25,
    p50,
    p75,
    deltaVsFace,
    history,
    delta3m,
    projection,
    rarity: RARITY_SCALE[rarityIdx],
    grades: gradesFromP50(p50),
  }
}

/** Reveal post-scan : tier/tirage/effet social/narration + total série. */
export function deriveReveal(coin: Coin): Reveal {
  const h = [...coin.eurioId].reduce((a, c) => a + c.charCodeAt(0), 0)
  const tierIdx = h % 5
  const tiers = ['Courante', 'Peu commune', 'Recherchée', 'Rare', 'Très rare']
  const mintages = [12_400_000, 1_480_000, 470_000, 92_000, 28_500]
  const ttb = [3, 6, 12, 30, 75][tierIdx]
  const pctOwn = [42, 18, 9, 4, 2][tierIdx]
  const nth = (h % 6) + 2
  const total = 12 + (h % 16)
  const owned = Math.max(1, total - (1 + (h % 5)))
  const accent =
    tierIdx >= 3
      ? `${pctOwn}% la détiennent`
      : owned >= total
        ? 'Série complète'
        : `${nth}ᵉ à la scanner ce mois`

  const name = coin.theme || coin.designDescription || coin.countryName

  return {
    tier: tiers[tierIdx],
    mintage: mintages[tierIdx],
    grades: { unc: Math.round(ttb * 2.2), ttb, tb: Math.max(2, Math.round(ttb * 0.55)) },
    nEffect:
      tierIdx >= 2
        ? `Tu es le ${nth}ᵉ à la scanner ce mois-ci`
        : `${pctOwn}% des collectionneurs la détiennent`,
    narration: {
      line: `${name} — frappe de ${coin.countryName}, millésime ${coin.year ?? '—'}.`,
      long: "Une fenêtre sur un fragment d'Europe : son dessin, son atelier et l'événement qu'elle commémore racontent une histoire que peu de gens prennent le temps de lire.",
    },
    completionTotal: total,
    completionOwned: owned,
    accent,
  }
}
