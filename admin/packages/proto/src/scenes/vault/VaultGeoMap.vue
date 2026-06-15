<script setup lang="ts">
/* Scène « Répartition géographique » — carte eurozone plein écran (SVG stylisé)
 * avec une épingle drapeau + compteur par pays possédé, et une feuille basse
 * REDIMENSIONNABLE qui liste les PIÈCES (pas les pays — divergence assumée vs
 * CoinSnap). Atteinte via « Tout voir » du Résumé. Coexiste avec la carte à
 * gratter (catalogue/complétion), accessible depuis la back-bar. */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getCoin, getCountryProgress, getMarket } from '@/api'
import type { Coin } from '@/api'
import { useCollectionStore } from '@/stores/collection'
import CoinImage from '@/components/CoinImage.vue'
import { CONTEXT, GEO } from './eurozone-geo'
import '@/styles/vault-geo.css'

const router = useRouter()
const store = useCollectionStore()

const VBW = 400
const VBH = 511

function flagFromIso(iso: string): string {
  if (iso.length !== 2) return '🏳️'
  const base = 0x1f1e6
  return String.fromCodePoint(base + (iso.charCodeAt(0) - 65), base + (iso.charCodeAt(1) - 65))
}

// Centroïde approximatif d'un path (moyenne des sommets) — GEO ne stocke que `d`.
const centroidCache = new Map<string, { x: number; y: number }>()
function centroidOf(iso: string): { x: number; y: number } | null {
  if (centroidCache.has(iso)) return centroidCache.get(iso)!
  const d = GEO[iso]?.d
  if (!d) return null
  const nums = d.match(/-?\d+\.?\d*/g)?.map(Number) ?? []
  let sx = 0, sy = 0, n = 0
  for (let i = 0; i + 1 < nums.length; i += 2) {
    sx += nums[i]
    sy += nums[i + 1]
    n++
  }
  const c = n ? { x: sx / n, y: sy / n } : null
  if (c) centroidCache.set(iso, c)
  return c
}
// Micro-états absents de GEO : ancrés sur le pays hôte + petit décalage (viewBox).
const MICRO_ANCHOR: Record<string, { host: string; dx: number; dy: number }> = {
  MC: { host: 'FR', dx: 34, dy: 48 },
  AD: { host: 'FR', dx: -18, dy: 64 },
  SM: { host: 'IT', dx: -6, dy: -10 },
  VA: { host: 'IT', dx: -12, dy: 10 },
}
function anchorOf(iso: string): { x: number; y: number } | null {
  const direct = centroidOf(iso)
  if (direct) return direct
  const m = MICRO_ANCHOR[iso]
  if (!m) return null
  const host = centroidOf(m.host)
  return host ? { x: host.x + m.dx, y: host.y + m.dy } : null
}

// ── Agrégat par pays (dérivé du store) ──
interface OwnedItem {
  coin: Coin
  count: number
  valueEur: number
}
interface CountryAgg {
  iso: string
  name: string
  flag: string
  items: OwnedItem[]
  total: number
}
const byCountry = computed<Map<string, CountryAgg>>(() => {
  const prog = new Map(getCountryProgress().map((c) => [c.iso, c]))
  const acc = new Map<string, CountryAgg>()
  for (const e of store.collection) {
    const coin = getCoin(e.eurioId)
    if (!coin) continue
    const iso = coin.country.toUpperCase()
    let c = acc.get(iso)
    if (!c) {
      const p = prog.get(iso)
      c = { iso, name: p?.name ?? coin.countryName, flag: p?.flag ?? flagFromIso(iso), items: [], total: 0 }
      acc.set(iso, c)
    }
    c.total += 1
    const existing = c.items.find((it) => it.coin.eurioId === coin.eurioId)
    if (existing) existing.count += 1
    else c.items.push({ coin, count: 1, valueEur: getMarket(coin.eurioId)?.p50 ?? coin.faceValue })
  }
  return acc
})

