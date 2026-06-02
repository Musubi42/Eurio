<script setup lang="ts">
/* Scène scan-transition-3d — transition diégétique caméra→3D : morph → flick-spin
 * → settle (le pic : flash + halo + haptique + clink) → posed. Port de
 * scan-transition-3d.html/.js. */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getCoin, getCoin3DAssets, simulateScan } from '@/api'
import { buildCoinFromUrls, buildProceduralEdgeTexture, createStage, disposeCoin, R_OUT } from '@/lib/coin3d'
import type { Coin as Coin3D, Stage } from '@/lib/coin3d'

const route = useRoute()
const router = useRouter()

const MORPH_DUR = 0.24
const MORPH_DUR_LIGHT = 0.14
const AUTO_IMPULSE = 18
const SPIN_DAMP = 3.4
const SETTLE_OMEGA = 2.2
const SNAP_DUR = 0.32
const POP_DUR = 0.24
const DRAG_K = 0.011
const FLICK_MAX = 30
const TAP_PX = 7
const HERO_FILL = 0.72

const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
const light = route.query.light === '1' || reduced

const eurioId = String(route.query.id ?? '') || simulateScan()
const coin = getCoin(eurioId) ?? getCoin(simulateScan(0))!

const phase = ref<'loading' | 'morph' | 'spin' | 'settle' | 'posed'>('loading')
const title = ref('Identification…')
const statusHidden = ref(false)

const rootRef = ref<HTMLElement | null>(null)
const canvasWrapRef = ref<HTMLElement | null>(null)
const flashRef = ref<HTMLElement | null>(null)
const haloRef = ref<HTMLElement | null>(null)

let stage: Stage | null = null
let coin3d: Coin3D | null = null
let audioCtx: AudioContext | null = null

function onClick(e: MouseEvent) {
  const a = (e.target as HTMLElement).closest('[data-action]')?.getAttribute('data-action')
  if (a === 'skip') forceSettleRef?.()
  else if (a === 'replay') playRef?.()
  else if (a === 'continue') router.push(`/scan/reveal?id=${encodeURIComponent(coin.eurioId)}`)
}

let forceSettleRef: (() => void) | null = null
let playRef: (() => void) | null = null

onMounted(async () => {
  const wrap = canvasWrapRef.value
  if (!wrap) return

  stage = createStage(wrap)
  const st = stage
  function frameCoin() {
    const w = wrap!.clientWidth || 1
    const h = wrap!.clientHeight || 1
    const tanHalfV = Math.tan((35 * Math.PI) / 180 / 2)
    const halfNeeded = R_OUT / HERO_FILL
    const dist = Math.max(halfNeeded / tanHalfV, halfNeeded / (tanHalfV * (w / h)))
    st.camera.position.set(0, dist * 0.06, dist)
    st.camera.lookAt(0, 0, 0)
  }
  frameCoin()

  let group: import('three').Group | null = null
  let omega = 0
  let idleT = 0
  const setScale = (m: number) => group?.scale.setScalar(m)
  const easeOut = (t: number) => 1 - Math.pow(1 - t, 3)

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

  let dragging = false
  st.onFrame((dt) => {
    frameCoin()
    advanceTweens(dt)
    if (!group) return
    if (phase.value === 'spin' && !dragging) {
      group.rotation.y += omega * dt
      omega *= Math.exp(-SPIN_DAMP * dt)
      if (Math.abs(omega) < SETTLE_OMEGA) enterSettle()
    } else if (phase.value === 'posed') {
      idleT += dt
      group.position.y = Math.sin(idleT * 1.1) * 0.25
      if (!dragging && Math.abs(omega) > 0.002) {
        group.rotation.y += omega * dt
        omega *= Math.exp(-SPIN_DAMP * dt)
      }
    }
  })
  st.start()

  function play() {
    if (!group) return
    clearTweens()
    omega = 0
    group.rotation.set(0, 0, 0)
    group.position.set(0, 0, 0)
    setScale(0.18)
    title.value = 'Identification…'
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
    title.value = 'Identifiée'
    phase.value = 'posed'
    idleT = 0
  }
  function forceSettle() {
    if (phase.value === 'settle' || phase.value === 'posed' || phase.value === 'loading') return
    clearTweens()
    omega = 0
    setScale(1)
    enterSettle()
  }
  playRef = play
  forceSettleRef = forceSettle

  function burst(el: HTMLElement | null) {
    if (!el) return
    el.classList.remove('is-burst')
    void el.offsetWidth
    el.classList.add('is-burst')
  }
  function fireSettleFX() {
    burst(flashRef.value)
    burst(haloRef.value)
    try {
      navigator.vibrate?.([0, 45, 35, 120])
    } catch {
      /* unsupported */
    }
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
    } catch {
      /* audio bloqué */
    }
  }

  // Pointer flick / drag / tap
  let down: { moved: number; lastX: number; lastT: number; vel: number } | null = null
  const onDown = (ev: PointerEvent) => {
    if (phase.value === 'loading') return
    st.renderer.domElement.setPointerCapture?.(ev.pointerId)
    dragging = true
    down = { moved: 0, lastX: ev.clientX, lastT: performance.now(), vel: 0 }
    if (audioCtx?.state === 'suspended') void audioCtx.resume()
  }
  const onMove = (ev: PointerEvent) => {
    if (!down || !group) return
    const dx = ev.clientX - down.lastX
    const dt = Math.max((performance.now() - down.lastT) / 1000, 1 / 240)
    down.moved += Math.abs(dx)
    if (phase.value === 'spin' || phase.value === 'posed' || phase.value === 'settle') {
      group.rotation.y += dx * DRAG_K
      down.vel = down.vel * 0.7 + ((dx * DRAG_K) / dt) * 0.3
    }
    down.lastX = ev.clientX
    down.lastT = performance.now()
  }
  const onUp = () => {
    if (!down) return
    const wasTap = down.moved < TAP_PX
    dragging = false
    if (wasTap) forceSettle()
    else {
      omega = Math.max(-FLICK_MAX, Math.min(FLICK_MAX, down.vel))
      if (Math.abs(omega) > SETTLE_OMEGA) phase.value = 'spin'
      else enterSettle()
    }
    down = null
  }
  wrap.addEventListener('pointerdown', onDown)
  wrap.addEventListener('pointermove', onMove)
  wrap.addEventListener('pointerup', onUp)
  wrap.addEventListener('pointercancel', onUp)

  // Boot
  const assets = getCoin3DAssets(coin.eurioId)
  if (!assets) return
  try {
    const edgeTex = buildProceduralEdgeTexture()
    coin3d = await buildCoinFromUrls({ obverse: assets.obverse, reverse: assets.reverse }, { edgeTex })
    // Quitté pendant le chargement async → la stage est disposée : abandonner.
    if (!stage) {
      disposeCoin(coin3d)
      coin3d = null
      return
    }
    group = coin3d.group
    st.scene.add(group)
    statusHidden.value = true
    play()
  } catch (err) {
    console.error('[scan-transition-3d] init failed', err)
  }
})

