/* stores/collection.ts — données PRODUITES par l'app (hors contrat api).
 *
 * Port de _shared/state.js : collection, niveau, prefs, flags. Persisté en
 * localStorage (futur Room côté Android). C'est la couche qui SUPERPOSE
 * l'`owned` sur le catalogue renvoyé par l'api (jointure côté store).
 */

import { defineStore } from 'pinia'
import { allCoins } from '@/api'
import { now } from '@/api/parity'
import { CHASE_DEFINITIONS, TIERS } from '@/api/fixtures/achievements'
import { chaseIsComplete } from '@/lib/achievements'
import presetPopulated from '@shared/fixtures/preset-populated.json'
import presetProfileDemo from '@shared/fixtures/preset-profile-demo.json'

// Presets de seed du coffre — générés par le dump QA (build_app_core_qa.py)
// depuis la curation, et lus TELS QUELS ici comme côté Android
// (MainActivity.seedFromFixture). Single-source → parité byte-exacte. Le
// contenu (eurio_id ⊆ subset, addedAt figés sur parity_now) est un OUTPUT, pas
// écrit à la main : ne pas éditer les JSON, régénérer via `go-task ml:build-app-core-qa`.
interface SeedPreset {
  name: string
  collection: Array<{
    eurioId: string
    addedAt: number
    valueAtAddCents: number | null
    condition: string | null
    note: string | null
  }>
}
const SEED_PRESETS: Record<string, SeedPreset> = {
  populated: presetPopulated as SeedPreset,
  'profile-demo': presetProfileDemo as SeedPreset,
  demo: presetPopulated as SeedPreset,
}

const LS_KEY = 'eurio.proto.v2'

/** Cible de pièces injectées par le seed démo (debug settings). */
const SEED_DEMO_TARGET = 15

export interface CollectionEntry {
  eurioId: string
  addedAt: number
  valueAtAddCents: number | null
  condition: string | null
  note: string | null
}

interface LevelState {
  tier: string
  progressPct: number
  nextThresholdHint: string
  pendingUnlock: string | null
  unlockedSets: string[]
}

export type VaultView = 'grid' | 'list'
export type VaultSort = 'country' | 'face' | 'price' | 'month'

export interface VaultFilters {
  countries: string[]
  faceValueCents: number[]
  types: string[]
  rarities: string[]
  conditions: string[]
  yearMin: number
  yearMax: number
}

export function defaultVaultFilters(): VaultFilters {
  return { countries: [], faceValueCents: [], types: [], rarities: [], conditions: [], yearMin: 1999, yearMax: 2026 }
}

export type NotifFreq = 'discrete' | 'normale'

interface Prefs {
  notifications: boolean
  // Notifications granulaires (port de profile-settings : opt-in, OFF par défaut).
  notifHunting: boolean
  notifSetDone: boolean
  notifNewCoins: boolean
  notifFreq: NotifFreq
  catalogUpdate: 'wifi' | 'cell' | 'manual'
  telemetry: boolean
  locale: string
  vaultView: VaultView
  vaultSort: VaultSort
  vaultFilters: VaultFilters
}

export type Lens = 'discovery' | 'valeur' | 'histoire' | 'collection'

interface CollectionState {
  firstRun: boolean
  collection: CollectionEntry[]
  level: LevelState
  prefs: Prefs
  lens: Lens
  debugMode: boolean
}

function defaultState(): CollectionState {
  return {
    firstRun: true,
    collection: [],
    level: {
      tier: 'Découvreur',
      progressPct: 0,
      nextThresholdHint: 'Scanne ta première pièce',
      pendingUnlock: null,
      unlockedSets: [],
    },
    prefs: {
      notifications: false,
      notifHunting: false,
      notifSetDone: false,
      notifNewCoins: false,
      notifFreq: 'discrete',
      catalogUpdate: 'wifi',
      telemetry: false,
      locale: 'fr',
      vaultView: 'grid',
      vaultSort: 'country',
      vaultFilters: defaultVaultFilters(),
    },
    lens: 'discovery',
    debugMode: false,
  }
}

function loadPersisted(): CollectionState {
  const base = defaultState()
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return base
    const parsed = JSON.parse(raw) as Partial<CollectionState>
    // Fusion PROFONDE : un state persité plus ancien peut manquer des sous-objets
    // (ex. prefs.vaultFilters) — un spread superficiel les écraserait par undefined.
    return {
      ...base,
      ...parsed,
      level: { ...base.level, ...(parsed.level ?? {}) },
      prefs: {
        ...base.prefs,
        ...(parsed.prefs ?? {}),
        vaultFilters: { ...base.prefs.vaultFilters, ...(parsed.prefs?.vaultFilters ?? {}) },
      },
    }
  } catch {
    return base
  }
}

