<script setup lang="ts">
import { computed } from 'vue'
import { CornerDownRight, Sparkles } from 'lucide-vue-next'
import type { FunnelDrop, SearchFunnel } from '../composables/useBenchApi'

const props = defineProps<{
  search: SearchFunnel
  selectedNodeId: string | null
}>()
const emit = defineEmits<{ select: [id: string] }>()

// Largeur d'une plaque ∝ son compte — le rétrécissement EST l'entonnoir.
function plateWidth(count: number): string {
  const pct = props.search.total ? (count / props.search.total) * 100 : 100
  return `${Math.max(46, pct).toFixed(1)}%`
}
function wrongTotal(drops: FunnelDrop[]): number {
  return drops.reduce((n, d) => n + d.wrong, 0)
}
const acceptWrong = computed(() => wrongTotal(props.search.acceptDrops))
const matcherWrong = computed(() => wrongTotal(props.search.matcherDrops))

const isActive = (id: string) => props.selectedNodeId === id
</script>

<template>
  <div class="flex flex-col items-center">
    <!-- Plaque : annonces brutes -->
    <button
      class="rounded-xl border px-4 py-3 text-left transition-all"
      :style="`width: ${plateWidth(search.total)}; ${isActive('raw')
        ? 'border-color: var(--indigo-600); background: var(--indigo-50);'
        : 'border-color: var(--ink-200); background: var(--surface);'}`"
      @click="emit('select', 'raw')"
    >
      <div class="flex items-baseline justify-between gap-3">
        <span class="text-[10.5px] font-medium uppercase tracking-[0.09em]"
              style="color: var(--ink-400);">Annonces brutes</span>
        <span class="text-[23px] leading-none"
              style="font-family: var(--font-display); font-weight: 600; color: var(--ink);">
          {{ search.total }}
        </span>
      </div>
    </button>

    <!-- Transition 1 : accept_listing -->
    <div class="my-1 h-3 w-px" style="background: var(--surface-3);" />
    <button
      class="w-full rounded-lg border px-3 py-2 text-left transition-all"
      :disabled="search.rejectedAccept.length === 0"
      :style="search.rejectedAccept.length === 0
        ? 'border-color: var(--surface-3); background: var(--surface-1); cursor: default;'
        : isActive('accept-drop')
          ? 'border-color: var(--indigo-600); background: var(--indigo-50);'
          : 'border-color: var(--danger); background: var(--surface);'"
      @click="search.rejectedAccept.length && emit('select', 'accept-drop')"
    >
      <div class="text-[11.5px] font-semibold" style="color: var(--ink);">
        Filtre 1 — accept_listing
      </div>
      <div class="mt-1 flex items-center gap-2 text-[11px]">
        <span v-if="search.rejectedAccept.length"
              style="color: var(--danger); font-family: var(--font-mono);">
          ✗ {{ search.rejectedAccept.length }} rejetées
        </span>
        <span v-else style="color: var(--success);">tout passe</span>
        <span
          class="ml-auto rounded-full px-1.5 py-0.5 text-[10px] font-semibold"
          :style="acceptWrong > 0
            ? 'background: var(--danger-soft, #f6dcd6); color: var(--danger);'
            : 'background: #dcefe4; color: var(--success);'"
        >{{ acceptWrong > 0 ? `⚠ ${acceptWrong} à tort` : '✓ 0 à tort' }}</span>
      </div>
    </button>

    <!-- Plaque : passé le filtre 1 -->
    <div class="my-1 h-3 w-px" style="background: var(--surface-3);" />
    <button
      class="rounded-xl border px-4 py-2.5 text-left transition-all"
      :style="`width: ${plateWidth(search.accepted.length)}; ${isActive('accepted')
        ? 'border-color: var(--indigo-600); background: var(--indigo-50);'
        : 'border-color: var(--indigo-300); background: var(--surface);'}`"
      @click="emit('select', 'accepted')"
    >
      <div class="flex items-baseline justify-between gap-3">
        <span class="text-[10.5px] font-medium uppercase tracking-[0.09em]"
              style="color: var(--ink-400);">Passé le filtre 1</span>
        <span class="text-[21px] leading-none"
              style="font-family: var(--font-display); font-weight: 600; color: var(--ink);">
          {{ search.accepted.length }}
        </span>
      </div>
    </button>

    <!-- Transition 2 : theme-matcher + garde-fou -->
    <div class="my-1 h-3 w-px" style="background: var(--surface-3);" />
    <button
      class="w-full rounded-lg border px-3 py-2 text-left transition-all"
      :disabled="search.contradicted.length === 0"
      :style="search.contradicted.length === 0
        ? 'border-color: var(--surface-3); background: var(--surface-1); cursor: default;'
        : isActive('matcher-drop')
          ? 'border-color: var(--indigo-600); background: var(--indigo-50);'
          : 'border-color: var(--danger); background: var(--surface);'"
      @click="search.contradicted.length && emit('select', 'matcher-drop')"
    >
      <div class="text-[11.5px] font-semibold" style="color: var(--ink);">
        Filtre 2 — theme-matcher + garde-fou
      </div>
      <div class="mt-1 flex items-center gap-2 text-[11px]">
        <span v-if="search.contradicted.length"
              style="color: var(--danger); font-family: var(--font-mono);">
          ✗ {{ search.contradicted.length }} contredites
        </span>
        <span v-else style="color: var(--success);">aucune contradiction</span>
        <span
          class="ml-auto rounded-full px-1.5 py-0.5 text-[10px] font-semibold"
          :style="matcherWrong > 0
            ? 'background: var(--danger-soft, #f6dcd6); color: var(--danger);'
            : 'background: #dcefe4; color: var(--success);'"
        >{{ matcherWrong > 0 ? `⚠ ${matcherWrong} à tort` : '✓ 0 à tort' }}</span>
      </div>
    </button>

    <!-- Plaque : retenu -->
    <div class="my-1 h-3 w-px" style="background: var(--surface-3);" />
    <button
      class="rounded-xl border px-4 py-2.5 text-left transition-all"
      :style="`width: ${plateWidth(search.retained.length)}; ${isActive('retained')
        ? 'border-color: var(--indigo-700); background: var(--indigo-100);'
        : 'border-color: var(--indigo-600); background: var(--indigo-50);'}`"
      @click="emit('select', 'retained')"
    >
      <div class="flex items-baseline justify-between gap-3">
        <span class="text-[10.5px] font-medium uppercase tracking-[0.09em]"
              style="color: var(--indigo-700);">Retenu</span>
        <span class="text-[21px] leading-none"
              style="font-family: var(--font-display); font-weight: 600; color: var(--indigo-700);">
          {{ search.retained.length }}
        </span>
      </div>
    </button>

    <!-- Attribution -->
    <div class="my-1 h-3 w-px" style="background: var(--surface-3);" />
    <div class="mb-2 flex items-center gap-1.5 text-[10.5px] font-medium uppercase tracking-[0.1em]"
         style="color: var(--ink-400);">
      <Sparkles class="h-3.5 w-3.5" /> Attribution
    </div>
    <div class="w-full space-y-1.5">
      <button
        v-for="branch in search.branches"
        :key="branch.id"
        class="flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left transition-all"
        :disabled="branch.listings.length === 0"
        :style="isActive(branch.id)
          ? 'border-color: var(--indigo-600); background: var(--indigo-50);'
          : `border-color: ${branch.kind === 'auto' ? 'var(--indigo-300)' : 'var(--gold-400)'}; background: var(--surface);`"
        @click="branch.listings.length && emit('select', branch.id)"
      >
        <CornerDownRight class="h-3.5 w-3.5 flex-shrink-0" style="color: var(--ink-300);" />
        <span class="text-[10px] font-semibold uppercase tracking-[0.07em]"
              :style="`color: ${branch.kind === 'auto' ? 'var(--indigo-700)' : 'var(--gold-700)'};`">
          {{ branch.kind === 'auto' ? 'auto →' : 'review' }}
        </span>
        <span v-if="branch.kind === 'auto'" class="truncate text-[11.5px]"
              style="font-family: var(--font-mono); color: var(--ink);">
          {{ branch.label }}
        </span>
        <span class="ml-auto flex items-center gap-1.5">
          <span v-if="branch.wrong > 0"
                class="rounded-full px-1.5 py-0.5 text-[9.5px] font-semibold"
                style="background: var(--danger-soft, #f6dcd6); color: var(--danger);">
            ⚠ {{ branch.wrong }}
          </span>
          <span class="text-[15px]"
                style="font-family: var(--font-display); font-weight: 600; color: var(--ink);">
            {{ branch.listings.length }}
          </span>
        </span>
      </button>
    </div>
  </div>
</template>
