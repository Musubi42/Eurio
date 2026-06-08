<script setup lang="ts">
// Synthèse top du drawer : verdict global d'auto-validation en 4 niveaux
// (auto_candidate / partial / divergent / unknown) + raison courte.
//
// Le verdict est calculé côté serveur (source unique — C0 du redesign
// auto-validation) et exposé dans le champ `auto_validate_verdict` de la
// réponse dino-suggestions. Ce composant ne fetche plus que Dino (le verdict
// embarque déjà la comparaison Dino + Texte) et l'affiche tel quel ; il
// s'affiche TOUJOURS, même hors scope (Dino 404 → état "unknown").

import { computed, ref, watch } from 'vue'
import { ShieldCheck } from 'lucide-vue-next'
import {
  fetchDinoSuggestionsByAssetId,
  fetchDinoSuggestionsByReviewId,
  type DinoSuggestionsResponse,
} from '../composables/useDinoSuggestions'
import {
  levelColor,
  levelLabel,
  type AutoValidateLevel,
} from '../composables/useAutoValidateVerdict'

const props = defineProps<{
  /** review_queue.id (single drawer). One of reviewId/assetId required. */
  reviewId?: string | null
  /** image_assets.id (lot drawer). One of reviewId/assetId required. */
  assetId?: string | null
}>()

const dino = ref<DinoSuggestionsResponse | null>(null)
const loading = ref(false)
const loaded = ref(false)

async function load() {
  loading.value = true
  loaded.value = false
  dino.value = null
  try {
    if (props.reviewId) {
      dino.value = await fetchDinoSuggestionsByReviewId(props.reviewId)
    } else if (props.assetId) {
      dino.value = await fetchDinoSuggestionsByAssetId(props.assetId)
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

// Dino 404 (pas de prédiction) → réponse null → on dégrade en "unknown".
// Le serveur ne renvoie jamais auto_validate_verdict=null en pratique (404
// amont quand il n'y a pas de prédiction).
const UNKNOWN: { level: AutoValidateLevel; reason: string } = {
  level: 'unknown',
  reason: 'Hors scope V1 (2€ commémo) ou Dino pas encore exécuté',
}
const verdict = computed(() => dino.value?.auto_validate_verdict ?? UNKNOWN)
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
