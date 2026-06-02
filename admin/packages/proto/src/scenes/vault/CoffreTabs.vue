<script setup lang="ts">
/* Onglets segmentés du Coffre (Mes pièces / Sets / Catalogue) — partagé par
 * vault-home, sets-list, catalog. Route vers les sous-vues. */
import { useRouter } from 'vue-router'

defineProps<{ active: 'coins' | 'sets' | 'catalog'; navClass?: string }>()
const router = useRouter()

const TABS = [
  { id: 'coins', label: 'Mes pièces', path: '/vault' },
  { id: 'sets', label: 'Sets', path: '/vault/sets' },
  { id: 'catalog', label: 'Catalogue', path: '/vault/catalog' },
] as const
</script>

<template>
  <nav class="tabbed-nav" :class="navClass" role="tablist" aria-label="Vues du coffre">
    <button
      v-for="t in TABS"
      :key="t.id"
      type="button"
      role="tab"
      :aria-selected="active === t.id"
      :data-coffre-tab="t.id"
      @click="router.push(t.path)"
    >
      {{ t.label }}
    </button>
  </nav>
</template>
