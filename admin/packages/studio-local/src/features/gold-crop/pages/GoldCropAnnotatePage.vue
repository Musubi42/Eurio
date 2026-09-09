<script setup lang="ts">
// La séance d'annotation du jeu d'or, dans le front (D12).
//
// Portage de l'outil local jetable `ml/bench/gold_crop/annotate/` : même geste,
// mêmes touches, mêmes garde-fous — mais joignable depuis n'importe quel
// navigateur, sans devShell, sans serveur, sans port. La séance était à l'arrêt
// à 2 images sur 60 ; ce qui bloquait n'était pas le tracé mais tout ce qu'il
// fallait avant de pouvoir tracer.
//
// PAS `heavy` : elle lit le canonique et des URLs MinIO présignées, comme la
// planche. Le ML local n'entre nulle part.
//
// Ce qui écrit, écrit AU CANONIQUE et à chaque validation. Il n'y a plus de
// filet fichier ici — donc la ligne « écrit » du panneau est le seul témoin, et
// elle doit dire ce qui a échoué, jamais un code nu.
//
// ⚠️ Le geste a changé le 2026-09-09. Trois poignées (centre, grand axe, petit
// axe) demandaient de penser en demi-axes : pour corriger UN bord, il fallait
// bouger le centre PUIS l'axe, et les deux se battaient. Ce qu'on veut dire est
// « ce bord-là est à côté » — donc quatre poignées de BORD, chacune tire son
// bord pendant que l'opposé ne bouge pas. Et les loupes, qui masquaient la
// pièce, sont sorties de la scène et se tirent elles aussi (4× plus fin).
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import {
  type AnnotationEnvoi,
  type AnnotationOr,
  type EllipseEdition,
  type EtatAnnotation,
  type ImageTirage,
  EDITEUR_WEB,
  STRATES,
  TAILLE_TIRAGE,
  ellipseDepuisPrefill,
  etatDepuisAnnotation,
  expliquerEchec,
  memeEllipse,
  normaliserEllipse,
  premiereAFaire,
  useGoldCropSeance,
} from '../composables/useGoldCropApi'
import { N_DOUBLE, sousEnsemblePasse2 } from '../composables/sha256'
import { TIRAGE_DEMO, JEU_DEMO } from '../fixtures'

const route = useRoute()
const version = String(route.query.version || 'v1')
const passe = Number(route.query.passe || 1)
const demo = route.query.demo === '1'

const { chargerTirage, chargerJeu, envoyerAnnotation } = useGoldCropSeance(version)

const images = ref<ImageTirage[]>([])
const etats = ref<Record<string, EtatAnnotation>>({})
const idx = ref(0)
const chargement = ref(true)
const erreur = ref<string | null>(null)
const gele = ref<string | null>(null)

/** L'ellipse en cours, et celle proposée au départ (pour `prefill_modifie`). */
const ell = ref<EllipseEdition>({ cx: 0, cy: 0, a: 1, b: 1, theta: 0 })
const prefill = ref<EllipseEdition>({ cx: 0, cy: 0, a: 1, b: 1, theta: 0 })

const vue = ref({ k: 1, tx: 0, ty: 0 })
const taille = ref({ w: 900, h: 700 })
const scene = ref<HTMLElement | null>(null)

let debut = performance.now()
const tic = ref(0) // fait battre le compteur de secondes, une fois par seconde
let horloge: ReturnType<typeof setInterval> | null = null

const flash = ref('')
let minuteurFlash: ReturnType<typeof setTimeout> | null = null
const ecrit = ref<{ ton: 'vert' | 'rouge'; texte: string } | null>(null)

const courante = computed<ImageTirage | null>(() => images.value[idx.value] ?? null)
const etatCourant = computed<EtatAnnotation | null>(
  () => (courante.value && etats.value[courante.value.asset_id]) || null,
)

/* ─── chargement ─────────────────────────────────────────────────────────── */

async function demarrer() {
  chargement.value = true
  erreur.value = null
  try {
    if (demo) {
      images.value = TIRAGE_DEMO.images
      appliquerJeu(JEU_DEMO.annotations)
    } else {
      const [tirage, jeu] = await Promise.all([chargerTirage('tirage'), chargerJeu(passe)])
      let liste = tirage.images.filter((i) => i.role === 'tirage')
      if (passe > 1) {
        // Le sous-ensemble de la 2ᵉ passe se tire du même hachage que
        // `serve.py`, sinon les deux instruments ne mesurent pas la même chose.
        const p1 = await chargerJeu(1)
        const garde = new Set(
          sousEnsemblePasse2(p1.annotations.map((a) => a.asset_id), N_DOUBLE),
        )
        liste = liste.filter((i) => garde.has(i.asset_id))
      }
      images.value = liste
      gele.value = jeu.version?.frozen_at ?? null
      appliquerJeu(jeu.annotations.filter((a) => a.passe === passe))
    }
    idx.value = premiereAFaire(images.value, etats.value)
    charger()
  } catch (e) {
    erreur.value = expliquerEchec(e)
  } finally {
    chargement.value = false
  }
}

function appliquerJeu(annotations: AnnotationOr[]) {
  const m: Record<string, EtatAnnotation> = {}
  for (const a of annotations) m[a.asset_id] = etatDepuisAnnotation(a)
  etats.value = m
}

function charger() {
  const r = courante.value
  if (!r) return
  // ⚠️ En 2ᵉ passe, le départ reste le PRÉ-REMPLISSAGE, jamais le tracé de la
  // passe 1 : on mesure la reproductibilité de la main, et montrer son tracé
  // précédent la mesurerait à zéro.
  prefill.value = ellipseDepuisPrefill(r)
  const e = etats.value[r.asset_id]
  ell.value = e?.ellipse ? { ...e.ellipse } : { ...prefill.value }
  loupeActive.value = null
  debut = performance.now()
  mesurer()
  recadrer()
}

