<script setup lang="ts">
/* Scène scan-reveal — LE flux unifié (T2). Une seule scène, une seule stage Three
 * (un objet 3D continu), navbar persistante.
 *
 *   idle caméra ──(auto-match)──▶ identification (morph → spin → settle, halo+son 1×)
 *   ──▶ reveal : pièce posée + titre sous la pièce + sheet 2 crans
 *        • pull-up    → fiche complète (<CoinDetailBody ctx="scan"/>) en header 3D
 *        • swipe-down → on repart en scan (nouvelle pièce)
 *
 * Pièce : tourne librement ; recentrée à plat + relâchée sans élan → se fige (lock) ;
 * re-flick → la rotation reprend. Pas de replay, pas de croix, pas de label « Identifié ».
 * Auto-add au coffre à l'identification + undo (snackbar « Annuler » + CTA Retirer). */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getCoin, getCoin3DAssets, getReveal, simulateScan } from '@/api'
import { useCollectionStore } from '@/stores/collection'
import { buildCoinFromUrls, buildProceduralEdgeTexture, createStage, disposeCoin, R_OUT } from '@/lib/coin3d'
import type { Coin as Coin3D, Stage } from '@/lib/coin3d'
import { confetti, chime, haptic } from '@/lib/celebration'
import { isParity, PARITY_COIN_POSE } from '@/api/parity'
import CoinDetailBody from '@/components/CoinDetailBody.vue'

const route = useRoute()
const router = useRouter()
const store = useCollectionStore()

// ── Constantes 3D (hero + chorégraphie) ──
const HERO_FILL = 0.7
const IDLE_SPD = 0.2
const DRAG_K = 0.011
const TILT_K = 0.006
const TILT_MAX = 0.55
const MORPH_DUR = 0.24
const MORPH_DUR_LIGHT = 0.14
const AUTO_IMPULSE = 18
const SPIN_DAMP = 3.4
const SETTLE_OMEGA = 2.2
const SNAP_DUR = 0.32
const POP_DUR = 0.24
const FLICK_MAX = 30
const TAP_PX = 7
const EXPANDED_FRAC = 0.92
const NAV_PAD = 88
const AUTO_MATCH_DELAY_MS = 2000

type Phase = 'idle' | 'morph' | 'spin' | 'settle' | 'revealed'

type Milestone = 'set' | 'country' | 'feat' | ''
const MILESTONE: Record<Exclude<Milestone, ''>, { label: string; confetti: number; chime: number[]; toast: string }> = {
  set: { label: 'Série complète', confetti: 24, chime: [523.25, 659.25, 783.99], toast: 'Série complétée ✓' },
  country: { label: 'Pays complété', confetti: 32, chime: [523.25, 659.25, 783.99, 880.0], toast: 'Pays complété ✓' },
  feat: { label: 'Légendaire', confetti: 44, chime: [523.25, 659.25, 783.99, 1046.5], toast: 'Pièce légendaire ajoutée ✓' },
}

const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
const light = route.query.light === '1' || reduced

// ── Résolution pièce (RÉACTIVE : un swipe-down relance un scan = nouvelle pièce) ──
// ?seed=N rend le tirage déterministe ; en parité, tirage SEEDÉ (pas Math.random).
const rawSeed = route.query.seed
const seed = rawSeed != null && rawSeed !== '' ? Number(rawSeed) : undefined
const rawMilestone = String(route.query.milestone ?? '').toLowerCase()
const initialOwned = route.query.owned === '1'

const ownedMode = ref(initialOwned)
const milestone = ref<Milestone>(initialOwned ? '' : (['set', 'country', 'feat'].includes(rawMilestone) ? (rawMilestone as Milestone) : ''))
const currentId = ref(String(route.query.id ?? '') || simulateScan(Number.isFinite(seed) ? seed : isParity() ? 0 : undefined))

const coin = computed(() => getCoin(currentId.value) ?? getCoin(simulateScan(0))!)
const reveal = computed(() => getReveal(coin.value.eurioId)!)
const ms = computed(() => (milestone.value ? MILESTONE[milestone.value] : null))

