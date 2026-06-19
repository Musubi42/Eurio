<script setup lang="ts">
// Affiche les signaux extraits du titre du listing + verdict vs target
// (chunk 7 auto-validation). Aide visuelle, aucune décision : le filtre
// dur du chunk 6.c a déjà fait son boulot pipeline-side, ici on
// surface les axes pour que le reviewer comprenne pourquoi le verdict
// est ce qu'il est.
//
// Le signal vit au niveau du listing (= source_image), pas du crop —
// pour un lot, tous les crops d'un même listing partagent ce panneau.
//
// 404 silencieux : si le step text_signal n'a pas tourné (run d'avant
// chunk 5), le composant ne rend rien.

import { computed, ref, watch } from 'vue'
import { Type } from 'lucide-vue-next'
import {
  axisState,
  axisStateColor,
  axisStateGlyph,
  fetchTextSignalsByAssetId,
  fetchTextSignalsByReviewId,
  verdictColor,
  verdictLabel,
  verdictTone,
  type TextSignalsResponse,
} from '../composables/useTextSignals'

const props = defineProps<{
  /** review_queue.id (single drawer). One of reviewId/assetId required. */
  reviewId?: string | null
  /** image_assets.id (lot drawer). One of reviewId/assetId required. */
  assetId?: string | null
  /** Compact = strip horizontal léger. Standard = panel droit / gauche. */
  variant?: 'standard' | 'compact'
}>()

const variant = computed(() => props.variant ?? 'standard')
const data = ref<TextSignalsResponse | null>(null)
const loading = ref(false)
const loaded = ref(false)

