<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  ChevronDown, ChevronRight, CornerDownRight, ScanLine, Sparkles,
} from 'lucide-vue-next'
import type { FunnelDrop, SearchFunnel } from '../composables/useBenchApi'
import BenchListingItem from './BenchListingItem.vue'

const props = defineProps<{ search: SearchFunnel }>()

const expanded = ref<Set<string>>(new Set())
function toggle(key: string) {
  if (expanded.value.has(key)) expanded.value.delete(key)
  else expanded.value.add(key)
}
const isOpen = (key: string) => expanded.value.has(key)

// Largeur d'une plaque ∝ son compte — le rétrécissement EST l'entonnoir.
// Plancher à 36 % pour que le libellé reste lisible.
function plateWidth(count: number): string {
  const pct = props.search.total ? (count / props.search.total) * 100 : 100
  return `${Math.max(36, pct).toFixed(1)}%`
}

function wrongTotal(drops: FunnelDrop[]): number {
  return drops.reduce((n, d) => n + d.wrong, 0)
}

const acceptWrong = computed(() => wrongTotal(props.search.acceptDrops))
const matcherWrong = computed(() => wrongTotal(props.search.matcherDrops))
const maxBranch = computed(
  () => Math.max(1, ...props.search.branches.map(b => b.listings.length)),
)
</script>

