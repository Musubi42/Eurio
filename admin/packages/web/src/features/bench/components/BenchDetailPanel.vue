<script setup lang="ts">
import { Coins, Inbox } from 'lucide-vue-next'
import type { FunnelNode, SearchFunnel } from '../composables/useBenchApi'
import BenchCoinCard from './BenchCoinCard.vue'
import BenchListingCard from './BenchListingCard.vue'

const props = defineProps<{
  search: SearchFunnel
  node: FunnelNode | null
}>()

function disagreements(node: FunnelNode): number {
  return node.listings.filter(l => !l.agreement).length
}
void props
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- En-tête du panneau -->
    <div
      class="flex items-center gap-2 border-b px-5 py-3"
      style="border-color: var(--surface-3);"
    >
      <component
        :is="node ? Inbox : Coins"
        class="h-4 w-4" style="color: var(--ink-400);"
      />
      <h3 class="text-[13px] font-semibold" style="color: var(--ink);">
        {{ node ? node.label : 'Pièces de la recherche' }}
      </h3>
      <span v-if="node" class="text-[12px]" style="color: var(--ink-400);">
        {{ node.listings.length }} annonce{{ node.listings.length > 1 ? 's' : '' }}
      </span>
      <span
        v-if="node && disagreements(node) > 0"
        class="rounded-full px-2 py-0.5 text-[10.5px] font-semibold"
        style="background: var(--danger-soft, #f6dcd6); color: var(--danger);"
      >⚠ {{ disagreements(node) }} désaccord(s)</span>
      <span v-else-if="!node" class="text-[12px]" style="color: var(--ink-400);">
        {{ search.coins.length }} commémo-sœur(s) à départager
      </span>
    </div>

    <!-- Corps -->
    <div class="flex-1 overflow-y-auto px-5 py-5">
      <!-- Vue pièces canoniques -->
      <div
        v-if="!node"
        class="grid gap-4"
        style="grid-template-columns: repeat(auto-fill, minmax(260px, 340px));"
      >
        <BenchCoinCard
          v-for="coin in search.coins"
          :key="coin.eurio_id"
          :coin="coin"
        />
      </div>

      <!-- Vue annonces -->
      <template v-else>
        <p
          v-if="node.listings.length === 0"
          class="py-10 text-center italic"
          style="font-family: var(--font-display); color: var(--ink-400);"
        >Aucune annonce à cette étape.</p>
        <div
          v-else
          class="grid gap-3.5"
          style="grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));"
        >
          <BenchListingCard
            v-for="l in node.listings"
            :key="l.listing_id"
            :listing="l"
          />
        </div>
      </template>
    </div>
  </div>
</template>
