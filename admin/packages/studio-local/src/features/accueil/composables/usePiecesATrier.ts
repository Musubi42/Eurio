/**
 * La liste de l'accueil — les pièces qu'un ami peut faire avancer aujourd'hui.
 *
 * ⛔ AUCUN FAIT N'EST CALCULÉ ICI. C'est une VUE sur `GET /class-need` : un
 * filtre, un ordre, et le vocabulaire d'un collectionneur posé par-dessus. Tous
 * les nombres viennent du back (`shared.class_need`), et l'ordre est celui de
 * `/besoin` — littéralement la même fonction. Deux écrans qui trient le même
 * fait avec deux règles finissent par se contredire sous les yeux de deux
 * personnes qui travaillent ensemble.
 *
 * LE FILTRE, ET POURQUOI IL EST NON NÉGOCIABLE (`ACCUEIL-AMI.md` §5)
 * ------------------------------------------------------------------
 * Seules les pièces à goulot `review` sont proposées :
 *   - `scrape` → il n'y a rien à trier, le clic mènerait à une file vide ;
 *   - `pleine` → c'est fini, il n'y a plus rien à y gagner.
 * C'est ce filtre qui garantit qu'un clic mène TOUJOURS à du travail. Un écran
 * qui propose une pièce dont la file est vide brûle la confiance d'un ami en un
 * clic, et il n'a aucun moyen de comprendre pourquoi.
 *
 * LES ACQUIS SONT COMPTÉS (§5.3)
 * ------------------------------
 * `acquis = have + accepted_pending`, jamais `have` seul. `have` ne bouge qu'au
 * rebuild de la banque : une ligne bâtie dessus resterait figée toute la semaine
 * au-dessus du travail de quelqu'un qui vient d'en faire. C'est la même somme
 * que le verdict (`bottleneck_for`) — et la même que la barre du but commun.
 *
 * LA CIBLE EST 8 **OU** 5 (§5.1)
 * ------------------------------
 * `target_for_family` rend 5 pour les émissions communes, 8 sinon. La ligne lit
 * le `target` de SA pièce ; écrire « sur 8 » en dur serait faux pour toute une
 * famille.
 */
import { computed, type Ref } from 'vue'

import {
  gestureHref, workOrder,
  type ClassNeedResponse, type ClassNeedRow,
} from '@/features/besoin/composables/useClassNeed'

/** Une ligne, dans le vocabulaire d'un ami — jamais celui du pipeline (§6). */
export interface PieceATrier {
  /** Clé de rendu. C'est un `class_id` ; il n'est JAMAIS affiché (§6). */
  key: string
  /** Ce qu'il lit : « 2 € Autriche 2018 — 100 ans République ». */
  nom: string
  /** Code pays, pour la pastille. `null` quand la pièce n'en a pas. */
  pays: string | null
  /** Images de référence acquises — `have + accepted_pending` (§5.3). */
  acquis: number
  /** Ce qu'il en faut : 8, ou 5 en émission commune (§5.1). */
  cible: number
  /** Où mène « Trier » : la pêche existante, cadrée sur cette pièce. */
  href: string
  /** La vignette canonique. `undefined` = pas encore demandée, `null` = le
   *  référentiel n'en a aucune. Les deux se dessinent pareil (`VignettePiece`),
   *  mais ce ne sont pas le même fait. */
  image?: string | null
}

function toPiece(r: ClassNeedRow, image?: string | null): PieceATrier | null {
  const href = gestureHref(r)
  // `gestureHref` rend `null` sur `scrape` — le filtre ci-dessous l'a déjà
  // écarté, mais un lien mort sur cet écran serait exactement le clic qui
  // trahit. On préfère perdre la ligne que la promesse.
  if (!href) return null
  return {
    key: r.class_id,
    nom: r.label,
    pays: r.country,
    acquis: r.have + r.accepted_pending,
    cible: r.target,
    href,
    image,
  }
}

/**
 * Les pièces à trier, dans l'ordre où le geste débloque le plus.
 *
 * L'ordre est `workOrder(rows, 'couverture')` : une pièce sans aucune image de
 * référence passe devant tout le reste. Ce n'est pas un tri de colonne mais
 * « ce que l'action débloque » — le premier exemplaire vaut ~9× les neuf
 * suivants. Un ami n'a pas à choisir où travailler : la liste le fait pour lui
 * (§2).
 */
export function usePiecesATrier(
  data: Ref<ClassNeedResponse | null>,
  /** Les vignettes, chargées à part (`useCanonicalThumbs`). Optionnelles : la
   *  liste doit s'afficher et se cliquer avant elles, et sans elles. Une image
   *  d'illustration ne bloque jamais un travail. */
  vignettes?: Ref<Record<string, string | null>>,
) {
  const pieces = computed<PieceATrier[]>(() => {
    const rows = data.value?.classes ?? []
    const v = vignettes?.value ?? {}
    return workOrder(rows.filter((r) => r.bottleneck === 'review'), 'couverture')
      .map((r) => toPiece(r, r.class_id in v ? v[r.class_id] : undefined))
      .filter((p): p is PieceATrier => p !== null)
  })

  /** Le but commun : « 412 des 671 pièces ont assez d'images ».
   *
   *  `coverage_acquired`, jamais `coverage` : le second compte `have >= 1` et
   *  reste donc figé entre deux rebuilds. Servi par le back — on ne réagrège
   *  rien ici, c'est le même nombre que celui de `/besoin`. */
  const butCommun = computed(() => {
    const t = data.value?.totals
    if (!t) return null
    return { atteint: t.coverage_acquired, total: t.n_classes }
  })

  return { pieces, butCommun }
}