<template>
  <div class="mx-auto" style="max-width: 680px;">
    <!-- ── En-tête de la recherche ─────────────────────────────────── -->
    <header class="mb-6">
      <div
        class="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.14em]"
        style="color: var(--ink-400);"
      >
        <ScanLine class="h-3.5 w-3.5" />
        Recherche eBay
      </div>
      <h2
        class="mt-1 text-[32px] leading-tight"
        style="font-family: var(--font-display); font-weight: 600; color: var(--ink);"
      >
        {{ search.country }}
        <span style="color: var(--ink-300);">·</span> {{ search.denomination }}
        <span style="color: var(--ink-300);">·</span> {{ search.year }}
      </h2>
      <p class="mt-0.5 text-[12px]" style="color: var(--ink-400);">
        Trois critères → {{ search.coins.length }} commémo{{ search.coins.length > 1 ? 's' : '' }}-sœur{{ search.coins.length > 1 ? 's' : '' }} à départager.
      </p>

      <!-- Pièces visées — cliquer pour le contexte i18n / alias -->
      <div class="mt-3 space-y-1.5">
        <div
          v-for="coin in search.coins"
          :key="coin.eurio_id"
          class="overflow-hidden rounded-lg border"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <button
            class="flex w-full items-center gap-2 px-3 py-2 text-left"
            @click="toggle('coin:' + coin.eurio_id)"
          >
            <component
              :is="isOpen('coin:' + coin.eurio_id) ? ChevronDown : ChevronRight"
              class="h-3.5 w-3.5 flex-shrink-0" style="color: var(--ink-400);"
            />
            <span
              class="text-[12px]"
              style="font-family: var(--font-mono); color: var(--indigo-700);"
            >{{ coin.eurio_id.replace(/^[a-z]{2}-\d{4}-2eur-/, '') }}</span>
            <span class="truncate text-[12px]" style="color: var(--ink-500);">
              {{ coin.theme }}
            </span>
          </button>
          <div
            v-if="isOpen('coin:' + coin.eurio_id)"
            class="border-t px-3 py-2"
            style="border-color: var(--surface-3); background: var(--surface-1);"
          >
            <div class="space-y-0.5">
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
            <div v-if="coin.aliases.length" class="mt-2 flex flex-wrap gap-1">
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
        </div>
      </div>
    </header>

    <!-- ── L'entonnoir ─────────────────────────────────────────────── -->
    <div class="flex flex-col items-center">
      <!-- Plaque : annonces brutes -->
      <div
        class="rounded-xl border px-5 py-3.5"
        :style="`width: ${plateWidth(search.total)}; border-color: var(--ink-200); background: var(--surface);`"
      >
        <div class="flex items-baseline justify-between gap-4">
          <span class="text-[11px] font-medium uppercase tracking-[0.1em]"
                style="color: var(--ink-400);">Annonces brutes</span>
          <span class="text-[26px] leading-none"
                style="font-family: var(--font-display); font-weight: 600; color: var(--ink);">
            {{ search.total }}
          </span>
        </div>
      </div>

      <!-- Transition 1 : accept_listing -->
      <div class="my-1 h-3 w-px" style="background: var(--surface-3);" />
      <button
        class="w-full overflow-hidden rounded-lg border text-left transition-colors"
        :style="search.nRejectedAccept > 0
          ? 'border-color: var(--danger); background: var(--surface);'
          : 'border-color: var(--surface-3); background: var(--surface-1);'"
        :disabled="search.nRejectedAccept === 0"
        @click="toggle('accept')"
      >
        <div class="flex items-center gap-2.5 px-4 py-2.5">
          <component
            :is="isOpen('accept') ? ChevronDown : ChevronRight"
            v-if="search.nRejectedAccept > 0"
            class="h-4 w-4 flex-shrink-0" style="color: var(--ink-400);"
          />
          <span v-else class="h-4 w-4 flex-shrink-0" />
          <span class="text-[12px] font-semibold" style="color: var(--ink);">
            Filtre 1 — accept_listing
          </span>
          <span class="ml-auto flex items-center gap-3 text-[12px]">
            <span v-if="search.nRejectedAccept > 0"
                  style="color: var(--danger); font-family: var(--font-mono);">
              ✗ {{ search.nRejectedAccept }} rejetées
            </span>
            <span v-else style="color: var(--success);">tout passe</span>
            <span
              class="rounded-full px-2 py-0.5 text-[10.5px] font-semibold"
              :style="acceptWrong > 0
                ? 'background: var(--danger-soft, #f6dcd6); color: var(--danger);'
                : 'background: #dcefe4; color: var(--success);'"
            >{{ acceptWrong > 0 ? `⚠ ${acceptWrong} à tort` : '✓ 0 à tort' }}</span>
          </span>
        </div>
        <!-- Détail : annonces rejetées, par motif -->
        <div
          v-if="isOpen('accept')"
          class="border-t" style="border-color: var(--surface-3); background: var(--surface-1);"
        >
          <div v-for="drop in search.acceptDrops" :key="drop.key">
            <div class="flex items-center gap-2 px-4 py-1.5 text-[11px]"
                 style="background: var(--surface-2); color: var(--ink-500);">
              <span class="font-semibold uppercase tracking-wide">{{ drop.label }}</span>
              <span style="font-family: var(--font-mono);">{{ drop.listings.length }}</span>
              <span v-if="drop.wrong > 0" class="ml-auto font-semibold"
                    style="color: var(--danger);">{{ drop.wrong }} pièce(s) valide(s) jetée(s)</span>
            </div>
            <BenchListingItem
              v-for="l in drop.listings" :key="l.listing_id" :listing="l"
            />
          </div>
        </div>
      </button>

      <!-- Plaque : passé le filtre 1 -->
      <div class="my-1 h-3 w-px" style="background: var(--surface-3);" />
      <div
        class="rounded-xl border px-5 py-3"
        :style="`width: ${plateWidth(search.nAccepted)}; border-color: var(--indigo-300); background: var(--surface);`"
      >
        <div class="flex items-baseline justify-between gap-4">
          <span class="text-[11px] font-medium uppercase tracking-[0.1em]"
                style="color: var(--ink-400);">Passé le filtre 1</span>
          <span class="text-[24px] leading-none"
                style="font-family: var(--font-display); font-weight: 600; color: var(--ink);">
            {{ search.nAccepted }}
          </span>
        </div>
      </div>

      <!-- Transition 2 : theme-matcher + garde-fou -->
      <div class="my-1 h-3 w-px" style="background: var(--surface-3);" />
      <button
        class="w-full overflow-hidden rounded-lg border text-left transition-colors"
        :style="search.nContradicted > 0
          ? 'border-color: var(--danger); background: var(--surface);'
          : 'border-color: var(--surface-3); background: var(--surface-1);'"
        :disabled="search.nContradicted === 0"
        @click="toggle('matcher')"
      >
        <div class="flex items-center gap-2.5 px-4 py-2.5">
          <component
            :is="isOpen('matcher') ? ChevronDown : ChevronRight"
            v-if="search.nContradicted > 0"
            class="h-4 w-4 flex-shrink-0" style="color: var(--ink-400);"
          />
          <span v-else class="h-4 w-4 flex-shrink-0" />
          <span class="text-[12px] font-semibold" style="color: var(--ink);">
            Filtre 2 — theme-matcher + garde-fou
          </span>
          <span class="ml-auto flex items-center gap-3 text-[12px]">
            <span v-if="search.nContradicted > 0"
                  style="color: var(--danger); font-family: var(--font-mono);">
              ✗ {{ search.nContradicted }} contredites
            </span>
            <span v-else style="color: var(--success);">aucune contradiction</span>
            <span
              class="rounded-full px-2 py-0.5 text-[10.5px] font-semibold"
              :style="matcherWrong > 0
                ? 'background: var(--danger-soft, #f6dcd6); color: var(--danger);'
                : 'background: #dcefe4; color: var(--success);'"
            >{{ matcherWrong > 0 ? `⚠ ${matcherWrong} à tort` : '✓ 0 à tort' }}</span>
          </span>
        </div>
        <div
          v-if="isOpen('matcher')"
          class="border-t" style="border-color: var(--surface-3); background: var(--surface-1);"
        >
          <div v-for="drop in search.matcherDrops" :key="drop.key">
            <div class="flex items-center gap-2 px-4 py-1.5 text-[11px]"
                 style="background: var(--surface-2); color: var(--ink-500);">
              <span class="font-semibold uppercase tracking-wide">
                contradiction {{ drop.label }}
              </span>
              <span style="font-family: var(--font-mono);">{{ drop.listings.length }}</span>
              <span v-if="drop.wrong > 0" class="ml-auto font-semibold"
                    style="color: var(--danger);">{{ drop.wrong }} valide(s) jetée(s)</span>
            </div>
            <BenchListingItem
              v-for="l in drop.listings" :key="l.listing_id" :listing="l"
            />
          </div>
        </div>
      </button>

      <!-- Plaque : retenu -->
      <div class="my-1 h-3 w-px" style="background: var(--surface-3);" />
      <div
        class="rounded-xl border px-5 py-3"
        :style="`width: ${plateWidth(search.nRetained)}; border-color: var(--indigo-600); background: var(--indigo-50);`"
      >
        <div class="flex items-baseline justify-between gap-4">
          <span class="text-[11px] font-medium uppercase tracking-[0.1em]"
                style="color: var(--indigo-700);">Retenu pour attribution</span>
          <span class="text-[24px] leading-none"
                style="font-family: var(--font-display); font-weight: 600; color: var(--indigo-700);">
            {{ search.nRetained }}
          </span>
        </div>
      </div>

      <!-- Étape 3 : attribution -->
      <div class="my-1 h-3 w-px" style="background: var(--surface-3);" />
      <div class="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.12em]"
           style="color: var(--ink-400);">
        <Sparkles class="h-3.5 w-3.5" />
        Attribution
      </div>
      <div class="mt-2 w-full space-y-1.5">
        <div
          v-for="(branch, i) in search.branches"
          :key="branch.label"
          class="overflow-hidden rounded-lg border"
          :style="`border-color: ${branch.kind === 'auto' ? 'var(--indigo-300)' : 'var(--gold-400)'};
                   background: var(--surface);`"
        >
          <button
            class="flex w-full items-center gap-2.5 px-3.5 py-2 text-left"
            :disabled="branch.listings.length === 0"
            @click="toggle('branch:' + i)"
          >
            <component
              :is="isOpen('branch:' + i) ? ChevronDown : ChevronRight"
              v-if="branch.listings.length > 0"
              class="h-3.5 w-3.5 flex-shrink-0" style="color: var(--ink-400);"
            />
            <span v-else class="h-3.5 w-3.5 flex-shrink-0" />
            <CornerDownRight class="h-3.5 w-3.5 flex-shrink-0" style="color: var(--ink-300);" />
            <span class="text-[10px] font-semibold uppercase tracking-[0.08em]"
                  :style="`color: ${branch.kind === 'auto' ? 'var(--indigo-700)' : 'var(--gold-700)'};`">
              {{ branch.kind === 'auto' ? 'auto →' : 'review' }}
            </span>
            <span v-if="branch.kind === 'auto'" class="text-[12px]"
                  style="font-family: var(--font-mono); color: var(--ink);">
              {{ branch.label }}
            </span>
            <!-- Barre proportionnelle au compte -->
            <span class="ml-auto flex items-center gap-2">
              <span
                v-if="branch.wrong > 0"
                class="rounded-full px-1.5 py-0.5 text-[10px] font-semibold"
                style="background: var(--danger-soft, #f6dcd6); color: var(--danger);"
              >⚠ {{ branch.wrong }}</span>
              <span class="h-1.5 rounded-full"
                    :style="`width: ${(branch.listings.length / maxBranch) * 88 + 8}px;
                             background: ${branch.kind === 'auto' ? 'var(--indigo-600)' : 'var(--gold-500)'};`" />
              <span class="w-6 text-right text-[14px]"
                    style="font-family: var(--font-display); font-weight: 600; color: var(--ink);">
                {{ branch.listings.length }}
              </span>
            </span>
          </button>
          <div
            v-if="isOpen('branch:' + i)"
            class="border-t" style="border-color: var(--surface-3); background: var(--surface-1);"
          >
            <BenchListingItem
              v-for="l in branch.listings" :key="l.listing_id" :listing="l"
            />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
