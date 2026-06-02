<script setup lang="ts">
/* Scène carte-à-gratter — catalogue eurozone : carte SVG (états gravé/en cours/
 * complété), micro-pastilles, feuille d'or à gratter sur le pays complété,
 * détail pays inline. Port de carte-a-gratter.html/.js. */
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { coinSvg, filterCoins, getCountryProgress, isCountryComplete } from '@/api'
import type { Coin, CountryProgress } from '@/api'
import { confetti, chime, haptic } from '@/lib/celebration'
import { CONTEXT, GEO } from './eurozone-geo'
import CoffreHeader from './CoffreHeader.vue'

const route = useRoute()
const router = useRouter()

const VBW = 400
const VBH = 511
const MICRO = ['LU', 'MT', 'CY']
const MICRO_ANCHOR: Record<string, { x: number; y: number }> = {
  LU: { x: 34, y: 250 },
  MT: { x: 256, y: 504 },
  CY: { x: 384, y: 452 },
}

const progress = getCountryProgress()
const byIso = new Map(progress.map((c) => [c.iso, c]))

function stateOf(c: CountryProgress): 'empty' | 'progress' | 'complete' {
  if (c.owned === 0) return 'empty'
  return isCountryComplete(c) ? 'complete' : 'progress'
}

// ── Géométrie déclarative ──
const contextPaths = Object.values(CONTEXT)
const countries = Object.keys(GEO)
  .filter((iso) => !MICRO.includes(iso) && byIso.has(iso))
  .map((iso) => ({ iso, d: GEO[iso].d, cx: GEO[iso].cx, cy: GEO[iso].cy, entry: byIso.get(iso)! }))
const micros = MICRO.filter((iso) => GEO[iso] && byIso.has(iso) && MICRO_ANCHOR[iso]).map((iso) => {
  const entry = byIso.get(iso)!
  const a = MICRO_ANCHOR[iso]
  return { iso, a, cx: GEO[iso].cx, cy: GEO[iso].cy, entry, fill: `rgba(200,168,100,${(0.2 + (entry.owned / entry.total) * 0.8).toFixed(2)})` }
})

const stats = computed(() => ({
  owned: progress.reduce((s, c) => s + c.owned, 0),
  total: progress.reduce((s, c) => s + c.total, 0),
}))

// ── Mode + sélection ──
const mode = ref<'map' | 'list'>('map')
const fromReveal = route.query.scratch === '1'
const selectedIso = ref(fromReveal ? (progress.find(isCountryComplete)?.iso ?? 'FR') : 'FR')

const sortedList = computed(() => [...progress].sort((a, b) => b.owned / b.total - a.owned / a.total))

const selected = computed(() => byIso.get(selectedIso.value) ?? progress[0])
const selectedPct = computed(() => Math.round((selected.value.owned / selected.value.total) * 100))
const selectedComplete = computed(() => isCountryComplete(selected.value))

const detailCells = computed<{ coin: Coin; owned: boolean }[]>(() => {
  const entry = selected.value
  const coins = filterCoins({ country: entry.iso.toLowerCase() })
    .slice()
    .sort((a, b) => (a.year || 0) - (b.year || 0) || a.faceValueCents - b.faceValueCents)
  const set = coins.slice(0, entry.total)
  const ownedN = selectedComplete.value ? set.length : Math.min(entry.owned, set.length)
  return set.map((coin, i) => ({ coin, owned: i < ownedN }))
})

function faceLabel(c: Coin): string {
  return c.faceValue >= 1 ? `${c.faceValue} €` : `${Math.round(c.faceValue * 100)} c`
}
function select(iso: string) {
  if (byIso.has(iso)) selectedIso.value = iso
}
function selectFromList(iso: string) {
  mode.value = 'map'
  select(iso)
}
function openCoin(c: Coin) {
  router.push(`/coin/${encodeURIComponent(c.eurioId)}`)
}

// ── Scratch-reveal (canvas sur le pays complété) ──
const rootRef = ref<HTMLElement | null>(null)

function celebrateCountry(entry: CountryProgress) {
  const card = rootRef.value?.querySelector<HTMLElement>('.cag-mapcard')
  if (!card) return
  const layer = document.createElement('div')
  layer.className = 'cel-confetti'
  card.appendChild(layer)
  const banner = document.createElement('div')
  banner.className = 'cag-cel-banner'
  banner.textContent = `${entry.name} complété`
  card.appendChild(banner)
  haptic([0, 35, 30, 80])
  chime([523.25, 659.25, 783.99, 1046.5])
  confetti(layer, { count: 40 })
  setTimeout(() => banner.classList.add('is-out'), 2800)
  setTimeout(() => {
    banner.remove()
    layer.remove()
  }, 3600)
}

