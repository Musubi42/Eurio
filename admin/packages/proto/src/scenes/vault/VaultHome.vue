<script setup lang="ts">
/* Scène vault-home — vue principale du Coffre. Port de vault-home.html/.js,
 * recâblé sur le store collection (jointure owned) + api (catalogue). */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getCoin } from '@/api'
import type { Coin } from '@/api'
import { now } from '@/api/parity'
import { useCollectionStore } from '@/stores/collection'
import type { CollectionEntry, VaultSort, VaultView } from '@/stores/collection'
import CoinImage from '@/components/CoinImage.vue'
import CoffreTabs from './CoffreTabs.vue'
import VaultRemoveConfirm from './VaultRemoveConfirm.vue'

const router = useRouter()
const store = useCollectionStore()

const isEmpty = computed(() => store.collection.length === 0)
const view = computed(() => store.prefs.vaultView)
const sort = computed(() => store.prefs.vaultSort)

// ── Formatters ──
function formatEuros(cents: number): string {
  const eur = cents / 100
  return Number.isInteger(eur) ? `${eur} €` : `${eur.toFixed(2).replace('.', ',')} €`
}
function formatFaceValue(cents: number): string {
  if (cents >= 100) {
    const eur = cents / 100
    return Number.isInteger(eur) ? `${eur} €` : `${eur.toFixed(2).replace('.', ',')} €`
  }
  return `${cents} c`
}
const MONTHS_FR = ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']

// ── Valeur totale + delta ──
function referenceCents(entry: CollectionEntry): number {
  return entry.valueAtAddCents ?? getCoin(entry.eurioId)?.faceValueCents ?? 0
}
const currentCents = computed(() => store.collection.reduce((sum, e) => sum + referenceCents(e), 0))
const valueInt = computed(() => Math.floor(currentCents.value / 100).toLocaleString('fr-FR'))
const deltaHidden = computed(() => currentCents.value < 50)
const deltaPct = computed(() => 0) // mock : current == initial (valueAtAddCents)

// ── Stats ──
const countries = computed(() => new Set(store.collection.map((e) => getCoin(e.eurioId)?.country).filter(Boolean)))
const stats = computed(() => ({
  coins: store.collection.length,
  countries: countries.value.size,
  series: `${countries.value.size}/21`,
}))

// ── Multiplicité ──
const multi = computed(() => {
  const m = new Map<string, number>()
  for (const e of store.collection) m.set(e.eurioId, (m.get(e.eurioId) ?? 0) + 1)
  return m
})

// ── Bucketing ──
interface Bucket {
  label: string
  entries: CollectionEntry[]
}
function bucket(col: CollectionEntry[], mode: VaultSort): Bucket[] {
  if (mode === 'face') {
    const b = new Map<number, Bucket & { cents: number }>()
    for (const e of col) {
      const cents = getCoin(e.eurioId)?.faceValueCents ?? 0
      if (!b.has(cents)) b.set(cents, { cents, label: formatFaceValue(cents), entries: [] })
      b.get(cents)!.entries.push(e)
    }
    return [...b.values()].sort((a, z) => z.cents - a.cents)
  }
  if (mode === 'month') {
    const b = new Map<string, Bucket & { key: string }>()
    for (const e of col) {
      const d = new Date(e.addedAt)
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
      if (!b.has(key)) b.set(key, { key, label: `${MONTHS_FR[d.getMonth()]} ${d.getFullYear()}`, entries: [] })
      b.get(key)!.entries.push(e)
    }
    return [...b.values()].sort((a, z) => z.key.localeCompare(a.key))
  }
  if (mode === 'price') {
    const sorted = [...col].sort((a, z) => referenceCents(z) - referenceCents(a))
    return [{ label: 'Trié par prix', entries: sorted }]
  }
  // country (défaut)
  const b = new Map<string, Bucket>()
  for (const e of col) {
    const label = getCoin(e.eurioId)?.countryName || '?'
    if (!b.has(label)) b.set(label, { label, entries: [] })
    b.get(label)!.entries.push(e)
  }
  return [...b.values()].sort((a, z) => a.label.localeCompare(z.label, 'fr'))
}

