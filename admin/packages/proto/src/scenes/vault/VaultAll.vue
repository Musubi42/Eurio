<script setup lang="ts">
/* Onglet « Pièces » (All) — navigateur du coffre, orienté VALEUR + identité.
 * Chaque pièce montre son vrai nom, son grade et sa cote marché (pas la faciale).
 * Recherche inline + filtres (store) appliqués en temps réel. Grille = vitrine,
 * liste = lecture dense des cotes. Extrait/refondu depuis l'ancien VaultHome. */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getCoin, getMarket } from '@/api'
import type { Coin } from '@/api'
import { useCollectionStore } from '@/stores/collection'
import { defaultVaultFilters } from '@/stores/collection'
import type { CollectionEntry, VaultSort, VaultView } from '@/stores/collection'
import CoinImage from '@/components/CoinImage.vue'
import CoffreHeader from './CoffreHeader.vue'
import VaultRemoveConfirm from './VaultRemoveConfirm.vue'
import '@/styles/vault-all.css'

const router = useRouter()
const store = useCollectionStore()

const isEmpty = computed(() => store.collection.length === 0)
const view = computed(() => store.prefs.vaultView)
const sort = computed(() => store.prefs.vaultSort)
const query = ref('')

// ── Formatters ──
function formatFaceValue(cents: number): string {
  if (cents >= 100) {
    const eur = cents / 100
    return Number.isInteger(eur) ? `${eur} €` : `${eur.toFixed(2).replace('.', ',')} €`
  }
  return `${cents} c`
}
function formatValue(eur: number): string {
  if (eur >= 1000) return `${Math.round(eur).toLocaleString('fr-FR')} €`
  return Number.isInteger(eur) ? `${eur} €` : `${eur.toFixed(2).replace('.', ',')} €`
}
const MONTHS_FR = ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']

// ── Valeur / identité / grade par pièce ──
function coinValueEur(coin: Coin): number {
  return getMarket(coin.eurioId)?.p50 ?? coin.faceValue
}
function coinRarityGold(coin: Coin): boolean {
  return getMarket(coin.eurioId)?.rarity.gold ?? false
}
// Nom affiché : thème/commémo si présent, sinon « faciale · pays ».
function displayName(coin: Coin): string {
  return coin.theme?.trim() || coin.designDescription?.trim() || `${formatFaceValue(coin.faceValueCents)} ${coin.countryName}`
}
// Grade (état) : première condition rencontrée pour cette pièce.
const conditionByCoin = computed(() => {
  const m = new Map<string, string | null>()
  for (const e of store.collection) if (!m.has(e.eurioId)) m.set(e.eurioId, e.condition)
  return m
})

// ── Filtres (store) + recherche inline appliqués aux ENTRÉES ──
const DEFAULTS = defaultVaultFilters()
const activeFilterCount = computed(() => {
  const f = store.prefs.vaultFilters
  let n = 0
  n += f.countries.length + f.faceValueCents.length + f.types.length + f.rarities.length + f.conditions.length
  if (f.yearMin !== DEFAULTS.yearMin || f.yearMax !== DEFAULTS.yearMax) n += 1
  return n
})
function passes(e: CollectionEntry, coin: Coin): boolean {
  const f = store.prefs.vaultFilters
  if (f.countries.length && !f.countries.includes(coin.country)) return false
  if (f.faceValueCents.length && !f.faceValueCents.includes(coin.faceValueCents)) return false
  if (f.types.length) {
    const t = coin.isCommemorative ? 'commemorative' : 'circulation'
    if (!f.types.includes(t)) return false
  }
  if (f.conditions.length && !f.conditions.includes(e.condition ?? 'unknown')) return false
  if (coin.year != null && (coin.year < f.yearMin || coin.year > f.yearMax)) return false
  if (query.value.trim()) {
    const q = query.value.trim().toLowerCase()
    const hay = `${coin.countryName} ${coin.theme ?? ''} ${coin.designDescription ?? ''} ${coin.year ?? ''}`.toLowerCase()
    if (!hay.includes(q)) return false
  }
  return true
}
const filteredEntries = computed(() =>
  store.collection.filter((e) => {
    const coin = getCoin(e.eurioId)
    return coin ? passes(e, coin) : false
  }),
)
const noResults = computed(() => !isEmpty.value && filteredEntries.value.length === 0)

// ── Multiplicité ──
const multi = computed(() => {
  const m = new Map<string, number>()
  for (const e of filteredEntries.value) m.set(e.eurioId, (m.get(e.eurioId) ?? 0) + 1)
  return m
})

