// Fixtures du jeu d'or — de quoi monter la séance sans canonique.
//
// Elles servent deux fois : aux tests, et à l'œil. `/gold-crop/annoter?demo=1`
// ouvre la page sur ces trois images sans toucher au réseau ni écrire quoi que
// ce soit — c'est la maquette-dans-le-front que R1 demande pour un écran
// d'admin (états vides, états d'erreur, validés à l'œil avant d'être branchés).
//
// Trois images, deux annotations, et le cas qui compte : `a2` porte une strate
// confirmée SANS ellipse. C'est exactement l'image que la reprise doit rouvrir,
// et le bug du 2026-08-28 la sautait.

import type { AnnotationOr, ImageTirage, JeuDOr, TirageOr } from './composables/useGoldCropApi'

function image(over: Partial<ImageTirage> & { asset_id: string }): ImageTirage {
  return {
    role: 'tirage',
    rn: 1,
    strate_tiree: 'S1_facile',
    width: 900,
    height: 900,
    hint: { cx: 450, cy: 450, r: 380 },
    prefill: null,
    prefill_reason: null,
    source: 'ebay',
    source_image_id: 'si-1',
    raw_url: 'https://eurio-s3.musubi.dev/raw/exemple.jpg',
    ...over,
  }
}

export const TIRAGE_DEMO: TirageOr = {
  gold_version: 'v1',
  n: 3,
  images: [
    image({
      asset_id: 'a1',
      rn: 1,
      prefill: { cx: 452, cy: 448, a: 372, b: 361, theta_deg: 12 },
      prefill_reason: 'fiable',
    }),
    image({ asset_id: 'a2', rn: 2, strate_tiree: 'S2_capsule', prefill_reason: 'measure_tilt a échoué' }),
    image({
      asset_id: 'a3',
      rn: 3,
      strate_tiree: 'S4_oblique',
      prefill: { cx: 430, cy: 470, a: 400, b: 300, theta_deg: 33 },
    }),
  ],
}

function annotation(over: Partial<AnnotationOr> & { asset_id: string }): AnnotationOr {
  return {
    gold_version: 'v1',
    passe: 1,
    actor: 'po',
    indecidable: 0,
    strate_tiree: 'S1_facile',
    strate_confirmee: null,
    secondes: 24,
    prefill_modifie: 1,
    editor_version: 'gold_web_v1',
    created_at: '2026-09-08T10:00:00Z',
    updated_at: '2026-09-08T10:00:00Z',
    resolution_status: 'manual',
    quality_reason: null,
    bbox_json: null,
    detection_method: 'yolo',
    source: 'ebay',
    source_image_id: 'si-1',
    raw_path: 'ebay/exemple.jpg',
    raw_url: 'https://eurio-s3.musubi.dev/raw/exemple.jpg',
    width: 900,
    height: 900,
    ...over,
  } as AnnotationOr
}

export const JEU_DEMO: JeuDOr = {
  gold_version: 'v1',
  version: null,
  n: 2,
  annotations: [
    annotation({ asset_id: 'a1', cx: 450, cy: 450, a: 370, b: 360, theta_deg: 12 }),
    // touchée mais PAS faite : une strate confirmée ne vaut pas une annotation
    annotation({ asset_id: 'a2', strate_confirmee: 'S2_capsule', secondes: 0, prefill_modifie: 0 }),
  ],
}

/* ══ La planche comparative — 2 bras × 3 cas ═════════════════════════════════
 *
 * Elle ouvre `/gold-crop/planche?demo=1` sans API ML et sans banc exécuté :
 * c'est la maquette-dans-le-front que R1 demande pour un écran d'admin. Les
 * chiffres sont choisis pour montrer ce que la planche doit rendre lisible —
 * une borne qui ne se classe pas, et deux bras que RE-7 refuse de départager
 * (33,3 % contre 33,3 %, soit 0 point d'écart).
 */