// ── Contenu (avec surcharges jalon) ──
const name = computed(() => coin.value.theme || coin.value.designDescription || coin.value.countryName)
const total = computed(() => reveal.value.completionTotal)
const ownedN = computed(() => (milestone.value === 'set' ? total.value : reveal.value.completionOwned))
const accent = computed(() => {
  if (milestone.value === 'set') return 'Série complète 🎉'
  if (milestone.value === 'country') return '🗺️ Pays complété'
  if (milestone.value === 'feat') return '★ Légendaire · 2% la détiennent'
  return reveal.value.accent
})

// ── État UI réactif ──
const phase = ref<Phase>('idle')
const state = ref<'peek' | 'expanded'>('peek')
const rotated = ref(false)
const added = ref(false)
const toastText = ref('')
const toastVisible = ref(false)
const toastActionLabel = ref('')
let toastActionFn: (() => void) | null = null
let toastTimer: ReturnType<typeof setTimeout> | null = null
function toast(t: string, action?: string, fn?: () => void) {
  toastText.value = t
  toastActionLabel.value = action ?? ''
  toastActionFn = fn ?? null
  toastVisible.value = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toastVisible.value = false), action ? 4500 : 2400)
}
function onToastAction() {
  const fn = toastActionFn
  toastVisible.value = false
  if (toastTimer) clearTimeout(toastTimer)
  fn?.()
}

// ── Refs DOM ──
const rootRef = ref<HTMLElement | null>(null)
const heroBandRef = ref<HTMLElement | null>(null)
const canvasWrapRef = ref<HTMLElement | null>(null)
const flashRef = ref<HTMLElement | null>(null)
const haloRef = ref<HTMLElement | null>(null)
const sheetRef = ref<HTMLElement | null>(null)
const handleRef = ref<HTMLElement | null>(null)
const sheetHeroRef = ref<HTMLElement | null>(null)
const summaryRef = ref<HTMLElement | null>(null)
const ctaRef = ref<HTMLElement | null>(null)
const celConfettiRef = ref<HTMLElement | null>(null)

// Le 3D (un seul objet, continu) migre du bandeau haut vers le header du sheet
// quand on déploie la fiche, et revient au bandeau quand on referme. createStage
// observe canvasWrap (ResizeObserver) → recadre renderer + caméra automatiquement.
watch(state, (s) => {
  const wrap = canvasWrapRef.value
  const dest = s === 'expanded' ? sheetHeroRef.value : heroBandRef.value
  if (wrap && dest && wrap.parentElement !== dest) dest.appendChild(wrap)
})

let stage: Stage | null = null
let coin3d: Coin3D | null = null
let audioCtx: AudioContext | null = null
let cleanupFns: (() => void)[] = []
let idleTimer: ReturnType<typeof setTimeout> | null = null

// Hooks impératifs câblés dans onMounted (pilotage de la chorégraphie / debug).
let startIdentifyRef: (() => void) | null = null

// ── Ajout au coffre (décision #3 : auto-add + undo) ──
function addToVault(withUndo: boolean) {
  store.addCoin(coin.value.eurioId, { valueAtAddCents: Math.round(reveal.value.grades.ttb * 100) })
  added.value = true
  const msg = ms.value ? ms.value.toast : 'Ajoutée au coffre'
  if (withUndo) toast(msg, 'Annuler', removeFromVault)
  else toast(`${msg} ✓`)
}
function removeFromVault() {
  store.removeCoin(coin.value.eurioId)
  added.value = false
  toast('Retirée du coffre')
}
// CTA état-aware : doublon → voir au coffre ; ajoutée → retirer (annulation tardive) ;
// jalon pays → gratter la carte ; sinon ajouter manuellement (si on a annulé).
const cta = computed<{ label: string; ghost: boolean; action: () => void }>(() => {
  if (ownedMode.value) return { label: 'Voir au coffre', ghost: false, action: () => router.push('/vault') }
  if (added.value && milestone.value === 'country') return { label: 'Gratter la carte 🪙', ghost: false, action: () => router.push('/vault/catalog?scratch=1') }
  if (added.value) return { label: 'Retirer du coffre', ghost: true, action: removeFromVault }
  return { label: 'Ajouter au coffre', ghost: false, action: () => addToVault(true) }
})
function onCta() {
  cta.value.action()
}
function forceMatch() {
  if (phase.value === 'idle') startIdentifyRef?.()
}

