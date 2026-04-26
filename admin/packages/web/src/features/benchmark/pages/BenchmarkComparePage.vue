<script setup lang="ts">
import { fetchBenchmarkRun } from '@/features/benchmark/composables/useBenchmarkApi'
import type { BenchmarkRunDetail } from '@/features/benchmark/types'
import { ArrowLeft, Loader2 } from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const idA = computed(() => (route.query.a ? String(route.query.a) : null))
const idB = computed(() => (route.query.b ? String(route.query.b) : null))

const runA = ref<BenchmarkRunDetail | null>(null)
const runB = ref<BenchmarkRunDetail | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

async function load() {
  if (!idA.value || !idB.value) {
    error.value = 'Paramètres a et b requis'
    loading.value = false
    return
  }
  loading.value = true
  error.value = null
  try {
    const [a, b] = await Promise.all([
      fetchBenchmarkRun(idA.value),
      fetchBenchmarkRun(idB.value),
    ])
    runA.value = a
    runB.value = b
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch([idA, idB], load)

/* ───────── Derived ───────── */

function formatPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function delta(a: number | null, b: number | null): string {
  if (a == null || b == null) return '—'
  const d = (b - a) * 100
  const sign = d > 0 ? '+' : ''
  return `${sign}${d.toFixed(1)} pts`
}

function deltaColor(a: number | null, b: number | null): string {
  if (a == null || b == null) return 'var(--ink-400)'
  const d = b - a
  if (d > 0.005) return 'var(--success)'
  if (d < -0.005) return 'var(--danger)'
  return 'var(--ink-500)'
}

function zoneColor(zone: string | null | undefined): string {
  if (zone === 'green') return 'var(--success)'
  if (zone === 'orange') return 'var(--warning)'
  if (zone === 'red') return 'var(--danger)'
  return 'var(--ink-400)'
}

const unionCoins = computed(() => {
  const set = new Set<string>()
  for (const r of [runA.value, runB.value]) {
    if (!r) continue
    for (const c of r.per_coin) set.add(c.eurio_id)
  }
  return Array.from(set).sort()
})

function coinMetric(run: BenchmarkRunDetail | null, eurio_id: string) {
  if (!run) return null
  return run.per_coin.find(c => c.eurio_id === eurio_id) ?? null
}

const unionZones = computed(() => {
  const set = new Set<string>()
  for (const r of [runA.value, runB.value]) {
    if (!r) continue
    for (const z of Object.keys(r.per_zone)) set.add(z)
  }
  return Array.from(set).sort()
})
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
      Chargement des deux runs…
    </div>
    <div
      v-else-if="error"
      class="rounded-md border px-4 py-3 text-sm"
      style="border-color: var(--danger); color: var(--ink);"
    >
      {{ error }}
    </div>
    <template v-else-if="runA && runB">
      <!-- Header -->
      <header class="mb-8">
        <p
          class="mb-1 text-[10px] font-medium uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          Comparaison binaire · A vs B
        </p>
        <h1
          class="font-display text-3xl italic font-semibold leading-tight"
          style="color: var(--indigo-700);"
        >
          {{ runA.model_name }} <span style="color: var(--ink-400);">vs</span> {{ runB.model_name }}
        </h1>
        <div class="mt-6 h-px w-16" style="background: var(--gold);" />
      </header>

      <!-- Side-by-side overview -->
      <section class="mb-10 grid grid-cols-2 gap-4">
        <article
          v-for="(run, label) in { A: runA, B: runB }"
          :key="label"
          class="rounded-lg border p-5"
          style="border-color: var(--surface-3); background: var(--surface); box-shadow: var(--shadow-sm);"
        >
          <div class="flex items-baseline justify-between">
            <p
              class="text-[10px] font-medium uppercase"
              style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);"
            >
              Run {{ label }}
            </p>
            <span class="font-mono text-[10px]" style="color: var(--ink-400);">{{ run.id }}</span>
          </div>
          <p class="mt-2 font-display text-xl italic" style="color: var(--indigo-700);">
            {{ run.model_name }}
          </p>
          <p class="mt-1 text-xs" style="color: var(--ink-500);">
            Recette : <span class="font-mono" style="color: var(--ink);">{{ run.recipe_id || '—' }}</span>
          </p>
          <p class="mt-1 text-xs" style="color: var(--ink-500);">
            {{ run.num_photos }} photos · {{ run.num_coins }} pièces
          </p>
        </article>
      </section>

      <!-- Global metrics diff -->
      <section class="mb-10">
        <p
          class="mb-3 text-[10px] font-medium uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          Métriques globales
        </p>
        <div
          class="overflow-hidden rounded-lg border"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b" style="border-color: var(--surface-3); background: var(--surface-1);">
                <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Métrique</th>
                <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">A</th>
                <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">B</th>
                <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">Δ (B − A)</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="{ key, label } in [
                  { key: 'r_at_1', label: 'R@1' },
                  { key: 'r_at_3', label: 'R@3' },
                  { key: 'r_at_5', label: 'R@5' },
                ] as const"
                :key="key"
                class="border-b"
                style="border-color: var(--surface-3);"
              >
                <td class="px-4 py-2">{{ label }}</td>
                <td class="px-4 py-2 text-right font-mono tabular-nums">
                  {{ formatPct(runA[key]) }}
                </td>
                <td class="px-4 py-2 text-right font-mono tabular-nums">
                  {{ formatPct(runB[key]) }}
                </td>
                <td
                  class="px-4 py-2 text-right font-mono tabular-nums"
                  :style="{ color: deltaColor(runA[key], runB[key]) }"
                >
                  {{ delta(runA[key], runB[key]) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Per-zone diff -->
      <section class="mb-10">
        <p
          class="mb-3 text-[10px] font-medium uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          Par zone (R@1)
        </p>
        <div
          class="overflow-hidden rounded-lg border"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b" style="border-color: var(--surface-3); background: var(--surface-1);">
                <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Zone</th>
                <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">A</th>
                <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">B</th>
                <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">Δ</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="z in unionZones" :key="z" class="border-b" style="border-color: var(--surface-3);">
                <td class="px-4 py-2">
                  <span
                    class="rounded-full px-2 py-0.5 text-[10px] font-medium"
                    :style="{
                      background: `color-mix(in srgb, ${zoneColor(z)} 15%, var(--surface))`,
                      color: zoneColor(z),
                    }"
                  >{{ z }}</span>
                </td>
                <td class="px-4 py-2 text-right font-mono tabular-nums">
                  {{ formatPct(runA.per_zone[z]?.r_at_1 ?? null) }}
                </td>
                <td class="px-4 py-2 text-right font-mono tabular-nums">
                  {{ formatPct(runB.per_zone[z]?.r_at_1 ?? null) }}
                </td>
                <td
                  class="px-4 py-2 text-right font-mono tabular-nums"
                  :style="{ color: deltaColor(runA.per_zone[z]?.r_at_1 ?? null, runB.per_zone[z]?.r_at_1 ?? null) }"
                >
                  {{ delta(runA.per_zone[z]?.r_at_1 ?? null, runB.per_zone[z]?.r_at_1 ?? null) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Per-coin diff -->
      <section>
        <p
          class="mb-3 text-[10px] font-medium uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          Par pièce (R@1)
        </p>
        <div
          class="overflow-hidden rounded-lg border"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b" style="border-color: var(--surface-3); background: var(--surface-1);">
                <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">eurio_id</th>
                <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">A</th>
                <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">B</th>
                <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">Δ</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="eid in unionCoins" :key="eid" class="border-b" style="border-color: var(--surface-3);">
                <td class="px-4 py-2 font-mono text-xs" style="color: var(--ink);">{{ eid }}</td>
                <td class="px-4 py-2 text-right font-mono tabular-nums">
                  {{ formatPct(coinMetric(runA, eid)?.r_at_1 ?? null) }}
                </td>
                <td class="px-4 py-2 text-right font-mono tabular-nums">
                  {{ formatPct(coinMetric(runB, eid)?.r_at_1 ?? null) }}
                </td>
                <td
                  class="px-4 py-2 text-right font-mono tabular-nums"
                  :style="{ color: deltaColor(coinMetric(runA, eid)?.r_at_1 ?? null, coinMetric(runB, eid)?.r_at_1 ?? null) }"
                >
                  {{ delta(coinMetric(runA, eid)?.r_at_1 ?? null, coinMetric(runB, eid)?.r_at_1 ?? null) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>