async function load() {
  loading.value = true
  loaded.value = false
  data.value = null
  try {
    if (props.reviewId) {
      data.value = await fetchTextSignalsByReviewId(props.reviewId)
    } else if (props.assetId) {
      data.value = await fetchTextSignalsByAssetId(props.assetId)
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

const verdict = computed(() => data.value?.vs_target_verdict ?? null)
const tone = computed(() => verdictTone(verdict.value))
const verdictTextColor = computed(() => verdictColor(tone.value))

// Per-axis state — recomputed côté front via convergences/contradictions
// (cohérent avec comparator.py).
const countryState = computed(() =>
  data.value ? axisState(data.value, 'country') : null,
)
const yearState = computed(() =>
  data.value ? axisState(data.value, 'year') : null,
)
const denomState = computed(() =>
  data.value ? axisState(data.value, 'denomination') : null,
)

const matchedFor = (axis: 'countries' | 'years' | 'denominations'): string => {
  const m = data.value?.matched?.[axis] ?? []
  if (m.length === 0) return ''
  return m.join(', ')
}
</script>

<template>
  <!-- ── Variante "standard" : panel sous la card "Listing source" ── -->
  <section
    v-if="variant === 'standard'"
    class="rounded-lg border px-3 py-3"
    :style="{
      borderColor: 'var(--surface-3)',
      background: 'color-mix(in srgb, var(--ink-700) 2%, var(--surface))',
    }"
  >
    <header class="flex items-baseline justify-between">
      <p
        class="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--ink-700);"
      >
        <Type class="h-3 w-3" />
        Signal texte
      </p>
      <p
        v-if="data && data.vs_target_verdict"
        class="font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--ink-400);"
      >
        verdict
        <span class="ml-1 font-semibold" :style="{ color: verdictTextColor }">
          {{ verdictLabel(data.vs_target_verdict) }}
        </span>
      </p>
      <p
        v-else-if="data"
        class="font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--ink-400);"
      >
        verdict <span class="ml-1">n/a</span>
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
      Pas de signal texte pour ce listing.<br />
      <span class="opacity-70">
        Step `text_signal` pas encore exécuté.
      </span>
    </p>

    <template v-else-if="data">
      <!-- ── Axes ── -->
      <ul
        v-if="data.vs_target_verdict !== null"
        class="mt-2 flex flex-col gap-1"
      >
        <li
          class="flex items-baseline gap-2 font-mono text-[11px]"
          :style="{ color: countryState ? axisStateColor(countryState) : 'var(--ink-500)' }"
        >
          <span class="w-3 text-center" aria-hidden="true">
            {{ countryState ? axisStateGlyph(countryState) : '' }}
          </span>
          <span class="w-20 shrink-0 text-[10px] uppercase tracking-wider opacity-70">
            pays
          </span>
          <span class="flex-1" style="color: var(--ink-700);">
            <template v-if="data.countries.length">
              {{ data.countries.join(', ') }}
              <span v-if="matchedFor('countries')" class="ml-1 opacity-50">
                ({{ matchedFor('countries') }})
              </span>
            </template>
            <span v-else class="opacity-50">absent</span>
          </span>
        </li>
        <li
          class="flex items-baseline gap-2 font-mono text-[11px]"
          :style="{ color: yearState ? axisStateColor(yearState) : 'var(--ink-500)' }"
        >
          <span class="w-3 text-center" aria-hidden="true">
            {{ yearState ? axisStateGlyph(yearState) : '' }}
          </span>
          <span class="w-20 shrink-0 text-[10px] uppercase tracking-wider opacity-70">
            année
          </span>
          <span class="flex-1" style="color: var(--ink-700);">
            <template v-if="data.years.length">
              {{ data.years.join(', ') }}
            </template>
            <span v-else class="opacity-50">absent</span>
          </span>
        </li>
        <li
          class="flex items-baseline gap-2 font-mono text-[11px]"
          :style="{ color: denomState ? axisStateColor(denomState) : 'var(--ink-500)' }"
        >
          <span class="w-3 text-center" aria-hidden="true">
            {{ denomState ? axisStateGlyph(denomState) : '' }}
          </span>
          <span class="w-20 shrink-0 text-[10px] uppercase tracking-wider opacity-70">
            denom
          </span>
          <span class="flex-1" style="color: var(--ink-700);">
            <template v-if="data.denominations.length">
              {{ data.denominations.map((d) => d.toFixed(2)).join(', ') }}€
            </template>
            <span v-else class="opacity-50">absent</span>
          </span>
        </li>
      </ul>

      <!-- ── Verdict null (pas de target) ── -->
      <p
        v-else
        class="mt-2 text-[11px]"
        style="color: var(--ink-400);"
      >
        Target non résolu — comparaison impossible.
        <span v-if="data.coverage === 'empty'" class="opacity-70">
          (titre vide ou trop pauvre)
        </span>
      </p>

      <!-- ── Chips secondaires ── -->
      <div
        v-if="data.is_lot || data.rejected_markers.length || data.coverage !== 'rich'"
        class="mt-2 flex flex-wrap items-center gap-1"
      >
        <span
          v-if="data.is_lot"
          class="rounded-md border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider"
          :style="{
            borderColor: 'var(--gold-600)',
            color: 'var(--gold-600)',
            background: 'color-mix(in srgb, var(--gold-600) 6%, var(--surface))',
          }"
          title="Lot transfrontalier ou multi-pièces — auto-accept inhibé chunk 8"
        >
          lot
        </span>
        <span
          v-for="m in data.rejected_markers"
          :key="m"
          class="rounded-md border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider"
          :style="{
            borderColor: 'var(--danger)',
            color: 'var(--danger)',
            background: 'color-mix(in srgb, var(--danger) 4%, var(--surface))',
          }"
          :title="`Marker hors-scope détecté : ${m}`"
        >
          {{ m }}
        </span>
        <span
          v-if="data.coverage !== 'rich'"
          class="rounded-md border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider"
          :style="{
            borderColor: 'var(--surface-3)',
            color: 'var(--ink-500)',
            background: 'var(--surface)',
          }"
          :title="data.coverage === 'sparse' ? 'Titre partiel : 1 ou 2 axes sur 3' : 'Titre vide ou non exploitable'"
        >
          {{ data.coverage }}
        </span>
      </div>

      <p
        class="mt-2 font-mono text-[9px] uppercase tracking-wider"
        style="color: var(--ink-400);"
      >
        extracteur {{ data.extractor_version }}
      </p>
    </template>
  </section>

  <!-- ── Variante "compact" : strip horizontal (lot drawer header) ── -->
  <section v-else class="flex flex-wrap items-center gap-2">
    <p
      class="inline-flex items-center gap-1 font-mono text-[9px] uppercase tracking-wider"
      style="color: var(--ink-500);"
    >
      <Type class="h-2.5 w-2.5" style="color: var(--ink-700);" />
      Texte
    </p>

    <p v-if="loading" class="font-mono text-[10px]" style="color: var(--ink-400);">
      …
    </p>
    <p v-else-if="loaded && !data" class="text-[10px]" style="color: var(--ink-400);">
      —
    </p>

    <template v-else-if="data">
      <span
        v-if="data.vs_target_verdict"
        class="font-mono text-[10px] uppercase tracking-wider"
        :style="{ color: verdictTextColor }"
      >
        {{ verdictLabel(data.vs_target_verdict) }}
      </span>
      <span
        v-if="countryState"
        class="font-mono text-[10px]"
        :style="{ color: axisStateColor(countryState) }"
        :title="`pays · ${data.countries.join(', ') || 'absent'}`"
      >
        {{ axisStateGlyph(countryState) }} pays
      </span>
      <span
        v-if="yearState"
        class="font-mono text-[10px]"
        :style="{ color: axisStateColor(yearState) }"
        :title="`année · ${data.years.join(', ') || 'absent'}`"
      >
        {{ axisStateGlyph(yearState) }} année
      </span>
      <span
        v-if="denomState"
        class="font-mono text-[10px]"
        :style="{ color: axisStateColor(denomState) }"
        :title="`denom · ${data.denominations.join(', ') || 'absent'}€`"
      >
        {{ axisStateGlyph(denomState) }} denom
      </span>
      <span
        v-if="data.is_lot"
        class="rounded border px-1 font-mono text-[9px] uppercase"
        :style="{ borderColor: 'var(--gold-600)', color: 'var(--gold-600)' }"
      >
        lot
      </span>
    </template>
  </section>
</template>
