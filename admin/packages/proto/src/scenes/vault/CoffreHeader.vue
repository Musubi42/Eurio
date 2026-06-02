<script setup lang="ts">
/* Header partagé des sous-vues Coffre (sets-list, catalog). Eyebrow + actions
 * + onglets segmentés. Port du pattern .coffre-header (components.css). */
import CoffreTabs from './CoffreTabs.vue'

defineProps<{ active: 'coins' | 'sets' | 'catalog' }>()
</script>

<template>
  <header class="coffre-header">
    <div class="coffre-header__top">
      <span class="eyebrow">Ton coffre</span>
      <div class="coffre-header__actions">
        <button type="button" class="coffre-header__icon" aria-label="Rechercher">
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>
        </button>
        <button type="button" class="coffre-header__icon" aria-label="Plus d'options">
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.3" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none" /><circle cx="19" cy="12" r="1.3" fill="currentColor" stroke="none" /></svg>
        </button>
      </div>
    </div>
    <CoffreTabs :active="active" />
  </header>
</template>
