// Maille CLASSE de la cohorte — le grain auquel l'entraînement raisonne.
//
// Piège central du sujet : le funnel compte par PIÈCE (129 lignes pour la
// giga-40), le preflight — celui qui autorise ou refuse l'entraînement — compte
// par CLASSE (40). Un standard, c'est plusieurs millésimes qui partagent leur
// avers : leurs photos s'additionnent dans UNE classe ArcFace. Afficher « 4/10 »
// par pièce ferait trier des photos inutiles et afficherait rouge sur des
// classes déjà vertes. Ce composable fait la jointure une bonne fois :
// preflight (vérité du seuil) × funnel agrégé par classe (stock à trancher).
//
// Ligne d'arrivée = le preflight, PAS un compteur local. `have` vient de
// `n_ebay` (crops eBay validés ET training-eligible) : un crop passé en
// « revers » est accepté puis écarté du training en silence — le compter ici
// ferait mentir la barre. Cf. docs/work-in-progress/giga-cohorte/PLAN.md §Tri.
//
// ⚠️ CE FICHIER NE DÉFINIT AUCUN SEUIL. `FLOOR = 10` et `GOAL = 30` y étaient
// écrits en dur le 2026-08-18 ; ils sont partis. Le plancher vient du canonique
// (`/lab/cohorts/{id}/thresholds`), et « au-delà du plancher » ne se mesure plus
// par un plafond inventé mais par le FACTEUR D'AUGMENTATION que le back calcule
// déjà : une classe à 10 réelles est gonflée ×10 pour atteindre la cible, une
// classe à 50 seulement ×2. C'est une grandeur mesurée, pas un chiffre rond.
// Cf. docs/work-in-progress/refacto-page-cohorte/DECISIONS.md §D5.

import { computed, toValue, type MaybeRefOrGetter } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import {
  fetchCohortThresholds,
  fetchCohortTrainingCropsState,
  fetchTrainingReadiness,
} from './useLabApi'
import { useCohortFunnelStatusQuery } from './useLabQueries'
import { fetchCoinsList } from '@/features/coins/composables/useCoinsApi'
import type {
  CohortFunnelCoin,
  PreflightClass,
  ResolvedThresholds,
  TrainingCropClassState,
} from '../types'

/**
 * Combien de crops ouverts il faut, en moyenne, pour en garder UN. Mesuré sur
 * les runs de juin/juillet : 61 % puis 75 % de rejets. C'est une ESTIMATION,
 * pas une garantie — elle ne sert qu'à distinguer « large » de « juste ».
 */
export const KEEP_RATIO = 4
/** Cadence de l'autopull de la réplique locale (client/replica.py, défaut 120 s). */
export const REPLICA_LAG_S = 120

/** Le filet, et seulement le filet : ce qu'on affiche le temps que le canonique
 *  réponde. Toute valeur affichée en régime normal vient du back. */
const PENDING_THRESHOLDS: ResolvedThresholds = {
  m_per_class: 4,
  min_real: 10,
  training_target: 100,
  source: { m_per_class: 'code', min_real: 'code', training_target: 'code' },
}