const ownedIso = computed(() => new Set(byCountry.value.keys()))
const summary = computed(() => {
  let coins = 0
  for (const c of byCountry.value.values()) coins += c.total
  return { coins, countries: byCountry.value.size }
})

// Géométrie
const contextPaths = Object.values(CONTEXT)
const geoPaths = computed(() =>
  Object.keys(GEO).map((iso) => ({ iso, d: GEO[iso].d, owned: ownedIso.value.has(iso) })),
)
interface Pin {
  iso: string
  flag: string
  count: number
  left: string
  top: string
}
const pins = computed<Pin[]>(() => {
  const out: Pin[] = []
  for (const c of byCountry.value.values()) {
    const a = anchorOf(c.iso)
    if (!a) continue
    out.push({
      iso: c.iso,
      flag: c.flag,
      count: c.total,
      left: `${(a.x / VBW) * 100}%`,
      top: `${(a.y / VBH) * 100}%`,
    })
  }
  return out
})

// ── Sélection + feuille ──
const selectedIso = ref<string | null>(null)
function togglePin(iso: string) {
  selectedIso.value = selectedIso.value === iso ? null : iso
}
const selectedCountry = computed(() => (selectedIso.value ? byCountry.value.get(selectedIso.value) ?? null : null))

interface CoinRow {
  coin: Coin
  count: number
  valueEur: number
  countryName: string
}
const coinRows = computed<CoinRow[]>(() => {
  const aggs = selectedCountry.value ? [selectedCountry.value] : [...byCountry.value.values()]
  const rows: CoinRow[] = []
  for (const c of aggs) {
    for (const it of c.items) rows.push({ coin: it.coin, count: it.count, valueEur: it.valueEur, countryName: c.name })
  }
  return rows.sort((a, z) => z.valueEur - a.valueEur)
})

function formatValue(eur: number): string {
  return Number.isInteger(eur) ? `${eur} €` : `${eur.toFixed(2).replace('.', ',')} €`
}
function faceLabel(coin: Coin): string {
  const cents = coin.faceValueCents
  if (cents >= 100) {
    const eur = cents / 100
    return Number.isInteger(eur) ? `${eur} €` : `${eur.toFixed(2).replace('.', ',')} €`
  }
  return `${cents} c`
}
function openCoin(coin: Coin) {
  router.push(`/coin/${encodeURIComponent(coin.eurioId)}?ctx=owned`)
}

// ── Feuille redimensionnable ──
const rootRef = ref<HTMLElement | null>(null)
const sheetPct = ref(0.32) // hauteur initiale ≈ 30 %
let dragStartY = 0
let dragStartPct = 0
function onHandleDown(e: PointerEvent) {
  dragStartY = e.clientY
  dragStartPct = sheetPct.value
  ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
  window.addEventListener('pointermove', onHandleMove)
  window.addEventListener('pointerup', onHandleUp)
}
function onHandleMove(e: PointerEvent) {
  const h = rootRef.value?.clientHeight ?? 1
  const dy = dragStartY - e.clientY
  sheetPct.value = Math.min(0.85, Math.max(0.18, dragStartPct + dy / h))
}
function onHandleUp() {
  window.removeEventListener('pointermove', onHandleMove)
  window.removeEventListener('pointerup', onHandleUp)
}

// ── Carte : pan + zoom ──
// La carte est plein écran (full-bleed) ; la feuille glisse PAR-DESSUS sans la
// redimensionner. Le pan/zoom s'applique en transform CSS sur un calque pannable
// (svg + épingles ensemble) ; les épingles sont contre-zoomées pour garder une
// taille constante. SVG = vectoriel → net à tout niveau de zoom, 100 % offline.
const MIN_ZOOM = 1
const MAX_ZOOM = 6
const mapRef = ref<HTMLElement | null>(null)
const canvasW = ref(0)
const canvasH = ref(0)
const zoom = ref(1)
const tx = ref(0)
const ty = ref(0)

