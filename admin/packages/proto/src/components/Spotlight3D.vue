<script setup lang="ts">
/* Spotlight3D — pièce en 3D live pour la carte « Tes meilleures pièces » du
 * Coffre. Réutilise le moteur de ScanReveal (createStage + buildCoinFromUrls) :
 * une seule stage, le modèle est remplacé quand la pièce change (re-build).
 * Auto-rotation douce ; pas d'interaction (le tap sur la carte ouvre la fiche). */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { getCoin, getCoin3DAssets } from '@/api'
import { buildCoinFromUrls, buildProceduralEdgeTexture, createStage, disposeCoin, R_OUT } from '@/lib/coin3d'
import CoinImage from '@/components/CoinImage.vue'

const props = withDefaults(
  defineProps<{
    eurioId: string
    /* Cadrage / orientation — défauts = hero turntable face caméra. La vue
       caractéristiques passe un tilt fort (profil) pour révéler l'épaisseur. */
    fill?: number // part du cadre occupée par le rayon de la pièce
    tiltX?: number // inclinaison avant/arrière (rad) — révèle la tranche
    spinAmp?: number // amplitude du balancement y (rad)
    spinSpeed?: number // vitesse du balancement
    /* Rotation libre au doigt (tous axes) : balancement idle conservé, l'utilisateur
       peut faire tourner la pièce dans n'importe quel angle ; le tangage se redresse
       doucement au repos. Utilisé par le hero de la fiche. */
    interactive?: boolean
  }>(),
  { fill: 0.6, tiltX: -0.18, spinAmp: 0.45, spinSpeed: 0.5, interactive: false },
)

const wrapRef = ref<HTMLElement | null>(null)
// Repli image si la pièce n'a pas d'assets 3D (ou si le build échoue) → la carte
// best-coins montre TOUJOURS une pièce.
const fallback = ref(false)
const coin = computed(() => getCoin(props.eurioId))

let stage: ReturnType<typeof createStage> | null = null
let coin3d: Awaited<ReturnType<typeof buildCoinFromUrls>> | null = null
let group: import('three').Group | null = null
let token = 0 // garde anti-course : seul le dernier load gagne
let spinT = 0 // horloge locale du balancement

// ── Rotation libre (mode interactif) ──
const DRAG_K = 0.011 // sensibilité lacet (gauche-droite)
const TILT_K = 0.009 // sensibilité tangage (haut-bas)
const PITCH_MAX = 1.5 // ~86° : on peut basculer voir le dessus/dessous
let dragging = false
let userYaw = 0 // lacet accumulé par l'utilisateur
let userPitch = props.tiltX // tangage courant (revient vers tiltX au repos)
let lastX = 0
let lastY = 0
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

function frameCoin() {
  const wrap = wrapRef.value
  if (!wrap || !stage) return
  const w = wrap.clientWidth || 1
  const h = wrap.clientHeight || 1
  const tanHalfV = Math.tan((35 * Math.PI) / 180 / 2)
  const halfNeeded = R_OUT / props.fill
  const dist = Math.max(halfNeeded / tanHalfV, halfNeeded / (tanHalfV * (w / h)))
  stage.camera.position.set(0, dist * 0.05, dist)
  stage.camera.lookAt(0, 0, 0)
}

async function loadModel(eurioId: string) {
  if (!stage) return
  const assets = getCoin3DAssets(eurioId)
  if (!assets) {
    // Pas d'assets 3D pour cette pièce → repli image, on retire un éventuel modèle.
    if (coin3d) { stage.scene.remove(coin3d.group); disposeCoin(coin3d); coin3d = null; group = null }
    fallback.value = true
    return
  }
  const myToken = ++token
  try {
    const edgeTex = buildProceduralEdgeTexture()
    const built = await buildCoinFromUrls({ obverse: assets.obverse, reverse: assets.reverse }, { edgeTex })
    // Une pièce plus récente a été demandée entre-temps, ou on a démonté : on jette.
    if (!stage || myToken !== token) {
      disposeCoin(built)
      return
    }
    if (coin3d) {
      stage.scene.remove(coin3d.group)
      disposeCoin(coin3d)
    }
    coin3d = built
    group = built.group
    group.rotation.set(props.tiltX, 0, 0) // tilt avant/arrière (hero: léger ; profil: fort)
    stage.scene.add(group)
    fallback.value = false
  } catch (err) {
    console.error('[spotlight-3d] build failed', err)
    fallback.value = true
  }
}