export interface CohortClass {
  /** design_group_id pour un standard (une ère), eurio_id pour une commémorative. */
  id: string
  kind: PreflightClass['class_kind']
  /** Libellé humain : désignation du groupe si on l'a, sinon l'identifiant. */
  label: string
  /**
   * TOUTES les pièces qui composent cette classe.
   *
   * ⚠️ Pas seulement les lignes du funnel : celui-ci collapse les millésimes
   * d'une même ère sur une ligne, et 7 pièces de la giga-40 (les « 2ᵉ carte » :
   * DE 2008, FR 2007, IT 2008, AT 2008, ES 2007, BE 2007 et 2009) n'y
   * apparaissent donc nulle part. Elles sont bien rattachées à leur classe et
   * seront entraînées — mais on croyait les avoir perdues. On réunit ici la
   * ligne et ses `era_member_eurio_ids` pour que le compte des pièces soit
   * juste (129, pas 122). Cf. DONNEES.md §1.
   */
  members: string[]
  /** Les membres que le funnel ne montrait pas — à signaler comme tels. */
  hiddenMembers: string[]
  /** Photos validées et retenues pour l'entraînement — le compteur. */
  have: number
  /**
   * Trois compteurs qui ne viennent QUE du canonique — d'où le `| null`.
   *
   * Ils valaient 0 tant que la réponse n'était pas là : le bandeau concluait
   * alors « aucune raison nommable » à un compteur figé, et l'encart des crops
   * hors file disparaissait — les 33 invisibles de la giga-40 redevenaient
   * invisibles précisément quand le serveur ne répondait pas. `null` veut dire
   * « on ne sait pas », et l'écran doit le dire ainsi.
   */
  /** Validées mais marquées REVERS : acceptées, puis écartées du bake. */
  reverseFlagged: number | null
  /** Validées mais face non tranchée : ne comptent pas encore. */
  unknownFace: number | null
  /**
   * Crops en `needs_review` SANS ligne ouverte en file : ni tranchés, ni
   * visibles nulle part. 33 sur la giga-40 — invisibles, donc jamais traités.
   * C'est exactement le genre de stock qu'un écran ne doit pas taire.
   */
  unrouted: number | null
  /**
   * Le compteur `have` de CETTE classe vient-il du canonique ? Le repli est
   * par classe (une classe résolue localement peut manquer de la réponse du
   * canonique) : l'annoncer globalement ferait passer un compteur figé de deux
   * minutes pour du temps réel au milieu d'une liste « en direct ».
   */
  haveIsLive: boolean
  /** Sources réelles toutes origines (eBay + Numista + réfs canoniques). */
  seed: number
  /** Avers Numista présents sur le disque (0 = pas de face de référence). */
  nNumista: number
  /** Réfs officielles BCE / EUR-Lex présentes. */
  nRef: number
  /** Membres absents du catalogue (réf morte / slug drift) — bloquants. */
  missingMembers: string[]
  status: PreflightClass['status']
  reason: string | null
  /** Ce qu'il reste à valider pour franchir le plancher (0 si franchi). */
  missing: number
  /** Stock de crops encore ouverts en review, par mode. */
  openSingle: number
  openLot: number
  /** Images téléchargées dont AUCUN crop n'est sorti — le gisement de la vue 3. */
  neverCropped: number
  /** Le même décompte, PAR PIÈCE : la découpe se lance pièce par pièce (une
   *  classe multi-millésimes en a plusieurs), et le job se suit par eurio_id. */
  zeroByMember: { eurioId: string; n: number }[]
  /** Images téléchargées, tous états confondus (0 = jamais scrapée). */
  sourceImages: number
  /**
   * De combien le bake gonfle cette classe pour atteindre la cible :
   * `ceil(cible / sources réelles)`. ×10 = neuf images sur dix seront des
   * variations de la même photo. C'est LA mesure d'inconfort d'une classe au-
   * dessus du plancher — elle remplace l'ancien plafond inventé à 30.
   */
  augFactor: number
  /** Scope de la review LOT : par ère pour un standard, par pièce sinon. */
  lotScope: { design_group: string } | { target: string }
  /**
   * Ce que le tri seul peut faire pour cette classe.
   *   · `impossible` — stock ouvert < ce qui manque : même en gardant TOUT on
   *     n'atteint pas le plancher. Démontrable.
   *   · `juste` — atteignable, mais il faudrait garder mieux que le taux
   *     habituel (~1 sur 4). Estimation, pas preuve.
   *   · `large` — le stock couvre le besoin avec de la marge.
   */
  reach: 'impossible' | 'juste' | 'large'
}

function reachOf(stock: number, missing: number): CohortClass['reach'] {
  if (missing === 0) return 'large'
  if (stock < missing) return 'impossible'
  return stock < missing * KEEP_RATIO ? 'juste' : 'large'
}

