/**
 * Le besoin par classe — lecture de `GET /class-need` (O1/O2, lots 0-2).
 *
 * ⛔ CE FICHIER NE CALCULE AUCUN FAIT. Il lit, il trie, il filtre. Tous les
 * comptes affichés (`sum_need`, `coverage`, `parked`, l'effet du filtre pays…)
 * viennent du back, qui les tient de `shared.class_need` et `shared.dino_scope`.
 * Un total réagrégé côté front finit par diverger de celui du back, et personne
 * ne sait plus lequel croire — c'est la leçon de `useCohortFloor.ts`.
 *
 * Ce qui EST calculé ici est de l'ordre de la vue, jamais du fait : l'ordre des
 * lignes et le sous-ensemble affiché.
 *
 * ROUTE LÉGÈRE, ET C'EST DÉLIBÉRÉ
 * -------------------------------
 * `/class-need` est du SQL pur sur le canonique — pas de `:8042`. La page
 * n'est donc PAS `meta.heavy` : savoir ce qui manque, et ce que ça coûterait,
 * ne doit pas dépendre d'un Mac allumé (O2 §Où elle vit). Seuls les GESTES
 * qu'elle propose sont lourds, et `AppLayout` les grise tout seul.
 */
import { computed, ref, shallowRef } from 'vue'

import { eurioApi } from '@/shared/api/eurio-api'

/** La banque lue. Sans elle, aucun chiffre de la page n'est reproductible :
 *  la banque a été rebâtie deux fois pendant la seule session de design. */
export interface BuildInfo {
  anchors_kind: string
  encoder_version: string
  build_id: string | null
  built_at: string | null
  n_anchors: number
}

/** Les crops ouverts que le besoin met hors travail (D2/D3). Deux causes, jamais
 *  confondues : `full_class` se répare par du tri, `no_prediction` par un
 *  backfill. */
export interface Parked {
  full_class: number
  no_prediction: number
}

export interface Totals {
  n_classes: number
  /** Palier 1 (D7) : classes à `have >= 1`. */
  coverage: number
  /** Palier 2 (D7) : Σ `need`, ce qui manque À LA BANQUE. */
  sum_need: number
  /** Σ `min(need, pending_scoped)` — ce que la file peut réellement poser. */
  sum_reachable: number
  accepted_pending: number
  rebuild_would_place: number
  n_open: number
  by_bottleneck: Record<string, number>
}

export type Bottleneck = 'pleine' | 'review' | 'scrape'
export type Family = 'nationale' | 'portrait_standard' | 'emission_commune'

export interface ClassNeedRow {
  class_id: string
  label: string
  country: string | null
  family: Family
  have: number
  cap: number
  target: number
  need: number
  pending: number
  pending_scoped: number
  best_margin: number | null
  bottleneck: Bottleneck
  n_train_eligible: number
  /** D8 — validés, pas encore bâtis. `have` ne bouge qu'au rebuild. */
  accepted_pending: number
  /** O4c — le filtre pays s'est retiré parce qu'il ne laissait rien. */
  country_disarmed: boolean
  /**
   * Ce que CHAQUE filtre retire, dans l'ordre où la file les applique. Ils sont
   * EMBOÎTÉS — `pending − era − country − denom = pending_scoped` — et jamais
   * additionnables autrement : les lire comme trois effets indépendants ferait
   * annoncer « 12 + 8 masqués » au-dessus d'une file qui en a perdu 15.
   */
  n_hidden_by_era: number
  n_hidden_by_country: number
  /** 0 tant que la porte dénomination n'est pas armée (`?min_denom=`) : elle
   *  coûte ~5 % de vrais positifs, c'est un choix d'opérateur. */
  n_hidden_by_denom: number
}

export interface ClassNeedResponse {
  build: BuildInfo
  totals: Totals
  parked: Parked
  classes: ClassNeedRow[]
}

/** Le seuil du verdict DINO. En dessous, le modèle n'est net sur AUCUN candidat
 *  de la file — mesuré : 73 des 147 classes du palier 1 sont dans ce cas. */
export const MARGIN_FLOOR = 0.05

export type Palier = 'couverture' | 'profondeur'

/**
 * L'ordre de travail. Ce n'est pas un tri de colonne : c'est « ce que l'action
 * débloque ».
 *
 * En palier 1 (couverture, D7) une classe à zéro passe devant tout le reste,
 * quel que soit son stock — le premier exemplaire vaut ~9× les neuf suivants
 * depuis l'amorce médoïde. En palier 2 on retombe sur l'ordre d'O2 :
 * `min(need, pending_scoped)` décroissant, pour ne pas mettre en tête une
 * classe à qui il manque 8 exemplaires mais qui n'a aucun candidat.
 *
 * Les classes sans geste (`pleine`, `scrape`) ne remontent jamais devant celles
 * qui en ont un.
 */