/* ─── vue ────────────────────────────────────────────────────────────────── */

function mesurer() {
  const el = scene.value
  if (!el || el.clientWidth <= 0) return
  const avant = taille.value
  const apres = { w: el.clientWidth, h: el.clientHeight }
  if (avant.w === apres.w && avant.h === apres.h) return
  taille.value = apres
  // La scène vient de changer de taille SANS que la fenêtre bouge — menu
  // replié, panneau qui s'ouvre. Le viewBox suit, sinon le SVG est remis à
  // l'échelle par `preserveAspectRatio` (bandes en haut et en bas) et 1 px du
  // pointeur ne vaut plus 1 unité. Le contenu reste centré plutôt que collé en
  // haut à gauche : on n'a pas à re-cadrer, donc on ne perd ni zoom ni pan.
  vue.value = {
    ...vue.value,
    tx: vue.value.tx + (apres.w - avant.w) / 2,
    ty: vue.value.ty + (apres.h - avant.h) / 2,
  }
}

/**
 * Point client → unités du viewBox, par la matrice RÉELLE du SVG.
 *
 * Le viewBox est censé valoir la taille de la scène, mais entre un changement
 * de mise en page et l'observateur qui le rattrape il y a une frame — et sur
 * cette frame le SVG est mis à l'échelle. Un glisser qui supposerait
 * « 1 px = 1 unité » y ferait sauter la poignée loin du pointeur (mesuré le
 * 2026-09-09 : 3 px de souris → 63 px de demi-axe). La matrice ne se trompe pas.
 */
function versToile(el: SVGSVGElement, X: number, Y: number): [number, number] {
  const m = typeof el.getScreenCTM === 'function' ? el.getScreenCTM() : null
  if (m && m.a && m.d) return [(X - m.e) / m.a, (Y - m.f) / m.d]
  const r = el.getBoundingClientRect ? el.getBoundingClientRect() : { left: 0, top: 0 }
  return [X - r.left, Y - r.top]
}

function recadrer() {
  const r = courante.value
  if (!r) return
  mesurer()
  const { w: W, h: H } = taille.value
  // on cadre sur l'ellipse, pas sur le raw : c'est le listel qu'on vient juger.
  // 1,12 et pas 1,35 : les loupes ne sont plus dans la scène, la pièce peut
  // enfin la remplir — le reste n'était que des bandes noires.
  // × 1,22 : assez serré pour que la pièce remplisse la scène, assez large pour
  // que les poignées de bord (rayon de prise 14 px) ne soient pas coupées par
  // le cadre — à × 1,12 le haut et le bas tombaient pile sur le bord (vu le 09/09)
  const rayon = Math.max(ell.value.a, ell.value.b, r.hint.r) * 1.22
  const k = Math.min(W, H) / (2 * rayon)
  vue.value = { k, tx: W / 2 - ell.value.cx * k, ty: H / 2 - ell.value.cy * k }
}

const versEcran = (x: number, y: number): [number, number] => [
  x * vue.value.k + vue.value.tx,
  y * vue.value.k + vue.value.ty,
]
const versImage = (X: number, Y: number): [number, number] => [
  (X - vue.value.tx) / vue.value.k,
  (Y - vue.value.ty) / vue.value.k,
]

/* ─── géométrie de l'ellipse ─────────────────────────────────────────────── */

/** Le repère propre de l'ellipse : `u` le long du grand axe, `v` la normale. */
function axes(e: EllipseEdition): { u: [number, number]; v: [number, number] } {
  const t = (e.theta * Math.PI) / 180
  return { u: [Math.cos(t), Math.sin(t)], v: [-Math.sin(t), Math.cos(t)] }
}

/** L'anneau de rotation se pose au-delà du bord E, hors du tracé. */
const RAYON_ANNEAU = 1.18

/** Le bord d'en face — celui qui NE BOUGE PAS quand on tire. */
const OPPOSE: Record<string, string> = { E: 'W', W: 'E', N: 'S', S: 'N' }

/** Où est une poignée, en coordonnées IMAGE. */
function pointPoignee(e: EllipseEdition, id: string): [number, number] {
  const { u, v } = axes(e)
  if (id === 'E') return [e.cx + e.a * u[0], e.cy + e.a * u[1]]
  if (id === 'W') return [e.cx - e.a * u[0], e.cy - e.a * u[1]]
  if (id === 'S') return [e.cx + e.b * v[0], e.cy + e.b * v[1]]
  if (id === 'N') return [e.cx - e.b * v[0], e.cy - e.b * v[1]]
  if (id === 'R') {
    return [e.cx + RAYON_ANNEAU * e.a * u[0], e.cy + RAYON_ANNEAU * e.a * u[1]]
  }
  return [e.cx, e.cy]
}

/** La direction qui SORT de l'ellipse au droit d'un bord. */
function sortante(e: EllipseEdition, id: string): [number, number] {
  const { u, v } = axes(e)
  if (id === 'E') return [u[0], u[1]]
  if (id === 'W') return [-u[0], -u[1]]
  if (id === 'S') return [v[0], v[1]]
  return [-v[0], -v[1]]
}

/**
 * Tirer UN bord vers un point, l'opposé restant cloué.
 *
 * Le pointeur est projeté sur la droite de l'axe passant par le bord fixe : on
 * ne demande à personne de viser une droite au pixel près. Le demi-axe devient
 * la moitié de la distance au bord fixe, et le centre se place au milieu — donc
 * tirer N vers le haut grandit `b` ET remonte le centre de la moitié.
 *
 * ⚠️ Aucune borne `b ≤ a` ici : pendant le glisser, un petit axe qui dépasse le
 * grand est une ellipse parfaitement légitime, seulement tournée d'un quart de
 * tour. La ramener de force ferait coller le bord au pointeur puis décrocher.
 * `normaliserEllipse` échange les axes À LA VALIDATION, là où le nombre part.
 */