// ── 3D + chorégraphie + sheet (impératif) ──
onMounted(async () => {
  const root = rootRef.value
  const wrap = canvasWrapRef.value
  const sheet = sheetRef.value
  const handle = handleRef.value
  if (!root || !wrap || !sheet || !handle) return

  // Marqueur capture parité : scène 3D → attendre __eurioCoinReady.
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
  let omega = 0
  let dragging = false
  let locked = false // pièce figée face avant (recentrée par l'utilisateur)
  const setScale = (m: number) => group?.scale.setScalar(m)
  const easeOut = (t: number) => 1 - Math.pow(1 - t, 3)

  // ── Tweens (chorégraphie d'identification) ──
  interface Tween { t: number; from: number; to: number; dur: number; ease?: (p: number) => number; onUpdate?: (v: number, p: number) => void; onDone?: () => void }
  const tweens: Tween[] = []
  const addTween = (o: Partial<Tween> & { dur: number }) => tweens.push({ t: 0, from: 0, to: 1, ...o })
  const clearTweens = () => (tweens.length = 0)
  function advanceTweens(dt: number) {
    for (let i = tweens.length - 1; i >= 0; i--) {
      const tw = tweens[i]
      tw.t += dt
      const p = tw.dur > 0 ? Math.min(tw.t / tw.dur, 1) : 1
      const e = tw.ease ? tw.ease(p) : p
      tw.onUpdate?.(tw.from + (tw.to - tw.from) * e, p)
      if (p >= 1) {
        tweens.splice(i, 1)
        tw.onDone?.()
      }
    }
  }

  st.onFrame((dt) => {
    frameCoin()
    if (isParity()) return // pose figée : aucune animation temporelle
    advanceTweens(dt)
    if (!group) return
    if (phase.value === 'spin' && !dragging) {
      group.rotation.y += omega * dt
      omega *= Math.exp(-SPIN_DAMP * dt)
      if (Math.abs(omega) < SETTLE_OMEGA) enterSettle()
    } else if (phase.value === 'revealed' && !dragging && !locked) {
      group.rotation.y += omega * dt
      omega += (IDLE_SPD - omega) * Math.min(1, dt * 2.5)
      group.rotation.x += (0 - group.rotation.x) * Math.min(1, dt * 4)
    }
  })
  st.start()

  // ── Chorégraphie d'identification (morph → spin → settle → revealed) ──
  function startIdentify() {
    if (phase.value !== 'idle' || !group) return
    if (idleTimer) { clearTimeout(idleTimer); idleTimer = null }
    // Journalise le scan (E8) — à chaque identification, y compris après un re-scan.
    if (!ownedMode.value) store.logScan(coin.value.eurioId)
    clearTweens()
    omega = 0
    locked = false
    group.rotation.set(0, 0, 0)
    setScale(0.18)
    phase.value = 'morph'
    addTween({
      dur: light ? MORPH_DUR_LIGHT : MORPH_DUR,
      ease: easeOut,
      onUpdate: (v) => setScale(0.18 + 0.82 * v),
      onDone: () => {
        setScale(1)
        if (light) settleStop()
        else {
          phase.value = 'spin'
          omega = AUTO_IMPULSE
        }
      },
    })
  }
  function enterSettle() {
    if (phase.value === 'settle' || !group) return
    phase.value = 'settle'
    const start = group.rotation.y
    const target = Math.round(start / (Math.PI * 2)) * (Math.PI * 2)
    addTween({ dur: SNAP_DUR, from: start, to: target, ease: easeOut, onUpdate: (v) => group && (group.rotation.y = v), onDone: settleStop })
  }
  function settleStop() {
    omega = 0
    setScale(1)
    addTween({ dur: POP_DUR, onUpdate: (_v, p) => setScale(1 + 0.07 * Math.sin(Math.PI * p)), onDone: () => setScale(1) })
    fireSettleFX()
    enterRevealed()
  }
  function forceSettle() {
    if (phase.value === 'settle' || phase.value === 'revealed' || phase.value === 'idle' || phase.value === 'morph') return
    clearTweens()
    omega = 0
    setScale(1)
    enterSettle()
  }
  function enterRevealed() {
    phase.value = 'revealed'
    omega = IDLE_SPD
    relayout()
    // Célébration jalon (overlay, jamais un 2e écran) — déclenchée à l'instant de l'ID.
    const cel = ms.value
    if (cel) {
      setTimeout(() => {
        haptic([0, 35, 30, 80])
        chime(cel.chime)
        if (celConfettiRef.value) confetti(celConfettiRef.value, { count: cel.confetti })
      }, 350)
    }
    if (ownedMode.value) {
      added.value = true // déjà au coffre (re-visualisation)
      toast("Tu l'as déjà — le scan continue")
    } else if (store.hasCoin(coin.value.eurioId)) {
      added.value = true // déjà possédée : pas de doublon, pas de toast
    } else {
      // Auto-add + undo : identifier ajoute par défaut ; le undo couvre le faux positif.
      addToVault(true)
    }
  }
  startIdentifyRef = startIdentify

  function burst(el: HTMLElement | null) {
    if (!el) return
    el.classList.remove('is-burst')
    void el.offsetWidth
    el.classList.add('is-burst')
  }
  function fireSettleFX() {
    burst(flashRef.value)
    burst(haloRef.value)
    try { navigator.vibrate?.([0, 45, 35, 120]) } catch { /* unsupported */ }
    playClink()
  }
  function playClink() {
    if (reduced) return
    try {
      const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      audioCtx = audioCtx ?? new Ctor()
      if (audioCtx.state === 'suspended') void audioCtx.resume()
      const now = audioCtx.currentTime
      const master = audioCtx.createGain()
      master.gain.value = 0.16
      master.connect(audioCtx.destination)
      ;[2280, 3160].forEach((freq, i) => {
        const osc = audioCtx!.createOscillator()
        osc.type = i === 0 ? 'triangle' : 'sine'
        osc.frequency.value = freq
        const g = audioCtx!.createGain()
        g.gain.setValueAtTime(0.0001, now)
        g.gain.exponentialRampToValueAtTime(i === 0 ? 1 : 0.5, now + 0.006)
        g.gain.exponentialRampToValueAtTime(0.0001, now + (i === 0 ? 0.22 : 0.14))
        osc.connect(g)
        g.connect(master)
        osc.start(now)
        osc.stop(now + 0.26)
      })
    } catch { /* audio bloqué */ }
  }

  // ── Pointer sur la pièce : skip pendant l'identification, drag une fois révélée ──
  let hdown: { lastX: number; lastY: number; lastT: number; vel: number; moved: number } | null = null
  const heroDown = (ev: PointerEvent) => {
    if (!group || phase.value === 'idle' || phase.value === 'morph') return
    wrap!.querySelector('canvas')?.setPointerCapture?.(ev.pointerId)
    dragging = true
    hdown = { lastX: ev.clientX, lastY: ev.clientY, lastT: performance.now(), vel: 0, moved: 0 }
    if (phase.value === 'revealed') rotated.value = true
    if (audioCtx?.state === 'suspended') void audioCtx.resume()
  }
  const heroMove = (ev: PointerEvent) => {
    if (!hdown || !group) return
    const dx = ev.clientX - hdown.lastX
    const dy = ev.clientY - hdown.lastY
    const dt = Math.max((performance.now() - hdown.lastT) / 1000, 1 / 240)
    hdown.moved += Math.abs(dx) + Math.abs(dy)
    group.rotation.y += dx * DRAG_K
    if (phase.value === 'revealed') {
      group.rotation.x = Math.max(-TILT_MAX, Math.min(TILT_MAX, group.rotation.x + dy * TILT_K))
    }
    hdown.vel = hdown.vel * 0.7 + ((dx * DRAG_K) / dt) * 0.3
    hdown.lastX = ev.clientX
    hdown.lastY = ev.clientY
    hdown.lastT = performance.now()
  }
  const heroUp = () => {
    if (!hdown) return
    dragging = false
    if (!group) { hdown = null; return }
    const wasTap = hdown.moved < TAP_PX
    if (phase.value === 'spin' || phase.value === 'settle') {
      // Tap = fige immédiatement + anim de fin (T3) ; flick = relance le spin.
      if (wasTap) forceSettle()
      else {
        omega = Math.max(-FLICK_MAX, Math.min(FLICK_MAX, hdown.vel))
        if (Math.abs(omega) > SETTLE_OMEGA) phase.value = 'spin'
        else enterSettle()
      }
    } else if (phase.value === 'revealed') {
      // Recentrage : si on relâche la pièce ~face avant (à plat) sans élan, elle
      // se fige là (lock). Sinon on relance la rotation libre (IDLE reprend).
      const v = hdown.vel || 0
      const HALF = Math.PI // 0 = avers à plat, π = revers à plat → les deux « centrés »
      const nearest = Math.round(group.rotation.y / HALF) * HALF
      const dyaw = Math.abs(group.rotation.y - nearest)
      const LOCK_MARGIN = 0.5 // ~28°
      if (Math.abs(v) < 2.5 && dyaw < LOCK_MARGIN && Math.abs(group.rotation.x) < LOCK_MARGIN) {
        locked = true
        omega = 0
        const y0 = group.rotation.y
        const x0 = group.rotation.x
        addTween({
          dur: SNAP_DUR,
          ease: easeOut,
          onUpdate: (val) => {
            if (!group) return
            group.rotation.y = y0 + (nearest - y0) * val
            group.rotation.x = x0 * (1 - val)
          },
        })
      } else {
        locked = false
        omega = Math.max(-12, Math.min(12, v || IDLE_SPD))
      }
    }
    hdown = null
  }
  wrap.addEventListener('pointerdown', heroDown)
  wrap.addEventListener('pointermove', heroMove)
  wrap.addEventListener('pointerup', heroUp)
  wrap.addEventListener('pointercancel', heroUp)

  // ── Bottom sheet (peek / expanded) ──
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
    const sumH = summaryRef.value?.offsetHeight || 140
    const ctaH = ctaRef.value?.offsetHeight || 52
    peekH = handleH + sumH + ctaH + NAV_PAD + 16
    peekH = Math.max(Math.round(rootH * 0.26), Math.min(peekH, Math.round(rootH * 0.44)))
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
    if (phase.value !== 'revealed') return
    handle!.setPointerCapture?.(ev.pointerId)
    sdown = { startY: ev.clientY, base: curHeight(), moved: 0 }
    sheet!.style.transition = 'none'
  }
  const onHandleMove = (ev: PointerEvent) => {
    if (!sdown) return
    const dy = sdown.startY - ev.clientY
    sdown.moved += Math.abs(dy)
    // On autorise un débord SOUS le peek (zone de dismiss → retour au scan).
    sheet!.style.height = `${Math.max(peekH - 150, Math.min(expandedH, sdown.base + dy))}px`
  }
  const endHandle = () => {
    if (!sdown) return
    sheet!.style.transition = ''
    const h = curHeight()
    // Depuis le peek, tirer franchement vers le bas → on repart en scan (re-scan).
    if (state.value !== 'expanded' && h < peekH - 60) {
      sdown = null
      void resetScan()
      return
    }
    if (sdown.moved < 6) setSheet(state.value === 'expanded' ? 'peek' : 'expanded')
    else setSheet(h > (peekH + expandedH) / 2 ? 'expanded' : 'peek')
    sdown = null
  }
  handle.addEventListener('pointerdown', onHandleDown)
  handle.addEventListener('pointermove', onHandleMove)
  handle.addEventListener('pointerup', endHandle)
  handle.addEventListener('pointercancel', endHandle)

  // ── Construction / re-construction du modèle 3D (un seul objet vivant) ──
  function armIdle() {
    if (idleTimer) clearTimeout(idleTimer)
    idleTimer = setTimeout(startIdentify, AUTO_MATCH_DELAY_MS)
  }
  async function loadCoinModel(): Promise<boolean> {
    const assets = getCoin3DAssets(coin.value.eurioId)
    if (!assets) return false
    try {
      const edgeTex = buildProceduralEdgeTexture()
      const built = await buildCoinFromUrls({ obverse: assets.obverse, reverse: assets.reverse }, { edgeTex })
      if (!stage) { disposeCoin(built); return false }
      if (coin3d) { st.scene.remove(coin3d.group); disposeCoin(coin3d) }
      coin3d = built
      group = built.group
      group.scale.setScalar(0.0001) // invisible pendant l'idle
      st.scene.add(group)
      return true
    } catch (err) {
      console.error('[scan-reveal] build failed', err)
      return false
    }
  }
  // Swipe-down sous le peek → on repart en scan avec une NOUVELLE pièce (flux continu).
  async function resetScan() {
    currentId.value = simulateScan(undefined)
    milestone.value = ''
    ownedMode.value = false
    added.value = false
    rotated.value = false
    locked = false
    state.value = 'peek'
    phase.value = 'idle'
    applyHeight(false)
    await loadCoinModel()
    relayout()
    armIdle()
  }

  // ── Boot ──
  if (!(await loadCoinModel())) return
  if (isParity()) {
    // Capture parité : saut direct à l'état révélé (ni chorégraphie ni FX).
    group!.rotation.set(PARITY_COIN_POSE.x, PARITY_COIN_POSE.y, PARITY_COIN_POSE.z)
    group!.scale.setScalar(1)
    phase.value = 'revealed'
    relayout()
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        ;(window as Window & { __eurioCoinReady?: boolean }).__eurioCoinReady = true
      }),
    )
  } else {
    // Auto-match (faux-scan) : l'identification démarre toute seule après le délai.
    armIdle()
  }
})

