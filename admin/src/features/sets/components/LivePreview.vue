<script setup lang="ts">
import type { Coin, SetCriteria } from '@/shared/supabase/types'
import { firstImageUrl } from '@/shared/utils/coin-images'
import { AlertCircle, CheckCircle2, ImageOff, Loader2 } from 'lucide-vue-next'
import { computed, toRef } from 'vue'
import { useCriteriaPreview } from '../composables/useCriteriaPreview'

const props = defineProps<{
  criteria: SetCriteria | null
  expectedCount?: number | null
}>()

const criteriaRef = toRef(props, 'criteria')
const { count, samples, loading, error, isEmpty } = useCriteriaPreview(criteriaRef)

const countStatus = computed(() => {
  if (isEmpty.value) return 'idle'
  if (loading.value) return 'loading'
  if (error.value) return 'error'
  if (props.expectedCount != null && count.value !== props.expectedCount) return 'mismatch'
  if (count.value === 0) return 'empty'
  return 'ok'
})

function firstImage(coin: Coin): string | null {
  return firstImageUrl(coin)
}
</script>

<template>
  <section class="rounded-lg border"
           style="border-color: var(--surface-3); background: var(--surface);">

    <!-- Header with count -->
    <div class="flex items-center justify-between border-b px-4 py-3"
         style="border-color: var(--surface-3);">
      <div class="flex items-center gap-2">
        <p class="text-[10px] font-medium uppercase tracking-widest"
           style="color: var(--ink-500);">
          Live preview
        </p>
        <Loader2 v-if="loading" class="h-3 w-3 animate-spin" style="color: var(--ink-400);" />
      </div>

      <div v-if="!isEmpty" class="flex items-center gap-2 font-mono text-sm">
        <template v-if="countStatus === 'error'">
          <AlertCircle class="h-4 w-4" style="color: var(--danger);" />
          <span style="color: var(--danger);">Erreur</span>
        </template>
        <template v-else-if="countStatus === 'empty'">
          <AlertCircle class="h-4 w-4" style="color: var(--warning);" />
          <span style="color: var(--warning);">Aucune pièce</span>
        </template>
        <template v-else-if="countStatus === 'mismatch'">
          <AlertCircle class="h-4 w-4" style="color: var(--warning);" />
          <span style="color: var(--warning);">
            {{ count }} pièce{{ count > 1 ? 's' : '' }}
            <span class="text-[10px]">(attendu : {{ expectedCount }})</span>
          </span>
        </template>
        <template v-else>
          <CheckCircle2 class="h-4 w-4" style="color: var(--success);" />
          <span style="color: var(--ink);">
            <strong>{{ count }}</strong> pièce{{ count > 1 ? 's' : '' }}
          </span>
        </template>
      </div>
    </div>

    <!-- Body -->
    <div class="p-3">
      <!-- Idle -->
      <p v-if="isEmpty" class="py-6 text-center text-xs" style="color: var(--ink-400);">
        Sélectionne au moins un critère pour prévisualiser les pièces qui matchent.
      </p>

      <!-- Error -->
      <p v-else-if="error" class="py-6 text-center text-xs font-mono" style="color: var(--danger);">
        {{ error }}
      </p>

      <!-- Empty -->
      <div v-else-if="!loading && count === 0"
           class="flex flex-col items-center justify-center py-6">
        <AlertCircle class="mb-2 h-5 w-5" style="color: var(--warning);" />
        <p class="text-xs" style="color: var(--ink-500);">
          Aucune pièce ne matche ces critères.
        </p>
      </div>

      <!-- Loading skeleton -->
      <div v-else-if="loading && samples.length === 0"
           class="grid grid-cols-6 gap-2 sm:grid-cols-8 lg:grid-cols-12">
        <div v-for="i in 12" :key="i"
             class="aspect-square animate-pulse rounded"
             style="background: var(--surface-1);" />
      </div>

      <!-- Samples grid -->
      <div v-else class="grid grid-cols-6 gap-2 sm:grid-cols-8 lg:grid-cols-12">
        <div
          v-for="coin in samples.slice(0, 24)"
          :key="coin.eurio_id"
          class="group relative aspect-square overflow-hidden rounded"
          style="background: var(--surface-1);"
          :title="`${coin.country} ${coin.year} — ${coin.theme ?? coin.eurio_id}`"
        >
          <img
            v-if="firstImage(coin)"
            :src="firstImage(coin)!"
            :alt="coin.eurio_id"
            class="h-full w-full object-contain p-1"
            loading="lazy"
          />
          <div v-else class="flex h-full w-full items-center justify-center"
               style="color: var(--ink-300);">
            <ImageOff class="h-3 w-3" />
          </div>
          <span class="absolute bottom-0 left-0 right-0 truncate bg-black/60 px-1 text-[9px] font-mono text-white">
            {{ coin.country }} {{ coin.year }}
          </span>
        </div>
      </div>
    </div>
  </section>
</template>
