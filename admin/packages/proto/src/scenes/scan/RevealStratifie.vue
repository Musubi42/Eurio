<script setup lang="ts">
/* Scène reveal-stratifie — reveal post-scan : héros 3D + bottom-sheet 2 crans
 * + jalons en overlay. Port de reveal-stratifie.html/.js. */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getCoin, getCoin3DAssets, getReveal, simulateScan } from '@/api'
import { useCollectionStore } from '@/stores/collection'
import { buildCoinFromUrls, buildProceduralEdgeTexture, createStage, disposeCoin, R_OUT } from '@/lib/coin3d'
import type { Coin as Coin3D, Stage } from '@/lib/coin3d'
import { confetti, chime, haptic } from '@/lib/celebration'
import { isParity, PARITY_COIN_POSE } from '@/api/parity'

const route = useRoute()
const router = useRouter()
const store = useCollectionStore()

const HERO_FILL = 0.78
const IDLE_SPD = 0.2
const DRAG_K = 0.011
const TILT_K = 0.006
const TILT_MAX = 0.55
const EXPANDED_FRAC = 0.6
const NAV_PAD = 88

type Milestone = 'set' | 'country' | 'feat' | ''
const MILESTONE: Record<Exclude<Milestone, ''>, { label: string; confetti: number; chime: number[]; toast: string }> = {
  set: { label: 'Série complète', confetti: 24, chime: [523.25, 659.25, 783.99], toast: 'Série complétée ✓' },
  country: { label: 'Pays complété', confetti: 32, chime: [523.25, 659.25, 783.99, 880.0], toast: 'Pays complété ✓' },
  feat: { label: 'Légendaire', confetti: 44, chime: [523.25, 659.25, 783.99, 1046.5], toast: 'Pièce légendaire ajoutée ✓' },
}

// ── Résolution pièce ──
const ownedMode = route.query.owned === '1'
// En parité, pas d'id explicite → tirage SEEDÉ (déterministe), pas Math.random.
const eurioId = String(route.query.id ?? '') || simulateScan(isParity() ? 0 : undefined)
const coin = getCoin(eurioId) ?? getCoin(simulateScan(0))!
const reveal = getReveal(coin.eurioId)!

const rawMilestone = String(route.query.milestone ?? '').toLowerCase()
const milestone: Milestone = ownedMode ? '' : (['set', 'country', 'feat'].includes(rawMilestone) ? (rawMilestone as Milestone) : '')
const ms = milestone ? MILESTONE[milestone] : null

// ── Contenu (avec surcharges jalon) ──
const name = coin.theme || coin.designDescription || coin.countryName
const total = reveal.completionTotal
const ownedN = milestone === 'set' ? total : reveal.completionOwned
const accent = computed(() => {
  if (milestone === 'set') return 'Série complète 🎉'
  if (milestone === 'country') return '🗺️ Pays complété'
  if (milestone === 'feat') return '★ Légendaire · 2% la détiennent'
  return reveal.accent
})
const missingText = ownedN >= total ? 'Série complète 🎉' : `Il te manque ${total - ownedN} pièce(s)`
const compPct = Math.round((ownedN / total) * 100)

// ── État UI réactif ──
const state = ref<'peek' | 'expanded'>('peek')
const rotated = ref(false)
const statusHidden = ref(false)
const addLabel = ref('Ajouter au coffre')
let addAction: 'add' | 'scratch' | 'vault' = 'add'
const addDisabled = ref(false)
const toastText = ref('')
const toastVisible = ref(false)
let toastTimer: ReturnType<typeof setTimeout> | null = null
function toast(t: string) {
  toastText.value = t
  toastVisible.value = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toastVisible.value = false), 2400)
}

// ── Refs DOM ──
const rootRef = ref<HTMLElement | null>(null)
const canvasWrapRef = ref<HTMLElement | null>(null)
const sheetRef = ref<HTMLElement | null>(null)
const handleRef = ref<HTMLElement | null>(null)
const summaryRef = ref<HTMLElement | null>(null)
const ctaRef = ref<HTMLElement | null>(null)
const celConfettiRef = ref<HTMLElement | null>(null)

let stage: Stage | null = null
let coin3d: Coin3D | null = null
let cleanupFns: (() => void)[] = []

