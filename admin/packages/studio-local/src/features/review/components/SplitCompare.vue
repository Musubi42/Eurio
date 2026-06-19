<script setup lang="ts">
defineProps<{
  cropUrl: string
  canonicalUrl: string | null
  bbox: { x: number; y: number; w: number; h: number } | null
}>()
</script>

<template>
  <div class="grid grid-cols-2 gap-3">
    <!-- CROP À RÉSOUDRE -->
    <figure class="flex flex-col gap-2">
      <figcaption
        class="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--ink-500);"
      >
        <span class="h-1.5 w-1.5 rounded-full" style="background: var(--indigo-700);"></span>
        Crop à résoudre
      </figcaption>
      <div
        class="relative aspect-square overflow-hidden rounded-lg border"
        style="border-color: var(--surface-3); background: var(--surface-1);"
      >
        <img :src="cropUrl" alt="crop à résoudre" class="h-full w-full object-cover" />
        <span
          v-if="bbox"
          class="absolute bottom-2 left-2 inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-mono text-[10px]"
          style="background: rgba(14,14,31,.78); color: var(--surface);"
        >
          bbox · {{ bbox.x }},{{ bbox.y }} · {{ bbox.w }}×{{ bbox.h }}
        </span>
      </div>
    </figure>

    <!-- IMAGE CANONIQUE DU CANDIDAT FOCUSÉ -->
    <figure class="flex flex-col gap-2">
      <figcaption
        class="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--ink-500);"
      >
        <span class="h-1.5 w-1.5 rounded-full" style="background: var(--gold-600);"></span>
        Canonique · candidat focusé
      </figcaption>
      <div
        class="relative aspect-square overflow-hidden rounded-lg border"
        style="border-color: var(--surface-3); background: var(--surface-1);"
      >
        <img
          v-if="canonicalUrl"
          :src="canonicalUrl"
          alt="canonique candidat"
          class="h-full w-full object-cover"
        />
        <div
          v-else
          class="flex h-full w-full flex-col items-center justify-center text-center"
        >
          <p class="font-display text-sm italic" style="color: var(--ink-400);">
            Aucun candidat focusé
          </p>
          <p class="mt-1 font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-400);">
            Touche 1 – 5 ou F
          </p>
        </div>
      </div>
    </figure>
  </div>
</template>