interface GroupItem {
  coin: Coin
  count: number
}
const groups = computed(() => {
  return bucket(store.collection, sort.value)
    .map((g) => {
      const seen = new Set<string>()
      const items: GroupItem[] = []
      for (const e of g.entries) {
        if (seen.has(e.eurioId)) continue
        seen.add(e.eurioId)
        const coin = getCoin(e.eurioId)
        if (coin) items.push({ coin, count: multi.value.get(e.eurioId) ?? 1 })
      }
      return { label: g.label, items }
    })
    .filter((g) => g.items.length)
})

// ── Sparkline (valeur sur 12 mois) ──
const sparkline = computed(() => {
  const col = store.collection
  if (!col.length) return null
  const sorted = [...col].sort((a, z) => a.addedAt - z.addedAt)
  const nowMs = now()
  const monthMs = 30 * 24 * 60 * 60 * 1000
  const samples = 12
  const points: number[] = []
  for (let i = samples - 1; i >= 0; i--) {
    const cutoff = nowMs - i * monthMs
    let total = 0
    for (const e of sorted) {
      if (e.addedAt > cutoff) continue
      total += referenceCents(e)
    }
    points.push(total)
  }
  const max = Math.max(...points, 1)
  const min = Math.min(...points)
  const range = Math.max(max - min, 1)
  const W = 300, H = 52, PAD = 6
  const coords = points.map((v, i) => [(i / (samples - 1)) * W, H - PAD - ((v - min) / range) * (H - PAD * 2)] as const)
  const line = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const fill = `${line} L${W},${H} L0,${H} Z`
  const [cx, cy] = coords[coords.length - 1]
  return { line, fill, cx: cx.toFixed(1), cy: cy.toFixed(1) }
})

// ── Retrait + undo ──
const removeTarget = ref<Coin | null>(null)
const undo = ref<{ entry: CollectionEntry; text: string } | null>(null)
let undoTimer: ReturnType<typeof setTimeout> | null = null

function openRemove(coin: Coin) {
  removeTarget.value = coin
}
function confirmRemove() {
  const coin = removeTarget.value
  removeTarget.value = null
  if (!coin) return
  const removed = store.removeCoin(coin.eurioId)
  if (!removed) return
  undo.value = { entry: removed, text: `${coin.countryName} retirée` }
  if (undoTimer) clearTimeout(undoTimer)
  undoTimer = setTimeout(() => (undo.value = null), 5000)
}
function doUndo() {
  if (undo.value) store.restoreEntry(undo.value.entry)
  undo.value = null
  if (undoTimer) clearTimeout(undoTimer)
}

// ── Nav ──
function openCoin(coin: Coin) {
  router.push(`/coin/${encodeURIComponent(coin.eurioId)}?ctx=owned`)
}
function setView(v: VaultView) {
  store.setVaultView(v)
}
function setSort(s: VaultSort) {
  store.setVaultSort(s)
}

const SORTS: { id: VaultSort; label: string }[] = [
  { id: 'country', label: 'Pays' },
  { id: 'face', label: 'Valeur faciale' },
  { id: 'price', label: 'Prix' },
  { id: 'month', label: "Date d'ajout" },
]
</script>

