<script setup lang="ts">
/* Onglets segmentés du Coffre (Summary / All / Sets) — partagé par les trois
 * sous-vues. Route vers chaque onglet. Le Catalogue (carte à gratter) n'a plus
 * d'onglet : il devient le « Tout voir » de la répartition géographique du
 * Summary. */
import { useRouter } from 'vue-router'

defineProps<{ active: 'summary' | 'all' | 'sets'; navClass?: string }>()
const router = useRouter()

const TABS = [
  { id: 'summary', label: 'Résumé', path: '/vault' },
  { id: 'all', label: 'Pièces', path: '/vault/all' },
  { id: 'sets', label: 'Sets', path: '/vault/sets' },
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
