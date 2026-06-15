<script setup lang="ts">
/* Onglet « Résumé » (Summary) — vitrine curée du Coffre, inspirée du flow
 * CoinSnap : carte spotlight des meilleures pièces, répartition géographique
 * (aperçu de la carte à gratter + liste pays), aperçu des sets. Le navigateur
 * brut des pièces vit dans l'onglet « Pièces » (VaultAll). Le header patrimoine
 * sobre est partagé (CoffreHeader). */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getCoin, getCountryProgress, getMarket, getSets } from '@/api'
import type { Coin } from '@/api'
import { useCollectionStore } from '@/stores/collection'
import Spotlight3D from '@/components/Spotlight3D.vue'
import CoffreHeader from './CoffreHeader.vue'
import { CONTEXT, GEO } from './eurozone-geo'

const router = useRouter()
const store = useCollectionStore()

const isEmpty = computed(() => store.collection.length === 0)

function formatValue(eur: number): string {
  return Number.isInteger(eur) ? `${eur} €` : `${eur.toFixed(2).replace('.', ',')} €`
}

// ───────── Meilleures pièces (spotlight = galerie de trophées) ─────────
// Chaque page du spotlight = UNE catégorie superlative ; la pièce gagnante est
// affichée en 3D (Spotlight3D). Valeur = cote médiane marché (getMarket.p50)
// avec repli sur la faciale.
const RARITY_RANK: Record<string, number> = { commune: 0, peu: 1, rare: 2, 'tres-rare': 3 }
const MICRO_STATES = new Set(['mc', 'va', 'sm', 'ad']) // Monaco, Vatican, Saint-Marin, Andorre
interface BestCoin {
  coin: Coin
  valueEur: number
  rarityLabel: string
  rarityRank: number
  mintage: number | null
}
const bestCoins = computed<BestCoin[]>(() => {
  const seen = new Set<string>()
  const list: BestCoin[] = []
  for (const e of store.collection) {
    if (seen.has(e.eurioId)) continue
    seen.add(e.eurioId)
    const coin = getCoin(e.eurioId)
    if (!coin) continue
    const m = getMarket(e.eurioId)
    list.push({
      coin,
      valueEur: m?.p50 ?? coin.faceValue,
      rarityLabel: m?.rarity.label ?? 'Commune',
      rarityRank: RARITY_RANK[m?.rarity.key ?? 'commune'] ?? 0,
      mintage: coin.mintage,
    })
  }
  return list
})

// Trophées dans l'ordre PO : précieuse · rare · ancienne · commémo phare · micro-état.
// Une catégorie sans pièce éligible est simplement omise.
interface Trophy {
  key: string
  icon: string
  label: string
  coin: Coin
  metric: string
}
const trophies = computed<Trophy[]>(() => {
  const pool = bestCoins.value
  if (!pool.length) return []
  const out: Trophy[] = []
  const used = new Set<string>()
  // Premier candidat d'une liste pré-triée dont la pièce n'a pas déjà gagné une
  // autre catégorie → 5 trophées sur 5 pièces DISTINCTES (sinon une pièce qui
  // cumule les superlatifs, ex Monaco Grace Kelly, occuperait plusieurs pages).
  const firstUnused = (list: BestCoin[]) => list.find((b) => !used.has(b.coin.eurioId)) ?? null
  const add = (t: Omit<Trophy, 'coin'> & { b: BestCoin | null }) => {
    if (!t.b) return
    used.add(t.b.coin.eurioId)
    out.push({ key: t.key, icon: t.icon, label: t.label, coin: t.b.coin, metric: t.metric })
  }

  const byValue = [...pool].sort((a, z) => z.valueEur - a.valueEur)
  const byRare = [...pool].sort((a, z) => z.rarityRank - a.rarityRank || (a.mintage ?? Infinity) - (z.mintage ?? Infinity))
  const byOld = pool.filter((b) => b.coin.year != null).sort((a, z) => (a.coin.year as number) - (z.coin.year as number))

  const precieuse = firstUnused(byValue)
  add({ key: 'precieuse', icon: '💎', label: 'La plus précieuse', b: precieuse, metric: precieuse ? formatValue(precieuse.valueEur) : '' })
  const rare = firstUnused(byRare)
  add({ key: 'rare', icon: '👑', label: 'La plus rare', b: rare, metric: rare ? (rare.mintage != null ? `Tirage ${rare.mintage.toLocaleString('fr-FR')}` : rare.rarityLabel) : '' })
  const ancienne = firstUnused(byOld)
  add({ key: 'ancienne', icon: '🏛️', label: 'La plus ancienne', b: ancienne, metric: ancienne ? String(ancienne.coin.year) : '' })
  const commemo = firstUnused(byValue.filter((b) => b.coin.isCommemorative))
  add({ key: 'commemo', icon: '⭐', label: 'La commémo phare', b: commemo, metric: commemo ? formatValue(commemo.valueEur) : '' })
  const micro = firstUnused(byValue.filter((b) => MICRO_STATES.has(b.coin.country)))
  add({ key: 'micro', icon: '🏰', label: 'Le micro-état', b: micro, metric: micro ? micro.coin.countryName : '' })

  return out
})
const showBest = computed(() => trophies.value.length >= 1)