<template>
  <section class="vault-home-root" data-scene="vault-home" :data-empty="isEmpty ? 'true' : 'false'">
    <!-- ───────── Empty ───────── -->
    <div v-if="isEmpty" class="vault-home-empty">
      <div class="vault-home-empty__art" aria-hidden="true">
        <svg viewBox="0 0 240 240" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <radialGradient id="vh-coin" cx="35%" cy="30%" r="80%">
              <stop offset="0%" stop-color="var(--gold-100)" />
              <stop offset="45%" stop-color="var(--gold)" />
              <stop offset="100%" stop-color="var(--gold-deep)" />
            </radialGradient>
            <radialGradient id="vh-halo" cx="50%" cy="50%" r="55%">
              <stop offset="0%" stop-color="rgba(200,168,100,0.28)" />
              <stop offset="100%" stop-color="rgba(200,168,100,0)" />
            </radialGradient>
          </defs>
          <circle cx="120" cy="120" r="115" fill="url(#vh-halo)" />
          <circle cx="120" cy="120" r="88" fill="none" stroke="var(--indigo-700)" stroke-opacity="0.1" stroke-width="1" stroke-dasharray="2 4" />
          <g opacity="0.28">
            <circle cx="50" cy="70" r="14" fill="var(--indigo-700)" />
            <circle cx="195" cy="80" r="11" fill="var(--indigo-700)" />
            <circle cx="60" cy="185" r="10" fill="var(--indigo-700)" />
            <circle cx="200" cy="180" r="13" fill="var(--indigo-700)" />
          </g>
          <g transform="translate(120 120) rotate(-8)">
            <ellipse cx="4" cy="8" rx="56" ry="12" fill="var(--ink)" opacity="0.15" />
            <circle r="58" fill="url(#vh-coin)" />
            <circle r="52" fill="none" stroke="var(--gold-deep)" stroke-opacity="0.45" stroke-width="1" stroke-dasharray="1 3" />
            <text y="10" text-anchor="middle" font-size="38" fill="var(--gold-deep)" opacity="0.8">€</text>
          </g>
        </svg>
      </div>
      <h1 class="vault-home-empty__title">Ton coffre<br />attend sa première pièce.</h1>
      <p class="vault-home-empty__sub">Scanne une pièce euro pour commencer ta collection. Eurio la reconnaît, l'évalue, et la range ici pour toi.</p>
      <button type="button" class="btn btn-primary vault-home-empty__cta" data-testid="empty-scan" @click="router.push('/scan')">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7V5a1 1 0 011-1h2M17 4h2a1 1 0 011 1v2M20 17v2a1 1 0 01-1 1h-2M7 20H5a1 1 0 01-1-1v-2" /><circle cx="12" cy="12" r="3.5" /></svg>
        <span>Scanner ma première pièce</span>
      </button>
    </div>

    <!-- ───────── Populated ───────── -->
    <div v-else class="vault-home-scroll">
      <header class="vault-home-header">
        <div class="vault-home-header__top">
          <div class="eyebrow">Ton coffre</div>
          <div class="vault-home-header__actions">
            <button type="button" class="vault-home-header__icon" aria-label="Exporter"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m0 0l-5-5m5 5l5-5M3 21h18" /></svg></button>
            <button type="button" class="vault-home-header__icon" aria-label="Plus d'options"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.3" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none" /><circle cx="19" cy="12" r="1.3" fill="currentColor" stroke="none" /></svg></button>
          </div>
        </div>

        <CoffreTabs active="coins" nav-class="vault-home-header__segnav" />

        <div class="vault-home-value">
          <span class="vault-home-value__label">Valeur totale</span>
          <div class="vault-home-value__amount tabular"><span>{{ valueInt }}</span><span class="vault-home-value__euro">€</span></div>
          <div v-show="!deltaHidden" class="vault-home-value__delta">
            <span class="vault-home-delta-chip tabular">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 14l5-5 5 5" /></svg>
              <span>+{{ deltaPct }}%</span>
            </span>
            <span>depuis tes premiers ajouts</span>
          </div>

          <div v-if="sparkline" class="vault-home-spark">
            <span class="vault-home-spark__scale">12 derniers mois</span>
            <svg viewBox="0 0 300 52" preserveAspectRatio="none" aria-hidden="true">
              <path class="vault-home-spark__fill" :d="sparkline.fill" />
              <path class="vault-home-spark__line" :d="sparkline.line" />
              <circle class="vault-home-spark__dot" :cx="sparkline.cx" :cy="sparkline.cy" r="3.2" />
            </svg>
          </div>
        </div>
      </header>

      <div class="vault-home-stats">
        <div class="stat"><span class="stat-value tabular">{{ stats.coins }}</span><span class="stat-label">Pièces</span></div>
        <div class="stat"><span class="stat-value tabular">{{ stats.countries }}</span><span class="stat-label">Pays</span></div>
        <div class="stat"><span class="stat-value tabular">{{ stats.series }}</span><span class="stat-label">Séries</span></div>
      </div>

      <div class="vault-home-toolbar">
        <button type="button" class="vault-home-search" data-testid="vault-search" @click="router.push('/vault/search')">
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" stroke-linecap="round" /></svg>
          <span>Chercher dans ton coffre</span>
        </button>

        <div class="vault-home-toolbar__row">
          <button type="button" class="vault-home-filters-btn" data-testid="vault-filters" @click="router.push('/vault/filters')">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M7 12h10M10 18h4" /></svg>
            <span>Filtres</span>
          </button>

          <div class="vault-home-toggle" role="tablist" aria-label="Mode d'affichage">
            <button type="button" :aria-selected="view === 'grid'" aria-label="Grille" @click="setView('grid')"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></svg></button>
            <button type="button" :aria-selected="view === 'list'" aria-label="Liste" @click="setView('list')"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" stroke-linecap="round" /></svg></button>
          </div>
        </div>

        <div class="vault-home-sort" role="radiogroup" aria-label="Trier par">
          <span class="vault-home-sort__label">Trier</span>
          <button v-for="s in SORTS" :key="s.id" type="button" class="vault-home-sort__chip" :aria-pressed="sort === s.id" @click="setSort(s.id)">{{ s.label }}</button>
        </div>
      </div>

      <div>
        <template v-for="g in groups" :key="g.label">
          <div class="vault-home-group">
            <span class="vault-home-group__label">{{ g.label }}</span>
            <span class="vault-home-group__line"></span>
          </div>

          <div v-if="view === 'list'" class="vault-home-list">
            <button v-for="it in g.items" :key="it.coin.eurioId" type="button" class="vault-home-row" @click="openCoin(it.coin)">
              <div class="vault-home-row__coin"><CoinImage :coin="it.coin" :size="44" :show-label="false" /></div>
              <div class="vault-home-row__meta">
                <span class="vault-home-row__title">{{ it.coin.countryName }}<template v-if="it.count > 1"> ×{{ it.count }}</template></span>
                <span class="vault-home-row__sub">{{ formatFaceValue(it.coin.faceValueCents) }} · {{ it.coin.year ?? '—' }}</span>
              </div>
              <div class="vault-home-row__value tabular">
                <span class="vault-home-row__price">{{ formatEuros(it.coin.faceValueCents) }}</span>
                <span class="vault-home-row__delta vault-home-row__delta--neutral">—</span>
              </div>
            </button>
          </div>

          <div v-else class="vault-home-grid">
            <button v-for="it in g.items" :key="it.coin.eurioId" type="button" class="vault-home-tile" :class="{ 'vault-home-tile--set-complete': it.coin.isCommemorative && it.count >= 2 }" @click="openCoin(it.coin)">
              <span v-if="it.count > 1" class="vault-home-tile__mult">×{{ it.count }}</span>
              <span class="vault-home-tile__more" aria-label="Plus d'options" @click.stop="openRemove(it.coin)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="5" cy="12" r="1.2" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" /><circle cx="19" cy="12" r="1.2" fill="currentColor" stroke="none" /></svg>
              </span>
              <div class="vault-home-tile__coin"><CoinImage :coin="it.coin" :size="120" /></div>
              <div class="vault-home-tile__meta">
                <span>{{ it.coin.country.toUpperCase() }}</span>
                <span>{{ it.coin.year ?? '' }}</span>
              </div>
            </button>
          </div>
        </template>
      </div>

      <div style="height: var(--space-10)"></div>
    </div>

    <!-- Overlay retrait -->
    <VaultRemoveConfirm v-if="removeTarget" :coin="removeTarget" @cancel="removeTarget = null" @confirm="confirmRemove" />

    <!-- Toast undo -->
    <div v-if="undo" class="vault-remove-toast">
      <span>{{ undo.text }}</span>
      <button type="button" class="vault-remove-toast__undo" data-testid="undo-remove" @click="doUndo">Annuler</button>
    </div>
  </section>
</template>

<style src="../../styles/vault-home.css"></style>
<!-- Le toast undo réutilise le style de l'overlay de retrait. -->
<style src="../../styles/vault-remove-confirm.css"></style>