onBeforeUnmount(() => {
  try {
    audioCtx?.close()
  } catch {
    /* déjà fermé */
  }
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
  <section ref="rootRef" class="scan-tx-root" data-scene="scan-transition-3d" :data-phase="phase" @click="onClick">
    <svg class="scan-tx-grain" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
      <filter id="scan-tx-turb"><feTurbulence type="fractalNoise" baseFrequency="1.4" numOctaves="2" seed="7" /><feColorMatrix type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.5 0" /></filter>
      <rect width="100%" height="100%" filter="url(#scan-tx-turb)" />
    </svg>

    <div ref="canvasWrapRef" class="scan-tx-canvas"></div>

    <div class="scan-tx-ghost" aria-hidden="true">
      <div class="scan-tx-ghost__ring"></div>
      <div class="scan-tx-ghost__corner scan-tx-ghost__corner--tl"></div>
      <div class="scan-tx-ghost__corner scan-tx-ghost__corner--tr"></div>
      <div class="scan-tx-ghost__corner scan-tx-ghost__corner--bl"></div>
      <div class="scan-tx-ghost__corner scan-tx-ghost__corner--br"></div>
    </div>

    <div ref="flashRef" class="scan-tx-flash" aria-hidden="true"></div>
    <div ref="haloRef" class="scan-tx-halo" aria-hidden="true"></div>

    <div class="scan-tx-header">
      <div class="eyebrow eyebrow--paper">Match · verrouillé</div>
      <div class="scan-tx-header__title">{{ title }}</div>
    </div>

    <button type="button" class="scan-tx-skip" data-action="skip">Passer</button>

    <div class="scan-tx-status" :class="{ 'is-hidden': statusHidden }">Chargement…</div>

    <div class="scan-tx-hint">
      <span class="scan-tx-hint__spark" aria-hidden="true"></span>
      <span>Lance la pièce d'un geste — ou tape pour poser</span>
    </div>

    <div class="scan-tx-done">
      <div class="scan-tx-done__country"><span>{{ coin.countryName }}</span><span>·</span><span>{{ coin.year ?? '—' }}</span></div>
      <div class="scan-tx-done__title">{{ coin.theme || coin.designDescription || coin.countryName }}</div>
      <div class="scan-tx-done__actions">
        <button type="button" class="btn btn-ghost btn-ghost--on-dark" data-action="replay">Rejouer</button>
        <button type="button" class="btn btn-gold" data-action="continue">Continuer</button>
      </div>
    </div>
  </section>
</template>

<style src="../../styles/scan-transition.css"></style>
