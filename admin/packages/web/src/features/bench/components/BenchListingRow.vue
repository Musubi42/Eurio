<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronRight, AlertTriangle } from 'lucide-vue-next'
import {
  type BenchListing,
  type BenchGroupCoin,
  acceptReasonLabel,
  outcomeLabel,
  outcomeTone,
  verdictLabel,
} from '../composables/useBenchApi'

const props = defineProps<{
  listing: BenchListing
  groupCoins: BenchGroupCoin[]
}>()

const open = ref(false)

// `be-2018-2eur-50-years-…esro-2b` → `…esro-2b` (lisible, sans le préfixe).
function shortEurio(id: string): string {
  return id.replace(/^[a-z]{2}-\d{4}-2eur-/, '')
}

const verdictTarget = computed(() =>
  props.listing.verdict.startsWith('coin:')
    ? props.listing.verdict.slice(5)
    : null,
)
const matched = computed(() => props.listing.matcher?.matched ?? [])

// Verdict du matcher en forme courte pour la ligne repliée.
const matcherText = computed(() => {
  const m = props.listing.matcher
  if (!m) return null
  if (m.verdict === 'single') return `single → ${shortEurio(m.matched[0] ?? '?')}`
  if (m.verdict === 'no_match') return `no_match (${m.contradictions.join(', ')})`
  if (m.verdict === 'lot') return `lot ×${m.matched.length}`
  return m.verdict
})
</script>

<template>
  <div class="border-b" style="border-color: var(--surface-3);">
    <!-- Ligne repliée -->
    <button
      class="flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors hover:bg-black/[0.02]"
      @click="open = !open"
    >
      <ChevronRight
        class="mt-0.5 h-4 w-4 flex-shrink-0 transition-transform"
        :class="open ? 'rotate-90' : ''"
        style="color: var(--ink-400);"
      />

      <!-- Badge issue -->
      <span
        class="mt-0.5 flex flex-shrink-0 items-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold"
        :style="`background: ${outcomeTone(listing.outcome)}1a; color: ${outcomeTone(listing.outcome)};`"
      >
        <AlertTriangle v-if="!listing.agreement" class="h-3 w-3" />
        {{ outcomeLabel(listing.outcome) }}
      </span>

      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <span class="truncate text-sm" style="color: var(--ink-700);">
            {{ listing.title }}
          </span>
          <span v-if="listing.marketplace"
                class="flex-shrink-0 rounded px-1.5 py-0.5 text-[10px] font-mono"
                style="background: var(--surface-2); color: var(--ink-400);">
            {{ listing.marketplace }}
          </span>
          <span class="flex-shrink-0 text-[11px] font-mono" style="color: var(--ink-400);">
            {{ listing.group_year }}
          </span>
        </div>
        <!-- Vérité humaine + pipeline -->
        <div class="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px]"
             style="color: var(--ink-500);">
          <span>
            vérité&nbsp;:
            <span class="font-mono" style="color: var(--ink-700);">
              {{ verdictLabel(listing.verdict) }}
            </span>
          </span>
          <span style="color: var(--ink-300);">·</span>
          <span :style="listing.accept.ok ? '' : 'color: var(--danger);'">
            accept&nbsp;{{ listing.accept.ok ? '✓' : '✗ ' + acceptReasonLabel(listing.accept.reason) }}
          </span>
          <template v-if="matcherText">
            <span style="color: var(--ink-300);">→</span>
            <span class="font-mono">{{ matcherText }}</span>
          </template>
        </div>
      </div>
    </button>

    <!-- Détail déplié -->
    <div v-if="open" class="px-4 pb-4 pl-11" style="background: var(--surface-1);">
      <div class="grid gap-4 lg:grid-cols-2">
        <!-- Métadonnées du listing -->
        <div>
          <p class="mb-1.5 text-[11px] font-medium uppercase tracking-wider"
             style="color: var(--ink-400);">Listing</p>
          <dl class="space-y-0.5 text-xs" style="color: var(--ink-600);">
            <div class="flex gap-2">
              <dt class="w-24 flex-shrink-0" style="color: var(--ink-400);">listing_id</dt>
              <dd class="font-mono break-all">{{ listing.listing_id }}</dd>
            </div>
            <div class="flex gap-2">
              <dt class="w-24 flex-shrink-0" style="color: var(--ink-400);">prix</dt>
              <dd>{{ listing.price ?? '—' }} {{ listing.currency ?? '' }}</dd>
            </div>
            <div class="flex gap-2">
              <dt class="w-24 flex-shrink-0" style="color: var(--ink-400);">bucket gold</dt>
              <dd class="font-mono">{{ listing.bucket ?? '—' }}</dd>
            </div>
            <div v-if="listing.note" class="flex gap-2">
              <dt class="w-24 flex-shrink-0" style="color: var(--ink-400);">note</dt>
              <dd class="italic">{{ listing.note }}</dd>
            </div>
            <div v-if="listing.matcher?.contradictions.length" class="flex gap-2">
              <dt class="w-24 flex-shrink-0" style="color: var(--ink-400);">contradiction</dt>
              <dd class="font-mono" style="color: var(--danger);">
                {{ listing.matcher.contradictions.join(', ') }}
              </dd>
            </div>
          </dl>
        </div>

        <!-- Contexte du groupe : les sœurs (pour juger) -->
        <div>
          <p class="mb-1.5 text-[11px] font-medium uppercase tracking-wider"
             style="color: var(--ink-400);">
            Groupe {{ listing.group_year }} — {{ groupCoins.length }} sœur(s)
          </p>
          <div class="space-y-2">
            <div
              v-for="coin in groupCoins"
              :key="coin.eurio_id"
              class="rounded-md border px-2.5 py-1.5"
              :style="verdictTarget === coin.eurio_id
                ? 'border-color: var(--indigo-600); background: var(--indigo-50);'
                : 'border-color: var(--surface-3); background: white;'"
            >
              <div class="flex items-center gap-1.5">
                <span class="font-mono text-xs" style="color: var(--ink-700);">
                  {{ shortEurio(coin.eurio_id) }}
                </span>
                <span v-if="verdictTarget === coin.eurio_id"
                      class="rounded px-1 text-[10px] font-semibold"
                      style="background: var(--indigo-600); color: white;">
                  vérité
                </span>
                <span v-if="matched.includes(coin.eurio_id)"
                      class="rounded px-1 text-[10px] font-semibold"
                      style="background: var(--gold-600); color: white;">
                  matcher
                </span>
              </div>
              <p class="mt-0.5 text-[11px]" style="color: var(--ink-500);">
                {{ coin.theme }}
              </p>
              <div class="mt-1 space-y-0.5 text-[11px]" style="color: var(--ink-500);">
                <div v-for="(title, lang) in coin.i18n" :key="lang" class="flex gap-1.5">
                  <span class="w-5 flex-shrink-0 font-mono uppercase"
                        style="color: var(--ink-300);">{{ lang }}</span>
                  <span>{{ title }}</span>
                </div>
              </div>
              <div v-if="coin.aliases.length" class="mt-1 flex flex-wrap gap-1">
                <span
                  v-for="a in coin.aliases"
                  :key="a"
                  class="rounded px-1.5 py-0.5 text-[10px] font-mono"
                  style="background: var(--surface-2); color: var(--ink-500);"
                >{{ a }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