export function workOrder(rows: ClassNeedRow[], palier: Palier): ClassNeedRow[] {
  const rank = (r: ClassNeedRow): number => {
    if (r.bottleneck !== 'review') return 0
    const debloque = Math.min(r.need, r.pending_scoped)
    if (palier === 'couverture' && r.have === 0) return 1_000_000 + debloque
    return debloque
  }
  return [...rows].sort((a, b) => {
    const d = rank(b) - rank(a)
    if (d !== 0) return d
    // Départage stable : la marge décide s'il vaut le coup de regarder.
    const ma = a.best_margin ?? -1
    const mb = b.best_margin ?? -1
    if (mb !== ma) return mb - ma
    return a.class_id.localeCompare(b.class_id)
  })
}

export interface Filters {
  bottleneck: Bottleneck | 'tous'
  country: string | 'tous'
  family: Family | 'toutes'
  /** N'afficher que les classes dont au moins un candidat dépasse le seuil. */
  margeUtile: boolean
  q: string
}

export const EMPTY_FILTERS: Filters = {
  bottleneck: 'tous', country: 'tous', family: 'toutes',
  margeUtile: false, q: '',
}

export function applyFilters(rows: ClassNeedRow[], f: Filters): ClassNeedRow[] {
  const q = f.q.trim().toLowerCase()
  return rows.filter((r) => {
    if (f.bottleneck !== 'tous' && r.bottleneck !== f.bottleneck) return false
    if (f.country !== 'tous' && r.country !== f.country) return false
    if (f.family !== 'toutes' && r.family !== f.family) return false
    if (f.margeUtile && (r.best_margin ?? 0) < MARGIN_FLOOR) return false
    if (q && !r.class_id.toLowerCase().includes(q)
        && !r.label.toLowerCase().includes(q)) return false
    return true
  })
}

/**
 * Le lien d'un geste. Il ne porte QUE ce qui change vraiment le périmètre.
 *
 * 🔴 CORRECTION DU 2026-08-23 — le lien portait `&pays=tous` sur les classes
 * désarmées, et c'était une régression, pas une précaution.
 *
 * Le raisonnement d'origine (« sans ça la pêche réappliquerait son filtre et
 * servirait zéro ») est FAUX depuis O4c : `build_dino_scope` se désarme
 * lui-même. Mesuré — pour une classe désarmée, lien nu et `pays=tous` servent
 * exactement le même nombre de crops. Ce que `pays=tous` changeait, c'est que
 * le résumé revenait avec `country_disarmed: false`, donc `PecheBar` affichait
 * « tous pays » au lieu de « ⚠ pays DE — désarmé ».
 *
 * Autrement dit : le lien ÉTEIGNAIT l'avertissement, sur les 97 classes (des
 * 211 en review) où il a précisément quelque chose à dire. L'opérateur ne
 * pouvait plus distinguer « j'ai levé le filtre » de « le back l'a retiré
 * parce qu'il ne laissait rien ».
 *
 * Règle qui en sort : un lien ne pré-règle un filtre que s'il change ce qui
 * est SERVI. Un réglage qui ne change que l'affichage doit être laissé au
 * back, qui sait, lui, pourquoi il l'a pris.
 */
export function gestureHref(r: ClassNeedRow): string | null {
  const p = new URLSearchParams({ class: r.class_id })
  if (r.bottleneck === 'pleine') {
    // Voir les parqués : on lève explicitement le cadrage par le besoin.
    // Celui-ci change bien ce qui est servi — il a sa place dans le lien.
    p.set('need', '0')
  } else if (r.bottleneck !== 'review') {
    return null // `scrape` : le geste est un plan, pas une file (moitié ACHETER).
  }
  // `review` : rien à porter. Le cadrage par le besoin est le DÉFAUT depuis D9,
  // et l'écrire (`need=1`) brouillerait la règle « seule la levée s'écrit dans
  // l'URL » que la pêche vient d'établir.
  return `/review/peche?${p.toString()}`
}

export function useClassNeed() {
  const data = shallowRef<ClassNeedResponse | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function load(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      data.value = await eurioApi.get<ClassNeedResponse>('/class-need')
    } catch (e) {
      // On n'affiche JAMAIS une liste vide sur erreur : une page muette se lit
      // « il n'y a rien à faire », ce qui est plausible et faux.
      data.value = null
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  /** Les pays présents, pour le filtre — dérivé des lignes, jamais codé en dur. */
  const countries = computed(() => {
    const s = new Set<string>()
    for (const r of data.value?.classes ?? []) if (r.country) s.add(r.country)
    return [...s].sort()
  })

  return { data, loading, error, load, countries }
}