function layout() {
  const root = rootRef.value
  if (!root) return
  const rw = root.clientWidth
  const rh = root.clientHeight
  // COUVRE tout le viewport (comme background-size: cover) : la carte remplit
  // toujours l'écran entier, taille FIXE. La feuille glisse par-dessus sans
  // jamais toucher cette taille — elle recouvre simplement le bas de la carte.
  const s = Math.max(rw / VBW, rh / VBH)
  canvasW.value = VBW * s
  canvasH.value = VBH * s
  tx.value = (rw - canvasW.value) / 2
  ty.value = (rh - canvasH.value) / 2
  zoom.value = 1
}

function applyZoom(factor: number, px: number, py: number) {
  const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom.value * factor))
  const k = next / zoom.value
  // Garde le point (px,py) fixe sous le doigt/curseur pendant le zoom.
  tx.value = px - k * (px - tx.value)
  ty.value = py - k * (py - ty.value)
  zoom.value = next
}

function relXY(e: { clientX: number; clientY: number }) {
  const r = mapRef.value!.getBoundingClientRect()
  return { x: e.clientX - r.left, y: e.clientY - r.top }
}
function onWheel(e: WheelEvent) {
  e.preventDefault()
  const { x, y } = relXY(e)
  applyZoom(e.deltaY < 0 ? 1.12 : 1 / 1.12, x, y)
}
function zoomBtn(factor: number) {
  const r = mapRef.value
  applyZoom(factor, (r?.clientWidth ?? 0) / 2, (r?.clientHeight ?? 0) / 2)
}

const pointers = new Map<number, { x: number; y: number }>()
let panLast: { x: number; y: number } | null = null
let pinchLast: { dist: number; mx: number; my: number } | null = null
function pinchState() {
  const pts = [...pointers.values()]
  const dx = pts[0].x - pts[1].x
  const dy = pts[0].y - pts[1].y
  const r = mapRef.value!.getBoundingClientRect()
  return { dist: Math.hypot(dx, dy) || 1, mx: (pts[0].x + pts[1].x) / 2 - r.left, my: (pts[0].y + pts[1].y) / 2 - r.top }
}
function onMapPointerDown(e: PointerEvent) {
  if ((e.target as HTMLElement).closest('.geo-pin')) return // laisse le tap d'épingle
  mapRef.value?.setPointerCapture(e.pointerId)
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
  if (pointers.size === 2) { panLast = null; pinchLast = pinchState() }
  else { panLast = { x: e.clientX, y: e.clientY } }
}
function onMapPointerMove(e: PointerEvent) {
  if (!pointers.has(e.pointerId)) return
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
  if (pointers.size >= 2) {
    const cur = pinchState()
    if (pinchLast) {
      applyZoom(cur.dist / pinchLast.dist, cur.mx, cur.my)
      tx.value += cur.mx - pinchLast.mx
      ty.value += cur.my - pinchLast.my
    }
    pinchLast = cur
  } else if (panLast) {
    tx.value += e.clientX - panLast.x
    ty.value += e.clientY - panLast.y
    panLast = { x: e.clientX, y: e.clientY }
  }
}
function onMapPointerUp(e: PointerEvent) {
  pointers.delete(e.pointerId)
  pinchLast = null
  const rest = [...pointers.values()]
  panLast = rest.length === 1 ? { ...rest[0] } : null
}

let ro: ResizeObserver | null = null
onMounted(() => {
  layout()
  if (rootRef.value) {
    ro = new ResizeObserver(layout)
    ro.observe(rootRef.value)
  }
})
onBeforeUnmount(() => ro?.disconnect())
</script>

