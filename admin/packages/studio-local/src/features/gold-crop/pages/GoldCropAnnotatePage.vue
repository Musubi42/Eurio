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
  debut = performance.now()
  mesurer()
  recadrer()
}

/* ─── vue ────────────────────────────────────────────────────────────────── */

function mesurer() {
  const el = scene.value
  if (el && el.clientWidth > 0) taille.value = { w: el.clientWidth, h: el.clientHeight }
}

function recadrer() {
  const r = courante.value
  if (!r) return
  mesurer()
  const { w: W, h: H } = taille.value
  // on cadre sur l'ellipse, pas sur le raw : c'est le listel qu'on vient juger
  const rayon = Math.max(ell.value.a, ell.value.b, r.hint.r) * 1.35
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

/** Les trois poignées, en coordonnées image. `A` porte AUSSI la rotation. */
const poignees = computed(() => {
  const t = (ell.value.theta * Math.PI) / 180
  const ux = Math.cos(t)
  const uy = Math.sin(t)
  const e = ell.value
  return [
    { id: 'C', couleur: '#60a5fa', titre: 'centre — déplacer', p: versEcran(e.cx, e.cy) },
    {
      id: 'A',
      couleur: '#4ade80',
      titre: 'grand axe — taille et rotation',
      p: versEcran(e.cx + e.a * ux, e.cy + e.a * uy),
    },
    {
      id: 'B',
      couleur: '#34d399',
      titre: 'petit axe — aplatir',
      p: versEcran(e.cx - e.b * uy, e.cy + e.b * ux),
    },
  ]
})

// Les quatre loupes du bord. « Mon ellipse est-elle SUR le bord ? » ne se répond
// pas à la vue d'ensemble : à l'échelle où la pièce tient à l'écran, 2 % du
// rayon font 4 pixels. On montre donc le contour de près, aux 4 points
// cardinaux, avec le trait dessus.
const LOUPE = 104
const ZOOM = 4

const loupes = computed(() => {
  const r = courante.value
  if (!r) return []
  const e = ell.value
  const t = (e.theta * Math.PI) / 180
  const ct = Math.cos(t)
  const st = Math.sin(t)
  const vues: [string, number][] = [
    ['haut', -Math.PI / 2],
    ['droite', 0],
    ['bas', Math.PI / 2],
    ['gauche', Math.PI],
  ]
  return vues.map(([nom, phi]) => {
    const u = e.a * Math.cos(phi)
    const v = e.b * Math.sin(phi)
    const px = e.cx + u * ct - v * st
    const py = e.cy + u * st + v * ct
    const tx = LOUPE / 2 - px * ZOOM
    const ty = LOUPE / 2 - py * ZOOM
    const cx = e.cx * ZOOM + tx
    const cy = e.cy * ZOOM + ty
    return {
      nom,
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

const secondesEcoulees = computed(() => {
  void tic.value
  return (performance.now() - debut) / 1000
})

/* ─── interaction ────────────────────────────────────────────────────────── */

let saisie: { type: string; x: number; y: number } | null = null

function surPointerDown(ev: PointerEvent) {
  const cible = (ev.target as HTMLElement | null)?.dataset?.poignee
  saisie = { type: cible || 'pan', x: ev.clientX, y: ev.clientY }
  const el = ev.currentTarget as SVGSVGElement
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
  const r = el.getBoundingClientRect ? el.getBoundingClientRect() : { left: 0, top: 0 }
  const [ix, iy] = versImage(ev.clientX - r.left, ev.clientY - r.top)
  const e = { ...ell.value }
  if (saisie.type === 'pan') {
    vue.value = {
      ...vue.value,
      tx: vue.value.tx + (ev.clientX - saisie.x),
      ty: vue.value.ty + (ev.clientY - saisie.y),
    }
    saisie.x = ev.clientX
    saisie.y = ev.clientY
    return
  }
  if (saisie.type === 'C') {
    e.cx = ix
    e.cy = iy
  } else if (saisie.type === 'A') {
    const dx = ix - e.cx
    const dy = iy - e.cy
    e.a = Math.max(4, Math.hypot(dx, dy))
    e.theta = (Math.atan2(dy, dx) * 180) / Math.PI // A porte AUSSI la rotation
    e.b = Math.min(e.b, e.a)
  } else if (saisie.type === 'B') {
    const t = (e.theta * Math.PI) / 180
    // projection sur la normale au grand axe : B ne change QUE le petit axe
    e.b = Math.min(
      e.a,
      Math.max(3, Math.abs(-(ix - e.cx) * Math.sin(t) + (iy - e.cy) * Math.cos(t))),
    )
  }
  // Pas de normalisation ICI : ramener θ dans [0, 180) en plein glisser ferait
  // sauter la poignée A à l'opposé dès qu'on passe à gauche du centre. On
  // normalise à la validation, là où le nombre part au canonique.
  ell.value = e
}

function surMolette(ev: WheelEvent) {
  ev.preventDefault()
  const el = ev.currentTarget as SVGSVGElement
  const r = el.getBoundingClientRect ? el.getBoundingClientRect() : { left: 0, top: 0 }
  const X = ev.clientX - r.left
  const Y = ev.clientY - r.top
  const [ix, iy] = versImage(X, Y)
  const k = vue.value.k * Math.exp(-ev.deltaY * 0.0015)
  vue.value = { k, tx: X - ix * k, ty: Y - iy * k }
}

function surClavier(ev: KeyboardEvent) {
  if (ev.key === 'Enter' || ev.key === 'ArrowRight') {
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

onMounted(() => {
  window.addEventListener('keydown', surClavier)
  window.addEventListener('resize', recadrer)
  horloge = setInterval(() => (tic.value += 1), 1000)
  void demarrer()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', surClavier)
  window.removeEventListener('resize', recadrer)
  if (horloge) clearInterval(horloge)
  if (enAttente) clearTimeout(enAttente)
  if (minuteurFlash) clearTimeout(minuteurFlash)
})
</script>

<template>
  <div class="annoter">
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
        <template v-for="h in poignees" :key="h.id">
          <!-- halo sombre : sur un listel clair, un disque plein seul disparaît -->
          <circle
            :cx="h.p[0]" :cy="h.p[1]" r="9" fill="none" stroke="#0b0d10"
            stroke-width="2.5" opacity="0.7" pointer-events="none"
          />
          <circle
            :data-poignee="h.id" :cx="h.p[0]" :cy="h.p[1]" r="7" :fill="h.couleur"
            stroke="#0b0d10" stroke-width="1.5" class="poignee"
          >
            <title>{{ h.titre }}</title>
          </circle>
        </template>
      </svg>

      <div class="loupes">
        <figure v-for="l in loupes" :key="l.nom">
          <svg :width="LOUPE" :height="LOUPE" :viewBox="`0 0 ${LOUPE} ${LOUPE}`">
            <image :href="l.url" :x="l.tx" :y="l.ty" :width="l.w" :height="l.h" />
            <ellipse
              :cx="l.cx" :cy="l.cy" :rx="l.rx" :ry="l.ry" :transform="l.rot"
              fill="none" stroke="#ffd166" stroke-width="1.2"
            />
            <circle
              :cx="LOUPE / 2" :cy="LOUPE / 2" r="2" fill="none" stroke="#ffd166"
              stroke-width="1" opacity="0.8"
            />
          </svg>
          <figcaption>{{ l.nom }}</figcaption>
        </figure>
      </div>

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
          Les 4 vignettes du bas montrent ce bord de près, aux 4 points cardinaux.
          Si le trait jaune y colle au métal, c'est bon.
        </p>
      </div>

      <section class="bloc">
        <h2>Les trois poignées</h2>
        <div class="legende">
          <i style="background: #60a5fa"></i><span><b>centre</b> — déplacer l'ellipse</span>
          <i style="background: #4ade80"></i><span><b>grand axe</b> — taille <em>et</em> rotation</span>
          <i style="background: #34d399"></i><span><b>petit axe</b> — aplatir seulement</span>
        </div>
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
          <kbd>← →</kbd><span>naviguer</span>
          <kbd>1…4</kbd><span>confirmer la strate</span>
          <kbd>i</kbd><span>indécidable</span>
          <kbd>r</kbd><span>revenir au pré-remplissage</span>
          <kbd>f</kbd><span>recadrer la vue</span>
          <kbd>molette</kbd><span>zoom · glisser = déplacer</span>
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

.loupes { position: absolute; left: 0.75rem; bottom: 3.5rem; display: flex; gap: 0.5rem; }
.loupes figure { margin: 0; background: var(--surface); border: 1px solid var(--surface-3);
                 border-radius: var(--radius-md); padding: 0.25rem; }
.loupes figcaption { text-align: center; font-size: 0.65rem; color: var(--ink-500);
                     letter-spacing: 0.06em; }

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
