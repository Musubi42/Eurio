<script setup lang="ts">
import { computed } from 'vue'
import { Inbox, MousePointerClick } from 'lucide-vue-next'
import type { FunnelNode } from '../composables/useBenchApi'
import BenchListingCard from './BenchListingCard.vue'

const props = defineProps<{ node: FunnelNode | null }>()

const nDisagreements = computed(
  () => props.node?.listings.filter(l => !l.agreement).length ?? 0,
)
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- En-tête -->
    <div
      class="flex flex-shrink-0 items-center gap-2 border-b px-5 py-3"
      style="border-color: var(--surface-3);"
    >
      <Inbox class="h-4 w-4" style="color: var(--ink-400);" />
      <h3 class="text-[13px] font-semibold" style="color: var(--ink);">
        {{ node ? node.label : 'Annonces du filtre' }}
      </h3>
      <span v-if="node" class="text-[12px]" style="color: var(--ink-400);">
        {{ node.listings.length }} annonce{{ node.listings.length > 1 ? 's' : '' }}
      </span>
      <span
        v-if="node && nDisagreements > 0"
        class="rounded-full px-2 py-0.5 text-[10.5px] font-semibold"
        style="background: var(--danger-soft, #f6dcd6); color: var(--danger);"
      >⚠ {{ nDisagreements }} désaccord(s)</span>
    </div>

    <!-- Corps -->
    <div class="flex-1 overflow-y-auto px-5 py-5">
      <!-- Aucun nœud choisi -->
      <div
        v-if="!node"
        class="flex h-full flex-col items-center justify-center gap-2 text-center"
      >
        <MousePointerClick class="h-7 w-7" style="color: var(--ink-300);" />
        <p class="text-[13px] italic"
           style="font-family: var(--font-display); color: var(--ink-400);">
          Clique une étape de l'entonnoir<br />pour voir ses annonces.
        </p>
      </div>

      <p
        v-else-if="node.listings.length === 0"
        class="py-10 text-center italic"
        style="font-family: var(--font-display); color: var(--ink-400);"
      >Aucune annonce à cette étape.</p>

      <div
        v-else
        class="grid gap-3.5"
        style="grid-template-columns: repeat(auto-fill, minmax(185px, 1fr));"
      >
        <BenchListingCard
          v-for="l in node.listings"
          :key="l.listing_id"
          :listing="l"
        />
      </div>
    </div>
  </div>
</template>
