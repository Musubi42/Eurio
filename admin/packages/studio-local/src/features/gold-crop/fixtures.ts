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
