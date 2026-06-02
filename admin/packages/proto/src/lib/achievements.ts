/* lib/achievements.ts — DÉRIVATION des chasses sur la collection du joueur.
 *
 * Logique pure (pas d'état) : prend l'ensemble des eurio_id possédés + le
 * catalogue (via le contrat api) et calcule la progression de chaque chase.
 * Les DÉFINITIONS vivent dans api/fixtures/achievements.ts (données démo) ;
 * ICI on ne fait que dériver. Consommé par les scènes profil et le store.
 *
 * Port dédupliqué de profile.js / profile-achievements.js / profile-set.js.
 */

import { filterCoins } from '@/api'
import {
  ALL_EZ,
  COUNTRY_ADJECTIVES,
  COUNTRY_NAMES,
  CHASE_DEFINITIONS,
  FOUNDING,
  STANDARD_DENOMS,
  chaseDef,
} from '@/api/fixtures/achievements'
import type { ChaseDef } from '@/api/fixtures/achievements'

// ───────── Helpers ─────────

/** ISO2 majuscule depuis un eurio_id (ex 'fr-2020-…' → 'FR'). */
function isoOf(eurioId: string): string {
  return eurioId.slice(0, 2).toUpperCase()
}

function countByCountry(ownedIds: Set<string>): Record<string, number> {
  const m: Record<string, number> = {}
  for (const id of ownedIds) {
    const cc = isoOf(id)
    m[cc] = (m[cc] || 0) + 1
  }
  return m
}

/** Nombre de 2 € commémoratives possédées (id contient -2eur- sans suffixe standard). */
function commemorative2eCount(ownedIds: Set<string>): number {
  let n = 0
  for (const id of ownedIds) {
    if (id.includes('-2eur-') && !id.endsWith('-standard')) n += 1
  }
  return n
}

// ───────── Membres d'une série de circulation ─────────

export interface SetCell {
  id: string
  label: string
  faceValueCents: number
  countryCode: string
  year: number | null
}

/**
 * Résout les 8 cases d'une série de circulation pour un pays : une pièce par
 * dénomination (préférence non-commémorative). Faute de pièce réelle dans le
 * catalogue (cas actuel : pas de circulation < 2 €), retombe sur un id de
 * substitution déterministe — jamais possédé → case manquante.
 */
export function circulationMembers(countryCode: string): SetCell[] {
  const cc = countryCode.toUpperCase()
  return STANDARD_DENOMS.map((d) => {
    const pool = filterCoins({ country: cc, faceValueCents: d.cents, isCommemorative: false })
    const pick = pool[0] ?? filterCoins({ country: cc, faceValueCents: d.cents })[0] ?? null
    return {
      id: pick ? pick.eurioId : `${cc.toLowerCase()}-standard-${d.cents}c`,
      label: d.label,
      faceValueCents: d.cents,
      countryCode: cc,
      year: pick ? pick.year : null,
    }
  })
}

// ───────── Progression d'une chase ─────────

export interface ChaseRaw {
  have: number
  total: number
  /** Libellés des éléments manquants (dénominations ou noms de pays). */
  missing: string[]
}

export function chaseProgress(def: ChaseDef, ownedIds: Set<string>): ChaseRaw {
  if (def.kind === 'circulation') {
    const members = circulationMembers(def.countryCode ?? 'FR')
    const missing = members.filter((m) => !ownedIds.has(m.id))
    return { have: members.length - missing.length, total: members.length, missing: missing.map((m) => m.label) }
  }
  if (def.kind === 'founding' || def.kind === 'grande') {
    const list = def.kind === 'founding' ? FOUNDING : ALL_EZ
    const byCc = countByCountry(ownedIds)
    const missing = list.filter((cc) => !byCc[cc])
    return { have: list.length - missing.length, total: list.length, missing: missing.map((cc) => COUNTRY_NAMES[cc] || cc) }
  }
  // commem : 10 emplacements abstraits, comptage des 2 € commémoratives.
  const count = Math.min(10, commemorative2eCount(ownedIds))
  return { have: count, total: 10, missing: [] }
}

export interface ChaseProgress extends ChaseRaw {
  def: ChaseDef
  pct: number
  unlocked: boolean
  hot: boolean
  started: boolean
}

export function computeChase(def: ChaseDef, ownedIds: Set<string>): ChaseProgress {
  const raw = chaseProgress(def, ownedIds)
  const pct = raw.total ? Math.round((raw.have / raw.total) * 100) : 0
  return {
    def,
    ...raw,
    pct,
    unlocked: raw.have >= raw.total,
    hot: pct >= 75 && raw.have < raw.total,
    started: raw.have > 0,
  }
}

export function listChases(ownedIds: Set<string>): ChaseProgress[] {
  return CHASE_DEFINITIONS.map((d) => computeChase(d, ownedIds))
}

/** Une chase est-elle complète ? (utilisé par le store pour la célébration.) */
export function chaseIsComplete(def: ChaseDef, ownedIds: Set<string>): boolean {
  const { have, total } = chaseProgress(def, ownedIds)
  return have >= total
}

