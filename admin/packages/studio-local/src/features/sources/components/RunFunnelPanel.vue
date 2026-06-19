<script setup lang="ts">
// RunFunnelPanel — onglet « Logs / Entonnoir » de la page run-detail.
//
// Vue structurée d'un run : la séquence des steps du pipeline en badges,
// puis l'entonnoir discovery → rejets → détection → sortie. Tout vient
// de l'endpoint /funnel — aucun log texte. Les raisons de rejet sont
// dépliables (drill-down vers les listings écartés).

import { computed, onMounted, ref, watch } from 'vue'
import { CheckCircle2, ChevronRight, Loader2, XCircle } from 'lucide-vue-next'
import {
  fetchRunFunnel,
  type RunFunnel,
  type StepStatus,
} from '../composables/useRunFunnel'
import {
  fetchRunDiscarded,
  reasonLabel,
  reasonTone,
  type DiscardedListing,
} from '../composables/useRunDiscarded'
import type { SourceId } from '../composables/useSourcesApi'

const props = defineProps<{ sourceId: SourceId; runId: string }>()

const data = ref<RunFunnel | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

// Drill-down rejets : raison ouverte → listings écartés (lazy-loaded).
const openReason = ref<string | null>(null)
const reasonListings = ref<Record<string, DiscardedListing[]>>({})
const reasonLoading = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    data.value = await fetchRunFunnel(props.sourceId, props.runId)
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
    data.value = null
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(() => [props.sourceId, props.runId], load)

async function toggleReason(reason: string) {
  if (openReason.value === reason) {
    openReason.value = null
    return
  }
  openReason.value = reason
  if (!reasonListings.value[reason]) {
    reasonLoading.value = reason
    try {
      const res = await fetchRunDiscarded(props.sourceId, props.runId, { reason })
      reasonListings.value[reason] = res.listings
    } catch {
      reasonListings.value[reason] = []
    } finally {
      reasonLoading.value = null
    }
  }
}

// ─── Steps ──────────────────────────────────────────────────────────────

// Libellés courts des steps du pipeline (ids = PIPELINE_STEPS backend).
const STEP_LABEL: Record<string, string> = {
  discover: 'eBay search',
  persist: 'Persist',
  text_signal: 'Filtrage',
  download: 'Download',
  detect: 'Crop',
  resolve: 'Resolve',
  auto_validate: 'Auto-valid',
  enqueue: 'Review queue',
  price_aggregate: 'Prix',
}
function stepLabel(name: string): string {
  return STEP_LABEL[name] ?? name
}

const STEP_TONE: Record<StepStatus, string> = {
  done: 'var(--success)',
  running: 'var(--indigo-500)',
  pending: 'var(--ink-400)',
  failed: 'var(--danger)',
}

// ─── Funnel derived ─────────────────────────────────────────────────────

/** Largeur de barre relative au max d'une série (0-100 %). */
function barPct(value: number, max: number): number {
  return max > 0 ? Math.round((value / max) * 100) : 0
}

const discoveryDrop = computed(() =>
  data.value ? data.value.n_summaries - data.value.n_kept : 0,
)
const zeroCropPct = computed(() =>
  data.value && data.value.n_images > 0
    ? Math.round((data.value.n_zero_crops / data.value.n_images) * 100)
    : 0,
)

function fmtDuration(s: number | null): string {
  if (s == null) return '—'
  const m = Math.floor(s / 60)
  return m > 0 ? `${m} min ${Math.round(s % 60)} s` : `${Math.round(s)} s`
}
</script>