function tirerBord(e: EllipseEdition, id: string, ix: number, iy: number): EllipseEdition {
  const { u, v } = axes(e)
  const d = id === 'E' || id === 'W' ? u : v
  const [fx, fy] = pointPoignee(e, OPPOSE[id])
  const s = (ix - fx) * d[0] + (iy - fy) * d[1]
  const signe = s < 0 ? -1 : 1
  const long = Math.max(8, Math.abs(s)) // demi-axe minimal : 4 px image
  const px = fx + signe * long * d[0]
  const py = fy + signe * long * d[1]
  const n: EllipseEdition = { ...e, cx: (fx + px) / 2, cy: (fy + py) / 2 }
  if (id === 'E' || id === 'W') n.a = long / 2
  else n.b = long / 2
  return n
}

/** Pousser un bord de `delta` pixels image vers l'extérieur (négatif = dedans). */
function deplacerBord(e: EllipseEdition, id: string, delta: number): EllipseEdition {
  const [px, py] = pointPoignee(e, id)
  const [ox, oy] = sortante(e, id)
  return tirerBord(e, id, px + delta * ox, py + delta * oy)
}

/* ─── rendu ──────────────────────────────────────────────────────────────── */

const boite = computed(() => `0 0 ${taille.value.w} ${taille.value.h}`)

const cadre = computed(() => {
  const r = courante.value
  return {
    x: vue.value.tx,
    y: vue.value.ty,
    w: (r?.width ?? 900) * vue.value.k,
    h: (r?.height ?? 900) * vue.value.k,
  }
})

const trace = computed(() => {
  const [cx, cy] = versEcran(ell.value.cx, ell.value.cy)
  return {
    cx,
    cy,
    rx: ell.value.a * vue.value.k,
    ry: ell.value.b * vue.value.k,
    rot: `rotate(${ell.value.theta} ${cx} ${cy})`,
  }
})

/** Les six poignées, à l'écran. Quatre bords, un centre, un anneau. */
const poignees = computed(() => {
  const e = ell.value
  const p = (id: string) => versEcran(...pointPoignee(e, id))
  return [
    { id: 'C', couleur: '#60a5fa', creuse: false, titre: 'centre — déplacer tout', p: p('C') },
    { id: 'E', couleur: '#4ade80', creuse: false, titre: 'bord droit — l’opposé ne bouge pas', p: p('E') },
    { id: 'W', couleur: '#4ade80', creuse: false, titre: 'bord gauche — l’opposé ne bouge pas', p: p('W') },
    { id: 'N', couleur: '#4ade80', creuse: false, titre: 'bord haut — l’opposé ne bouge pas', p: p('N') },
    { id: 'S', couleur: '#4ade80', creuse: false, titre: 'bord bas — l’opposé ne bouge pas', p: p('S') },
    { id: 'R', couleur: '#f0abfc', creuse: true, titre: 'anneau — tourner seulement', p: p('R') },
  ]
})

// Les quatre loupes du bord. « Mon ellipse est-elle SUR le bord ? » ne se répond
// pas à la vue d'ensemble : à l'échelle où la pièce tient à l'écran, 2 % du
// rayon font 4 pixels. On montre donc le contour de près, aux 4 bords, avec le
// trait dessus — et SOUS la scène, plus par-dessus la pièce.
const LOUPE = 128
const ZOOM = 4

/** Chaque loupe regarde un bord : c'est aussi par elle qu'on le tire. */
const VUES: { nom: string; id: string }[] = [
  { nom: 'haut', id: 'N' },
  { nom: 'droite', id: 'E' },
  { nom: 'bas', id: 'S' },
  { nom: 'gauche', id: 'W' },
]

const loupeActive = ref<string | null>(null)

const loupes = computed(() => {
  const r = courante.value
  if (!r) return []
  const e = ell.value
  return VUES.map(({ nom, id }) => {
    const [px, py] = pointPoignee(e, id)
    const tx = LOUPE / 2 - px * ZOOM
    const ty = LOUPE / 2 - py * ZOOM
    const cx = e.cx * ZOOM + tx
    const cy = e.cy * ZOOM + ty
    return {
      nom,
      id,
      url: r.raw_url,
      tx,
      ty,
      w: r.width * ZOOM,
      h: r.height * ZOOM,
      cx,
      cy,
      rx: e.a * ZOOM,
      ry: e.b * ZOOM,
      rot: `rotate(${e.theta} ${cx} ${cy})`,
    }
  })
})

/** La tige qui relie le bord E à l'anneau — sinon l'anneau flotte sans lien. */
const tige = computed(() => {
  const [x1, y1] = versEcran(...pointPoignee(ell.value, 'E'))
  const [x2, y2] = versEcran(...pointPoignee(ell.value, 'R'))
  return { x1, y1, x2, y2 }
})

const secondesEcoulees = computed(() => {
  void tic.value
  return (performance.now() - debut) / 1000
})

/* ─── interaction : la scène ─────────────────────────────────────────────── */

// `x, y` : le pointeur en unités du viewBox (pour le pan). `dx, dy` : l'écart
// entre la poignée et l'endroit où on l'a saisie, en pixels image — on tient
// une poignée par son bord aussi bien que par son centre, et l'ellipse ne
// doit pas sauter de cet écart au premier mouvement.
let saisie: { type: string; x: number; y: number; dx: number; dy: number } | null = null