// Pagination du spotlight (1 catégorie à la fois).
const spotIndex = ref(0)
const trophy = computed(() => trophies.value[Math.min(spotIndex.value, trophies.value.length - 1)] ?? null)
function goSpot(i: number) {
  spotIndex.value = i
}

// ───────── Répartition géographique ─────────
// Dérivée du store (cohérente avec le header) ; la fixture getCountryProgress
// ne sert qu'à récupérer drapeau + nom localisé.
interface GeoRow {
  iso: string
  name: string
  flag: string
  owned: number
}
// Emoji drapeau dérivé de l'ISO alpha-2 (indicateurs régionaux) — couvre les
// micro-états absents de la fixture getCountryProgress.
function flagFromIso(iso: string): string {
  if (iso.length !== 2) return '🏳️'
  const base = 0x1f1e6
  return String.fromCodePoint(base + (iso.charCodeAt(0) - 65), base + (iso.charCodeAt(1) - 65))
}
const ownedCountries = computed<GeoRow[]>(() => {
  const byIso = new Map(getCountryProgress().map((c) => [c.iso, c]))
  const acc = new Map<string, GeoRow>()
  for (const e of store.collection) {
    const coin = getCoin(e.eurioId)
    if (!coin) continue
    const iso = coin.country.toUpperCase()
    const row = acc.get(iso)
    if (row) {
      row.owned += 1
    } else {
      const p = byIso.get(iso)
      acc.set(iso, { iso, name: p?.name ?? coin.countryName, flag: p?.flag ?? flagFromIso(iso), owned: 1 })
    }
  }
  return [...acc.values()].sort((a, z) => z.owned - a.owned)
})
const geoSummary = computed(() => ({
  coins: ownedCountries.value.reduce((n, c) => n + c.owned, 0),
  countries: ownedCountries.value.length,
}))
const topCountries = computed(() => ownedCountries.value.slice(0, 3))
const ownedIso = computed(() => new Set(ownedCountries.value.map((c) => c.iso)))

// Mini-carte (aperçu non interactif de la carte à gratter).
const contextPaths = Object.values(CONTEXT)
const geoPaths = computed(() =>
  Object.keys(GEO).map((iso) => ({ iso, d: GEO[iso].d, owned: ownedIso.value.has(iso) })),
)

// ───────── Aperçu des sets ─────────
const setsPreview = computed(() => {
  const all = getSets()
  const live = all
    .filter((s) => s.completedAt == null && s.owned > 0)
    .sort((a, z) => z.owned / z.total - a.owned / a.total)
  const rest = all.filter((s) => !(s.completedAt == null && s.owned > 0))
  return [...live, ...rest].slice(0, 3)
})
function setPct(owned: number, total: number): number {
  return total ? Math.round((owned / total) * 100) : 0
}

// ───────── Nav ─────────
function openCoin(coin: Coin) {
  router.push(`/coin/${encodeURIComponent(coin.eurioId)}?ctx=owned`)
}
</script>