/**
 * Nom lisible d'une classe.
 *
 * Les standards portent une désignation d'ère toute faite (« CY 2€ standard
 * (1er type) »). Les commémoratives n'en ont pas : jusqu'ici la file affichait
 * leur identifiant brut, illisible. Le référentiel donne `design_description`
 * sous la forme `2 Euros (Bundesländer - "Schleswig-Holstein")` — on en extrait
 * le sujet et on le préfixe du pays et du millésime.
 */
function subjectOf(designDescription: string | null): string | null {
  if (!designDescription) return null
  const m = designDescription.match(/\(([^)]{3,})\)\s*$/)
  const raw = (m?.[1] ?? designDescription).trim()
  // Guillemets droits du référentiel → typographie française.
  return raw.replace(/\s*-\s*"([^"]+)"/, ' « $1 »').replace(/"/g, '')
}

function labelOf(
  id: string,
  coins: CohortFunnelCoin[],
  named: Map<string, { design_description: string | null; country: string | null; year: number | null }>,
): string {
  const era = coins.find(c => c.design_group_designation)?.design_group_designation
  if (era) return era
  for (const c of coins) {
    const info = named.get(c.eurio_id)
    const subject = subjectOf(info?.design_description ?? null)
    if (!subject) continue
    const head = [info?.country?.toUpperCase(), info?.year].filter(Boolean).join(' ')
    return head ? `${head} — ${subject}` : subject
  }
  return id
}

/**
 * Regroupe le funnel par classe et le joint au preflight.
 * Retourne TOUTES les classes (pas seulement celles sous le plancher) : la
 * ligne d'arrivée a besoin des vertes pour dessiner le peloton.
 */
