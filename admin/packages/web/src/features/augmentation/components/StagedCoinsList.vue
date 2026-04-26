<script setup lang="ts">
import { zoneStyle } from '@/features/confusion/composables/useConfusionZone'
import type { Coin, ConfusionZone } from '@/shared/supabase/types'
import { firstImageUrl } from '@/shared/utils/coin-images'
import { ImageOff } from 'lucide-vue-next'

defineProps<{
  coins: Coin[]
  activeIndex: number
  zoneByEurioId: Record<string, ConfusionZone | null>
  statusByEurioId: Record<string, 'pending' | 'done' | 'error' | undefined>
}>()

defineEmits<{
  (e: 'select', index: number): void
}>()

function statusSymbol(status: string | undefined): string {
  if (status === 'done') return '✓'
  if (status === 'error') return '⚠'
  return '•'
}

function statusColor(status: string | undefined): string {
  if (status === 'done') return 'var(--success)'
  if (status === 'error') return 'var(--danger)'
  return 'var(--ink-400)'
}
</script>

<template>
  <aside class="flex flex-col gap-2">
    <p
      class="text-[10px] font-medium uppercase"
      style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
    >
      Pièces stagées ({{ coins.length }})
    </p>

    <div v-if="coins.length === 0" class="text-xs" style="color: var(--ink-400);">
      Aucune pièce — reviens sur /coins et clique <span class="font-mono">Augmenter</span>.
    </div>

    <ul class="flex flex-col gap-1">
      <li
        v-for="(coin, index) in coins"
        :key="coin.eurio_id"
      >
        <button
          type="button"
          class="flex w-full items-center gap-2 rounded-md border px-2 py-2 text-left transition-colors"
          :style="{
            background: index === activeIndex
              ? 'color-mix(in srgb, var(--indigo-700) 8%, var(--surface))'
              : 'var(--surface)',
            borderColor: index === activeIndex ? 'var(--indigo-700)' : 'var(--surface-3)',
          }"
          @click="$emit('select', index)"
        >
          <div
            class="flex h-9 w-9 flex-shrink-0 items-center justify-center overflow-hidden rounded-sm"
            style="background: var(--surface-1);"
          >
            <img
              v-if="firstImageUrl(coin)"
              :src="firstImageUrl(coin) as string"
              :alt="coin.eurio_id"
              class="h-full w-full object-contain"
            />
            <ImageOff v-else class="h-3.5 w-3.5" style="color: var(--ink-400);" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center justify-between gap-1">
              <span
                class="truncate font-mono text-[11px]"
                style="color: var(--ink);"
              >{{ coin.eurio_id }}</span>
              <span
                class="flex-shrink-0 font-mono text-xs"
                :style="{ color: statusColor(statusByEurioId[coin.eurio_id]) }"
              >{{ statusSymbol(statusByEurioId[coin.eurio_id]) }}</span>
            </div>
            <div class="mt-0.5 flex items-center gap-1.5">
              <span
                v-if="zoneByEurioId[coin.eurio_id]"
                class="rounded-full px-1.5 py-0.5 text-[9px] font-medium uppercase"
                :style="{
                  background: zoneStyle(zoneByEurioId[coin.eurio_id] as ConfusionZone).soft,
                  color: zoneStyle(zoneByEurioId[coin.eurio_id] as ConfusionZone).solid,
                }"
              >{{ zoneStyle(zoneByEurioId[coin.eurio_id] as ConfusionZone).short }}</span>
              <span class="text-[10px]" style="color: var(--ink-400);">
                {{ coin.country }} · {{ coin.face_value }} €
              </span>
            </div>
          </div>
        </button>
      </li>
    </ul>
  </aside>
</template>