<template>
  <section class="vault-home-root" data-scene="vault-summary" :data-empty="isEmpty ? 'true' : 'false'">
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

    <!-- ───────── Résumé ───────── -->
    <template v-else>
      <CoffreHeader active="summary" />

      <div class="summary-scroll">
        <!-- Meilleures pièces : carte spotlight -->
        <section v-if="showBest" class="summary-section" data-testid="vault-best">
          <div class="summary-section__head">
            <span class="summary-section__title">Tes meilleures pièces</span>
          </div>

          <div v-if="trophy" class="summary-spot" @click="openCoin(trophy.coin)">
            <span class="summary-spot__name">{{ trophy.coin.countryName }}<template v-if="trophy.coin.year"> · {{ trophy.coin.year }}</template></span>
            <div class="summary-spot__stage"><Spotlight3D :eurio-id="trophy.coin.eurioId" /></div>
            <div class="summary-spot__laurel">
              <span class="summary-spot__laurel-leaf" aria-hidden="true">🌿</span>
              <span class="summary-spot__value tabular">{{ trophy.metric }}</span>
              <span class="summary-spot__laurel-leaf summary-spot__laurel-leaf--flip" aria-hidden="true">🌿</span>
            </div>
            <span class="summary-spot__superlative">{{ trophy.icon }} {{ trophy.label }}</span>
          </div>

          <div v-if="trophies.length > 1" class="summary-spot__dots" role="tablist" aria-label="Catégories">
            <button v-for="(t, i) in trophies" :key="t.key" type="button" class="summary-spot__dot" :aria-selected="i === spotIndex" :aria-label="t.label" @click.stop="goSpot(i)"></button>
          </div>
        </section>

        <!-- Répartition géographique -->
        <section v-if="geoSummary.countries" class="summary-section">
          <div class="summary-section__head">
            <span class="summary-section__title">Répartition géographique</span>
          </div>
          <p class="summary-geo__lead">
            <strong>{{ geoSummary.coins }}</strong> {{ geoSummary.coins > 1 ? 'pièces réparties' : 'pièce' }} dans
            <strong>{{ geoSummary.countries }}</strong> {{ geoSummary.countries > 1 ? 'pays' : 'pays' }}
          </p>

          <button type="button" class="summary-geo__map" aria-label="Voir la répartition de tes pièces" @click="router.push('/vault/geo')">
            <svg viewBox="0 0 400 511" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Carte de l'eurozone">
              <path v-for="(d, i) in contextPaths" :key="`ctx-${i}`" :d="d" class="summary-geo__context" />
              <path v-for="c in geoPaths" :key="c.iso" :d="c.d" class="summary-geo__country" :class="{ 'is-owned': c.owned }" />
            </svg>
            <span class="summary-geo__expand" aria-hidden="true">
              <svg viewBox="0 0 24 24"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" /></svg>
            </span>
          </button>

          <div class="summary-geo__list">
            <button v-for="c in topCountries" :key="c.iso" type="button" class="summary-geo__row" @click="router.push('/vault/geo')">
              <span class="summary-geo__flag">{{ c.flag }}</span>
              <span class="summary-geo__country-name">{{ c.name }}</span>
              <span class="summary-geo__count tabular">{{ c.owned }} {{ c.owned > 1 ? 'pièces' : 'pièce' }}</span>
            </button>
          </div>

          <button type="button" class="summary-link" @click="router.push('/vault/geo')">Tout voir</button>
        </section>

        <!-- Aperçu des sets -->
        <section v-if="setsPreview.length" class="summary-section">
          <div class="summary-section__head">
            <span class="summary-section__title">Tes sets</span>
            <button type="button" class="summary-section__action" @click="router.push('/vault/sets')">Tout voir</button>
          </div>
          <div class="summary-sets">
            <button v-for="s in setsPreview" :key="s.id" type="button" class="summary-set" @click="router.push(`/vault/sets/${encodeURIComponent(s.id)}`)">
              <div class="summary-set__top">
                <span class="summary-set__title">{{ s.title }}</span>
                <span class="summary-set__count tabular">{{ s.owned }}/{{ s.total }}</span>
              </div>
              <div class="progress-bar"><div class="progress-track"><div class="progress-fill" :style="{ width: setPct(s.owned, s.total) + '%' }"></div></div></div>
            </button>
          </div>
        </section>

        <div style="height: var(--space-10)"></div>
      </div>
    </template>
  </section>
</template>

<style src="../../styles/vault-home.css"></style>
<style src="../../styles/vault-summary.css"></style>