<template>
  <section ref="rootRef" class="geo-root" data-scene="vault-geo">
    <!-- Back-bar : retour + pont vers le catalogue à gratter -->
    <div class="geo-backbar">
      <button type="button" class="coffre-header__icon" aria-label="Retour au coffre" @click="router.push('/vault')">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7" /></svg>
      </button>
      <span class="geo-backbar__title">Répartition</span>
      <button type="button" class="geo-backbar__link" @click="router.push('/vault/catalog')">Catalogue →</button>
    </div>

    <!-- Carte plein écran (full-bleed) : pan + zoom. La feuille glisse par-dessus. -->
    <div
      ref="mapRef"
      class="geo-map"
      @pointerdown="onMapPointerDown"
      @pointermove="onMapPointerMove"
      @pointerup="onMapPointerUp"
      @pointercancel="onMapPointerUp"
      @wheel="onWheel"
    >
      <div
        class="geo-map__pannable"
        :style="{ width: `${canvasW}px`, height: `${canvasH}px`, transform: `translate(${tx}px, ${ty}px) scale(${zoom})` }"
      >
        <svg viewBox="0 0 400 511" preserveAspectRatio="none" role="img" aria-label="Carte de répartition de tes pièces">
          <path v-for="(d, i) in contextPaths" :key="`ctx-${i}`" :d="d" class="geo-map__context" />
          <path v-for="c in geoPaths" :key="c.iso" :d="c.d" class="geo-map__country" :class="{ 'is-owned': c.owned, 'is-selected': c.iso === selectedIso }" />
        </svg>
        <div
          v-for="p in pins"
          :key="p.iso"
          class="geo-pin"
          :style="{ left: p.left, top: p.top }"
        >
          <button
            type="button"
            class="geo-pin__pill"
            :class="{ 'is-selected': p.iso === selectedIso }"
            :style="{ transform: `scale(${1 / zoom})` }"
            :aria-label="`${p.iso} : ${p.count}`"
            @click="togglePin(p.iso)"
          >
            <span class="geo-pin__flag">{{ p.flag }}</span>
            <span class="geo-pin__count tabular">{{ p.count }}</span>
          </button>
        </div>
      </div>

      <div class="geo-zoom">
        <button type="button" aria-label="Zoomer" @click="zoomBtn(1.4)">+</button>
        <button type="button" aria-label="Dézoomer" @click="zoomBtn(1 / 1.4)">−</button>
      </div>
    </div>

    <!-- Feuille pièces (redimensionnable) -->
    <div class="geo-sheet" :style="{ height: `${sheetPct * 100}%` }">
      <div class="geo-sheet__handle" @pointerdown="onHandleDown"><span></span></div>
      <div class="geo-sheet__head">
        <template v-if="selectedCountry">
          <span class="geo-sheet__flag">{{ selectedCountry.flag }}</span>
          <span class="geo-sheet__title">{{ selectedCountry.name }}</span>
          <span class="geo-sheet__count">{{ selectedCountry.total }} {{ selectedCountry.total > 1 ? 'pièces' : 'pièce' }}</span>
          <button type="button" class="geo-sheet__clear" @click="selectedIso = null">Tout</button>
        </template>
        <template v-else>
          <span class="geo-sheet__title"><strong>{{ summary.coins }}</strong> {{ summary.coins > 1 ? 'pièces' : 'pièce' }}</span>
          <span class="geo-sheet__count">{{ summary.countries }} {{ summary.countries > 1 ? 'pays' : 'pays' }}</span>
        </template>
      </div>
      <div class="geo-sheet__list">
        <button v-for="r in coinRows" :key="r.coin.eurioId" type="button" class="geo-row" @click="openCoin(r.coin)">
          <div class="geo-row__coin"><CoinImage :coin="r.coin" :size="44" :show-label="false" /></div>
          <div class="geo-row__meta">
            <span class="geo-row__title">{{ r.countryName }}<template v-if="r.count > 1"> ×{{ r.count }}</template></span>
            <span class="geo-row__sub">{{ faceLabel(r.coin) }} · {{ r.coin.year ?? '—' }}</span>
          </div>
          <span class="geo-row__value tabular">{{ formatValue(r.valueEur) }}</span>
        </button>
      </div>
    </div>
  </section>
</template>
