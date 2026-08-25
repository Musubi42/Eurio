/**
 * Les états de la section « images d'évaluation », pour la maquette
 * (`/coins/eval-images/maquette`).
 *
 * POURQUOI DES FIXTURES ET PAS LA VRAIE DONNÉE
 * --------------------------------------------
 * Un écran se juge sur ses cas limites autant que sur son cas nominal, et ces
 * cas-là ne se commandent pas en base : une classe sans aucune photo d'éval, un
 * `:8042` qui ne répond pas, une pièce dont TOUTES les photos viennent d'une
 * autre pièce du même groupe de dessin, les 6 captures belges justes à la
 * classe et fausses à la pièce. Les rendre regardables en un clic, c'est ce qui
 * permet de trancher le visuel AVANT de brancher.
 *
 * ⛔ CE FICHIER NE SERT QU'À LA MAQUETTE. Aucun écran branché ne l'importe : la
 * section réelle lit `/scan-corpus/captures/:eurio_id` et rien d'autre. Une
 * fixture qui fuit dans un écran de production, c'est un chiffre inventé montré
 * à quelqu'un qui le croit.
 *
 * Les valeurs sont calquées sur du mesuré (LOT1-IMPORT §3/§4) : conditions
 * réelles des deux séances, quatre normaliseurs (`hough_tight`, `hough_relaxed`,
 * `hough_strict`, `hough_loose`), horodatages sans fuseau (heure locale du
 * device — le sidecar n'en porte pas).
 */
import type { ScanCapture, ScanCorpusResponse } from '../composables/useScanCorpus'

export interface EtatEvalImages {
  id: string
  titre: string
  /** Ce que cet état met à l'épreuve — affiché dans le sélecteur. */
  enjeu: string
  data: ScanCorpusResponse | null
  loading: boolean
  error: string | null
}

/** Une image locale ne convient pas : la maquette doit montrer de VRAIES
 *  vignettes pour dire quelque chose de la densité de la grille. Faute de
 *  `:8042` en maquette, on assume le placeholder — et une vignette cassée est
 *  elle aussi un état à regarder (dernière capture ci-dessous). */