export const useCollectionStore = defineStore('collection', {
  state: (): CollectionState => loadPersisted(),

  getters: {
    count: (s): number => s.collection.length,
    ownedIds: (s): Set<string> => new Set(s.collection.map((c) => c.eurioId)),
    hasCoin:
      (s) =>
      (eurioId: string): boolean =>
        s.collection.some((c) => c.eurioId === eurioId),
    entry:
      (s) =>
      (eurioId: string): CollectionEntry | null =>
        s.collection.find((c) => c.eurioId === eurioId) ?? null,
  },

  actions: {
    persist() {
      try {
        localStorage.setItem(LS_KEY, JSON.stringify(this.$state))
      } catch {
        /* quota / private mode — non bloquant pour le proto */
      }
    },

    addCoin(eurioId: string, opts: Partial<Omit<CollectionEntry, 'eurioId'>> = {}) {
      if (this.hasCoin(eurioId)) return
      this.collection.push({
        eurioId,
        // addedAt explicite (seed déterministe) sinon horloge — figée en parité.
        addedAt: opts.addedAt ?? now(),
        valueAtAddCents: opts.valueAtAddCents ?? null,
        condition: opts.condition ?? null,
        note: opts.note ?? null,
      })
      this.recomputeLevel()
      this.checkSetCompletions()
      this.persist()
    },

    /** Retire une entrée et la renvoie (pour permettre l'undo). */
    removeCoin(eurioId: string): CollectionEntry | null {
      const idx = this.collection.findIndex((c) => c.eurioId === eurioId)
      if (idx < 0) return null
      const [removed] = this.collection.splice(idx, 1)
      this.recomputeLevel()
      this.persist()
      return removed
    },

    /** Réinsère une entrée retirée (undo) — bypass du garde-fou anti-doublon. */
    restoreEntry(entry: CollectionEntry) {
      this.collection.push(entry)
      this.recomputeLevel()
      this.persist()
    },

    setVaultView(view: VaultView) {
      this.prefs.vaultView = view
      this.persist()
    },

    setVaultSort(sort: VaultSort) {
      this.prefs.vaultSort = sort
      this.persist()
    },

    setVaultFilters(filters: VaultFilters) {
      this.prefs.vaultFilters = filters
      this.persist()
    },

    recomputeLevel() {
      const count = this.collection.length
      // Seuils dérivés de la table unique TIERS (fixtures/achievements).
      let idx = 0
      for (let i = 0; i < TIERS.length; i++) if (count >= TIERS[i].min) idx = i
      const current = TIERS[idx]
      const next = TIERS[idx + 1]
      this.level.tier = current.name
      if (next && current.nextAt != null) {
        const span = current.nextAt - current.min
        const done = count - current.min
        this.level.progressPct = Math.min(100, Math.round((done / span) * 100))
        this.level.nextThresholdHint = `Encore ${current.nextAt - count} pièces pour devenir ${next.name}`
      } else {
        this.level.progressPct = 100
        this.level.nextThresholdHint = 'Tu as atteint le rang le plus élevé.'
      }
    },

    /**
     * Détecte les chasses fraîchement complétées → arme une célébration unlock.
     * Itère les définitions partagées (CHASE_DEFINITIONS). Une seule à la fois :
     * on s'arrête à la première nouvelle complétion. circulation-fr ne se
     * déclenche jamais tant que le catalogue n'a pas la circulation (cf. note
     * fixtures/achievements) — comportement honnête, pas un bug.
     */
    checkSetCompletions() {
      const ids = this.ownedIds
      const already = new Set(this.level.unlockedSets)
      for (const def of CHASE_DEFINITIONS) {
        if (already.has(def.id)) continue
        if (chaseIsComplete(def, ids)) {
          this.level.pendingUnlock = def.id
          this.level.unlockedSets = [...already, def.id]
          return
        }
      }
    },

    /**
     * IDs du seed démo : pièces RÉELLES du catalogue, une par pays distinct,
     * dans l'ordre du snapshot, jusqu'à SEED_DEMO_TARGET. Déterministe (pas de
     * hasard) → fait progresser les chasses pays + 2€ commémo.
     */
    demoCoinIds(): string[] {
      const byCountry = new Map<string, string>()
      for (const c of allCoins()) {
        if (!byCountry.has(c.country)) byCountry.set(c.country, c.eurioId)
        if (byCountry.size >= SEED_DEMO_TARGET) break
      }
      return [...byCountry.values()]
    },

    /** Seed démo (bouton debug settings) : ajoute les pièces démo à l'horloge courante. */
    seedDemoCollection() {
      for (const eurioId of this.demoCoinIds()) this.addCoin(eurioId)
    },

    /**
     * Applique un état de collection NOMMÉ (contrat PARITY_STATE des flows parité).
     * Lit le preset généré par le dump QA (SEED_PRESETS, single-source partagé avec
     * Android) et applique chaque entrée verbatim — eurio_id ⊆ subset, addedAt figés
     * sur parity_now → buckets « mois » + sparkline 12 mois byte-identiques web↔android.
     */
    seedFixture(name: string) {
      this.reset()
      this.completeOnboarding()
      if (name === 'empty') return
      const preset = SEED_PRESETS[name] ?? SEED_PRESETS.populated
      for (const entry of preset.collection) {
        this.addCoin(entry.eurioId, {
          addedAt: entry.addedAt,
          valueAtAddCents: entry.valueAtAddCents,
          condition: entry.condition,
          note: entry.note,
        })
      }
    },

    consumePendingUnlock(): string | null {
      const id = this.level.pendingUnlock
      this.level.pendingUnlock = null
      this.persist()
      return id
    },

    completeOnboarding() {
      this.firstRun = false
      this.persist()
    },

    replayOnboarding() {
      this.firstRun = true
      this.persist()
    },

    setLens(lens: Lens) {
      this.lens = lens
      this.persist()
    },

    toggleDebug(): boolean {
      this.debugMode = !this.debugMode
      this.persist()
      return this.debugMode
    },

    reset() {
      this.$patch(defaultState())
      this.persist()
    },
  },
})
