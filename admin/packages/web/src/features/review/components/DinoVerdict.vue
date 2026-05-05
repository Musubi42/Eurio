<script setup lang="ts">
// Affiche le verdict Dino par critère (top1==target, sim, spread) en
// miroir de TextSignals.vue. Aide visuelle, aucune décision : sert au
// reviewer à pinpointer pourquoi un crop n'est pas auto-candidat.
//
// Symétrique à TextSignals.vue côté layout/style — bandes ✓/✗ par axe.
//
// 404 silencieux : si le step auto_validate n'a pas tourné (run pré-
// chunk-2, ou hors scope V1 2€ commémo), on rend une note explicative
// au lieu de masquer — l'utilisateur veut savoir si Dino a tourné ou
// non sur ce crop.

import { computed, ref, watch } from 'vue'
import { Sparkles } from 'lucide-vue-next'
import {
  fetchDinoSuggestionsByAssetId,
  fetchDinoSuggestionsByReviewId,
  type DinoSuggestionsResponse,
} from '../composables/useDinoSuggestions'
import {
  computeDinoVerdict,
  criterionStateColor,
  criterionStateGlyph,
} from '../composables/useAutoValidateVerdict'

const props = defineProps<{
  /** review_queue.id (single drawer). One of reviewId/assetId required. */
  reviewId?: string | null
  /** image_assets.id (lot drawer). One of reviewId/assetId required. */
  assetId?: string | null
  /** Compact = strip horizontal léger. Standard = panel droit / gauche. */
  variant?: 'standard' | 'compact'
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

const verdict = computed(() => computeDinoVerdict(data.value))
</script>

<template>
  <!-- ── Variante "standard" ── -->
  <section
    v-if="variant === 'standard'"
    class="rounded-lg border px-3 py-3"
    :style="{
      borderColor: 'var(--surface-3)',
      background: 'color-mix(in srgb, var(--indigo-700) 2%, var(--surface))',
    }"
  >
    <header class="flex items-baseline justify-between">
      <p
        class="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--indigo-700);"
      >
        <Sparkles class="h-3 w-3" />
        Signal Dino
      </p>
      <p
        v-if="data && data.target_eurio_id"
        class="font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--ink-400);"
      >
        cible
        <span class="ml-1 font-semibold" style="color: var(--indigo-700);">
          {{ data.target_eurio_id }}
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
      <ul class="mt-2 flex flex-col gap-1">
        <li
          v-for="c in verdict.criteria"
          :key="c.key"
          class="flex items-baseline gap-2 font-mono text-[11px]"
          :style="{ color: criterionStateColor(c.state) }"
        >
          <span class="w-3 text-center" aria-hidden="true">
            {{ criterionStateGlyph(c.state) }}
          </span>
          <span class="w-28 shrink-0 text-[10px] uppercase tracking-wider opacity-70">
            {{ c.label }}
          </span>
          <span class="flex-1 truncate" style="color: var(--ink-700);" :title="c.hint">
            {{ c.value }}
            <span class="ml-1 opacity-50">({{ c.hint }})</span>
          </span>
        </li>
      </ul>

      <p
        class="mt-2 font-mono text-[9px] uppercase tracking-wider"
        style="color: var(--ink-400);"
      >
        {{ data.encoder_version }} · {{ data.anchors_kind }}
      </p>
    </template>
  </section>

  <!-- ── Variante "compact" : strip horizontal ── -->
  <section v-else class="flex flex-wrap items-center gap-2">
    <p
      class="inline-flex items-center gap-1 font-mono text-[9px] uppercase tracking-wider"
      style="color: var(--ink-500);"
    >
      <Sparkles class="h-2.5 w-2.5" style="color: var(--indigo-700);" />
      Dino
    </p>

    <p v-if="loading" class="font-mono text-[10px]" style="color: var(--ink-400);">
      …
    </p>
    <p v-else-if="loaded && !data" class="text-[10px]" style="color: var(--ink-400);">
      —
    </p>

    <template v-else-if="data">
      <span
        v-for="c in verdict.criteria"
        :key="c.key"
        class="font-mono text-[10px]"
        :style="{ color: criterionStateColor(c.state) }"
        :title="`${c.label} · ${c.value} (${c.hint})`"
      >
        {{ criterionStateGlyph(c.state) }} {{ c.label }}
      </span>
    </template>
  </section>
</template>
