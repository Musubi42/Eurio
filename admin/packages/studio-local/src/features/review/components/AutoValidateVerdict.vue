<script setup lang="ts">
// Synthèse top du drawer : verdict de CONSENSUS (C3) = la décision de routage
// qui fait foi (accepté / à revoir / rejeté) + la lane + la raison courte.
//
// Le verdict est calculé côté serveur (source unique) et exposé dans le champ
// `consensus_verdict` de la réponse dino-suggestions — c'est ce qui a décidé la
// lane en review_queue. On l'affiche tel quel (fin du drift où le verdict Dino
// 4-niveaux pouvait diverger de la lane, ex. crop_cap). Le détail Dino par
// critère vit dans `DinoVerdict.vue`. S'affiche TOUJOURS, même hors scope
// (Dino 404 → réponse null → on dégrade en "à revoir / manuel").

import { computed, ref, watch } from 'vue'
import { ShieldCheck } from 'lucide-vue-next'
import {
  fetchDinoSuggestionsByAssetId,
  fetchDinoSuggestionsByReviewId,
  type DinoSuggestionsResponse,
} from '../composables/useDinoSuggestions'
import {
  laneLabel,
  outcomeColor,
  outcomeLabel,
  type ConsensusLane,
  type ConsensusOutcome,
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

// Dino 404 (pas de prédiction / hors scope) → réponse null → on dégrade vers le
// filet humain (à revoir / manuel), cohérent avec la règle "aucun signal".
interface ConsensusView {
  outcome: ConsensusOutcome
  lane: ConsensusLane
  reason: string
}
const FALLBACK: ConsensusView = {
  outcome: 'needs_review',
  lane: 'manual',
  reason: 'Hors scope V1 (2€ commémo) ou Dino pas encore exécuté',
}
const verdict = computed<ConsensusView>(
  () => dino.value?.consensus_verdict ?? FALLBACK,
)
const color = computed(() => outcomeColor(verdict.value.outcome))
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
        Verdict consensus
      </p>
      <p
        class="font-mono text-[11px] font-semibold uppercase tracking-wider"
        :style="{ color }"
      >
        <span v-if="loading" class="opacity-60">…</span>
        <span v-else
          >{{ outcomeLabel(verdict.outcome) }}
          <span class="opacity-60">· {{ laneLabel(verdict.lane) }}</span></span
        >
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
