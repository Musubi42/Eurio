<script setup lang="ts">
import { ImageOff } from 'lucide-vue-next'
import { ML_API } from '../composables/useAugmentationApi'
import type { PreviewImage } from '../types'

defineProps<{
  images: PreviewImage[]
  count: number
  loading: boolean
  error?: string | null
}>()

defineEmits<{
  (event: 'open-lightbox', url: string, index: number): void
}>()

function absoluteUrl(u: string): string {
  if (u.startsWith('http')) return u
  return `${ML_API}${u}`
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <div
      v-if="error"
      class="rounded-md border px-3 py-2 text-xs"
      style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);"
    >
      {{ error }}
    </div>

    <div class="grid grid-cols-4 gap-2">
      <template v-if="loading || images.length === 0">
        <div
          v-for="i in count"
          :key="`skel-${i}`"
          class="aspect-square animate-pulse rounded-md"
          style="background: var(--surface-1);"
        />
      </template>
      <template v-else>
        <button
          v-for="img in images"
          :key="img.index"
          type="button"
          class="group relative overflow-hidden rounded-md border transition-transform hover:-translate-y-0.5"
          style="background: var(--surface-1); border-color: var(--surface-3); aspect-ratio: 1/1;"
          @click="$emit('open-lightbox', absoluteUrl(img.url), img.index)"
        >
          <img
            :src="absoluteUrl(img.url)"
            :alt="`Variation ${img.index}`"
            class="h-full w-full object-contain p-1 transition-opacity"
            loading="lazy"
            @error="(e) => { (e.target as HTMLImageElement).style.opacity = '0.15' }"
          />
          <span
            class="pointer-events-none absolute left-1 top-1 rounded px-1 py-0.5 font-mono text-[9px] tabular-nums opacity-0 transition-opacity group-hover:opacity-100"
            style="background: rgba(0,0,0,0.6); color: white;"
          >#{{ img.index }}</span>
        </button>
      </template>
    </div>

    <div
      v-if="!loading && images.length === 0 && !error"
      class="flex items-center justify-center rounded-md border py-8 text-xs"
      style="border-color: var(--surface-3); color: var(--ink-400);"
    >
      <ImageOff class="mr-2 h-3.5 w-3.5" />
      Aucune variation — clique Regenerate.
    </div>
  </div>
</template>