function surPointerDown(ev: PointerEvent) {
  const cible = (ev.target as HTMLElement | null)?.dataset?.poignee
  const el = ev.currentTarget as SVGSVGElement
  const [X, Y] = versToile(el, ev.clientX, ev.clientY)
  let dx = 0
  let dy = 0
  if (cible) {
    const [ix, iy] = versImage(X, Y)
    const [px, py] = pointPoignee(ell.value, cible)
    dx = px - ix
    dy = py - iy
  }
  saisie = { type: cible || 'pan', x: X, y: Y, dx, dy }
  try {
    el.setPointerCapture(ev.pointerId)
  } catch {
    /* jsdom n'a pas la capture de pointeur — le glisser marche quand même */
  }
}

function surPointerUp(ev: PointerEvent) {
  saisie = null
  try {
    ;(ev.currentTarget as SVGSVGElement).releasePointerCapture(ev.pointerId)
  } catch {
    /* idem */
  }
}

function surPointerMove(ev: PointerEvent) {
  if (!saisie) return
  const el = ev.currentTarget as SVGSVGElement
  const [X, Y] = versToile(el, ev.clientX, ev.clientY)
  const [ix0, iy0] = versImage(X, Y)
  const ix = ix0 + saisie.dx
  const iy = iy0 + saisie.dy
  const e = { ...ell.value }
  if (saisie.type === 'pan') {
    vue.value = {
      ...vue.value,
      tx: vue.value.tx + (X - saisie.x),
      ty: vue.value.ty + (Y - saisie.y),
    }
    saisie.x = X
    saisie.y = Y
    return
  }
  if (saisie.type === 'C') {
    e.cx = ix
    e.cy = iy
    ell.value = e
  } else if (saisie.type === 'R') {
    // l'anneau ne fait QUE tourner : ni taille ni centre
    e.theta = (Math.atan2(iy - e.cy, ix - e.cx) * 180) / Math.PI
    ell.value = e
  } else if (OPPOSE[saisie.type]) {
    ell.value = tirerBord(e, saisie.type, ix, iy)
  }
  // Pas de normalisation ICI : ramener θ dans [0, 180) en plein glisser ferait
  // sauter l'anneau à l'opposé dès qu'on passe à gauche du centre. On normalise
  // à la validation, là où le nombre part au canonique.
}

function surMolette(ev: WheelEvent) {
  ev.preventDefault()
  const el = ev.currentTarget as SVGSVGElement
  const [X, Y] = versToile(el, ev.clientX, ev.clientY)
  const [ix, iy] = versImage(X, Y)
  const k = vue.value.k * Math.exp(-ev.deltaY * 0.0015)
  vue.value = { k, tx: X - ix * k, ty: Y - iy * k }
}

/* ─── interaction : les loupes ───────────────────────────────────────────── */

// Une loupe n'est pas qu'un témoin : c'est la surface d'édition FINE. Elle
// montre le bord à ×4, donc un pixel de souris y vaut un quart de pixel image —
// c'est là qu'on gagne les deux derniers pixels de listel.
let saisieLoupe: { nom: string; id: string; x: number; y: number } | null = null

function surLoupeDown(ev: PointerEvent, l: { nom: string; id: string }) {
  loupeActive.value = l.nom
  saisieLoupe = { nom: l.nom, id: l.id, x: ev.clientX, y: ev.clientY }
  try {
    ;(ev.currentTarget as SVGSVGElement).setPointerCapture(ev.pointerId)
  } catch {
    /* idem : jsdom */
  }
}

function surLoupeUp(ev: PointerEvent) {
  saisieLoupe = null
  try {
    ;(ev.currentTarget as SVGSVGElement).releasePointerCapture(ev.pointerId)
  } catch {
    /* idem */
  }
}

function surLoupeMove(ev: PointerEvent) {
  const s = saisieLoupe
  if (!s) return
  const [ox, oy] = sortante(ell.value, s.id)
  // le déplacement du pointeur, projeté sur la sortante, ramené en pixels image
  const delta = ((ev.clientX - s.x) * ox + (ev.clientY - s.y) * oy) / ZOOM
  s.x = ev.clientX
  s.y = ev.clientY
  if (delta) ell.value = deplacerBord(ell.value, s.id, delta)
}

function surLoupeMolette(ev: WheelEvent, l: { nom: string; id: string }) {
  ev.preventDefault()
  loupeActive.value = l.nom
  ell.value = deplacerBord(ell.value, l.id, ev.deltaY < 0 ? 0.25 : -0.25)
}

/** Les flèches, en direction d'écran. */
const FLECHES: Record<string, [number, number]> = {
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
}

function pousserBord(nom: string, fleche: [number, number], pas: number) {
  const l = VUES.find((v) => v.nom === nom)
  if (!l) return
  const [ox, oy] = sortante(ell.value, l.id)
  const signe = Math.sign(fleche[0] * ox + fleche[1] * oy)
  if (!signe) return
  ell.value = deplacerBord(ell.value, l.id, signe * pas)
}

function surClavier(ev: KeyboardEvent) {
  const fleche = FLECHES[ev.key]
  if (ev.key === 'Escape') {
    loupeActive.value = null
  } else if (fleche && loupeActive.value) {
    // Une loupe choisie confisque les flèches : elles poussent son bord au lieu
    // de changer d'image. Échap rend la navigation.
    pousserBord(loupeActive.value, fleche, ev.shiftKey ? 2 : 0.5)
  } else if (ev.key === 'Enter' || ev.key === 'ArrowRight') {
    valider()
    aller(+1)
  } else if (ev.key === 'ArrowLeft') {
    valider()
    aller(-1)
  } else if (ev.key === 'r') {
    ell.value = { ...prefill.value }
  } else if (ev.key === 'f') {
    recadrer()
  } else if (ev.key === 'i') {
    basculerIndecidable()
  } else if (['1', '2', '3', '4'].includes(ev.key)) {
    poserStrate(STRATES[Number(ev.key) - 1])
  } else return
  ev.preventDefault()
}

