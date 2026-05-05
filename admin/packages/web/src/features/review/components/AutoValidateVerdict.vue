<script setup lang="ts">
// Synthèse top du drawer : verdict global d'auto-validation en 3
// niveaux (auto_candidate / partial / divergent) + raison courte.
//
// Réplique en miniature ce que fera le chunk 8 (auto-accept) sans
// écrire en DB. Source de vérité = les seuils de
// ml/foundation/thresholds.py exposés par l'API Dino.
//
// Le composant fetche lui-même Dino + Texte (via les composables) pour
// rester drop-in dans n'importe quel drawer ; il s'affiche TOUJOURS,
// même quand Dino n'a pas tourné (état "unknown" → "Hors scope V1").

import { computed, ref, watch } from 'vue'
import { ShieldCheck } from 'lucide-vue-next'
import {
  fetchDinoSuggestionsByAssetId,
  fetchDinoSuggestionsByReviewId,
  type DinoSuggestionsResponse,
} from '../composables/useDinoSuggestions'
import {
  fetchTextSignalsByAssetId,
  fetchTextSignalsByReviewId,
  type TextSignalsResponse,
} from '../composables/useTextSignals'
import {
  computeAutoValidateVerdict,
  computeDinoVerdict,
  levelColor,
  levelLabel,
} from '../composables/useAutoValidateVerdict'

const props = defineProps<{
  /** review_queue.id (single drawer). One of reviewId/assetId required. */
  reviewId?: string | null
  /** image_assets.id (lot drawer). One of reviewId/assetId required. */
  assetId?: string | null
}>()

const dino = ref<DinoSuggestionsResponse | null>(null)
const text = ref<TextSignalsResponse | null>(null)
const loading = ref(false)
const loaded = ref(false)

async function load() {
  loading.value = true
  loaded.value = false
  dino.value = null
  text.value = null
  try {
    if (props.reviewId) {
      const [d, t] = await Promise.all([
        fetchDinoSuggestionsByReviewId(props.reviewId),
        fetchTextSignalsByReviewId(props.reviewId),
      ])
      dino.value = d
      text.value = t
    } else if (props.assetId) {
      const [d, t] = await Promise.all([
        fetchDinoSuggestionsByAssetId(props.assetId),
        fetchTextSignalsByAssetId(props.assetId),
      ])
      dino.value = d
      text.value = t
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

const verdict = computed(() =>
  computeAutoValidateVerdict(computeDinoVerdict(dino.value), text.value),
)
const color = computed(() => levelColor(verdict.value.level))
</script>

<template>
  <section
    class="rounded-lg border px-3 py-2"
    :style="{
      borderColor: color,
      background: `color-mix(in srgb, ${color} 6%, var(--surface))`,
    }"
  >
    <div class="flex items-center justify-between gap-3">
      <p
        class="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider"
        :style="{ color }"
      >
        <ShieldCheck class="h-3 w-3" />
        Verdict auto-validate
      </p>
      <p
        class="font-mono text-[11px] font-semibold uppercase tracking-wider"
        :style="{ color }"
      >
        <span v-if="loading" class="opacity-60">…</span>
        <span v-else>{{ levelLabel(verdict.level) }}</span>
      </p>
    </div>
    <p
      v-if="!loading"
      class="mt-1 font-mono text-[10px]"
      style="color: var(--ink-500);"
    >
      {{ verdict.reason }}
    </p>
  </section>
</template>
