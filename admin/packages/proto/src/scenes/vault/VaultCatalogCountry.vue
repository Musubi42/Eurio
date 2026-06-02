<script setup lang="ts">
/* Scène vault-catalog-country — planche complète d'un pays (drill-down).
 * Port de vault-catalog-country.html/.js. Fixture démo, fallback FR. */
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getCountryPlanche } from '@/api'
import type { PlancheCoin } from '@/api'

const route = useRoute()
const router = useRouter()

const country = computed(() => getCountryPlanche(String(route.params.iso ?? 'FR')))

const filter = ref<'all' | 'circulation' | 'commemo'>('all')
const coins = computed(() => (filter.value === 'all' ? country.value.coins : country.value.coins.filter((c) => c.type === filter.value)))

const ownedCount = computed(() => country.value.coins.filter((c) => c.owned).length)
const total = computed(() => country.value.coins.length)
const pct = computed(() => Math.round((ownedCount.value / total.value) * 100))

const FILTERS = [
  { id: 'all', label: 'Tout' },
  { id: 'circulation', label: 'Circulation' },
  { id: 'commemo', label: 'Commémos' },
] as const

function formatDateShort(iso: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  return `${String(d.getDate()).padStart(2, '0')}·${String(d.getMonth() + 1).padStart(2, '0')}·${String(d.getFullYear()).slice(2)}`
}

// Long-press case manquante (mock)
const toastText = ref('')
const toastOpen = ref(false)
let toastTimer: ReturnType<typeof setTimeout> | null = null
let pressTimer: ReturnType<typeof setTimeout> | null = null
function toast(t: string) {
  toastText.value = t
  toastOpen.value = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toastOpen.value = false), 1800)
}
function pressStart(c: PlancheCoin) {
  if (c.owned) return
  pressTimer = setTimeout(() => toast(`Marquer ${c.val} comme possédée ?`), 550)
}
function pressCancel() {
  if (pressTimer) clearTimeout(pressTimer)
}
function openCoin(c: PlancheCoin) {
  router.push(`/coin/${encodeURIComponent(c.eurioId)}`)
}
</script>

<template>
  <section class="scene-vcc-root" data-scene="vault-catalog-country">
    <div class="scene-vcc-topbar">
      <a class="scene-vcc-back" data-testid="catalog-country-back" @click.prevent="router.push('/vault/catalog')">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7" /></svg>
        <span>Carte</span>
      </a>
      <button type="button" class="scene-vcc-topbar__more" aria-label="Plus d'options">
        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="19" cy="12" r="1.5" /></svg>
      </button>
    </div>

    <header class="scene-vcc-hero">
      <div class="scene-vcc-flag">{{ country.flag }}</div>
      <div class="scene-vcc-hero__body">
        <div class="scene-vcc-hero__eyebrow">Catalogue · pays</div>
        <h1 class="scene-vcc-hero__name">{{ country.name }}</h1>
        <div class="scene-vcc-hero__ratio"><strong>{{ ownedCount }} / {{ total }}</strong> possédées · <span>{{ pct }}%</span></div>
        <div class="scene-vcc-hero__bar progress-bar"><div class="progress-track"><div class="progress-fill" :style="{ width: pct + '%' }"></div></div></div>
      </div>
    </header>

    <div class="scene-vcc-filters">
      <div class="scene-vcc-filter-row" role="radiogroup" aria-label="Filtrer par type d'émission">
        <button v-for="f in FILTERS" :key="f.id" type="button" :data-filter="f.id" :aria-selected="filter === f.id" @click="filter = f.id">{{ f.label }}</button>
      </div>
    </div>

    <div class="scene-vcc-planche-wrap">
      <div class="scene-vcc-section-head">
        <h2>Planche du pays</h2>
        <span class="scene-vcc-section-head__count">{{ coins.length }} pièces</span>
      </div>
      <div class="planche">
        <div class="planche__grid">
          <div
            v-for="c in coins"
            :key="c.eurioId"
            :class="c.owned ? 'planche__cell' : 'planche__cell planche__cell--missing'"
            :data-owned="c.owned ? 'true' : 'false'"
            @click="openCoin(c)"
            @pointerdown="pressStart(c)"
            @pointerup="pressCancel"
            @pointerleave="pressCancel"
            @pointercancel="pressCancel"
          >
            <div class="disc" :class="c.owned ? `disc--${c.metal}` : 'disc--missing'"><span class="disc__val">{{ c.val }}</span></div>
            <span v-if="c.owned && formatDateShort(c.scannedAt)" class="planche__cell__date">{{ formatDateShort(c.scannedAt) }}</span>
          </div>
        </div>
      </div>
    </div>

    <div style="height: var(--space-10)"></div>
    <div class="toast" :data-visible="toastOpen ? 'true' : 'false'" role="status">{{ toastText }}</div>
  </section>
</template>

<style src="../../styles/vault-catalog-country.css"></style>