// ── Actions ──
function onClose() {
  router.push('/scan')
}
function onAdd() {
  if (addAction === 'vault') return router.push('/vault')
  if (addAction === 'scratch') return router.push('/vault/catalog?scratch=1')
  // add
  store.addCoin(coin.eurioId, { valueAtAddCents: Math.round(reveal.grades.ttb * 100) })
  toast(ms ? ms.toast : 'Ajoutée au coffre ✓')
  if (milestone === 'country') {
    addLabel.value = 'Gratter la carte 🪙'
    addAction = 'scratch'
  } else {
    addLabel.value = 'Ajoutée ✓'
    addDisabled.value = true
  }
}
function onDetails() {
  router.push(`/coin/${encodeURIComponent(coin.eurioId)}`)
}

// ── 3D + sheet (impératif) ──
onMounted(async () => {
  const root = rootRef.value
  const wrap = canvasWrapRef.value
  const sheet = sheetRef.value
  const handle = handleRef.value
  if (!root || !wrap || !sheet || !handle) return

  // ----- 3D hero -----
  // Marqueur pour la capture parité : scène 3D → attendre __eurioCoinReady.
  if (isParity()) (window as Window & { __eurioHas3D?: boolean }).__eurioHas3D = true
  stage = createStage(wrap)
  const st = stage
  function frameCoin() {
    const w = wrap!.clientWidth || 1
    const h = wrap!.clientHeight || 1
    const tanHalfV = Math.tan((35 * Math.PI) / 180 / 2)
    const halfNeeded = R_OUT / HERO_FILL
    const dist = Math.max(halfNeeded / tanHalfV, halfNeeded / (tanHalfV * (w / h)))
    st.camera.position.set(0, dist * 0.05, dist)
    st.camera.lookAt(0, 0, 0)
  }
  frameCoin()

  let group: import('three').Group | null = null
  let omega = IDLE_SPD
  let dragging = false
  st.onFrame((dt) => {
    frameCoin()
    if (!group) return
    if (!dragging && !isParity()) {
      group.rotation.y += omega * dt
      omega += (IDLE_SPD - omega) * Math.min(1, dt * 2.5)
      group.rotation.x += (0 - group.rotation.x) * Math.min(1, dt * 4)
    }
  })
  st.start()

  let hdown: { lastX: number; lastY: number; lastT: number; vel: number } | null = null
  const heroDown = (ev: PointerEvent) => {
    if (!group) return
    wrap!.querySelector('canvas')?.setPointerCapture?.(ev.pointerId)
    dragging = true
    hdown = { lastX: ev.clientX, lastY: ev.clientY, lastT: performance.now(), vel: 0 }
    rotated.value = true
  }
  const heroMove = (ev: PointerEvent) => {
    if (!hdown || !group) return
    const dx = ev.clientX - hdown.lastX
    const dy = ev.clientY - hdown.lastY
    const dt = Math.max((performance.now() - hdown.lastT) / 1000, 1 / 240)
    group.rotation.y += dx * DRAG_K
    group.rotation.x = Math.max(-TILT_MAX, Math.min(TILT_MAX, group.rotation.x + dy * TILT_K))
    hdown.vel = hdown.vel * 0.7 + ((dx * DRAG_K) / dt) * 0.3
    hdown.lastX = ev.clientX
    hdown.lastY = ev.clientY
    hdown.lastT = performance.now()
  }
  const heroUp = () => {
    if (!hdown) return
    dragging = false
    omega = Math.max(-12, Math.min(12, hdown.vel || IDLE_SPD))
    hdown = null
  }
  wrap.addEventListener('pointerdown', heroDown)
  wrap.addEventListener('pointermove', heroMove)
  wrap.addEventListener('pointerup', heroUp)
  wrap.addEventListener('pointercancel', heroUp)

  // ----- Bottom sheet (peek / expanded) -----
  let peekH = 0
  let expandedH = 0
  let sdown: { startY: number; base: number; moved: number } | null = null

  function applyHeight(animate = true) {
    sheet!.style.transition = animate ? '' : 'none'
    sheet!.style.height = `${state.value === 'expanded' ? expandedH : peekH}px`
    if (!animate) requestAnimationFrame(() => (sheet!.style.transition = ''))
  }
  function relayout() {
    const rootH = root!.clientHeight || 1
    expandedH = Math.round(rootH * EXPANDED_FRAC)
    const handleH = handle!.offsetHeight || 30
    const sumH = summaryRef.value?.offsetHeight || 180
    const ctaH = ctaRef.value?.offsetHeight || 52
    peekH = handleH + sumH + ctaH + NAV_PAD + 16
    peekH = Math.max(Math.round(rootH * 0.3), Math.min(peekH, Math.round(rootH * 0.56)))
    if (expandedH < peekH + 80) expandedH = peekH + 80
    if (!sdown) applyHeight(false)
  }
  function setSheet(s: 'peek' | 'expanded') {
    state.value = s
    applyHeight(true)
  }
  function curHeight() {
    return parseFloat(sheet!.style.height) || peekH
  }
  relayout()
  applyHeight(false)
  const ro = new ResizeObserver(() => relayout())
  ro.observe(root)
  cleanupFns.push(() => ro.disconnect())

  const onHandleDown = (ev: PointerEvent) => {
    handle!.setPointerCapture?.(ev.pointerId)
    sdown = { startY: ev.clientY, base: curHeight(), moved: 0 }
    sheet!.style.transition = 'none'
  }
  const onHandleMove = (ev: PointerEvent) => {
    if (!sdown) return
    const dy = sdown.startY - ev.clientY
    sdown.moved += Math.abs(dy)
    sheet!.style.height = `${Math.max(peekH, Math.min(expandedH, sdown.base + dy))}px`
  }
  const endHandle = () => {
    if (!sdown) return
    sheet!.style.transition = ''
    if (sdown.moved < 6) setSheet(state.value === 'expanded' ? 'peek' : 'expanded')
    else setSheet(curHeight() > (peekH + expandedH) / 2 ? 'expanded' : 'peek')
    sdown = null
  }
  handle.addEventListener('pointerdown', onHandleDown)
  handle.addEventListener('pointermove', onHandleMove)
  handle.addEventListener('pointerup', endHandle)
  handle.addEventListener('pointercancel', endHandle)

  // ----- Build coin -----
  const assets = getCoin3DAssets(coin.eurioId)
  if (!assets) {
    statusHidden.value = false
    return
  }
  try {
    const edgeTex = buildProceduralEdgeTexture()
    coin3d = await buildCoinFromUrls({ obverse: assets.obverse, reverse: assets.reverse }, { edgeTex })
    // Quitté pendant le chargement async → la stage est disposée : ne pas y ajouter.
    if (!stage) {
      disposeCoin(coin3d)
      coin3d = null
      return
    }
    group = coin3d.group
    st.scene.add(group)
    // Capture parité : pose figée (le spin idle est désactivé dans onFrame) +
    // signal « coin prêt » après 2 frames (texture uploadée au GPU) → la capture
    // attend ce flag au lieu d'un délai aveugle (déterminisme 3D).
    if (isParity()) {
      group.rotation.set(PARITY_COIN_POSE.x, PARITY_COIN_POSE.y, PARITY_COIN_POSE.z)
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          ;(window as Window & { __eurioCoinReady?: boolean }).__eurioCoinReady = true
        }),
      )
    }
    statusHidden.value = true
    relayout()

    if (ms) {
      setTimeout(() => {
        haptic([0, 35, 30, 80])
        chime(ms.chime)
        if (celConfettiRef.value) confetti(celConfettiRef.value, { count: ms.confetti })
      }, 650)
    }
    if (ownedMode) {
      toast("Tu l'as déjà — le scan continue")
      addLabel.value = 'Voir au coffre'
      addAction = 'vault'
    }
  } catch (err) {
    console.error('[reveal] build failed', err)
  }
})

