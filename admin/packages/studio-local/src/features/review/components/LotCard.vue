<script setup lang="ts">
import { Image as ImageIcon, Layers, Package } from 'lucide-vue-next'
import type { LotListItem } from '../composables/useLotReview'

defineProps<{ lot: LotListItem }>()
defineEmits<{ (e: 'open', listingKey: string): void }>()

function formatRelative(iso: string): string {
  const d = new Date(iso.replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return iso
  const diffMs = Date.now() - d.getTime()
  const days = Math.floor(diffMs / 86400000)
  if (days >= 1) return `il y a ${days}j`
  const hours = Math.floor(diffMs / 3600000)
  if (hours >= 1) return `il y a ${hours}h`
  const mins = Math.floor(diffMs / 60000)
  return mins >= 1 ? `il y a ${mins}min` : 'à l\'instant'
}
</script>

<template>
  <article
    class="group flex cursor-pointer flex-col overflow-hidden rounded-lg border transition-colors"
    style="border-color: var(--surface-3); background: var(--surface);"
    @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.borderColor = 'var(--gold-600)')"
    @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.borderColor = 'var(--surface-3)')"
    @click="$emit('open', lot.listing_key)"
  >
    <!-- Thumbnail -->
    <div
      class="relative aspect-[4/3] w-full overflow-hidden"
      style="background: var(--surface-1);"
    >
      <img
        v-if="lot.thumb_url"
        :src="lot.thumb_url"
        :alt="lot.listing_title ?? lot.listing_key"
        class="h-full w-full object-cover transition-transform group-hover:scale-[1.02]"
        loading="lazy"
      />
      <div
        v-else
        class="flex h-full w-full items-center justify-center"
        style="color: var(--ink-400);"
      >
        <ImageIcon class="h-8 w-8" />
      </div>
      <!-- Badge type -->
      <div class="absolute left-2 top-2 inline-flex items-center gap-1">
        <span
          v-if="lot.is_lot_suspected"
          class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[10px] font-semibold backdrop-blur"
          style="background: color-mix(in srgb, var(--gold-600) 90%, transparent); color: white;"
        >
          <Package class="h-2.5 w-2.5" />
          Lot
        </span>
        <span
          v-else
          class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[10px] font-semibold backdrop-blur"
          style="background: color-mix(in srgb, var(--indigo-700) 90%, transparent); color: white;"
        >
          <Layers class="h-2.5 w-2.5" />
          Multi-crop
        </span>
      </div>
      <!-- Count crops -->
      <div
        class="absolute right-2 bottom-2 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-[10px]"
        style="background: rgba(14,14,31,.78); color: white;"
      >
        {{ lot.n_crops_in_review }} crop{{ lot.n_crops_in_review > 1 ? 's' : '' }}
        <span class="opacity-60">/ {{ lot.n_images }} img</span>
      </div>
    </div>

    <!-- Body -->
    <div class="flex flex-1 flex-col gap-2 px-3 py-2.5">
      <p
        class="line-clamp-2 font-display text-[13px] italic leading-snug"
        style="color: var(--ink);"
        :title="lot.listing_title ?? ''"
      >
        « {{ lot.listing_title ?? '— sans titre —' }} »
      </p>
      <div class="flex items-baseline justify-between font-mono text-[10px]" style="color: var(--ink-500);">
        <span>
          <span class="opacity-70">src&nbsp;·</span>
          <span class="ml-1" style="color: var(--ink-700);">{{ lot.source }}</span>
          <span v-if="lot.listing_price !== null" class="ml-3 opacity-70">prix&nbsp;·</span>
          <span v-if="lot.listing_price !== null" class="ml-1" style="color: var(--ink-700);">
            {{ lot.listing_price.toFixed(2) }}€
          </span>
        </span>
        <span class="opacity-60">{{ formatRelative(lot.oldest_enqueued_at) }}</span>
      </div>
      <p
        v-if="lot.target_eurio_id"
        class="truncate font-mono text-[10px]"
        style="color: var(--ink-400);"
        :title="lot.target_eurio_id"
      >
        cible · <span style="color: var(--indigo-700);">{{ lot.target_eurio_id }}</span>
      </p>
    </div>
  </article>
</template>