function setupScratch() {
  const root = rootRef.value
  const complete = progress.find(isCountryComplete)
  if (!root || !complete || MICRO.includes(complete.iso)) return
  const path = root.querySelector<SVGPathElement>(`.cag-country[data-iso="${complete.iso}"]`)
  const mapEl = root.querySelector<HTMLElement>('.cag-map')
  if (!path || !mapEl) return

  const build = () => {
    const rect = mapEl.getBoundingClientRect()
    const bbox = path.getBBox()
    // getBBox peut renvoyer 0 tant que le SVG n'est pas peint → on réessaie.
    if (!rect.width || !bbox.width) {
      requestAnimationFrame(build)
      return
    }
    const sx = rect.width / VBW
    const sy = rect.height / VBH
    const dpr = window.devicePixelRatio || 1
    const pad = 3
    const bx = bbox.x - pad
    const by = bbox.y - pad
    const bw = bbox.width + 2 * pad
    const bh = bbox.height + 2 * pad

    const canvas = document.createElement('canvas')
    canvas.className = 'cag-scratch'
    canvas.style.left = `${bx * sx}px`
    canvas.style.top = `${by * sy}px`
    canvas.style.width = `${bw * sx}px`
    canvas.style.height = `${bh * sy}px`
    canvas.width = Math.round(bw * sx * dpr)
    canvas.height = Math.round(bh * sy * dpr)
    canvas.setAttribute('aria-label', `Gratter pour révéler ${complete.name} complété`)
    if (fromReveal) canvas.classList.add('cag-scratch--pulse')
    mapEl.appendChild(canvas)

    const cctx = canvas.getContext('2d')!
    cctx.setTransform(sx * dpr, 0, 0, sy * dpr, -bx * sx * dpr, -by * sy * dpr)
    const p2d = new Path2D(path.getAttribute('d')!)
    cctx.save()
    cctx.clip(p2d)
    const grad = cctx.createLinearGradient(bx, by, bx + bw, by + bh)
    grad.addColorStop(0, '#F5EBD3')
    grad.addColorStop(0.35, '#E7CB8B')
    grad.addColorStop(0.6, '#C8A864')
    grad.addColorStop(0.85, '#8F7637')
    grad.addColorStop(1, '#E7CB8B')
    cctx.fillStyle = grad
    cctx.fillRect(bx, by, bw, bh)
    cctx.fillStyle = 'rgba(20,20,46,0.62)'
    cctx.font = '700 7px ui-monospace, monospace'
    cctx.textAlign = 'center'
    cctx.textBaseline = 'middle'
    cctx.fillText('GRATTE', bbox.x + bbox.width / 2, bbox.y + bbox.height / 2)
    cctx.restore()

    const base: number[] = []
    const img0 = cctx.getImageData(0, 0, canvas.width, canvas.height).data
    for (let i = 3; i < img0.length; i += 4 * 30) if (img0[i] > 200) base.push(i)

    let scratching = false
    let done = false
    let moves = 0
    const toVB = (ev: PointerEvent): [number, number] => {
      const r = mapEl.getBoundingClientRect()
      return [((ev.clientX - r.left) / r.width) * VBW, ((ev.clientY - r.top) / r.height) * VBH]
    }
    const erase = (x: number, y: number) => {
      cctx.save()
      cctx.globalCompositeOperation = 'destination-out'
      cctx.beginPath()
      cctx.arc(x, y, 12, 0, Math.PI * 2)
      cctx.fill()
      cctx.restore()
    }
    const cleared = (): number => {
      const d = cctx.getImageData(0, 0, canvas.width, canvas.height).data
      let c = 0
      for (const i of base) if (d[i] < 30) c++
      return base.length ? c / base.length : 0
    }
    const finish = () => {
      if (done) return
      done = true
      canvas.style.transition = 'opacity 0.5s var(--ease-out)'
      canvas.style.opacity = '0'
      setTimeout(() => canvas.remove(), 540)
      celebrateCountry(complete)
    }
    canvas.addEventListener('pointerdown', (e) => {
      try {
        canvas.setPointerCapture(e.pointerId)
      } catch {
        /* synthétique */
      }
      scratching = true
      erase(...toVB(e))
    })
    canvas.addEventListener('pointermove', (e) => {
      if (!scratching) return
      erase(...toVB(e))
      if (++moves % 6 === 0 && cleared() > 0.5) finish()
    })
    canvas.addEventListener('pointerup', () => {
      scratching = false
      if (cleared() > 0.5) finish()
    })
    canvas.addEventListener('pointercancel', () => {
      scratching = false
    })
  }
  requestAnimationFrame(build)
}

onMounted(async () => {
  await nextTick()
  setupScratch()
  if (fromReveal) rootRef.value?.querySelector('.cag-mapcard')?.scrollIntoView({ block: 'center' })
})
</script>

