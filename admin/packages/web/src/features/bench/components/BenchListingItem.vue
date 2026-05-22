<script setup lang="ts">
import { computed, ref } from 'vue'
import { ImageOff } from 'lucide-vue-next'
import {
  type BenchGroupCoin, type BenchListing, shortEurio, verdictLabel,
} from '../composables/useBenchApi'

const props = defineProps<{
  listing: BenchListing
  coins: BenchGroupCoin[]
}>()

const open = ref(false)
const thumbBroken = ref(false)
const photoBroken = ref(false)

// La « vérité » humaine pointe-t-elle une pièce valide ?
const isValid = computed(
  () => props.listing.verdict.startsWith('coin:')
    || props.listing.verdict === 'ambiguous',
)
</script>

<template>
  <div class="border-t" style="border-color: var(--surface-3);">
    <!-- Ligne -->
    <button
      class="flex w-full items-center gap-2.5 py-1.5 pl-3 pr-2 text-left text-[12px] leading-snug transition-colors hover:bg-black/[0.02]"
      @click="open = !open"
    >
      <span
        class="h-1.5 w-1.5 flex-shrink-0 rounded-full"
        :style="`background: ${listing.agreement ? 'var(--success)' : 'var(--danger)'};`"
        :title="listing.agreement ? 'décision correcte' : 'désaccord avec le label humain'"
      />

      <!-- Vignette photo de l'annonce -->
      <span
        class="flex h-9 w-9 flex-shrink-0 items-center justify-center overflow-hidden rounded"
        style="background: var(--surface-2);"
      >
        <img
          v-if="listing.image_url && !thumbBroken"
          :src="listing.image_url"
          alt=""
          class="h-full w-full object-cover"
          loading="lazy"
          @error="thumbBroken = true"
        />
        <ImageOff v-else class="h-3.5 w-3.5" style="color: var(--ink-300);" />
      </span>

      <span class="min-w-0 flex-1 truncate" style="color: var(--ink);">
        {{ listing.title }}
      </span>

      <span
        v-if="listing.marketplace"
        class="flex-shrink-0 rounded px-1 py-px text-[10px]"
        style="background: var(--surface-2); color: var(--ink-400); font-family: var(--font-mono);"
      >{{ listing.marketplace }}</span>

      <span class="flex-shrink-0 whitespace-nowrap" style="color: var(--ink-400);">
        vérité
        <span
          :style="`font-family: var(--font-mono); color: ${
            isValid ? 'var(--indigo-700)' : 'var(--gold-700)'};`"
        >{{ verdictLabel(listing.verdict) }}</span>
      </span>
    </button>

    <!-- Comparaison dépliée : photo de l'annonce vs face(s) de pièce -->
    <div
      v-if="open"
      class="flex flex-wrap gap-3 px-3 pb-3 pl-[1.85rem]"
    >
      <!-- Photo de l'annonce eBay -->
      <figure class="w-44">
        <div
          class="flex aspect-square items-center justify-center overflow-hidden rounded-lg border"
          style="border-color: var(--surface-3); background: var(--surface-2);"
        >
          <img
            v-if="listing.image_url && !photoBroken"
            :src="listing.image_url"
            alt="Photo de l'annonce eBay"
            class="h-full w-full object-contain"
            @error="photoBroken = true"
          />
          <div v-else class="flex flex-col items-center gap-1">
            <ImageOff class="h-5 w-5" style="color: var(--ink-300);" />
            <span class="text-[10px]" style="color: var(--ink-400);">pas d'image</span>
          </div>
        </div>
        <figcaption
          class="mt-1 text-[10px] uppercase tracking-wide"
          style="color: var(--ink-400);"
        >Annonce eBay — brut</figcaption>
      </figure>

      <!-- Face(s) des pièces visées par la recherche -->
      <figure v-for="coin in coins" :key="coin.eurio_id" class="w-44">
        <div
          class="flex aspect-square items-center justify-center overflow-hidden rounded-lg border"
          style="border-color: var(--indigo-200, #cdd0ec); background: var(--surface);"
        >
          <img
            v-if="coin.obverse_url"
            :src="coin.obverse_url"
            :alt="`Face — ${coin.theme}`"
            class="h-full w-full object-contain"
          />
          <ImageOff v-else class="h-5 w-5" style="color: var(--ink-300);" />
        </div>
        <figcaption
          class="mt-1 truncate text-[10px] uppercase tracking-wide"
          style="color: var(--indigo-700);"
        >Face — {{ shortEurio(coin.eurio_id) }}</figcaption>
      </figure>
    </div>
  </div>
</template>
