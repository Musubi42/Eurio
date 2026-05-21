<script setup lang="ts">
// ListingContextCard — carte d'audit « Listing & marché » de la review
// single (chunk C4). Remplace l'ancienne carte « Listing source ».
//
// Lane secondaire : pendant que le reviewer attribue la pièce (⏎), cette
// carte affiche en coup d'œil le type de listing, l'état numismatique,
// l'âge, et le cross-check prix vs marché de référence (C3). Les badges
// en faible confiance passent en ambre. Correction opt-in au clavier
// (K / C) — gérée par la vue parente, la carte ne fait qu'afficher.

import { computed, type Component } from 'vue'
import { Coins, Layers, Package, ShieldCheck } from 'lucide-vue-next'
import type {
  ConditionTier,
  ListingKind,
  MarketQuote,
} from '../composables/useReviewApi'

const props = defineProps<{
  title: string | null
  source: string
  price: number | null
  kind: ListingKind | null
  kindConfidence: number | null
  kindCorrected: boolean
  condition: ConditionTier | null
  conditionConfidence: number | null
  conditionCorrected: boolean
  originDate: string | null
  soldQty: number | null
  marketQuote: MarketQuote | null
}>()

// Sous ce seuil, le badge passe en ambre : « l'heuristique C2 n'est pas
// sûre, vérifie ». Les défauts UNC (conf 0.2) tombent ici ; les signaux
// explicites (0.85+) et corrigés non.
const LOW_CONFIDENCE = 0.6

const KIND_META: Record<ListingKind, { label: string; icon: Component }> = {
  single: { label: 'pièce nue', icon: Coins },
  lot: { label: 'lot', icon: Layers },
  coffret: { label: 'coffret', icon: Package },
  graded_slab: { label: 'slab gradé', icon: ShieldCheck },
}
const COND_META: Record<ConditionTier, string> = {
  UNC: 'neuve',
  TTB: 'bon état',
  TB: 'usée',
}

const kindMeta = computed(() => (props.kind ? KIND_META[props.kind] : null))
const condLabel = computed(() => (props.condition ? COND_META[props.condition] : null))

const kindLow = computed(
  () => !props.kindCorrected
    && props.kindConfidence != null
    && props.kindConfidence < LOW_CONFIDENCE,
)
const conditionLow = computed(
  () => !props.conditionCorrected
    && props.conditionConfidence != null
    && props.conditionConfidence < LOW_CONFIDENCE,
)

function pct(v: number | null): string {
  return v == null ? '' : `${Math.round(v * 100)}%`
}

// Âge de l'annonce — « il y a 3 mois », « il y a 12 j ».
const ageLabel = computed(() => {
  if (!props.originDate) return null
  const t = Date.parse(props.originDate)
  if (Number.isNaN(t)) return null
  const days = Math.floor((Date.now() - t) / 86_400_000)
  if (days < 1) return "aujourd'hui"
  if (days < 60) return `il y a ${days} j`
  const months = Math.round(days / 30.44)
  if (months < 24) return `il y a ${months} mois`
  return `il y a ${Math.round(months / 12)} ans`
})

// Cross-check prix : écart du listing vs p50 marché.
const marketDelta = computed(() => {
  const p50 = props.marketQuote?.p50
  if (p50 == null || p50 <= 0 || props.price == null) return null
  return Math.round(((props.price - p50) / p50) * 100)
})
// Anomalie : un listing `single` au-dessus du p90 marché est
// probablement un coffret/slab mal tagué — ou une mauvaise attribution.
const priceAnomaly = computed(
  () => props.kind === 'single'
    && props.marketQuote?.p90 != null
    && props.price != null
    && props.price > props.marketQuote.p90,
)
</script>