// ── Bucketing ──
interface Bucket {
  label: string
  entries: CollectionEntry[]
}
function valueRefEur(coin: Coin): number {
  return coinValueEur(coin)
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
    const sorted = [...col].sort((a, z) => valueRefEur(getCoin(z.eurioId)!) - valueRefEur(getCoin(a.eurioId)!))
    return [{ label: 'Par valeur', entries: sorted }]
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
  valueEur: number
  rarityGold: boolean
  grade: string | null
}
interface Group {
  label: string
  items: GroupItem[]
  count: number
  totalEur: number
}
const groups = computed<Group[]>(() => {
  return bucket(filteredEntries.value, sort.value)
    .map((g) => {
      const seen = new Set<string>()
      const items: GroupItem[] = []
      let count = 0
      let totalEur = 0
      for (const e of g.entries) {
        count += 1
        const coin = getCoin(e.eurioId)
        if (!coin) continue
        totalEur += coinValueEur(coin)
        if (seen.has(e.eurioId)) continue
        seen.add(e.eurioId)
        items.push({
          coin,
          count: multi.value.get(e.eurioId) ?? 1,
          valueEur: coinValueEur(coin),
          rarityGold: coinRarityGold(coin),
          grade: conditionByCoin.value.get(e.eurioId) ?? null,
        })
      }
      return { label: g.label, items, count, totalEur }
    })
    .filter((g) => g.items.length)
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

// ── Nav / prefs ──
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
  { id: 'price', label: 'Valeur' },
  { id: 'face', label: 'Faciale' },
  { id: 'month', label: 'Date' },
]
</script>

<template>
  <section class="vault-home-root" data-scene="vault-all">
    <CoffreHeader active="all" />

    <div v-if="isEmpty" class="vault-all-empty">
      <p>Aucune pièce dans ton coffre.</p>
      <button type="button" class="btn btn-primary" @click="router.push('/scan')">Scanner une pièce</button>
    </div>

    <div v-else class="vault-home-scroll vault-all-scroll">
      <!-- Toolbar slim : recherche inline + filtres + tri + vue -->
      <div class="vault-all-bar">
        <label class="vault-all-search">
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" stroke-linecap="round" /></svg>
          <input v-model="query" type="search" placeholder="Chercher dans ton coffre" data-testid="vault-search-inline" />
        </label>

        <div class="vault-all-bar__row">
          <button type="button" class="vault-all-filters" :class="{ 'is-active': activeFilterCount > 0 }" data-testid="vault-filters" @click="router.push('/vault/filters')">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M7 12h10M10 18h4" /></svg>
            <span>Filtres</span>
            <span v-if="activeFilterCount > 0" class="vault-all-filters__badge tabular">{{ activeFilterCount }}</span>
          </button>

          <div class="vault-all-sort" role="radiogroup" aria-label="Trier par">
            <button v-for="s in SORTS" :key="s.id" type="button" class="vault-all-sort__chip" :aria-pressed="sort === s.id" @click="setSort(s.id)">{{ s.label }}</button>
          </div>

          <div class="vault-home-toggle" role="tablist" aria-label="Mode d'affichage">
            <button type="button" :aria-selected="view === 'grid'" aria-label="Grille" @click="setView('grid')"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></svg></button>
            <button type="button" :aria-selected="view === 'list'" aria-label="Liste" @click="setView('list')"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" stroke-linecap="round" /></svg></button>
          </div>
        </div>
      </div>

      <p v-if="noResults" class="vault-all-noresult">Aucune pièce ne correspond.</p>

      <div v-else>
        <template v-for="g in groups" :key="g.label">
          <div class="vault-home-group">
            <span class="vault-home-group__label">{{ g.label }}</span>
            <span class="vault-home-group__line"></span>
            <span class="vault-all-group__total tabular">{{ g.count }} · {{ formatValue(g.totalEur) }}</span>
          </div>

          <!-- Liste : orientée valeur -->
          <div v-if="view === 'list'" class="vault-home-list">
            <button v-for="it in g.items" :key="it.coin.eurioId" type="button" class="vault-all-row" @click="openCoin(it.coin)">
              <div class="vault-all-row__coin"><CoinImage :coin="it.coin" :size="48" :show-label="false" /></div>
              <div class="vault-all-row__meta">
                <span class="vault-all-row__title">{{ displayName(it.coin) }}<template v-if="it.count > 1"> ×{{ it.count }}</template></span>
                <span class="vault-all-row__sub">
                  <span v-if="it.grade" class="vault-all-grade">{{ it.grade }}</span>
                  {{ it.coin.countryName }} · {{ it.coin.year ?? '—' }}
                </span>
              </div>
              <span class="vault-all-row__value tabular" :class="{ 'is-precious': it.rarityGold }">{{ formatValue(it.valueEur) }}</span>
            </button>
          </div>

          <!-- Grille : vitrine -->
          <div v-else class="vault-home-grid">
            <button v-for="it in g.items" :key="it.coin.eurioId" type="button" class="vault-all-tile" :class="{ 'is-precious': it.rarityGold, 'is-commemo': it.coin.isCommemorative }" @click="openCoin(it.coin)">
              <span v-if="it.count > 1" class="vault-home-tile__mult">×{{ it.count }}</span>
              <span class="vault-home-tile__more" aria-label="Plus d'options" @click.stop="openRemove(it.coin)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="5" cy="12" r="1.2" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" /><circle cx="19" cy="12" r="1.2" fill="currentColor" stroke="none" /></svg>
              </span>
              <div class="vault-all-tile__coin"><CoinImage :coin="it.coin" :size="120" /></div>
              <div class="vault-all-tile__foot">
                <span class="vault-all-tile__country">{{ it.coin.country.toUpperCase() }}<span class="vault-all-tile__year">{{ it.coin.year ?? '' }}</span></span>
                <span class="vault-all-tile__value tabular" :class="{ 'is-precious': it.rarityGold }">{{ formatValue(it.valueEur) }}</span>
              </div>
            </button>
          </div>
        </template>
      </div>

      <div style="height: var(--space-10)"></div>
    </div>

    <VaultRemoveConfirm v-if="removeTarget" :coin="removeTarget" @cancel="removeTarget = null" @confirm="confirmRemove" />

    <div v-if="undo" class="vault-remove-toast">
      <span>{{ undo.text }}</span>
      <button type="button" class="vault-remove-toast__undo" data-testid="undo-remove" @click="doUndo">Annuler</button>
    </div>
  </section>
</template>

<style src="../../styles/vault-home.css"></style>
<style src="../../styles/vault-remove-confirm.css"></style>
