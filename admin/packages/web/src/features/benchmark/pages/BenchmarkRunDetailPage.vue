<script setup lang="ts">
import {
  fetchBenchmarkRun,
  thumbnailUrl,
} from '@/features/benchmark/composables/useBenchmarkApi'
import type { BenchmarkRunDetail } from '@/features/benchmark/types'
import PerConditionTable from '@/features/lab/components/PerConditionTable.vue'
import { ArrowLeft, Loader2 } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const runId = computed(() => String(route.params.id))
const run = ref<BenchmarkRunDetail | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

onMounted(load)

async function load() {
  loading.value = true
  error.value = null
  try {
    run.value = await fetchBenchmarkRun(runId.value)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

/* ───────── Derived ───────── */

function formatPct(v: number | null): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('fr-FR', {
    day: 'numeric', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function zoneColor(zone: string | null | undefined): string {
  if (zone === 'green') return 'var(--success)'
  if (zone === 'orange') return 'var(--warning)'
  if (zone === 'red') return 'var(--danger)'
  return 'var(--ink-400)'
}

/* Confusion matrix cells — simple heatmap (white → red), diagonal kept
   separate so it doesn't compress the scale. */

const confusionMatrix = computed(() => {
  if (!run.value) return { rows: [] as string[], cols: [] as string[], data: {} as Record<string, Record<string, number>>, max: 1 }
  const rows = Object.keys(run.value.confusion).sort()
  const colSet = new Set<string>()
  for (const r of rows) {
    for (const c of Object.keys(run.value.confusion[r])) colSet.add(c)
  }
  const cols = Array.from(colSet).sort()
  let max = 1
  for (const r of rows) {
    for (const c of cols) {
      if (r === c) continue
      const v = run.value.confusion[r]?.[c] || 0
      if (v > max) max = v
    }
  }
  return { rows, cols, data: run.value.confusion, max }
})

function cellStyle(row: string, col: string, max: number): Record<string, string> {
  const v = run.value?.confusion[row]?.[col] || 0
  if (v === 0) return { background: 'var(--surface)', color: 'var(--ink-400)' }
  if (row === col) {
    // diagonal — neutral
    return {
      background: 'color-mix(in srgb, var(--success) 20%, var(--surface))',
      color: 'var(--success)',
    }
  }
  const pct = Math.min(100, Math.round((v / max) * 100))
  return {
    background: `color-mix(in srgb, var(--danger) ${Math.max(5, pct * 0.6)}%, var(--surface))`,
    color: 'var(--ink)',
  }
}
</script>

<template>
  <div class="p-8">
    <button
      class="mb-4 flex items-center gap-1 text-sm transition-colors"
      style="color: var(--ink-500);"
      @click="router.push('/benchmark')"
    >
      <ArrowLeft class="h-3.5 w-3.5" />
      Retour à l'historique
    </button>

    <div v-if="loading" class="flex items-center gap-3 text-sm" style="color: var(--ink-500);">
      <Loader2 class="h-4 w-4 animate-spin" />
      Chargement…
    </div>
    <div
      v-else-if="error"
      class="rounded-md border px-4 py-3 text-sm"
      style="border-color: var(--danger); color: var(--ink);"
    >
      {{ error }}
    </div>
    <template v-else-if="run">
      <!-- Header -->
      <header class="mb-8">
        <p
          class="mb-1 text-[10px] font-medium uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          Benchmark · run {{ run.id }}
        </p>
        <h1
          class="font-display text-3xl italic font-semibold leading-tight"
          style="color: var(--indigo-700);"
        >
          {{ run.model_name }}
        </h1>
        <div class="mt-3 flex flex-wrap gap-4 text-xs" style="color: var(--ink-500);">
          <span>Recette : <span class="font-mono" style="color: var(--ink);">{{ run.recipe_id || '—' }}</span></span>
          <span>Training run : <span class="font-mono" style="color: var(--ink);">{{ run.training_run_id || '—' }}</span></span>
          <span>Démarré : {{ formatDate(run.started_at) }}</span>
          <span>Terminé : {{ formatDate(run.finished_at) }}</span>
          <span>Photos : <span class="font-mono" style="color: var(--ink);">{{ run.num_photos }}</span></span>
          <span>Pièces : <span class="font-mono" style="color: var(--ink);">{{ run.num_coins }}</span></span>
        </div>
        <div class="mt-6 h-px w-16" style="background: var(--gold);" />
      </header>

      <!-- Metric cards -->
      <section class="mb-10 grid grid-cols-2 gap-4 md:grid-cols-4">
        <article
          v-for="{ label, value, tint } in [
            { label: 'R@1 global', value: formatPct(run.r_at_1), tint: 'var(--indigo-700)' },
            { label: 'R@3 global', value: formatPct(run.r_at_3), tint: 'var(--ink)' },
            { label: 'R@5 global', value: formatPct(run.r_at_5), tint: 'var(--ink)' },
            { label: 'Spread moyen', value: run.mean_spread != null ? run.mean_spread.toFixed(3) : '—', tint: 'var(--ink)' },
          ]"
          :key="label"
          class="rounded-lg border p-5"
          style="border-color: var(--surface-3); background: var(--surface); box-shadow: var(--shadow-sm);"
        >
          <p
            class="text-[10px] font-medium uppercase"
            style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);"
          >
            {{ label }}
          </p>
          <p
            class="mt-2 font-display text-3xl font-semibold tabular-nums leading-none"
            :style="{ color: tint }"
          >
            {{ value }}
          </p>
        </article>
      </section>

      <!-- Per zone -->
      <section class="mb-10">
        <p
          class="mb-3 text-[10px] font-medium uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          Par zone
        </p>
        <div
          class="rounded-lg border"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b" style="border-color: var(--surface-3); background: var(--surface-1);">
                <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Zone</th>
                <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">Photos</th>
                <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">R@1</th>
                <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">R@3</th>
                <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">R@5</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(metrics, zone) in run.per_zone" :key="zone" class="border-b" style="border-color: var(--surface-3);">
                <td class="px-4 py-2">
                  <span
                    class="rounded-full px-2 py-0.5 text-[10px] font-medium"
                    :style="{
                      background: `color-mix(in srgb, ${zoneColor(zone)} 15%, var(--surface))`,
                      color: zoneColor(zone),
                    }"
                  >{{ zone }}</span>
                </td>
                <td class="px-4 py-2 text-right font-mono tabular-nums">{{ metrics.num_photos }}</td>
                <td class="px-4 py-2 text-right font-mono tabular-nums" style="color: var(--indigo-700);">
                  {{ formatPct(metrics.r_at_1) }}
                </td>
                <td class="px-4 py-2 text-right font-mono tabular-nums">{{ formatPct(metrics.r_at_3) }}</td>
                <td class="px-4 py-2 text-right font-mono tabular-nums">{{ formatPct(metrics.r_at_5) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Per coin -->
      <section class="mb-10">
        <p
          class="mb-3 text-[10px] font-medium uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          Par pièce
        </p>
        <div
          class="overflow-hidden rounded-lg border"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b" style="border-color: var(--surface-3); background: var(--surface-1);">
                <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">eurio_id</th>
                <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Zone</th>
                <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">Photos</th>
                <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">R@1</th>
                <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">R@3</th>
                <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">R@5</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="coin in run.per_coin" :key="coin.eurio_id" class="border-b" style="border-color: var(--surface-3);">
                <td class="px-4 py-2 font-mono text-xs" style="color: var(--ink);">{{ coin.eurio_id }}</td>
                <td class="px-4 py-2">
                  <span
                    v-if="coin.zone"
                    class="rounded-full px-2 py-0.5 text-[10px] font-medium"
                    :style="{
                      background: `color-mix(in srgb, ${zoneColor(coin.zone)} 15%, var(--surface))`,
                      color: zoneColor(coin.zone),
                    }"
                  >{{ coin.zone }}</span>
                  <span v-else class="text-xs" style="color: var(--ink-400);">—</span>
                </td>
                <td class="px-4 py-2 text-right font-mono tabular-nums">{{ coin.num_photos }}</td>
                <td
                  class="px-4 py-2 text-right font-mono tabular-nums"
                  :style="{
                    color: coin.r_at_1 >= 0.85
                      ? 'var(--success)'
                      : coin.r_at_1 >= 0.65 ? 'var(--warning)' : 'var(--danger)',
                  }"
                >
                  {{ formatPct(coin.r_at_1) }}
                </td>
                <td class="px-4 py-2 text-right font-mono tabular-nums">{{ formatPct(coin.r_at_3) }}</td>
                <td class="px-4 py-2 text-right font-mono tabular-nums">{{ formatPct(coin.r_at_5) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Per condition metrics -->
      <section class="mb-10" v-if="Object.keys(run.per_condition ?? {}).length">
        <p
          class="mb-3 text-[10px] font-medium uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          Par axe de variabilité (lighting / background / angle)
        </p>
        <PerConditionTable :per-condition="run.per_condition ?? {}" />
      </section>

      <!-- Confusion matrix -->
      <section class="mb-10" v-if="confusionMatrix.rows.length">
        <p
          class="mb-3 text-[10px] font-medium uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          Matrice de confusion (ground truth → prédiction)
        </p>
        <div class="overflow-x-auto">
          <table class="text-[11px]" style="border-collapse: separate; border-spacing: 2px;">
            <thead>
              <tr>
                <th class="px-2 py-1"></th>
                <th
                  v-for="c in confusionMatrix.cols"
                  :key="c"
                  class="px-2 py-1 text-left font-mono"
                  style="color: var(--ink-500); white-space: nowrap;"
                >
                  {{ c }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in confusionMatrix.rows" :key="r">
                <th
                  class="pr-2 py-1 text-right font-mono"
                  style="color: var(--ink-500); white-space: nowrap;"
                >
                  {{ r }}
                </th>
                <td
                  v-for="c in confusionMatrix.cols"
                  :key="c"
                  class="w-12 rounded px-2 py-1 text-center font-mono tabular-nums"
                  :style="cellStyle(r, c, confusionMatrix.max)"
                >
                  {{ run.confusion[r]?.[c] || '' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Top confusions -->
      <section v-if="run.top_confusions.length">
        <p
          class="mb-3 text-[10px] font-medium uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          Top {{ run.top_confusions.length }} photos foirées (spread ↑)
        </p>
        <div class="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
          <article
            v-for="conf in run.top_confusions"
            :key="conf.photo_path"
            class="overflow-hidden rounded-lg border"
            style="border-color: var(--surface-3); background: var(--surface);"
          >
            <img
              :src="thumbnailUrl(conf.photo_path.replace(/^ml\/data\/real_photos\//, ''))"
              :alt="conf.ground_truth"
              class="h-36 w-full object-cover"
              style="background: var(--surface-1);"
              loading="lazy"
            />
            <div class="p-3 text-xs">
              <p class="font-mono" style="color: var(--ink);">
                <span class="font-medium">GT:</span> {{ conf.ground_truth }}
              </p>
              <p class="mt-1" style="color: var(--ink-500);">
                spread <span class="font-mono" :style="{ color: conf.spread < 0.05 ? 'var(--danger)' : 'var(--ink)' }">
                  {{ conf.spread.toFixed(3) }}
                </span>
              </p>
              <ul class="mt-2 space-y-1">
                <li
                  v-for="(pred, i) in conf.top_3"
                  :key="pred.class_id"
                  class="flex items-center justify-between gap-1"
                >
                  <span class="font-mono" :style="{ color: i === 0 ? 'var(--danger)' : 'var(--ink-500)' }">
                    {{ i + 1 }}. {{ pred.class_id }}
                  </span>
                  <span class="font-mono tabular-nums" style="color: var(--ink-400);">
                    {{ pred.similarity.toFixed(3) }}
                  </span>
                </li>
              </ul>
            </div>
          </article>
        </div>
      </section>
    </template>
  </div>
</template>
