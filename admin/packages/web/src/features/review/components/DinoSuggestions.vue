<script setup lang="ts">
// Affiche le top-K DINOv2 pour un crop (asset). V1 = aide visuelle, pas
// de décision. Cliquer une suggestion émet `select` ; le parent
// (SingleReviewView ou LotReviewDetailPage via ReviewRightColumn)
// traduit en assign sur le crop actif.
//
// Le chargement est lazy : passer `reviewId` OU `assetId` selon le
// contexte du drawer. 404 = no-op silencieux (Dino n'a pas tourné sur
// ce crop, ou hors scope V1 2€ commémo).
//
// Chunk 3.5 — dual band : si l'asset porte un target_country (dérivé
// de l'eBay query parente), on rend une bande "Pays cible" en premier
// avec un re-rank restreint aux ancres de ce pays (R@1 10 % → 34 % en
// mesure), puis la bande globale en fallback. Sans target_country
// (e.g. mock source), on retombe sur l'ancien rendu single-band.

import { computed, ref, watch } from 'vue'
import { Sparkles, Globe } from 'lucide-vue-next'
import {
  fetchDinoSuggestionsByAssetId,
  fetchDinoSuggestionsByReviewId,
  simTier,
  simTierColor,
  spreadLabel,
  type DinoSuggestion,
  type DinoSuggestionsResponse,
} from '../composables/useDinoSuggestions'
import CoinHoverPreview from './CoinHoverPreview.vue'

const props = defineProps<{
  /** review_queue.id (single drawer). One of reviewId/assetId required. */
  reviewId?: string | null
  /** image_assets.id (lot drawer). One of reviewId/assetId required. */
  assetId?: string | null
  /** Compact = lot drawer per-crop strip. Standard = single drawer right column. */
  variant?: 'standard' | 'compact'
  /** eurio_id assigné au crop actif (contexte lot). La suggestion correspondante
   *  passe "validé" (vert + check). Non fourni = comportement single inchangé. */
  assignedEurioId?: string | null
}>()

const emit = defineEmits<{
  (e: 'select', suggestion: DinoSuggestion): void
}>()

const variant = computed(() => props.variant ?? 'standard')
const data = ref<DinoSuggestionsResponse | null>(null)
const loading = ref(false)
const loaded = ref(false)

async function load() {
  loading.value = true
  loaded.value = false
  data.value = null
  try {
    if (props.reviewId) {
      data.value = await fetchDinoSuggestionsByReviewId(props.reviewId)
    } else if (props.assetId) {
      data.value = await fetchDinoSuggestionsByAssetId(props.assetId)
    }
  } finally {
    loading.value = false
    loaded.value = true
  }
}

watch(
  () => [props.reviewId, props.assetId],
  () => {
    if (props.reviewId || props.assetId) void load()
  },
  { immediate: true },
)

const hasCountryBand = computed(
  () => !!(data.value?.top_k_country && data.value.top_k_country.length > 0),
)

const top1Global = computed(() => data.value?.top1_sim ?? 0)
const top1Country = computed(() => data.value?.top1_country_sim ?? 0)

// In standard variant we show all 5 country candidates + 3 globals (the
// globals are a fallback for when the seller listed a coin from a
// different country than the eBay query expected — ~20 % of cases per
// our measure).
const globalFallbackCount = 3

const formatYearTheme = (s: DinoSuggestion): string => {
  const bits = [s.year ? String(s.year) : null, s.theme]
  return bits.filter(Boolean).join(' · ')
}

// ─── Hover preview ──────────────────────────────────────────────────────
//
// Une seule preview à la fois. `hoveredKey` identifie la ligne (préfixe
// `c-` ou `g-` pour distinguer bande pays vs globale en cas de doublon
// d'eurio_id). Le rect viewport est capturé à mouseenter pour positionner
// la preview en `position: fixed` au-dessus de la ligne.

const hoveredKey = ref<string | null>(null)
const hoveredRect = ref<DOMRect | null>(null)
const hoveredSuggestion = ref<DinoSuggestion | null>(null)