// ───────── Vue d'une planche (scene profile-set) ─────────

export interface SetCellView {
  label: string
  meta: string
  owned: boolean
  /** Classe de métal du disque ('' si manquante). */
  metal: string
}

export interface SetView {
  eyebrow: string
  titleHead: string
  titleEm: string
  desc: string
  have: number
  total: number
  pct: number
  cells: SetCellView[]
  missing: { label: string }[]
}

function metalFor(cents: number | null): string {
  if (cents == null) return 'nordic'
  if (cents <= 5) return 'copper'
  if (cents <= 50) return 'nordic'
  if (cents < 100) return 'silver'
  return 'bimetal'
}

function cellView(label: string, cents: number | null, owned: boolean, year: number | null): SetCellView {
  const meta = year ? String(year) : owned ? 'Acquise' : 'Manquante'
  return { label, meta, owned, metal: owned ? metalFor(cents) : '' }
}

/**
 * Construit la vue planche d'un set pour scenes/profile-set.
 * setId connus : circulation-<iso2>, eurozone-founding, grande-chasse,
 * commemoratives-2e (cf. CHASE_DEFINITIONS + résolution paramétrique pays).
 * Fallback France.
 */
export function resolveSetView(setId: string, ownedIds: Set<string>): SetView {
  const def = chaseDef(setId)
  const byCc = countByCountry(ownedIds)

  // ── Séries pays (founding / grande) ──
  if (def && (def.kind === 'founding' || def.kind === 'grande')) {
    const list = def.kind === 'founding' ? FOUNDING : ALL_EZ
    const cells = list.map((cc) => {
      const owned = !!byCc[cc]
      return cellView(COUNTRY_NAMES[cc] || cc, 200, owned, null)
    })
    const have = cells.filter((c) => c.owned).length
    const missing = list.filter((cc) => !byCc[cc]).map((cc) => ({ label: COUNTRY_NAMES[cc] || cc }))
    return {
      eyebrow: `Série · ${list.length} pays`,
      titleHead: def.kind === 'founding' ? 'Douze pays,' : 'Vingt-et-un pays,',
      titleEm: def.kind === 'founding' ? 'une union fondatrice.' : 'la grande chasse.',
      desc:
        def.kind === 'founding'
          ? 'Les douze pays fondateurs de la zone euro, une pièce par pays.'
          : "Une pièce de chaque pays de la zone euro — l'aboutissement.",
      have,
      total: list.length,
      pct: list.length ? Math.round((have / list.length) * 100) : 0,
      cells,
      missing,
    }
  }

  // ── Dix 2 € commémoratives (comptage) ──
  if (def && def.kind === 'commem') {
    const count = Math.min(10, commemorative2eCount(ownedIds))
    const cells = Array.from({ length: 10 }, (_, i) => {
      const owned = i < count
      return cellView(`N° ${i + 1}`, 200, owned, null)
    })
    const missing = cells.filter((c) => !c.owned).map((c) => ({ label: c.label }))
    return {
      eyebrow: 'Série · 2 € commémoratives',
      titleHead: 'Dix commémoratives,',
      titleEm: 'une décennie.',
      desc: 'Dix pièces commémoratives de 2 € issues de toute la zone euro.',
      have: count,
      total: 10,
      pct: count * 10,
      cells,
      missing,
    }
  }

  // ── Série de circulation (circulation-<iso2>, défaut FR) ──
  const m = /^circulation-([a-z]{2})$/i.exec(setId)
  const cc = (def?.countryCode ?? m?.[1] ?? 'FR').toUpperCase()
  const name = COUNTRY_NAMES[cc] || cc
  const members = circulationMembers(cc)
  // Match exact id, ou repli souple pays:dénomination (id forgé du catalogue absent).
  const byCcDenom: Record<string, number> = {}
  for (const id of ownedIds) {
    const face = /-(\d+)(c|eur)-/i.exec(id)
    let cents: number | null = null
    if (face) cents = face[2].toLowerCase() === 'eur' ? parseInt(face[1], 10) * 100 : parseInt(face[1], 10)
    byCcDenom[`${isoOf(id)}:${cents}`] = (byCcDenom[`${isoOf(id)}:${cents}`] || 0) + 1
  }
  const cells = members.map((mem) => {
    const owned = ownedIds.has(mem.id) || !!byCcDenom[`${mem.countryCode}:${mem.faceValueCents}`]
    return cellView(mem.label, mem.faceValueCents, owned, mem.year)
  })
  const have = cells.filter((c) => c.owned).length
  const missing = members.filter((_, i) => !cells[i].owned).map((mem) => ({ label: mem.label }))
  const adj = COUNTRY_ADJECTIVES[name] || `de ${name}`
  return {
    eyebrow: `Série · ${name}`,
    titleHead: 'Huit pièces,',
    titleEm: `une série ${name.toLowerCase()}.`,
    desc: `Toutes les pièces de circulation ${adj}, du centime à deux euros.`,
    have,
    total: members.length,
    pct: members.length ? Math.round((have / members.length) * 100) : 0,
    cells,
    missing,
  }
}