import type { CasRun, RunBras, RunsBanc } from './composables/useGoldCropApi'

function cas(over: Partial<CasRun> & { asset_id: string }): CasRun {
  return {
    strate: 'S1_facile',
    strate_confirmee: null,
    strate_retenue: 'S1_facile',
    verdict_humain: 'accept',
    gold: { cx: 450, cy: 450, a: 400, b: 392, theta: 0.36 },
    pred: { cx: 450, cy: 450, r: 396 },
    ampute: false,
    C1_ok: true,
    C2_ok: true,
    C1_marge_min_frac: 0.01,
    marge_promise_ok: true,
    arc_coverage: 1,
    boundary_iou: 0.91,
    mask_iou: 0.99,
    hausdorff_frac: 0.004,
    largeur: 900,
    hauteur: 900,
    raw_url: 'https://eurio-s3.musubi.dev/raw/exemple.jpg',
    ...over,
  }
}

function bras(over: Partial<RunBras> & { bras: string }): RunBras {
  return {
    borne: false,
    juge_version: 1,
    execute_le: '2026-09-08T08:30:24+00:00',
    params: { m: 0, d_frac: 0.08, arc_min: 11 / 12, region: 'retenu', c2_compte: false },
    resume: { n: 3 },
    re4: { verdict: 'impossible', raison: 'un des deux groupes est vide' },
    cas: [],
    ...over,
  }
}

const CAS_DEMO: CasRun[] = [
  cas({ asset_id: 'a1' }),
  cas({
    // Tirée S1 par le texte de l'annonce, CONFIRMÉE S2 par l'œil : c'est le
    // cas qui rend la stratification honnête, et celui sur lequel un filtre
    // branché sur la strate du tirage se trahit.
    asset_id: 'a2', strate: 'S1_facile', strate_confirmee: 'S2_capsule',
    strate_retenue: 'S2_capsule',
    verdict_humain: 'reject', ampute: true, C1_ok: false, marge_promise_ok: false,
    C1_marge_min_frac: -0.023, boundary_iou: 0.68, mask_iou: 0.97,
    pred: { cx: 448, cy: 452, r: 372 },
  }),
  cas({
    asset_id: 'a3', strate: 'S4_oblique', strate_retenue: 'S4_oblique',
    gold: { cx: 430, cy: 470, a: 400, b: 300, theta: 0.58 },
    pred: { cx: 430, cy: 470, r: 305 }, boundary_iou: 0.26,
  }),
]

export const RUNS_DEMO: RunsBanc = {
  gold_version: 'v1',
  n: 3,
  runs: [
    bras({
      bras: 'gold_replay', borne: true, re4: null,
      resume: { n: 3, amputation_pct: 0, amp_C1_pct: 0, amp_C2_pct: 0,
                marge_promise_ko_pct: 0, biou_med: 1, biou_p10: 1,
                iou_masque_med: 1, hausdorff_p90: 0 },
      cas: CAS_DEMO.map((c) => ({ ...c, ampute: false, C1_ok: true, boundary_iou: 1 })),
    }),
    bras({
      bras: 'baseline_prod',
      resume: { n: 3, amputation_pct: 33.3, amp_C1_pct: 33.3, amp_C2_pct: 0,
                marge_promise_ko_pct: 33.3, biou_med: 0.68, biou_p10: 0.34,
                iou_masque_med: 0.99, hausdorff_p90: 0.021 },
      cas: CAS_DEMO,
    }),
    bras({
      bras: 'measure_tilt_ellipse',
      resume: { n: 3, amputation_pct: 33.3, amp_C1_pct: 33.3, amp_C2_pct: 0,
                marge_promise_ko_pct: 66.6, biou_med: 0.4, biou_p10: 0.08,
                iou_masque_med: 0.89, hausdorff_p90: 0.104 },
      cas: CAS_DEMO.map((c) => ({ ...c, pred: { ...c.pred!, r: c.pred!.r - 12 } })),
    }),
  ],
}