function onRowEnter(key: string, suggestion: DinoSuggestion, e: MouseEvent) {
  const target = e.currentTarget as HTMLElement | null
  if (!target) return
  hoveredKey.value = key
  hoveredRect.value = target.getBoundingClientRect()
  hoveredSuggestion.value = suggestion
}

function onRowLeave(key: string) {
  if (hoveredKey.value === key) {
    hoveredKey.value = null
    hoveredRect.value = null
    hoveredSuggestion.value = null
  }
}

const previewLabel = computed(() => {
  const s = hoveredSuggestion.value
  if (!s) return null
  const bits = [s.country_name, formatYearTheme(s)].filter(Boolean)
  return bits.join(' · ') || null
})
</script>

<template>
  <!-- ── Variante "standard" : panel droit du SingleReviewView ── -->
  <section
    v-if="variant === 'standard'"
    class="rounded-lg border px-3 py-3"
    :style="{
      borderColor: 'var(--surface-3)',
      background: 'color-mix(in srgb, var(--indigo-700) 3%, var(--surface))',
    }"
  >
    <header class="flex items-baseline justify-between">
      <p
        class="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--indigo-700);"
      >
        <Sparkles class="h-3 w-3" />
        Suggestions Dino
      </p>
      <p
        v-if="data"
        class="font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--ink-400);"
      >
        spread
        <span :style="{ color: simTierColor(spreadLabel(data.spread).tone) }">
          {{ data.spread !== null ? data.spread.toFixed(3) : '—' }}
        </span>
        ·
        <span :style="{ color: simTierColor(spreadLabel(data.spread).tone) }">
          {{ spreadLabel(data.spread).text }}
        </span>
      </p>
    </header>

    <p
      v-if="loading"
      class="mt-3 font-mono text-[11px]"
      style="color: var(--ink-400);"
    >
      …chargement.
    </p>

    <p
      v-else-if="loaded && !data"
      class="mt-3 text-[11px]"
      style="color: var(--ink-400);"
    >
      Pas de prédiction Dino pour ce crop.<br />
      <span class="opacity-70">
        Hors scope (V1 = 2€ commémo) ou pas encore backfillé.
      </span>
    </p>

    <template v-else-if="data">
      <!-- ── Bande pays (primaire) ── -->
      <div v-if="hasCountryBand" class="mt-3">
        <div class="flex items-baseline justify-between">
          <p
            class="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-wider"
            style="color: var(--indigo-700);"
          >
            <Globe class="h-2.5 w-2.5" />
            Pays cible
            <span
              class="ml-0.5 font-semibold"
              :style="{ color: 'var(--indigo-700)' }"
            >
              {{ data.target_country?.toUpperCase() }}
            </span>
            <span class="font-normal" style="color: var(--ink-400);">
              · {{ data.country_anchors_count ?? 0 }} ancres
            </span>
          </p>
          <p
            v-if="data.country_spread !== null"
            class="font-mono text-[9px] uppercase tracking-wider"
            style="color: var(--ink-400);"
          >
            spread
            <span :style="{ color: simTierColor(spreadLabel(data.country_spread).tone) }">
              {{ data.country_spread.toFixed(3) }}
            </span>
          </p>
        </div>

        <ul class="mt-1.5 flex flex-col gap-1.5">
          <li
            v-for="(s, idx) in data.top_k_country"
            :key="`c-${s.eurio_id}-${idx}`"
            class="flex items-stretch gap-2.5 rounded-md border px-2 py-1.5 transition-colors"
            :style="{
              borderColor: s.eurio_id === assignedEurioId ? 'var(--success)' : 'var(--indigo-700)',
              background: s.eurio_id === assignedEurioId
                ? 'color-mix(in srgb, var(--success) 8%, var(--surface))'
                : 'var(--surface)',
            }"
            @mouseenter="onRowEnter(`c-${s.eurio_id}-${idx}`, s, $event)"
            @mouseleave="onRowLeave(`c-${s.eurio_id}-${idx}`)"
          >
            <img
              v-if="s.obverse_url"
              :src="s.obverse_url"
              :alt="s.eurio_id"
              class="h-9 w-9 shrink-0 rounded-md object-cover"
              style="background: var(--surface-1);"
            />
            <div
              v-else
              class="h-9 w-9 shrink-0 rounded-md"
              style="background: var(--surface-1);"
            />

            <div class="min-w-0 flex-1">
              <p
                class="truncate font-mono text-[11px] font-medium"
                style="color: var(--ink);"
              >
                {{ s.eurio_id }}
              </p>
              <p
                class="mt-0.5 truncate text-[10px]"
                style="color: var(--ink-500);"
              >
                <span v-if="s.country_name">{{ s.country_name }}</span>
                <span v-if="s.country_name && formatYearTheme(s)" class="opacity-50"> · </span>
                <span>{{ formatYearTheme(s) }}</span>
              </p>
            </div>

            <div class="flex shrink-0 flex-col items-end justify-center">
              <span
                class="font-mono text-[12px] font-semibold tabular-nums"
                :style="{ color: simTierColor(simTier(s.sim, top1Country)) }"
              >
                {{ s.sim.toFixed(3) }}
              </span>
              <span
                class="font-mono text-[8px] uppercase tracking-wider"
                style="color: var(--ink-400);"
              >
                sim
              </span>
            </div>

            <button
              type="button"
              class="shrink-0 rounded-md px-2 font-mono text-[10px] uppercase tracking-wider transition-colors active:scale-[0.97]"
              :style="{
                background: s.eurio_id === assignedEurioId ? 'var(--success)' : 'var(--indigo-700)',
                color: 'var(--surface)',
              }"
              @click="emit('select', s)"
            >
              {{ s.eurio_id === assignedEurioId ? '✓ validé' : 'Sélec.' }}
            </button>
          </li>
        </ul>
      </div>

      <!-- ── Bande globale (primaire si pas de country, sinon fallback) ── -->
      <div :class="hasCountryBand ? 'mt-3' : 'mt-2'">
        <p
          v-if="hasCountryBand"
          class="font-mono text-[9px] uppercase tracking-wider"
          style="color: var(--ink-400);"
        >
          Toute la bank — fallback si la query n'a pas le bon pays
        </p>

        <ul class="mt-1.5 flex flex-col gap-1.5">
          <li
            v-for="(s, idx) in (hasCountryBand ? data.top_k.slice(0, globalFallbackCount) : data.top_k)"
            :key="`g-${s.eurio_id}-${idx}`"
            class="flex items-stretch gap-2.5 rounded-md border px-2 py-1.5 transition-colors"
            :style="{
              borderColor: s.eurio_id === assignedEurioId ? 'var(--success)' : 'var(--surface-3)',
              background: s.eurio_id === assignedEurioId
                ? 'color-mix(in srgb, var(--success) 8%, var(--surface))'
                : 'var(--surface)',
            }"
            @mouseenter="onRowEnter(`g-${s.eurio_id}-${idx}`, s, $event)"
            @mouseleave="onRowLeave(`g-${s.eurio_id}-${idx}`)"
          >
            <img
              v-if="s.obverse_url"
              :src="s.obverse_url"
              :alt="s.eurio_id"
              class="h-9 w-9 shrink-0 rounded-md object-cover"
              style="background: var(--surface-1);"
            />
            <div
              v-else
              class="h-9 w-9 shrink-0 rounded-md"
              style="background: var(--surface-1);"
            />

            <div class="min-w-0 flex-1">
              <p
                class="truncate font-mono text-[11px] font-medium"
                style="color: var(--ink);"
              >
                {{ s.eurio_id }}
              </p>
              <p
                class="mt-0.5 truncate text-[10px]"
                style="color: var(--ink-500);"
              >
                <span v-if="s.country_name">{{ s.country_name }}</span>
                <span v-if="s.country_name && formatYearTheme(s)" class="opacity-50"> · </span>
                <span>{{ formatYearTheme(s) }}</span>
              </p>
            </div>

            <div class="flex shrink-0 flex-col items-end justify-center">
              <span
                class="font-mono text-[12px] font-semibold tabular-nums"
                :style="{ color: simTierColor(simTier(s.sim, top1Global)) }"
              >
                {{ s.sim.toFixed(3) }}
              </span>
              <span
                class="font-mono text-[8px] uppercase tracking-wider"
                style="color: var(--ink-400);"
              >
                sim
              </span>
            </div>

            <button
              type="button"
              class="shrink-0 rounded-md px-2 font-mono text-[10px] uppercase tracking-wider transition-colors active:scale-[0.97]"
              :style="{
                background: s.eurio_id === assignedEurioId ? 'var(--success)' : 'var(--indigo-700)',
                color: 'var(--surface)',
              }"
              @click="emit('select', s)"
            >
              {{ s.eurio_id === assignedEurioId ? '✓ validé' : 'Sélec.' }}
            </button>
          </li>
        </ul>
      </div>
    </template>

    <p
      v-if="data"
      class="mt-2 font-mono text-[9px] uppercase tracking-wider"
      style="color: var(--ink-400);"
    >
      {{ data.encoder_version }} · {{ data.anchors_count }} ancres · {{ data.anchors_kind }}
      <span v-if="data.duration_ms !== null"> · {{ data.duration_ms }}ms</span>
    </p>

    <CoinHoverPreview
      v-if="hoveredSuggestion && hoveredRect"
      :image-url="hoveredSuggestion.obverse_url ?? null"
      :eurio-id="hoveredSuggestion.eurio_id"
      :label="previewLabel"
      :anchor-rect="hoveredRect"
    />
  </section>

  <!-- ── Variante "compact" : sous chaque crop dans le drawer lot ── -->
  <section
    v-else
    class="flex flex-col gap-1"
  >
    <p
      class="inline-flex items-center gap-1 font-mono text-[9px] uppercase tracking-wider"
      style="color: var(--ink-500);"
    >
      <Sparkles class="h-2.5 w-2.5" style="color: var(--indigo-700);" />
      Dino
      <span
        v-if="hasCountryBand && data?.target_country"
        class="ml-1 inline-flex items-center gap-0.5 font-semibold"
        style="color: var(--indigo-700);"
      >
        <Globe class="h-2.5 w-2.5" />
        {{ data.target_country.toUpperCase() }}
      </span>
      <span
        v-if="data && (hasCountryBand ? data.country_spread : data.spread) !== null"
        class="ml-1 font-normal"
        :style="{
          color: simTierColor(
            spreadLabel(hasCountryBand ? data.country_spread : data.spread).tone,
          ),
        }"
      >
        spread
        {{ (hasCountryBand ? data.country_spread : data.spread)?.toFixed(3) ?? '—' }}
      </span>
    </p>

    <p
      v-if="loading"
      class="font-mono text-[10px]"
      style="color: var(--ink-400);"
    >…</p>

    <p
      v-else-if="loaded && !data"
      class="text-[10px]"
      style="color: var(--ink-400);"
    >
      —
    </p>

    <ul v-else-if="data" class="flex flex-wrap gap-1">
      <li
        v-for="(s, idx) in (hasCountryBand ? data.top_k_country : data.top_k).slice(0, 5)"
        :key="s.eurio_id + idx"
      >
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-md border px-1.5 py-0.5 transition-colors"
          :style="{
            borderColor: hasCountryBand ? 'var(--indigo-700)' : 'var(--surface-3)',
            background: 'var(--surface)',
          }"
          :title="`${s.eurio_id} · ${s.country_name ?? ''} ${formatYearTheme(s)}`"
          @click="emit('select', s)"
        >
          <img
            v-if="s.obverse_url"
            :src="s.obverse_url"
            :alt="s.eurio_id"
            class="h-5 w-5 rounded object-cover"
            style="background: var(--surface-1);"
          />
          <span
            class="font-mono text-[10px] tabular-nums"
            :style="{ color: simTierColor(simTier(s.sim, hasCountryBand ? top1Country : top1Global)) }"
          >
            {{ s.sim.toFixed(2) }}
          </span>
        </button>
      </li>
    </ul>
  </section>
</template>