<template>
  <article
    class="rounded-lg border px-4 py-3"
    style="border-color: var(--surface-3); background: var(--surface);"
  >
    <div class="flex items-baseline justify-between gap-3">
      <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
        Listing &amp; marché
      </p>
      <span class="font-mono text-[11px]" style="color: var(--ink-400);">{{ source }}</span>
    </div>

    <p class="mt-1 font-display text-sm italic" style="color: var(--ink);">
      « {{ title || '—' }} »
    </p>

    <!-- ── Badges type / état ── -->
    <div class="mt-3 flex flex-col gap-1.5">
      <!-- type -->
      <div class="flex items-center gap-2 text-[11px]">
        <span class="w-9 font-mono uppercase tracking-wider" style="color: var(--ink-400);">type</span>
        <span
          class="badge"
          :class="{ 'badge-low': kindLow, 'badge-fixed': kindCorrected }"
        >
          <component :is="kindMeta.icon" v-if="kindMeta" class="h-3 w-3" />
          <span class="font-medium">{{ kindMeta?.label ?? '—' }}</span>
        </span>
        <span class="font-mono text-[10px]" style="color: var(--ink-400);">
          <template v-if="kindCorrected">✓ manuel</template>
          <template v-else-if="kindConfidence != null">{{ pct(kindConfidence) }}</template>
        </span>
        <span class="ml-1 font-mono text-[9px] uppercase tracking-wider" style="color: var(--ink-400);">K&nbsp;⟳</span>
      </div>
      <!-- état -->
      <div class="flex items-center gap-2 text-[11px]">
        <span class="w-9 font-mono uppercase tracking-wider" style="color: var(--ink-400);">état</span>
        <span
          class="badge"
          :class="{ 'badge-low': conditionLow, 'badge-fixed': conditionCorrected }"
        >
          <span class="font-medium">{{ condition ?? '—' }}</span>
          <span v-if="condLabel" class="opacity-60">· {{ condLabel }}</span>
        </span>
        <span class="font-mono text-[10px]" style="color: var(--ink-400);">
          <template v-if="conditionCorrected">✓ manuel</template>
          <template v-else-if="conditionConfidence != null">{{ pct(conditionConfidence) }}</template>
        </span>
        <span class="ml-1 font-mono text-[9px] uppercase tracking-wider" style="color: var(--ink-400);">C&nbsp;⟳</span>
      </div>
    </div>

    <!-- ── Méta : prix listing · âge · ventes ── -->
    <div
      class="mt-2.5 flex flex-wrap items-baseline gap-x-4 gap-y-1 font-mono text-[11px]"
      style="color: var(--ink-500);"
    >
      <span v-if="price != null">
        <span class="opacity-70">prix&nbsp;·</span>
        <span class="ml-1 font-semibold" style="color: var(--ink);">{{ price.toFixed(2) }} €</span>
      </span>
      <span v-if="ageLabel">
        <span class="opacity-70">posté&nbsp;·</span>
        <span class="ml-1" style="color: var(--ink-700);">{{ ageLabel }}</span>
      </span>
      <span v-if="soldQty != null">
        <span class="opacity-70">vendu&nbsp;·</span>
        <span class="ml-1" style="color: var(--ink-700);">{{ soldQty }}</span>
      </span>
    </div>

    <!-- ── Cross-check marché (C3) ── -->
    <div class="mt-3 border-t border-dashed pt-2" style="border-color: var(--surface-3);">
      <template v-if="marketQuote && marketQuote.p50 != null">
        <div class="flex flex-wrap items-baseline gap-x-3 font-mono text-[11px]">
          <span class="text-[10px] uppercase tracking-wider" style="color: var(--ink-400);">
            marché · {{ marketQuote.condition }}
          </span>
          <span>
            <span class="opacity-70">réf p50&nbsp;·</span>
            <span class="ml-1 font-semibold" style="color: var(--ink);">
              {{ marketQuote.p50.toFixed(2) }} €
            </span>
          </span>
          <span style="color: var(--ink-400);">n={{ marketQuote.sample_size }}</span>
          <span
            v-if="marketDelta != null"
            class="ml-auto font-semibold"
            :style="{ color: priceAnomaly ? 'var(--warning)' : 'var(--ink-500)' }"
          >
            {{ marketDelta >= 0 ? '+' : '' }}{{ marketDelta }}%
            <template v-if="priceAnomaly">⚠</template>
          </span>
        </div>
        <p
          v-if="priceAnomaly"
          class="mt-1 text-[10px] italic"
          style="color: var(--warning);"
        >
          listing « pièce nue » au-dessus du p90 marché — probable coffret /
          slab mal tagué, ou attribution à vérifier.
        </p>
      </template>
      <p v-else class="font-mono text-[10px]" style="color: var(--ink-400);">
        pas encore de prix de référence pour cette pièce.
      </p>
    </div>
  </article>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 5px;
  border: 1px solid var(--surface-3);
  background: var(--surface-1);
  color: var(--ink-700);
}
/* Faible confiance C2 → ambre : « à vérifier ». */
.badge-low {
  border-color: var(--warning);
  color: var(--warning);
  background: color-mix(in srgb, var(--warning) 10%, var(--surface));
}
/* Corrigé à la main → indigo, signal « figé ». */
.badge-fixed {
  border-color: var(--indigo-700);
  color: var(--indigo-700);
  background: color-mix(in srgb, var(--indigo-700) 8%, var(--surface));
}
</style>