/* ─── annotation ─────────────────────────────────────────────────────────── */

function entree(): EtatAnnotation {
  const r = courante.value!
  const existant = etats.value[r.asset_id]
  if (existant) return existant
  const neuf: EtatAnnotation = {
    asset_id: r.asset_id,
    strate_tiree: r.strate_tiree,
    strate_confirmee: null,
    indecidable: false,
    secondes: 0,
    ellipse: null,
    prefill_modifie: false,
  }
  etats.value = { ...etats.value, [r.asset_id]: neuf }
  return neuf
}

function poserStrate(s: string) {
  if (!courante.value) return
  const a = entree()
  a.strate_confirmee = a.strate_confirmee === s ? null : s
  etats.value = { ...etats.value }
  // Une strate seule ne s'écrit pas : le canonique ne retient que les
  // annotations tracées ou déclarées indécidables (même filtre que `serve.py`).
  if (a.ellipse || a.indecidable) enregistrer(a)
}

function basculerIndecidable() {
  if (!courante.value) return
  const a = entree()
  a.indecidable = !a.indecidable
  etats.value = { ...etats.value }
  enregistrer(a)
}

function valider() {
  if (!courante.value) return
  if (gele.value) {
    montrerFlash('version gelée — rien ne s’écrit')
    return
  }
  const a = entree()
  a.ellipse = normaliserEllipse({ ...ell.value })
  a.prefill_modifie = !memeEllipse(a.ellipse, prefill.value)
  a.secondes = Number((a.secondes + (performance.now() - debut) / 1000).toFixed(1))
  etats.value = { ...etats.value }
  enregistrer(a)
}

function aller(d: number) {
  const n = idx.value + d
  if (n < 0 || n >= images.value.length) {
    montrerFlash('fin du tirage')
    return
  }
  idx.value = n
  charger()
}

function corpsEnvoi(a: EtatAnnotation): AnnotationEnvoi {
  return {
    asset_id: a.asset_id,
    ellipse: a.ellipse,
    indecidable: a.indecidable,
    passe,
    strate_tiree: a.strate_tiree,
    strate_confirmee: a.strate_confirmee,
    secondes: a.secondes || null,
    prefill_modifie: a.prefill_modifie,
    editor_version: EDITEUR_WEB,
  }
}

let enAttente: ReturnType<typeof setTimeout> | null = null

function enregistrer(a: EtatAnnotation) {
  if (demo) return
  if (enAttente) clearTimeout(enAttente)
  enAttente = setTimeout(() => {
    void envoyer(a)
  }, 120)
}

async function envoyer(a: EtatAnnotation) {
  try {
    const rep = await envoyerAnnotation(corpsEnvoi(a))
    ecrit.value = { ton: 'vert', texte: `canonique · ${rep?.n ?? faites.value.length}` }
  } catch (e) {
    // Un échec d'écriture est la seule panne qui coûte la séance : elle se dit
    // en toutes lettres, et elle reste à l'écran.
    ecrit.value = { ton: 'rouge', texte: expliquerEchec(e) }
    montrerFlash('🔴 non sauvegardé au canonique')
  }
}

function montrerFlash(txt: string) {
  flash.value = txt
  if (minuteurFlash) clearTimeout(minuteurFlash)
  minuteurFlash = setTimeout(() => (flash.value = ''), 1400)
}

/* ─── panneau ────────────────────────────────────────────────────────────── */

const faites = computed(() =>
  Object.values(etats.value).filter((e) => e.ellipse || e.indecidable),
)
const nIndecidables = computed(
  () => Object.values(etats.value).filter((e) => e.indecidable).length,
)
const mediane = computed(() => {
  const s = faites.value
    .map((e) => e.secondes)
    .filter((x) => x > 0)
    .sort((p, q) => p - q)
  return s.length ? `${s[s.length >> 1].toFixed(0)} s` : '—'
})
const progres = computed(() =>
  images.value.length ? (100 * faites.value.length) / images.value.length : 0,
)

const etatImage = computed(() => {
  const e = etatCourant.value
  if (e?.indecidable) return { classe: 'rej', texte: 'indécidable' }
  if (e?.ellipse)
    return {
      classe: 'acc',
      texte: e.strate_confirmee ? 'validée' : 'validée · strate non confirmée',
    }
  return { classe: 'todo', texte: 'à faire — Entrée pour valider' }
})

const prefillTexte = computed(() => {
  const r = courante.value
  if (!r) return '—'
  if (r.prefill) return `measure_tilt${r.prefill_reason ? ` · ${r.prefill_reason}` : ''}`
  return `cercle du crop${r.prefill_reason ? ` · ${r.prefill_reason}` : ''}`
})

let observateur: ResizeObserver | null = null

onMounted(() => {
  window.addEventListener('keydown', surClavier)
  window.addEventListener('resize', recadrer)
  // Un `resize` de fenêtre ne dit rien d'un menu replié ni d'un panneau qui
  // s'ouvre : c'est la scène qu'il faut observer, pas la fenêtre.
  if (typeof ResizeObserver !== 'undefined' && scene.value) {
    observateur = new ResizeObserver(() => mesurer())
    observateur.observe(scene.value)
  }
  horloge = setInterval(() => (tic.value += 1), 1000)
  void demarrer()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', surClavier)
  window.removeEventListener('resize', recadrer)
  observateur?.disconnect()
  if (horloge) clearInterval(horloge)
  if (enAttente) clearTimeout(enAttente)
  if (minuteurFlash) clearTimeout(minuteurFlash)
})
</script>