<template>
  <section ref="rootRef" class="cag-root" data-scene="carte-a-gratter" :data-mode="mode">
    <CoffreHeader active="catalog" />

    <div class="cag-toggle-row">
      <div class="cag-toggle" role="tablist" aria-label="Mode d'affichage">
        <button type="button" :aria-selected="mode === 'map'" @click="mode = 'map'">Carte</button>
        <button type="button" :aria-selected="mode === 'list'" @click="mode = 'list'">Liste</button>
      </div>
    </div>

    <!-- Map card -->
    <div class="cag-mapcard">
      <div class="cag-frame" aria-hidden="true"></div>
      <div class="cag-head">
        <span class="cag-eyebrow">Eurozone · 21 pays</span>
        <div class="cag-stat"><strong>{{ stats.owned }}</strong>/<span>{{ stats.total }}</span> pièces</div>
      </div>

      <div class="cag-map">
        <svg viewBox="0 0 400 511" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Carte de l'eurozone">
          <defs>
            <linearGradient id="cag-gold" x1="0" y1="0" x2="0.35" y2="1">
              <stop class="cag-g0" offset="0%" />
              <stop class="cag-g1" offset="42%" />
              <stop class="cag-g2" offset="100%" />
            </linearGradient>
            <filter id="cag-relief" x="-10%" y="-10%" width="120%" height="120%">
              <feDropShadow dx="0" dy="1.2" stdDeviation="1.1" flood-color="rgba(8,8,24,0.55)" />
            </filter>
          </defs>

          <g>
            <path v-for="(d, i) in contextPaths" :key="i" class="cag-context" :d="d" />
          </g>
          <g filter="url(#cag-relief)">
            <path
              v-for="c in countries"
              :key="c.iso"
              class="cag-country"
              :data-iso="c.iso"
              :d="c.d"
              :data-state="stateOf(c.entry)"
              :data-selected="selectedIso === c.iso ? '1' : undefined"
              @click="select(c.iso)"
            />
          </g>
          <g>
            <template v-for="m in micros" :key="m.iso">
              <line class="cag-leader" :x1="m.a.x" :y1="m.a.y" :x2="m.cx" :y2="m.cy" />
              <circle class="cag-micro-dot" :data-iso="m.iso" :cx="m.a.x" :cy="m.a.y" r="12" :style="{ fill: m.fill }" :data-selected="selectedIso === m.iso ? '1' : undefined" @click="select(m.iso)" />
              <text class="cag-micro-label" :x="m.a.x" :y="m.a.y">{{ m.iso }}</text>
              <text class="cag-micro-ratio" :x="m.a.x" :y="m.a.y + 19">{{ m.entry.owned }}/{{ m.entry.total }}</text>
            </template>
          </g>
          <g>
            <template v-for="c in countries" :key="`l-${c.iso}`">
              <text class="cag-label" :x="c.cx" :y="c.cy - 3">{{ c.iso }}</text>
              <text class="cag-ratio" :x="c.cx" :y="c.cy + 6">{{ c.entry.owned }}/{{ c.entry.total }}</text>
            </template>
          </g>
        </svg>
      </div>

      <div class="cag-legend">
        <span class="cag-legend__item"><i class="cag-sw cag-sw--empty"></i>Aucune</span>
        <span class="cag-legend__item"><i class="cag-sw cag-sw--progress"></i>En cours</span>
        <span class="cag-legend__item"><i class="cag-sw cag-sw--complete"></i>Complète</span>
        <span class="cag-legend__item"><i class="cag-sw cag-sw--context"></i>Hors zone €</span>
      </div>
    </div>

    <!-- Détail pays inline -->
    <section class="cag-detail" :data-complete="selectedComplete ? '1' : '0'" aria-live="polite">
      <header class="cag-detail__head">
        <div class="cag-detail__flag">{{ selected.flag }}</div>
        <div class="cag-detail__hgroup">
          <div class="cag-detail__name">{{ selected.name }}</div>
          <div class="cag-detail__meta">
            <span>{{ selected.owned }} / {{ selected.total }}</span>
            <div class="cag-detail__bar progress-bar"><div class="progress-track"><div class="progress-fill" :style="{ width: selectedPct + '%' }"></div></div></div>
            <span>{{ selectedPct }}%</span>
          </div>
        </div>
      </header>
      <div class="cag-detail__grid">
        <button v-for="cell in detailCells" :key="cell.coin.eurioId" type="button" class="cag-coin" :data-owned="cell.owned ? 1 : 0" @click="openCoin(cell.coin)">
          <span class="cag-coin__disc" v-html="coinSvg(cell.coin, { size: 46, showLabel: false })" />
          <span class="cag-coin__label">{{ faceLabel(cell.coin) }}{{ cell.coin.year ? ` · ${cell.coin.year}` : '' }}</span>
        </button>
        <p v-if="!detailCells.length" class="cag-detail__empty">Pas de pièces au catalogue pour ce pays (données proto).</p>
      </div>
    </section>

    <!-- List mode -->
    <div class="cag-list">
      <button v-for="c in sortedList" :key="c.iso" type="button" class="cag-listrow" @click="selectFromList(c.iso)">
        <div class="cag-listrow__flag">{{ c.flag }}</div>
        <div class="cag-listrow__name">{{ c.name }}<span v-if="isCountryComplete(c)">✓ complet</span></div>
        <div class="cag-listrow__bar progress-bar"><div class="progress-track"><div class="progress-fill" :style="{ width: Math.round((c.owned / c.total) * 100) + '%' }"></div></div></div>
        <div class="cag-listrow__ratio">{{ c.owned }}/{{ c.total }}</div>
      </button>
    </div>

    <div style="height: var(--space-10)"></div>
  </section>
</template>

<style src="../../styles/vault-catalog.css"></style>
