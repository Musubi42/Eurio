<script setup lang="ts">
import { computed } from 'vue'
import { type BenchListing, verdictLabel } from '../composables/useBenchApi'

const props = defineProps<{ listing: BenchListing }>()

// La « vérité » humaine pointe-t-elle une pièce valide ?
const isValid = computed(
  () => props.listing.verdict.startsWith('coin:')
    || props.listing.verdict === 'ambiguous',
)
</script>

<template>
  <div class="flex items-baseline gap-2.5 py-1.5 pl-3 pr-2 text-[12px] leading-snug">
    <!-- Pastille d'accord : le pipeline a-t-il eu raison ? -->
    <span
      class="mt-1 h-1.5 w-1.5 flex-shrink-0 rounded-full"
      :style="`background: ${listing.agreement ? 'var(--success)' : 'var(--danger)'};`"
      :title="listing.agreement ? 'décision correcte' : 'désaccord avec le label humain'"
    />

    <span class="min-w-0 flex-1 truncate" style="color: var(--ink);">
      {{ listing.title }}
    </span>

    <span
      v-if="listing.marketplace"
      class="flex-shrink-0 rounded px-1 py-px text-[10px]"
      style="background: var(--surface-2); color: var(--ink-400); font-family: var(--font-mono);"
    >{{ listing.marketplace }}</span>

    <!-- Le verdict humain = la vérité de référence -->
    <span class="flex-shrink-0 whitespace-nowrap" style="color: var(--ink-400);">
      vérité
      <span
        :style="`font-family: var(--font-mono); color: ${
          isValid ? 'var(--indigo-700)' : 'var(--gold-700)'};`"
      >{{ verdictLabel(listing.verdict) }}</span>
    </span>
  </div>
</template>
