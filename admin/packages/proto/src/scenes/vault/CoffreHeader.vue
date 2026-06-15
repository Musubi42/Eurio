<script setup lang="ts">
/* Header patrimoine sobre, partagé par les trois onglets du Coffre (Summary /
 * All / Sets). Inspiré du flow CoinSnap : valeur totale en hero + « N Pièces |
 * N Pays » + onglets segmentés. Lit le store collection (source unique). */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { getCoin } from '@/api'
import { useCollectionStore } from '@/stores/collection'
import type { CollectionEntry } from '@/stores/collection'
import CoffreTabs from './CoffreTabs.vue'

defineProps<{ active: 'summary' | 'all' | 'sets' }>()
const router = useRouter()
const store = useCollectionStore()

// Valeur de référence d'une entrée : valeur à l'ajout, repli sur la faciale.
function referenceCents(entry: CollectionEntry): number {
  return entry.valueAtAddCents ?? getCoin(entry.eurioId)?.faceValueCents ?? 0
}
const totalCents = computed(() => store.collection.reduce((sum, e) => sum + referenceCents(e), 0))
const valueInt = computed(() => Math.floor(totalCents.value / 100).toLocaleString('fr-FR'))
const coinCount = computed(() => store.collection.length)
const countryCount = computed(
  () => new Set(store.collection.map((e) => getCoin(e.eurioId)?.country).filter(Boolean)).size,
)
</script>

<template>
  <header class="coffre-header">
    <div class="coffre-header__top">
      <div class="coffre-header__actions">
        <button type="button" class="coffre-header__icon" aria-label="Rechercher" @click="router.push('/vault/search')">
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>
        </button>
        <button type="button" class="coffre-header__icon" aria-label="Exporter">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m0 0l-5-5m5 5l5-5M3 21h18" /></svg>
        </button>
        <button type="button" class="coffre-header__icon" aria-label="Plus d'options">
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.3" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none" /><circle cx="19" cy="12" r="1.3" fill="currentColor" stroke="none" /></svg>
        </button>
      </div>
    </div>

    <div class="coffre-header__value">
      <div class="coffre-header__amount tabular"><span>{{ valueInt }}</span><span class="coffre-header__euro">€</span></div>
      <span class="coffre-header__value-label">Valeur du coffre</span>
    </div>

    <div class="coffre-header__stats">
      <div class="coffre-stat">
        <span class="coffre-stat__value tabular">{{ coinCount }}</span>
        <span class="coffre-stat__label">{{ coinCount > 1 ? 'Pièces' : 'Pièce' }}</span>
      </div>
      <div class="coffre-stat">
        <span class="coffre-stat__value tabular">{{ countryCount }}</span>
        <span class="coffre-stat__label">{{ countryCount > 1 ? 'Pays' : 'Pays' }}</span>
      </div>
    </div>

    <CoffreTabs :active="active" />
  </header>
</template>