<template>
  <div class="annoter">
    <div class="colonne">
      <div ref="scene" class="scene">
        <svg
          v-if="courante"
          class="toile"
          :viewBox="boite"
          @pointerdown="surPointerDown"
          @pointerup="surPointerUp"
          @pointercancel="surPointerUp"
          @pointermove="surPointerMove"
          @wheel="surMolette"
        >
          <image
            :href="courante.raw_url" :x="cadre.x" :y="cadre.y"
            :width="cadre.w" :height="cadre.h"
          />
          <ellipse
            :cx="trace.cx" :cy="trace.cy" :rx="trace.rx" :ry="trace.ry"
            :transform="trace.rot" fill="none" stroke="#ffd166" stroke-width="1.6"
          />
          <!-- la bande du Boundary IoU, d = 0,08·a : ce que le juge regardera -->
          <ellipse
            :cx="trace.cx" :cy="trace.cy" :rx="trace.rx * 0.92" :ry="trace.ry * 0.92"
            :transform="trace.rot" fill="none" stroke="#ffd166" stroke-width="0.8"
            stroke-dasharray="4 4" opacity="0.55"
          />
          <!-- la tige de l'anneau : sans elle, il flotte sans dire d'où il vient -->
          <line
            :x1="tige.x1" :y1="tige.y1" :x2="tige.x2" :y2="tige.y2"
            stroke="#f0abfc" stroke-width="1" opacity="0.5" pointer-events="none"
          />
          <template v-for="h in poignees" :key="h.id">
            <!-- halo sombre : sur un listel clair, un disque plein seul disparaît -->
            <circle
              :cx="h.p[0]" :cy="h.p[1]" r="9" fill="none" stroke="#0b0d10"
              stroke-width="2.5" opacity="0.7" pointer-events="none"
            />
            <circle
              :cx="h.p[0]" :cy="h.p[1]" r="7" :fill="h.creuse ? 'none' : h.couleur"
              :stroke="h.creuse ? h.couleur : '#0b0d10'" :stroke-width="h.creuse ? 2.5 : 1.5"
              pointer-events="none"
            />
            <!-- la cible du doigt fait le double du disque : on vise un bord,
                 pas un pixel -->
            <circle
              :data-poignee="h.id" :cx="h.p[0]" :cy="h.p[1]" r="14"
              fill="transparent" class="poignee"
            >
              <title>{{ h.titre }}</title>
            </circle>
          </template>
        </svg>

        <div v-if="courante" class="incrust gauche">
          a={{ ell.a.toFixed(1) }} b={{ ell.b.toFixed(1) }}
          b/a={{ (ell.b / ell.a).toFixed(3) }} θ={{ ell.theta.toFixed(1) }}°
          <span class="doux">· {{ secondesEcoulees.toFixed(0) }} s</span>
        </div>
        <div v-if="courante" class="incrust droite">
          <span class="pastille" :class="etatImage.classe">{{ etatImage.texte }}</span>
        </div>
        <div v-if="flash" class="flash">{{ flash }}</div>

        <div v-if="chargement" class="vide">chargement…</div>
        <div v-else-if="erreur" class="vide erreur">{{ erreur }}</div>
        <div v-else-if="!images.length" class="vide">
          <b>Le tirage n'est pas encore publié au canonique.</b>
          <p class="doux">
            Ce n'est pas une panne : il n'y a rien à annoter tant que les 60 images
            n'ont pas été tirées et publiées. Depuis la machine du ML :
          </p>
          <pre>python -m bench.gold_crop.publier_tirage --out state/gold_crop/{{ version }}</pre>
        </div>
      </div>

      <!-- Les loupes vivent SOUS la scène, jamais dessus : elles montraient le
           bord en cachant la pièce. -->
      <div class="loupes">
        <figure v-for="l in loupes" :key="l.nom" :class="{ actif: loupeActive === l.nom }">
          <svg
            :data-loupe="l.nom" :width="LOUPE" :height="LOUPE"
            :viewBox="`0 0 ${LOUPE} ${LOUPE}`"
            @pointerdown="surLoupeDown($event, l)"
            @pointermove="surLoupeMove"
            @pointerup="surLoupeUp"
            @pointercancel="surLoupeUp"
            @wheel="surLoupeMolette($event, l)"
          >
            <image :href="l.url" :x="l.tx" :y="l.ty" :width="l.w" :height="l.h" />
            <ellipse
              :cx="l.cx" :cy="l.cy" :rx="l.rx" :ry="l.ry" :transform="l.rot"
              fill="none" stroke="#ffd166" stroke-width="1.2"
            />
            <!-- la croisée dit où est le bord exactement, au pixel de la loupe -->
            <line
              :x1="LOUPE / 2 - 9" :y1="LOUPE / 2" :x2="LOUPE / 2 + 9" :y2="LOUPE / 2"
              stroke="#ffd166" stroke-width="0.8" opacity="0.9"
            />
            <line
              :x1="LOUPE / 2" :y1="LOUPE / 2 - 9" :x2="LOUPE / 2" :y2="LOUPE / 2 + 9"
              stroke="#ffd166" stroke-width="0.8" opacity="0.9"
            />
          </svg>
          <figcaption>{{ l.nom }}</figcaption>
        </figure>
      </div>
    </div>

    <aside>
      <h1>Jeu d'or — ellipses</h1>
      <p class="doux soustitre">
        passe {{ passe }} · {{ images.length }} images · version {{ version }}
        <span v-if="demo" class="pastille todo">fixture</span>
      </p>
      <div class="barre"><i :style="{ width: `${progres}%` }"></i></div>

      <div v-if="gele" class="gele">
        <b>Version gelée le {{ gele.slice(0, 10) }}.</b>
        Plus une écriture n'entre (le canonique répond 409). Cette séance est en
        lecture seule ; il faut une nouvelle version d'or pour annoter encore.
      </div>

      <div class="consigne">
        <b>Ce qu'on te demande</b>
        Fais coïncider l'ellipse jaune avec le <b>bord extérieur de la pièce</b> —
        le listel, pas l'anneau aux étoiles. Puis <kbd>Entrée</kbd>.
        <p class="doux">
          Les 4 loupes sous l'image montrent ce bord de près. Si le trait jaune y
          colle au métal, c'est bon.
        </p>
      </div>

      <section class="bloc">
        <h2>Les gestes</h2>
        <div class="legende">
          <i style="background: #4ade80"></i><span><b>bord</b> — tire un bord, l'opposé ne bouge pas</span>
          <i style="background: #60a5fa"></i><span><b>centre</b> — déplace tout</span>
          <i style="background: #f0abfc"></i><span><b>anneau</b> — tourne</span>
        </div>
        <p class="doux">
          Les loupes se tirent aussi : 4× plus fin, flèches ±0,5 px.
        </p>
      </section>

      <section class="bloc">
        <h2>Image</h2>
        <div class="lignes">
          <b>rang</b><span>{{ courante ? idx + 1 : 0 }} / {{ images.length }}</span>
          <b>état</b><span>{{ etatImage.texte }}</span>
          <b>strate tirée</b><span>{{ courante?.strate_tiree || '—' }}</span>
          <b>pré-remplissage</b><span>{{ prefillTexte }}</span>
          <b>asset</b><span class="mono">{{ courante?.asset_id || '—' }}</span>
        </div>
      </section>

      <section class="bloc">
        <h2>Cette image, c'est laquelle des quatre ?</h2>
        <div class="rangee">
          <button
            v-for="(s, i) in STRATES" :key="s" class="strate"
            :class="{ actif: etatCourant?.strate_confirmee === s }"
            @click="poserStrate(s)"
          >
            {{ s.slice(0, 2) }} <kbd>{{ i + 1 }}</kbd>
          </button>
        </div>
        <dl class="strates-aide">
          <dt>S1 facile</dt><dd>une seule pièce, nette, vue quasi de face, fond simple</dd>
          <dt>S2 capsule</dt><dd>sous plastique — blister, coffret, slab gradé. Reflets et halo</dd>
          <dt>S3 multi</dt><dd>plusieurs pièces dans l'image, ou un lot, ou un coffret</dd>
          <dt>S4 oblique</dt><dd>la pièce est nettement de biais — elle paraît ovale</dd>
        </dl>
        <p class="doux">
          Les {{ TAILLE_TIRAGE }} images ont été tirées 15 par famille, pour qu'une
          méthode qui marche sur les photos faciles et rate les pièces de biais se
          voie. Mais le tirage s'est fait sur le <b>texte de l'annonce</b>, qui
          ment : cette image a été tirée comme
          <b>{{ courante?.strate_tiree || '—' }}</b>. Si ce n'est pas ça, corrige.
        </p>
      </section>

      <section class="bloc">
        <h2>Cas non annotable</h2>
        <div class="rangee">
          <button
            class="danger" :class="{ actif: etatCourant?.indecidable }"
            @click="basculerIndecidable()"
          >
            Indécidable <kbd>i</kbd>
          </button>
        </div>
        <p class="doux">
          Pièce coupée par le bord, floue, masquée. Un cas non annotable sort
          explicitement — il ne s'annote pas au jugé. La réserve le remplace.
        </p>
      </section>

      <section class="bloc">
        <h2>Clavier</h2>
        <div class="aide">
          <kbd>Entrée</kbd><span>valider et suivante</span>
          <kbd>← →</kbd><span>naviguer — <em>sauf</em> si une loupe est choisie</span>
          <kbd>flèches</kbd><span>loupe choisie : pousser le bord ±0,5 px</span>
          <kbd>Maj + flèche</kbd><span>±2 px</span>
          <kbd>molette</kbd><span>sur une loupe : ±0,25 px</span>
          <kbd>Échap</kbd><span>lâcher la loupe et rendre les flèches</span>
          <kbd>1…4</kbd><span>confirmer la strate</span>
          <kbd>i</kbd><span>indécidable</span>
          <kbd>r</kbd><span>revenir au pré-remplissage</span>
          <kbd>f</kbd><span>recadrer la vue</span>
          <kbd>molette</kbd><span>sur la scène : zoom · glisser = déplacer</span>
        </div>
      </section>

      <section class="bloc">
        <h2>Séance</h2>
        <div class="lignes">
          <b>annotées</b><span>{{ faites.length }} / {{ images.length }}</span>
          <b>indécidables</b><span>{{ nIndecidables }}</span>
          <b>médiane / image</b><span>{{ mediane }}</span>
          <b>écrit</b>
          <span
            class="ecrit"
            :class="ecrit?.ton === 'rouge' ? 'ko' : ecrit ? 'ok' : ''"
          >{{ ecrit?.texte || '—' }}</span>
        </div>
        <p class="doux">
          Le chrono n'est pas une pression : il sert à repérer une famille d'images
          où la proposition de départ est mauvaise. Rien à faire de ton côté.
        </p>
      </section>
    </aside>
  </div>