onBeforeUnmount(() => {
  cleanupFns.forEach((fn) => fn())
  cleanupFns = []
  if (coin3d && stage) {
    stage.scene.remove(coin3d.group)
    disposeCoin(coin3d)
  }
  stage?.dispose()
  stage = null
  coin3d = null
})
</script>

<template>
  <section ref="rootRef" class="reveal-root" data-scene="reveal-stratifie" :data-state="state" :data-owned="ownedMode ? '1' : '0'" :data-rotated="rotated ? '1' : '0'" :data-milestone="milestone || undefined">
    <div class="reveal-top">
      <span class="reveal-top__owned"><span aria-hidden="true">✓</span> Déjà au coffre</span>
      <span style="flex: 1"></span>
      <button type="button" class="reveal-close" data-testid="reveal-close" aria-label="Fermer" @click="onClose">&times;</button>
    </div>

    <div class="reveal-hero">
      <div class="reveal-cel__rays" aria-hidden="true"></div>
      <div ref="canvasWrapRef" class="reveal-hero__canvas"></div>
      <div class="reveal-hero__status" :class="{ 'is-hidden': statusHidden }">Révélation…</div>
      <div class="reveal-hero__hint">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v4h4" /></svg>
        Tourne-la
      </div>
    </div>

    <div class="reveal-cel" aria-hidden="true">
      <div ref="celConfettiRef" class="cel-confetti"></div>
      <div class="reveal-cel__bannerwrap"><span class="reveal-cel__banner">{{ ms?.label ?? 'Série complète' }}</span></div>
    </div>

    <aside ref="sheetRef" class="reveal-sheet" aria-label="Détails de la pièce">
      <button ref="handleRef" type="button" class="reveal-sheet__handle" aria-label="Déployer les détails">
        <span class="reveal-sheet__grip" aria-hidden="true"></span>
      </button>

      <div class="reveal-sheet__scroll">
        <div ref="summaryRef" class="reveal-sum">
          <span class="reveal-sum__eyebrow">{{ ownedMode ? 'Doublon' : 'Nouvelle pièce' }}</span>
          <h2 class="reveal-sum__title">{{ name }}</h2>
          <div class="reveal-sum__sub">{{ coin.countryName }} · {{ coin.year ?? '—' }} · 2&nbsp;€</div>
          <p class="reveal-sum__line">{{ reveal.narration.line }}</p>
          <div class="reveal-drives">
            <span class="reveal-drive reveal-drive--new">{{ ownedMode ? 'Déjà' : 'Nouvelle' }}</span>
            <span class="reveal-drive">{{ coin.countryName }} · {{ ownedN }}/{{ total }}</span>
            <span class="reveal-drive reveal-drive--accent">{{ accent }}</span>
          </div>
        </div>

        <div class="reveal-more">
          <div class="reveal-more__hint">Plus de détails</div>
          <section class="reveal-sec">
            <span class="reveal-sec__eyebrow">Histoire</span>
            <p class="reveal-sec__line">{{ reveal.narration.line }}</p>
            <p class="reveal-sec__line">{{ reveal.narration.long }}</p>
          </section>
          <section class="reveal-sec">
            <span class="reveal-sec__eyebrow">Rareté</span>
            <div class="reveal-tier">{{ reveal.tier }}</div>
            <p class="reveal-sec__line">Tirage {{ reveal.mintage.toLocaleString('fr-FR') }} ex.</p>
            <p class="reveal-sec__line">{{ reveal.nEffect }}</p>
          </section>
          <section class="reveal-sec">
            <span class="reveal-sec__eyebrow">Valeur · indicative</span>
            <div class="reveal-tier">≈ {{ reveal.grades.ttb }} € en TTB</div>
            <div class="reveal-grades">
              <div class="reveal-grade"><div class="reveal-grade__g">UNC</div><div class="reveal-grade__v">{{ reveal.grades.unc }} €</div></div>
              <div class="reveal-grade"><div class="reveal-grade__g">TTB</div><div class="reveal-grade__v">{{ reveal.grades.ttb }} €</div></div>
              <div class="reveal-grade"><div class="reveal-grade__g">TB</div><div class="reveal-grade__v">{{ reveal.grades.tb }} €</div></div>
            </div>
          </section>
          <section class="reveal-sec">
            <span class="reveal-sec__eyebrow">Complétion</span>
            <div class="reveal-comp"><span class="reveal-comp__big">{{ ownedN }}</span><span class="reveal-comp__total">/ {{ total }}</span></div>
            <div class="reveal-comp__bar progress-bar"><div class="progress-track"><div class="progress-fill" :style="{ width: compPct + '%' }"></div></div></div>
            <p class="reveal-comp__missing">{{ missingText }}</p>
          </section>
        </div>
      </div>

      <div ref="ctaRef" class="reveal-cta">
        <button type="button" class="btn btn-ghost btn-ghost--on-dark" data-testid="reveal-details" @click="onDetails">Voir la fiche</button>
        <button type="button" class="btn btn-gold" data-testid="reveal-add" :disabled="addDisabled" @click="onAdd">{{ addLabel }}</button>
      </div>
    </aside>

    <div class="toast toast--on-dark" :data-visible="toastVisible ? 'true' : 'false'" role="status">{{ toastText }}</div>
  </section>
</template>

<style src="../../styles/reveal-stratifie.css"></style>
