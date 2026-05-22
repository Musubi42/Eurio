<script setup lang="ts">
import { computed, ref } from 'vue'
import { ExternalLink, ImageOff } from 'lucide-vue-next'
import { type BenchListing, ebayItemUrl, verdictLabel } from '../composables/useBenchApi'

const props = defineProps<{ listing: BenchListing }>()

const broken = ref(false)
const ebayUrl = computed(() => ebayItemUrl(props.listing.listing_id))

const isValid = computed(
  () => props.listing.verdict.startsWith('coin:')
    || props.listing.verdict === 'ambiguous',
)

const OUTCOME_LABEL: Record<string, string> = {
  FALSE_DISCARD: 'Faux rejet',
  auto_ok: 'Auto — correct',
  auto_WRONG: 'Auto — erronée',
  review: 'Review',
  junk_discarded: 'Junk rejeté',
  FALSE_KEEP: 'Junk gardé',
}
const outcomeText = computed(
  () => OUTCOME_LABEL[props.listing.outcome] ?? props.listing.outcome,
)

// Raison du verdict — surface les signaux que le matcher / le filtre ont vus.
// `accept.ok=false` : motif de rejet du filtre 1.
// `matcher.matched`/`contradictions` : tokens qui ont déclenché l'attribution
//   (ou qui la contredisent). Sans ça, le badge « erronée » est injugeable.
const reason = computed<{ label: string; tone: 'filter' | 'match' | 'warn' } | null>(() => {
  const l = props.listing
  if (!l.accept.ok) return { label: `Filtre 1 — ${l.accept.reason}`, tone: 'filter' }
  if (!l.matcher) return null
  if (l.matcher.contradictions.length) {
    return { label: `Contradiction : ${l.matcher.contradictions.join(', ')}`, tone: 'warn' }
  }
  if (l.matcher.verdict === 'no_match') return { label: 'Aucun match', tone: 'warn' }
  if (l.matcher.matched.length) {
    return { label: `Match → ${l.matcher.matched.join(', ')}`, tone: 'match' }
  }
  return null
})
</script>

<template>
  <article
    class="flex flex-col overflow-hidden rounded-xl border"
    :style="listing.agreement
      ? 'border-color: var(--surface-3); background: var(--surface);'
      : 'border-color: var(--danger); background: var(--surface); box-shadow: 0 0 0 1px var(--danger);'"
  >
    <!-- Photo de l'annonce -->
    <div
      class="relative flex aspect-square items-center justify-center overflow-hidden"
      style="background: var(--surface-2);"
    >
      <img
        v-if="listing.image_url && !broken"
        :src="listing.image_url"
        :alt="listing.title"
        class="h-full w-full object-contain"
        loading="lazy"
        @error="broken = true"
      />
      <div v-else class="flex flex-col items-center gap-1">
        <ImageOff class="h-6 w-6" style="color: var(--ink-300);" />
        <span class="text-[10px]" style="color: var(--ink-400);">pas d'image</span>
      </div>
      <!-- Verdict du pipeline : pastille d'accord -->
      <span
        class="absolute right-2 top-2 rounded-full px-2 py-0.5 text-[10px] font-semibold"
        :style="listing.agreement
          ? 'background: #dcefe4; color: var(--success);'
          : 'background: var(--danger); color: white;'"
      >{{ outcomeText }}</span>
    </div>

    <!-- Méta -->
    <div class="flex flex-1 flex-col gap-1.5 px-3 py-2.5">
      <p
        class="text-[12px] leading-snug"
        style="color: var(--ink); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;"
      >{{ listing.title }}</p>

      <!-- Raison du verdict (cf. composable : accept.reason / matcher.matched). -->
      <p
        v-if="reason"
        class="truncate text-[11px]"
        :title="reason.label"
        :style="`font-family: var(--font-mono); color: ${
          reason.tone === 'filter' ? 'var(--danger)' :
          reason.tone === 'warn'   ? 'var(--gold-700)' :
          'var(--indigo-700)'};`"
      >{{ reason.label }}</p>

      <div class="mt-auto flex items-center gap-1.5 pt-1">
        <span
          v-if="listing.marketplace"
          class="rounded px-1 py-px text-[10px]"
          style="background: var(--surface-2); color: var(--ink-400); font-family: var(--font-mono);"
        >{{ listing.marketplace }}</span>
        <span class="text-[11px]" style="color: var(--ink-400);">
          vérité
          <span :style="`font-family: var(--font-mono); color: ${
            isValid ? 'var(--indigo-700)' : 'var(--gold-700)'};`"
          >{{ verdictLabel(listing.verdict) }}</span>
        </span>
        <a
          v-if="ebayUrl"
          :href="ebayUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="ml-auto flex items-center gap-0.5 text-[11px] hover:underline"
          style="color: var(--indigo-600);"
          @click.stop
        >
          <ExternalLink class="h-3 w-3" /> eBay
        </a>
      </div>
    </div>
  </article>
</template>
