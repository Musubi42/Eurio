<script setup lang="ts">
import { Info } from 'lucide-vue-next'
import { computed } from 'vue'

const props = defineProps<{
  kind: string
  label?: string | null
  title?: string | null
  active?: boolean
}>()

const emit = defineEmits<{ (e: 'select'): void }>()

// Libellé court FR par variant_kind (le label complet va dans le tooltip).
const KIND_SHORT: Record<string, string> = {
  classic: 'Classique',
  coloured: 'Colorisée',
  hologram: 'Hologramme',
  gilded: 'Dorée',
  mule: 'Mule',
  pattern: 'Essai',
  'mis-strike': 'Erreur',
  other: 'Variante',
}
const shortLabel = computed(() => KIND_SHORT[props.kind] ?? props.kind)
const tooltip = computed(() => props.label || props.title || shortLabel.value)
</script>

<template>
  <button
    type="button"
    class="variant-badge group"
    :class="{ 'variant-badge--active': active }"
    @click="emit('select')"
  >
    <span class="variant-badge__text">{{ shortLabel }}</span>
    <span class="variant-badge__info">
      <Info :size="11" :stroke-width="2.25" />
      <span class="variant-badge__tip" role="tooltip">{{ tooltip }}</span>
    </span>
  </button>
</template>

<style scoped>
.variant-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px 2px 8px;
  border-radius: 9999px;
  border: 1px solid var(--indigo-300);
  background: var(--indigo-50);
  color: var(--indigo-600);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
}
.variant-badge:hover {
  background: var(--indigo-100);
}
.variant-badge--active {
  border-color: var(--gold);
  background: var(--gold);
  color: #fff;
  cursor: default;
}
.variant-badge__info {
  position: relative;
  display: inline-flex;
  align-items: center;
  opacity: 0.7;
}
.variant-badge__tip {
  position: absolute;
  bottom: calc(100% + 6px);
  right: 0;
  z-index: 30;
  white-space: nowrap;
  padding: 4px 8px;
  border-radius: 6px;
  background: var(--ink-700, #1f2433);
  color: #fff;
  font-size: 11px;
  font-weight: 500;
  text-transform: none;
  letter-spacing: normal;
  opacity: 0;
  pointer-events: none;
  transform: translateY(2px);
  transition: opacity 0.12s, transform 0.12s;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.18);
}
.variant-badge:hover .variant-badge__tip {
  opacity: 1;
  transform: translateY(0);
}
</style>