</template>

<style scoped>
/* Thème CLAIR du front admin : toutes les couleurs viennent de `shared/tokens.css`
   (R2). Seul le fond de scène est sombre — un trait d'or sur du blanc ne se voit
   pas, et c'est le trait qu'on vient juger. */
.annoter { display: flex; height: calc(100vh - 3.5rem); color: var(--ink-700); }
.colonne { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.scene { flex: 1; position: relative; overflow: hidden; background: var(--ink); }
.toile { width: 100%; height: 100%; display: block; cursor: grab; touch-action: none; }
.poignee { cursor: grab; }

aside { width: 340px; flex: none; overflow-y: auto; padding: var(--space-5);
        border-left: 1px solid var(--surface-3); background: var(--surface); }
h1 { font-size: var(--text-lg); margin: 0 0 0.15rem; font-family: var(--font-display); }
h2 { font-size: var(--text-xs); text-transform: uppercase; letter-spacing: var(--tracking-eyebrow);
     color: var(--ink-500); margin: 0 0 0.5rem; font-weight: 600; }
.soustitre { margin: 0; font-size: var(--text-xs); }
.doux { color: var(--ink-500); font-size: var(--text-xs); }
.mono { font-family: var(--font-mono); font-size: var(--text-xs); }

.barre { height: 5px; background: var(--surface-2); border-radius: 3px;
         overflow: hidden; margin-top: 0.5rem; }
.barre i { display: block; height: 100%; background: var(--success);
           transition: width var(--duration-base) var(--ease-out); }

.bloc { border-top: 1px solid var(--surface-3); margin-top: var(--space-4);
        padding-top: var(--space-3); }
.bloc p { margin: 0.5rem 0 0; }
.lignes { display: grid; grid-template-columns: auto 1fr; gap: 0.2rem 0.7rem;
          font-size: var(--text-xs); font-variant-numeric: tabular-nums; }
.lignes b { color: var(--ink-500); font-weight: 400; }

button { font: inherit; font-size: var(--text-xs); color: var(--ink-700);
         background: var(--surface); border: 1px solid var(--surface-3);
         border-radius: var(--radius-sm); padding: 0.25rem 0.55rem; cursor: pointer; }
button:hover { background: var(--surface-2); }
button.actif { background: var(--indigo-600); border-color: var(--indigo-600);
               color: #fff; font-weight: 600; }
button.danger.actif { background: var(--danger); border-color: var(--danger); }
.rangee { display: flex; gap: 0.35rem; flex-wrap: wrap; }

kbd { background: var(--surface-2); border: 1px solid var(--surface-3);
      border-bottom-width: 2px; border-radius: var(--radius-xs); padding: 0 0.3rem;
      font-family: var(--font-mono); font-size: 0.7rem; }
.aide { display: grid; grid-template-columns: auto 1fr; gap: 0.25rem 0.6rem;
        align-items: center; color: var(--ink-500); font-size: var(--text-xs); }

.consigne { margin-top: var(--space-4); padding: 0.65rem 0.75rem;
            border-radius: var(--radius-md); background: var(--gold-100);
            border: 1px solid var(--gold-300); font-size: var(--text-xs);
            line-height: var(--leading-base); }
.consigne > b { color: var(--gold-700); display: block; margin-bottom: 0.15rem; }
.consigne p { margin: 0.4rem 0 0; }
.gele { margin-top: var(--space-4); padding: 0.65rem 0.75rem; border-radius: var(--radius-md);
        background: var(--danger-soft); color: var(--danger); font-size: var(--text-xs); }
.gele b { display: block; }

.legende { display: grid; grid-template-columns: auto 1fr; gap: 0.35rem 0.6rem;
           align-items: center; font-size: var(--text-xs); }
.legende i { width: 11px; height: 11px; border-radius: var(--radius-full); display: block; }
.strates-aide { display: grid; grid-template-columns: auto 1fr; gap: 0.2rem 0.6rem;
                margin: 0.55rem 0 0; font-size: var(--text-xs); }
.strates-aide dt { font-weight: 600; white-space: nowrap; }
.strates-aide dd { margin: 0; color: var(--ink-500); }

/* La bande des loupes : sous la scène, jamais dessus. */
.loupes { flex: none; display: flex; gap: var(--space-3); justify-content: center;
          padding: 0.5rem var(--space-3); background: var(--surface);
          border-top: 1px solid var(--surface-3); }
.loupes figure { margin: 0; background: var(--ink); border: 1px solid var(--surface-3);
                 border-radius: var(--radius-md); padding: 0.2rem; cursor: ns-resize; }
.loupes figure.actif { border-color: var(--gold-500);
                       box-shadow: 0 0 0 2px var(--gold-300); }
.loupes svg { display: block; touch-action: none; }
.loupes figcaption { text-align: center; font-size: 0.65rem; color: var(--ink-500);
                     letter-spacing: 0.06em; padding-top: 0.1rem; }

.incrust { position: absolute; bottom: 0.75rem; background: var(--surface);
           border: 1px solid var(--surface-3); border-radius: var(--radius-sm);
           padding: 0.3rem 0.6rem; font-size: var(--text-xs);
           font-variant-numeric: tabular-nums; }
.incrust.gauche { left: 0.75rem; }
.incrust.droite { right: 0.75rem; }
.flash { position: absolute; right: 0.75rem; top: 0.75rem; background: var(--surface);
         border: 1px solid var(--surface-3); border-radius: var(--radius-sm);
         padding: 0.3rem 0.6rem; font-size: var(--text-xs); }
.pastille { display: inline-block; padding: 0.05rem 0.45rem; border-radius: var(--radius-full);
            font-size: var(--text-xs); font-weight: 600; }
.acc { background: var(--success-soft); color: var(--success); }
.rej { background: var(--danger-soft); color: var(--danger); }
.todo { background: var(--surface-2); color: var(--ink-500); }
.ecrit.ok { color: var(--success); font-weight: 600; }
.ecrit.ko { color: var(--danger); font-weight: 600; }

.vide { position: absolute; inset: auto 0 0 0; top: 0; display: flex;
        flex-direction: column; justify-content: center; align-items: center;
        gap: 0.4rem; padding: var(--space-6); text-align: center;
        color: var(--surface-1); background: var(--ink); font-size: var(--text-sm); }
.vide .doux { color: var(--ink-300); max-width: 42ch; }
.vide.erreur { color: var(--danger); }
.vide pre { margin: 0; padding: 0.5rem 0.7rem; background: var(--ink-700);
            border-radius: var(--radius-sm); font-family: var(--font-mono);
            font-size: var(--text-xs); color: var(--surface); overflow-x: auto; max-width: 100%; }
</style>