onBeforeUnmount(() => {
  if (idleTimer) clearTimeout(idleTimer)
  cleanupFns.forEach((fn) => fn())
  cleanupFns = []
  try { audioCtx?.close() } catch { /* déjà fermé */ }
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
  <section
    ref="rootRef"
    class="reveal-root scan-reveal-root"
    data-scene="scan-reveal"
    :data-phase="phase"
    :data-state="state"
    :data-owned="ownedMode ? '1' : '0'"
    :data-rotated="rotated ? '1' : '0'"
    :data-milestone="milestone || undefined"
  >
    <!-- Hero 3D (bande haute, continu sur toutes les phases) -->
    <div ref="heroBandRef" class="reveal-hero">
      <div class="reveal-cel__rays" aria-hidden="true"></div>
      <div ref="canvasWrapRef" class="reveal-hero__canvas"></div>
      <div ref="flashRef" class="scan-reveal-flash" aria-hidden="true"></div>
      <div ref="haloRef" class="scan-reveal-halo" aria-hidden="true"></div>

      <!-- Phase idle : guide caméra (ex ScanIdle) -->
      <div class="scan-reveal-idle" aria-hidden="true">
        <div class="scan-reveal-idle__corner scan-reveal-idle__corner--tl"></div>
        <div class="scan-reveal-idle__corner scan-reveal-idle__corner--tr"></div>
        <div class="scan-reveal-idle__corner scan-reveal-idle__corner--bl"></div>
        <div class="scan-reveal-idle__corner scan-reveal-idle__corner--br"></div>
      </div>

      <!-- Statut : "Identification…" pendant la chorégraphie (la pièce révélée se suffit). -->
      <div class="scan-reveal-status scan-reveal-status--id">Identification…</div>
    </div>

    <!-- Header idle (sobre, hors hero pour rester centré) -->
    <div class="scan-reveal-idlehead">
      <div class="eyebrow eyebrow--paper">Scan · Eurio</div>
      <div class="scan-reveal-idlehead__title">Approche une pièce</div>
    </div>
    <div class="scan-reveal-idlehint">
      <span class="scan-reveal-idlehint__dot" aria-hidden="true"></span>
      <span>En attente — centre la pièce dans le cadre</span>
    </div>

    <!-- Titre remonté, collé sous la pièce (wireframe A) -->
    <div class="scan-reveal-title">
      <div class="scan-reveal-title__main">{{ coin.countryName }} · {{ coin.year ?? '—' }}</div>
      <div class="scan-reveal-title__sub">{{ name }}</div>
    </div>

    <!-- Célébration overlay (jalon) — superposée, jamais un 2e écran -->
    <div class="reveal-cel" aria-hidden="true">
      <div ref="celConfettiRef" class="cel-confetti"></div>
      <div class="reveal-cel__bannerwrap"><span class="reveal-cel__banner">{{ ms?.label ?? 'Série complète' }}</span></div>
    </div>

    <!-- Bottom sheet (2 crans) — c'est la fiche qui remonte -->
    <aside ref="sheetRef" class="reveal-sheet" aria-label="Détails de la pièce">
      <button ref="handleRef" type="button" class="reveal-sheet__handle" aria-label="Déployer les détails">
        <span class="reveal-sheet__grip" aria-hidden="true"></span>
      </button>

      <div class="reveal-sheet__scroll">
        <!-- En-tête de fiche (visible une fois déployé : le titre est sous la pièce en peek) -->
        <div class="scan-reveal-sheethead">
          <div class="scan-reveal-sheethead__main">{{ coin.countryName }} · {{ coin.year ?? '—' }}</div>
          <div class="scan-reveal-sheethead__sub">{{ name }}</div>
        </div>
        <!-- Header 3D : le canvas y migre quand on déploie (un seul objet 3D) -->
        <div ref="sheetHeroRef" class="scan-reveal-sheethero"></div>

        <div ref="summaryRef" class="reveal-sum">
          <span class="reveal-sum__eyebrow">{{ ownedMode ? 'Doublon' : 'Nouvelle pièce' }}</span>
          <div class="reveal-sum__value">
            <span class="reveal-sum__value-num">≈ {{ reveal.grades.ttb }} €</span>
            <span class="reveal-sum__value-tier">{{ reveal.tier }}</span>
          </div>
          <div class="reveal-drives">
            <span class="reveal-drive reveal-drive--new">{{ ownedMode ? 'Déjà' : 'Nouvelle' }}</span>
            <span class="reveal-drive">{{ coin.countryName }} · {{ ownedN }}/{{ total }}</span>
            <span class="reveal-drive reveal-drive--accent">{{ accent }}</span>
          </div>
        </div>

        <!-- La fiche complète (= source de vérité partagée avec /coin/:id) -->
        <CoinDetailBody :coin="coin" ctx="scan" :show-hero="false" @toast="toast" />
      </div>

      <div ref="ctaRef" class="reveal-cta">
        <button type="button" class="btn" :class="cta.ghost ? 'btn-ghost btn-ghost--on-dark' : 'btn-gold'" data-testid="reveal-cta" @click="onCta">{{ cta.label }}</button>
      </div>
    </aside>

    <!-- Debug : forcer un match sans attendre l'auto-match -->
    <button v-if="store.debugMode" type="button" class="scan-reveal-debug btn btn-ghost btn-ghost--on-dark" data-testid="force-match" @click="forceMatch">
      <span class="u-mono">FORCER UN MATCH</span>
    </button>

    <div class="toast toast--on-dark" :class="{ 'toast--action': !!toastActionLabel }" :data-visible="toastVisible ? 'true' : 'false'" role="status">
      <span>{{ toastText }}</span>
      <button v-if="toastActionLabel" type="button" class="toast__action" data-testid="toast-undo" @click="onToastAction">{{ toastActionLabel }}</button>
    </div>
  </section>
</template>

<style src="../../styles/reveal-stratifie.css"></style>
<style src="../../styles/scan-reveal.css"></style>