<template>
  <div>
    <div
      v-if="loading"
      class="flex items-center gap-2 py-12 text-sm"
      style="color: var(--ink-400);"
    >
      <Loader2 class="h-4 w-4 animate-spin" /> Chargement de l'entonnoir…
    </div>

    <div
      v-else-if="error"
      class="rounded-lg border px-5 py-3 text-sm"
      style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);"
    >
      {{ error }}
    </div>

    <template v-else-if="data">
      <!-- ═══ Steps du pipeline ═══ -->
      <section class="mb-7">
        <h3
          class="mb-3 font-mono text-[10px] uppercase tracking-wider"
          style="color: var(--ink-500);"
        >
          Pipeline · {{ fmtDuration(data.duration_s) }}
        </h3>
        <ol class="flex flex-wrap items-center gap-y-2">
          <li
            v-for="(step, i) in data.steps"
            :key="step.name"
            class="flex items-center"
          >
            <div
              class="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1"
              :style="{
                borderColor: STEP_TONE[step.status],
                color: STEP_TONE[step.status],
                background: `color-mix(in srgb, ${STEP_TONE[step.status]} 8%, var(--surface))`,
              }"
            >
              <span class="font-mono text-[9px] opacity-60">{{ i + 1 }}</span>
              <CheckCircle2 v-if="step.status === 'done'" class="h-3 w-3" />
              <Loader2 v-else-if="step.status === 'running'" class="h-3 w-3 animate-spin" />
              <XCircle v-else-if="step.status === 'failed'" class="h-3 w-3" />
              <span v-else class="h-1.5 w-1.5 rounded-full" style="background: currentColor;" />
              <span class="text-[11px] font-medium">{{ stepLabel(step.name) }}</span>
            </div>
            <ChevronRight
              v-if="i < data.steps.length - 1"
              class="mx-0.5 h-3 w-3 shrink-0"
              style="color: var(--ink-400);"
            />
          </li>
        </ol>
      </section>

      <!-- ═══ Entonnoir ═══ -->
      <div class="grid gap-4 md:grid-cols-3">
        <!-- Discovery -->
        <article
          class="rounded-lg border px-4 py-3"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
            Discovery
          </p>
          <p class="mt-2 font-mono text-[11px]" style="color: var(--ink-500);">
            {{ data.n_searches }} recherches · {{ data.n_summaries }} résultats bruts
          </p>
          <p class="mt-1 text-2xl font-semibold tabular-nums" style="color: var(--indigo-700);">
            {{ data.n_kept }}
            <span class="text-[11px] font-normal" style="color: var(--ink-400);">listings retenus</span>
          </p>
          <p class="mt-1 font-mono text-[11px]" style="color: var(--warning);">
            −{{ discoveryDrop }} écartés (voir ci-dessous)
          </p>
        </article>

        <!-- Détection -->
        <article
          class="rounded-lg border px-4 py-3"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
            Détection (crop)
          </p>
          <p class="mt-2 font-mono text-[11px]" style="color: var(--ink-500);">
            {{ data.n_images }} images téléchargées
          </p>
          <p class="mt-1 text-2xl font-semibold tabular-nums" style="color: var(--indigo-700);">
            {{ data.n_cropped }}
            <span class="text-[11px] font-normal" style="color: var(--ink-400);">images cropées</span>
          </p>
          <p
            class="mt-1 font-mono text-[11px]"
            :style="{ color: zeroCropPct > 50 ? 'var(--danger)' : 'var(--warning)' }"
          >
            ✕ {{ data.n_zero_crops }} zéro-crop ({{ zeroCropPct }} %)
            <span v-if="data.n_crop_pending" style="color: var(--ink-400);">
              · {{ data.n_crop_pending }} en attente
            </span>
          </p>
        </article>

        <!-- Sortie -->
        <article
          class="rounded-lg border px-4 py-3"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
            Sortie
          </p>
          <dl class="mt-2 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 font-mono text-[11px]">
            <dt style="color: var(--ink-500);">crops en review</dt>
            <dd class="text-right tabular-nums" style="color: var(--ink);">{{ data.n_review_enqueued }}</dd>
            <dt style="color: var(--ink-500);">pending quotes</dt>
            <dd class="text-right tabular-nums" style="color: var(--ink);">{{ data.n_pending_quotes }}</dd>
            <dt style="color: var(--ink-500);">quotes prix</dt>
            <dd class="text-right tabular-nums" style="color: var(--success);">{{ data.n_quotes }}</dd>
          </dl>
          <p
            v-if="data.n_errors"
            class="mt-2 font-mono text-[11px]"
            style="color: var(--warning);"
          >
            {{ data.n_errors }} erreurs · {{ data.error_summary }}
          </p>
        </article>
      </div>

      <!-- ═══ Rejets pré-ingestion ═══ -->
      <section class="mt-7">
        <h3
          class="mb-3 font-mono text-[10px] uppercase tracking-wider"
          style="color: var(--ink-500);"
        >
          Rejets · {{ data.n_discarded }}
        </h3>
        <div
          v-if="!data.discards.length"
          class="rounded-lg border-2 border-dashed px-6 py-6 text-center font-mono text-[11px]"
          style="border-color: var(--surface-3); color: var(--ink-400);"
        >
          Aucun listing rejeté.
        </div>
        <div
          v-else
          class="overflow-hidden rounded-lg border"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <template v-for="d in data.discards" :key="d.reason">
            <button
              type="button"
              class="flex w-full items-center gap-3 border-t px-4 py-2 text-left transition-colors first:border-t-0"
              style="border-color: var(--surface-2);"
              @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = 'var(--surface-1)')"
              @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')"
              @click="toggleReason(d.reason)"
            >
              <ChevronRight
                class="h-3 w-3 shrink-0 transition-transform"
                :style="{
                  color: 'var(--ink-400)',
                  transform: openReason === d.reason ? 'rotate(90deg)' : 'none',
                }"
              />
              <span
                class="rounded px-1.5 py-0.5 font-mono text-[10px]"
                :style="{
                  color: reasonTone(d.reason),
                  background: `color-mix(in srgb, ${reasonTone(d.reason)} 12%, var(--surface))`,
                }"
              >
                {{ d.reason }}
              </span>
              <span class="flex-1 truncate text-[11px]" style="color: var(--ink-500);">
                {{ reasonLabel(d.reason) }}
              </span>
              <!-- Barre proportionnelle -->
              <span class="hidden h-1.5 w-24 overflow-hidden rounded-full sm:block"
                    style="background: var(--surface-2);">
                <span
                  class="block h-full"
                  :style="{
                    width: barPct(d.count, data.n_discarded) + '%',
                    background: reasonTone(d.reason),
                  }"
                />
              </span>
              <span class="w-10 text-right font-mono text-[12px] font-semibold tabular-nums"
                    style="color: var(--ink);">
                {{ d.count }}
              </span>
            </button>

            <!-- Drill-down : listings écartés pour cette raison -->
            <div
              v-if="openReason === d.reason"
              class="border-t px-4 py-2"
              style="border-color: var(--surface-2); background: var(--surface-1);"
            >
              <div
                v-if="reasonLoading === d.reason"
                class="flex items-center gap-2 py-2 font-mono text-[11px]"
                style="color: var(--ink-400);"
              >
                <Loader2 class="h-3 w-3 animate-spin" /> Chargement…
              </div>
              <ul v-else class="flex flex-col gap-1 py-1">
                <li
                  v-for="l in (reasonListings[d.reason] ?? []).slice(0, 50)"
                  :key="l.id"
                  class="flex items-baseline gap-2 font-mono text-[11px]"
                >
                  <span v-if="l.price != null" class="shrink-0 tabular-nums" style="color: var(--ink-400);">
                    {{ l.price.toFixed(2) }}{{ l.currency === 'EUR' ? '€' : ' ' + (l.currency ?? '') }}
                  </span>
                  <span class="truncate" style="color: var(--ink-700);">
                    {{ l.title || l.source_ref }}
                  </span>
                  <a
                    v-if="l.item_web_url"
                    :href="l.item_web_url"
                    target="_blank"
                    rel="noopener"
                    class="shrink-0 underline"
                    style="color: var(--indigo-700);"
                  >eBay</a>
                </li>
                <li
                  v-if="(reasonListings[d.reason] ?? []).length > 50"
                  class="font-mono text-[10px]"
                  style="color: var(--ink-400);"
                >
                  … +{{ (reasonListings[d.reason] ?? []).length - 50 }} autres
                </li>
              </ul>
            </div>
          </template>
        </div>
      </section>
    </template>
  </div>
</template>
