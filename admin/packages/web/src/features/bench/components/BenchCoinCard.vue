<script setup lang="ts">
import { ImageOff } from 'lucide-vue-next'
import { type BenchGroupCoin, shortEurio } from '../composables/useBenchApi'

defineProps<{ coin: BenchGroupCoin }>()
</script>

<template>
  <article
    class="flex flex-col overflow-hidden rounded-2xl border"
    style="border-color: var(--surface-3); background: var(--surface);"
  >
    <!-- Face de la pièce, en grand -->
    <div
      class="flex aspect-square items-center justify-center overflow-hidden p-4"
      style="background: var(--paper);"
    >
      <img
        v-if="coin.obverse_url"
        :src="coin.obverse_url"
        :alt="coin.theme ?? coin.eurio_id"
        class="h-full w-full object-contain"
        style="filter: drop-shadow(0 6px 14px rgba(14,14,31,0.18));"
      />
      <ImageOff v-else class="h-8 w-8" style="color: var(--ink-300);" />
    </div>

    <div class="border-t px-4 py-3" style="border-color: var(--surface-3);">
      <div
        class="text-[12px]"
        style="font-family: var(--font-mono); color: var(--indigo-700);"
      >{{ shortEurio(coin.eurio_id) }}</div>
      <div
        class="mt-0.5 text-[15px] italic leading-snug"
        style="font-family: var(--font-display); font-weight: 600; color: var(--ink);"
      >{{ coin.theme }}</div>

      <!-- Titres i18n -->
      <div class="mt-2.5 space-y-0.5">
        <div
          v-for="(title, lang) in coin.i18n"
          :key="lang"
          class="flex gap-2 text-[11.5px]"
        >
          <span
            class="w-5 flex-shrink-0 uppercase"
            style="color: var(--ink-300); font-family: var(--font-mono);"
          >{{ lang }}</span>
          <span style="color: var(--ink-500);">{{ title }}</span>
        </div>
      </div>

      <!-- Alias de marché -->
      <div v-if="coin.aliases.length" class="mt-2.5 flex flex-wrap items-center gap-1">
        <span class="mr-0.5 text-[10px] uppercase tracking-wide"
              style="color: var(--ink-400);">alias</span>
        <span
          v-for="a in coin.aliases"
          :key="a"
          class="rounded px-1.5 py-0.5 text-[10px]"
          style="background: var(--gold-100); color: var(--gold-700); font-family: var(--font-mono);"
        >{{ a }}</span>
      </div>
    </div>
  </article>
</template>