onMounted(async () => {
  const wrap = wrapRef.value
  if (!wrap) return
  stage = createStage(wrap)
  frameCoin()
  stage.onFrame((dt) => {
    frameCoin()
    if (!group) return
    if (props.interactive) {
      if (!dragging) {
        spinT += dt
        // Le tangage se redresse doucement vers la pose de repos (tiltX).
        userPitch += (props.tiltX - userPitch) * Math.min(1, dt * 1.4)
      }
      // Balancement idle ajouté par-dessus le lacet de l'utilisateur (figé pendant le drag).
      const sway = dragging ? 0 : Math.sin(spinT * props.spinSpeed) * props.spinAmp
      group.rotation.y = userYaw + sway
      group.rotation.x = userPitch
    } else {
      // Balancement doux « turntable » face caméra (jamais sur la tranche).
      spinT += dt
      group.rotation.y = Math.sin(spinT * props.spinSpeed) * props.spinAmp
      group.rotation.x = props.tiltX
    }
  })
  stage.start()

  if (props.interactive) {
    const onDown = (e: PointerEvent) => {
      dragging = true
      lastX = e.clientX
      lastY = e.clientY
      wrap.setPointerCapture?.(e.pointerId)
    }
    const onMove = (e: PointerEvent) => {
      if (!dragging) return
      userYaw += (e.clientX - lastX) * DRAG_K
      userPitch = clamp(userPitch + (e.clientY - lastY) * TILT_K, -PITCH_MAX, PITCH_MAX)
      lastX = e.clientX
      lastY = e.clientY
    }
    const onUp = () => (dragging = false)
    wrap.addEventListener('pointerdown', onDown)
    wrap.addEventListener('pointermove', onMove)
    wrap.addEventListener('pointerup', onUp)
    wrap.addEventListener('pointercancel', onUp)
    pointerCleanup = () => {
      wrap.removeEventListener('pointerdown', onDown)
      wrap.removeEventListener('pointermove', onMove)
      wrap.removeEventListener('pointerup', onUp)
      wrap.removeEventListener('pointercancel', onUp)
    }
  }

  await loadModel(props.eurioId)
})

let pointerCleanup: (() => void) | null = null

watch(
  () => props.eurioId,
  (id) => loadModel(id),
)

onBeforeUnmount(() => {
  token++ // invalide tout load en vol
  pointerCleanup?.()
  if (coin3d) {
    disposeCoin(coin3d)
    coin3d = null
  }
  stage?.dispose()
  stage = null
  group = null
})
</script>

<template>
  <div class="spotlight-3d" :class="{ 'spotlight-3d--interactive': interactive }">
    <div v-show="!fallback" ref="wrapRef" class="spotlight-3d__stage" aria-hidden="true"></div>
    <div v-if="fallback && coin" class="spotlight-3d__fallback">
      <CoinImage :coin="coin" :size="160" :show-label="false" />
    </div>
  </div>
</template>

<style scoped>
.spotlight-3d {
  width: 100%;
  height: 100%;
}
/* Mode interactif : on capte le geste (pas de scroll de page) + curseur grab. */
.spotlight-3d--interactive {
  touch-action: none;
  cursor: grab;
}
.spotlight-3d--interactive:active {
  cursor: grabbing;
}
.spotlight-3d__stage {
  width: 100%;
  height: 100%;
}
.spotlight-3d__fallback {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
}
.spotlight-3d__fallback :deep(img),
.spotlight-3d__fallback :deep(svg) {
  width: auto;
  max-width: 70%;
  max-height: 90%;
}
/* createStage appelle setSize(w,h,false) → ne pose pas le style du canvas.
 * On le contraint au conteneur sinon il s'affiche à sa taille intrinsèque. */
.spotlight-3d__stage :deep(canvas) {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