export function useCohortClasses(
  cohortId: MaybeRefOrGetter<string>,
  opts: { live?: MaybeRefOrGetter<boolean> } = {},
) {
  const funnelQuery = useCohortFunnelStatusQuery(cohortId)

  // ── LES SEUILS, LUS AU CANONIQUE ────────────────────────────────────────
  // Le front n'en définit aucun. Cette requête est la SEULE source du plancher
  // affiché ; le préflight local en renvoie sa propre copie (potentiellement
  // périmée de ≤120 s), qu'on compare pour annoncer l'attente.
  const thresholdsQuery = useQuery({
    queryKey: computed(() => ['lab', 'cohort', toValue(cohortId), 'thresholds'] as const),
    queryFn: () => fetchCohortThresholds(toValue(cohortId)),
    enabled: computed(() => !!toValue(cohortId)),
    staleTime: 30 * 1000,
    refetchOnMount: 'always',
    retry: 1,
  })

  // ── LE COMPTEUR, LU AU CANONIQUE (VPS), PAS SUR LA COPIE LOCALE ──────────
  // La copie locale que sert l'API Mac n'est rafraîchie que toutes les 120 s
  // (autopull, client/replica.py) : un tri restait invisible jusqu'à 2 min, ce
  // qui se lisait comme un blocage. Le canonique, lui, EST la source des
  // décisions de review — donc du compteur.
  //
  // Vérifié le 2026-08-18 sur les 40 classes de la giga-40 : `n_eligible`
  // (canonique) == `n_ebay` (préflight local), écart total 0. Même découpage en
  // classes, même plancher. Coût mesuré : 68 Ko compressés, 0,29 s — la liste
  // des crops voyage avec, on s'en accommode.
  const liveQuery = useQuery({
    queryKey: computed(() => ['lab', 'cohort', toValue(cohortId), 'live-counts'] as const),
    queryFn: () => fetchCohortTrainingCropsState(toValue(cohortId)),
    enabled: computed(() => !!toValue(cohortId)),
    staleTime: 5 * 1000,
    refetchOnMount: 'always',
    refetchInterval: computed(() => (toValue(opts.live) ? 15_000 : false)),
    // Filet : si le canonique est injoignable, on retombe sur le préflight
    // local — périmé mais présent. L'appelant l'affiche comme tel.
    retry: 1,
  })
  // Mesuré le 2026-08-18 : training-readiness 0,14 s, funnel-status 3,58 s.
  // On ne poll donc QUE le readiness pendant qu'une classe est en main.
  //
  // ⚠ PLAFOND DE FRAÎCHEUR : sur Mac, l'API lit une RÉPLIQUE du canonique VPS,
  // rafraîchie par autopull toutes les 120 s (EURIO_REPLICA_AUTOPULL_INTERVAL,
  // client/replica.py). Les reviews, elles, écrivent au VPS. Le compteur peut
  // donc accuser jusqu'à 2 min de retard QUOI QU'ON FASSE ici — battre plus
  // vite ne ferait qu'interroger plus souvent la même copie périmée. On cale
  // le battement à 20 s et on EXPOSE l'attente à l'écran plutôt que de laisser
  // croire à un blocage.
  const readinessQuery = useQuery({
    queryKey: computed(() => ['lab', 'cohort', toValue(cohortId), 'training-readiness'] as const),
    queryFn: () => fetchTrainingReadiness(toValue(cohortId)),
    enabled: computed(() => !!toValue(cohortId)),
    staleTime: 3 * 1000,
    refetchOnMount: 'always',
    refetchInterval: computed(() => (toValue(opts.live) ? 20_000 : false)),
  })

  // Référentiel des pièces de la cohorte — un seul appel groupé pour les noms.
  // Statique : `staleTime` long, jamais poll.
  const memberIds = computed(() => {
    const ids = new Set<string>()
    for (const c of funnelQuery.data.value?.per_coin ?? []) ids.add(c.eurio_id)
    return [...ids]
  })
  const coinsQuery = useQuery({
    // memberIds DANS la clé : le funnel met 3,6 s, et une pièce ajoutée à la
    // cohorte doit relancer la requête. Sans ça, les pièces arrivées après le
    // premier vol gardaient leur identifiant brut à l'écran, sans le dire.
    queryKey: computed(
      () => ['lab', 'cohort', toValue(cohortId), 'coin-labels', memberIds.value.join('|')] as const,
    ),
    queryFn: () => fetchCoinsList({ eurio_ids: memberIds.value, limit: 500 }),
    enabled: computed(() => memberIds.value.length > 0),
    staleTime: 30 * 60 * 1000,
  })
  const coinInfo = computed(() => {
    const m = new Map<string, { design_description: string | null; country: string | null; year: number | null }>()
    for (const c of coinsQuery.data.value?.items ?? []) {
      m.set(c.eurio_id, {
        design_description: c.design_description ?? null,
        country: c.country ?? null,
        year: c.year ?? null,
      })
    }
    return m
  })

  /** Les seuils qui font autorité : ceux du canonique. */
  const thresholds = computed<ResolvedThresholds>(
    () =>
      thresholdsQuery.data.value?.effective
      ?? liveQuery.data.value?.thresholds
      ?? readinessQuery.data.value?.thresholds
      ?? PENDING_THRESHOLDS,
  )
  const floor = computed(() => thresholds.value.min_real)

  /**
   * Le préflight tourne-t-il encore avec un ancien seuil ? Sur Mac/PC il lit
   * une réplique rafraîchie toutes les 120 s : après un changement, son verdict
   * met jusqu'à deux minutes à suivre. Sans l'annoncer, on verrait un préflight
   * « prêt » sous un plancher qui, à l'écran, n'est plus franchi.
   */
  const preflightThresholds = computed<ResolvedThresholds | null>(
    () => readinessQuery.data.value?.thresholds ?? null,
  )
  const thresholdLag = computed(() => {
    const local = preflightThresholds.value
    if (!local || !thresholdsQuery.data.value) return null
    const ref = thresholds.value
    const drift = (['m_per_class', 'min_real', 'training_target'] as const).filter(
      k => local[k] !== ref[k],
    )
    return drift.length ? { keys: drift, local, canonical: ref } : null
  })

  const liveByClass = computed(() => {
    const m = new Map<string, TrainingCropClassState>()
    for (const c of liveQuery.data.value?.classes ?? []) m.set(c.class_id, c)
    return m
  })
  /**
   * D'où vient le compteur, en trois états distincts — et pas deux.
   *
   * `liveByClass.size > 0` mélangeait « la requête est encore en vol » avec
   * « le serveur est injoignable », et l'écran annonçait le second pendant le
   * premier. On lit donc l'état de la requête elle-même.
   */
  const countsSource = computed<'live' | 'loading' | 'fallback'>(() => {
    if (liveQuery.isSuccess.value && liveByClass.value.size > 0) return 'live'
    if (liveQuery.isError.value) return 'fallback'
    return liveQuery.isPending.value ? 'loading' : 'fallback'
  })
  /** Vrai quand le compteur vient du canonique (pas de décalage). */
  const liveCounts = computed(() => countsSource.value === 'live')

  const classes = computed<CohortClass[]>(() => {
    const preflight = readinessQuery.data.value?.preflight
    if (!preflight) return []
    const min = floor.value
    const target = thresholds.value.training_target

    // Funnel groupé par classe. Un coin sans design_group forme sa propre classe.
    const byClass = new Map<string, CohortFunnelCoin[]>()
    for (const coin of funnelQuery.data.value?.per_coin ?? []) {
      const key = coin.design_group_id || coin.eurio_id
      const bucket = byClass.get(key)
      if (bucket) bucket.push(coin)
      else byClass.set(key, [coin])
    }

    return preflight.classes.map((pc) => {
      const coins = byClass.get(pc.class_id) ?? []
      const sum = (f: (c: CohortFunnelCoin) => number) =>
        coins.reduce((a, c) => a + (f(c) || 0), 0)
      // Un standard se review en lot à l'échelle de l'ère : l'avers est partagé
      // sur tous les millésimes, scoper sur une seule pièce viderait le reviewer.
      const isStandard = pc.class_kind === 'design_group_id'
      // Compteur live si le canonique répond, sinon le préflight local.
      const live = liveByClass.value.get(pc.class_id)
      const have = live?.n_eligible ?? pc.n_ebay
      // Union « ligne du funnel » + membres d'ère qu'elle représente : sans ça
      // le compte des pièces manque les millésimes collapsés (cf. `members`).
      const listed = new Set(coins.map(c => c.eurio_id))
      const allMembers = [...listed]
      for (const c of coins) {
        for (const m of c.era_member_eurio_ids ?? []) {
          if (!listed.has(m) && !allMembers.includes(m)) allMembers.push(m)
        }
      }
      const openSingle = sum(c => c.n_open_review_single)
      const openLot = sum(c => c.n_open_review_lot)
      const missing = Math.max(min - have, 0)
      return {
        id: pc.class_id,
        kind: pc.class_kind,
        label: labelOf(pc.class_id, coins, coinInfo.value),
        members: allMembers,
        hiddenMembers: allMembers.filter(m => !listed.has(m)),
        have,
        haveIsLive: live !== undefined,
        reverseFlagged: live?.n_reverse_flagged ?? null,
        unknownFace: live?.n_unknown_face ?? null,
        unrouted: live?.n_review_unrouted ?? null,
        seed: pc.seed,
        nNumista: pc.n_numista,
        nRef: pc.n_ref,
        missingMembers: pc.missing_eurio_ids ?? [],
        status: pc.status,
        reason: pc.reason,
        missing,
        openSingle,
        openLot,
        neverCropped: sum(c => c.n_zero_crops),
        zeroByMember: coins
          .filter(c => (c.n_zero_crops || 0) > 0)
          .map(c => ({ eurioId: c.eurio_id, n: c.n_zero_crops }))
          .sort((a2, b2) => b2.n - a2.n),
        sourceImages: sum(c => c.n_source_images),
        // Même formule que le bake (foundation/enrichment.projection) : on
        // recalcule ici parce que le funnel la donne par PIÈCE et qu'une classe
        // agrège plusieurs pièces — sommer des facteurs n'aurait aucun sens.
        augFactor: Math.max(1, Math.ceil(target / Math.max(pc.seed, 1))),
        lotScope: isStandard ? { design_group: pc.class_id } : { target: pc.class_id },
        reach: reachOf(openSingle + openLot, missing),
      }
    })
  })

  /** Sous le plancher, la plus rapide à débloquer en tête. */
  const belowFloor = computed(() =>
    classes.value
      .filter(c => c.have < floor.value)
      .sort((a, b) => a.missing - b.missing || b.openSingle - a.openSingle),
  )

  /**
   * À sourcer : celles que le tri n'amènera pas au plancher (`impossible`) et
   * celles qui n'y arriveraient que de justesse (`juste`) — savoir qu'on n'a
   * aucune marge vaut d'être dit AVANT d'y passer une heure. Les plus démunies
   * d'abord.
   */
  const needSourcing = computed(() =>
    belowFloor.value
      .filter(c => c.reach !== 'large')
      .sort(
        (a, b) =>
          (a.reach === 'impossible' ? 0 : 1) - (b.reach === 'impossible' ? 0 : 1)
          || a.openSingle + a.openLot - (b.openSingle + b.openLot),
      ),
  )

  /**
   * Vue 3 — classes ayant des images téléchargées dont aucun crop n'est sorti.
   * Le gisement le plus rentable de la cohorte : 4 486 images sur la giga-40,
   * rouvertes par la passe de secours bimétal (mesuré le 2026-08-18 :
   * fr-2010-degaulle 0 → 144 crops sur 193 photos). Les plus fournies d'abord.
   */
  const needCrops = computed(() =>
    classes.value
      .filter(c => c.neverCropped > 0)
      .sort((a, b) => b.neverCropped - a.neverCropped),
  )

  /**
   * Les crops partis sur des pièces SŒURS hors cohorte (D4). On ne les récupère
   * pas et on n'élargit rien : on les AFFICHE. 56 crops sur 37 pièces au dernier
   * relevé — du travail réel qui n'entraînera rien, et qu'on croyait perdu
   * seulement parce qu'aucun écran ne le nommait.
   */
  /** Total des crops bloqués hors file — `null` tant qu'on ne sait pas. */
  const nUnrouted = computed(() => {
    const known = classes.value.filter(c => c.unrouted !== null)
    if (known.length === 0) return null
    return known.reduce((a, c) => a + (c.unrouted ?? 0), 0)
  })

  const sistersLeak = computed(() => funnelQuery.data.value?.rescued_to_sisters ?? [])
  const nSistersLeak = computed(() =>
    sistersLeak.value.reduce((a, s) => a + s.n, 0),
  )

  return {
    classes,
    belowFloor,
    needSourcing,
    needCrops,
    sistersLeak,
    nSistersLeak,
    nUnrouted,
    /** Rafraîchit le stock singles/lots (coûteux) — après un changement de classe. */
    refetchFunnel: () => funnelQuery.refetch(),
    /** Vrai quand le compteur est lu au canonique — donc sans décalage. */
    liveCounts,
    /** 'live' | 'loading' | 'fallback' — à afficher tel quel, sans raccourci. */
    countsSource,
    /** Décalage à annoncer UNIQUEMENT en repli sur la copie locale. */
    lagSeconds: REPLICA_LAG_S,
    /** Les trois seuils du canonique, et le plancher isolé (le plus utilisé). */
    thresholds,
    floor,
    thresholdState: computed(() => thresholdsQuery.data.value ?? null),
    refetchThresholds: () => thresholdsQuery.refetch(),
    /** Non-null quand le préflight local n'a pas encore vu le nouveau seuil. */
    thresholdLag,
    /** Les seuils que le préflight local a réellement appliqués (≤120 s de retard). */
    preflightThresholds,
    /** Quota eBay restant, tel que le backend l'estime. */
    quota: computed(() => funnelQuery.data.value?.quota ?? null),
    ready: computed(() => readinessQuery.data.value?.ready ?? false),
    unresolved: computed(() => readinessQuery.data.value?.unresolved ?? []),
    nTotal: computed(() => classes.value.length),
    nMissing: computed(() => belowFloor.value.reduce((a, c) => a + c.missing, 0)),
    isLoading: computed(() => readinessQuery.isPending.value || funnelQuery.isPending.value),
    error: computed(
      () =>
        (readinessQuery.error.value as Error | null)?.message
        ?? (funnelQuery.error.value as Error | null)?.message
        ?? null,
    ),
  }
}