const PLACEHOLDER =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="144" height="144">
      <rect width="144" height="144" fill="#E2E0D6"/>
      <circle cx="72" cy="72" r="52" fill="#C9C6B8"/>
      <circle cx="72" cy="72" r="36" fill="#D8D5C7"/>
      <text x="72" y="78" font-family="monospace" font-size="13"
            text-anchor="middle" fill="#55566C">2 €</text>
    </svg>`,
  )

let seq = 0
function capture(over: Partial<ScanCapture> = {}): ScanCapture {
  seq += 1
  const id = `cap${String(seq).padStart(13, '0')}`
  return {
    capture_id: id,
    eurio_id: 'fr-2018-2eur-simone-veil',
    is_exact_match: true,
    condition: 'bright_plain',
    bundle_source: 'device_pull_20260601',
    captured_at: '2026-06-01T15:34:57.631',
    device_model: null,
    raw_w: 480,
    raw_h: 640,
    crop_w: 224,
    crop_h: 224,
    normalize_method: 'hough_strict',
    class_level_only: false,
    eval_decision: null,
    eval_decision_by: null,
    eval_decision_at: null,
    eval_decision_reason: null,
    notes: null,
    crop_url: PLACEHOLDER,
    raw_url: PLACEHOLDER,
    decisions: [],
    ...over,
  }
}

function reponse(over: Partial<ScanCorpusResponse>): ScanCorpusResponse {
  const captures = over.captures ?? []
  return {
    eurio_id: 'fr-2018-2eur-simone-veil',
    class_id: 'fr-2018-2eur-simone-veil',
    class_kind: 'eurio_id',
    class_eurio_ids: ['fr-2018-2eur-simone-veil'],
    scope: 'coin',
    scope_note: 'Les photos rendues sont celles de cette pièce.',
    referential_available: true,
    n_captures: captures.length,
    n_exact_match: captures.filter((c) => c.is_exact_match).length,
    n_class_level_only: captures.filter((c) => c.class_level_only).length,
    n_excluded: captures.filter((c) => c.eval_decision === 'exclude').length,
    n_kept: captures.filter((c) => c.eval_decision === 'keep').length,
    n_undecided: captures.filter((c) => c.eval_decision === null).length,
    ...over,
    captures,
  }
}

// ── Nominal : les 26 captures de Simone Veil, un seul pool mélangé ─────────
// 6 viennent de la séance d'avril, 20 de celle de juin. Elles ne sont PAS
// regroupées : « une photo de val pour une classe, c'est une photo ». La
// provenance reste lisible sous chaque vignette, et c'est tout ce qu'elle est.
const NOMINAL: ScanCapture[] = [
  ...['bright_plain', 'bright_textured', 'dim', 'glare_specular', 'oblique'].flatMap(
    (condition, i) =>
      [0, 1, 2, 3].map((p) =>
        capture({
          condition,
          bundle_source: 'device_pull_20260601',
          normalize_method: p === 3 ? 'hough_loose' : 'hough_strict',
          captured_at: `2026-06-01T15:3${i}:0${p}.100`,
        }),
      ),
  ),
  ...['bright_plain', 'close_plain', 'daylight_plain', 'dim_plain', 'tilt_plain', 'bright_textured'].map(
    (condition, i) =>
      capture({
        condition,
        bundle_source: 'device_pull_20260429',
        normalize_method: i === 2 ? 'hough_relaxed' : 'hough_tight',
        captured_at: `2026-04-29T16:4${i}:50.336`,
      }),
  ),
]
// Un avis déjà posé de chaque sorte, pour voir les trois traitements visuels
// côte à côte (gardée / écartée / à juger).
NOMINAL[2] = {
  ...NOMINAL[2],
  eval_decision: 'keep',
  eval_decision_by: 'po',
  eval_decision_at: '2026-08-25T18:00:00+00:00',
  decisions: [
    {
      id: 1,
      capture_id: NOMINAL[2].capture_id,
      kind: 'eval_decision',
      old_value: null,
      new_value: 'keep',
      reason: null,
      decided_by: 'po',
      decided_at: '2026-08-25T18:00:00+00:00',
    },
  ],
}
NOMINAL[7] = {
  ...NOMINAL[7],
  eval_decision: 'exclude',
  eval_decision_by: 'po',
  eval_decision_at: '2026-08-25T18:01:00+00:00',
  eval_decision_reason: 'cadrage raté, la pièce sort du cadre',
  decisions: [
    {
      id: 2,
      capture_id: NOMINAL[7].capture_id,
      kind: 'eval_decision',
      old_value: null,
      new_value: 'exclude',
      reason: 'cadrage raté, la pièce sort du cadre',
      decided_by: 'po',
      decided_at: '2026-08-25T18:01:00+00:00',
    },
  ],
}
// Vignette cassée : l'URL ne répond pas. C'est un état réel (frame effacée du
// disque) et il doit rester lisible.
NOMINAL[11] = { ...NOMINAL[11], crop_url: 'https://exemple.invalide/cassee.jpg' }

// ── Groupe de dessin : AUCUNE photo n'est celle de la pièce demandée ───────
const GROUPE: ScanCapture[] = ['bright_plain', 'close_plain', 'daylight_plain',
  'dim_plain', 'tilt_plain', 'bright_textured'].map((condition, i) =>
  capture({
    eurio_id: 'fr-2007-2eur-standard-2nd-map',
    is_exact_match: false,
    condition,
    bundle_source: 'device_pull_20260429',
    normalize_method: 'hough_tight',
    captured_at: `2026-04-29T17:0${i}:12.000`,
    decisions: [
      {
        id: 10 + i,
        capture_id: `remap-${i}`,
        kind: 'remap',
        old_value: 'fr-1999-2eur-standard-1st-map (class_level_only=false)',
        new_value: 'fr-2007-2eur-standard-2nd-map (class_level_only=false)',
        reason: 'le dossier dit 2007 ; le catalogue tranche à la maille pièce',
        decided_by: 'po',
        decided_at: '2026-08-25T18:05:00+00:00',
      },
    ],
  }),
)

// ── Le cas belge : juste à la CLASSE, faux à la PIÈCE ──────────────────────
const BELGE: ScanCapture[] = ['bright_plain', 'bright_textured', 'close_plain',
  'daylight_plain', 'dim_plain', 'tilt_plain'].map((condition, i) =>
  capture({
    eurio_id: 'be-2008-2eur-standard-albert-ii-2nd-map-2nd-type-2nd-portrait',
    condition,
    class_level_only: true,
    bundle_source: 'device_pull_20260429',
    normalize_method: 'hough_tight',
    captured_at: `2026-04-29T16:5${i}:00.000`,
  }),
)

export const ETATS: EtatEvalImages[] = [
  {
    id: 'nominal',
    titre: 'Une classe bien fournie',
    enjeu:
      "26 photos d'un seul pool, deux séances mélangées. La provenance se lit sous chaque vignette, elle ne regroupe rien.",
    data: reponse({ captures: NOMINAL }),
    loading: false,
    error: null,
  },
  {
    id: 'groupe',
    titre: 'Groupe de dessin — aucune photo de CETTE pièce',
    enjeu:
      "La maille doit être dite : ces photos jugent le groupe, pas la pièce. Sans le bandeau, l'écran ment sur ce qu'il montre.",
    data: reponse({
      eurio_id: 'fr-1999-2eur-standard-1st-map',
      class_id: 'fr-2euro-standard-t1',
      class_kind: 'design_group_id',
      class_eurio_ids: ['fr-1999-2eur-standard-1st-map', 'fr-2007-2eur-standard-2nd-map'],
      scope: 'design_group',
      scope_note:
        'Ces photos jugent le GROUPE DE DESSIN « fr-2euro-standard-t1 » : certaines montrent une autre pièce du groupe. C\'est la maille de la classe, pas une erreur de label.',
      captures: GROUPE,
    }),
    loading: false,
    error: null,
  },
  {
    id: 'classe-seule',
    titre: 'Juste à la classe, faux à la pièce',
    enjeu:
      'Les 6 captures belges : le référentiel ne possède pas la pièce montrée (datée 2011). Un remap à l\'aveugle les casserait.',
    data: reponse({
      eurio_id: 'be-2008-2eur-standard-albert-ii-2nd-map-2nd-type-2nd-portrait',
      class_id: 'be-2euro-albert-ii-t2',
      class_kind: 'design_group_id',
      class_eurio_ids: ['be-2008-2eur-standard-albert-ii-2nd-map-2nd-type-2nd-portrait'],
      captures: BELGE,
    }),
    loading: false,
    error: null,
  },
  {
    id: 'vide',
    titre: 'Aucune photo d\'évaluation',
    enjeu:
      'Le cas le plus fréquent : 20 classes sur 689 ont des captures. La section doit le dire sans avoir l\'air en panne.',
    data: reponse({ captures: [] }),
    loading: false,
    error: null,
  },
  {
    id: 'chargement',
    titre: 'Chargement',
    enjeu: 'Le premier dixième de seconde — la section ne doit pas sauter.',
    data: null,
    loading: true,
    error: null,
  },
  {
    id: 'erreur',
    titre: 'L\'API ML ne répond pas',
    enjeu:
      ':8042 éteint, ou pièce inconnue du référentiel. Le message doit dire lequel des deux.',
    data: null,
    loading: false,
    error: 'Pièce inconnue du référentiel : fr-2018-2eur-simone-vei',
  },
]
