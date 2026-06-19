<script setup lang="ts">
import { useDashboardQuery } from '@/features/lab/composables/useLabQueries'
import { Loader2 } from 'lucide-vue-next'
import { computed } from 'vue'

const dashboardQuery = useDashboardQuery()
const data = computed(() => dashboardQuery.data.value ?? null)
const loading = computed(() => dashboardQuery.isLoading.value && !data.value)
const error = computed(() => (dashboardQuery.error.value as Error | null)?.message ?? null)

const empty = computed(() =>
  !!data.value &&
  data.value.top_recipes.length === 0 &&
  data.value.difficult_coins.length === 0 &&
  data.value.distance_distribution.total === 0,
)

function pct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function tintForR1(v: number | null): string {
  if (v == null) return 'var(--ink-400)'
  if (v >= 0.85) return 'var(--success)'
  if (v >= 0.70) return 'var(--warning)'
  return 'var(--danger)'
}

const maxBinCount = computed(() => {
  const bins = data.value?.distance_distribution.bins ?? []
  return Math.max(1, ...bins.map((b) => b.count))
})
</script>

<template>
  <section class="mb-10">
    <div class="mb-4 flex items-center justify-between">
      <p
        class="text-[10px] font-medium uppercase"
        style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
      >
        Dashboard cross-cohort
      </p>
    </div>

    <div
      v-if="loading"
      class="flex items-center gap-2 rounded-lg border p-4 text-sm"
      style="border-color: var(--surface-3); color: var(--ink-400);"
    >
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

    <div
      v-else-if="empty"
      class="rounded-lg border p-4 text-sm"
      style="border-color: var(--surface-3); color: var(--ink-500);"
    >
      Pas encore de données agrégées — termine une itération avec live tests
      pour voir le dashboard se peupler.
    </div>

    <div v-else-if="data" class="grid gap-4 lg:grid-cols-3">
      <!-- Top recipes -->
      <article
        class="rounded-lg border p-4"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <p class="mb-3 text-[11px] font-medium uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
          Top recipes (R@1 live moyen)
        </p>
        <div v-if="data.top_recipes.length === 0" class="text-xs" style="color: var(--ink-500);">
          Aucune iteration completed avec recipe + live tests pour l'instant.
        </div>
        <ul v-else class="space-y-2">
          <li
            v-for="r in data.top_recipes.slice(0, 5)"
            :key="r.recipe_id"
            class="flex items-baseline justify-between gap-2 text-xs"
          >
            <div class="min-w-0 flex-1">
              <span class="truncate font-mono" style="color: var(--ink);">
                {{ r.recipe_name || r.recipe_id }}
              </span>
              <span v-if="r.zone" class="ml-2 text-[10px]" style="color: var(--ink-500);">
                · {{ r.zone }}
              </span>
            </div>
            <div class="flex flex-shrink-0 items-baseline gap-2 tabular-nums">
              <span :style="{ color: tintForR1(r.mean_live_r_at_1) }">
                {{ pct(r.mean_live_r_at_1) }}
              </span>
              <span class="text-[10px]" style="color: var(--ink-500);">
                / studio {{ pct(r.mean_studio_r_at_1) }}
              </span>
              <span class="text-[10px]" style="color: var(--ink-400);">
                ({{ r.n_iterations }})
              </span>
            </div>
          </li>
        </ul>
      </article>

      <!-- Difficult coins -->
      <article
        class="rounded-lg border p-4"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <p class="mb-3 text-[11px] font-medium uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
          Pièces difficiles (R@1 live &lt; {{ pct(data.distance_distribution.threshold_difficult_r_at_1) }})
        </p>
        <p class="mb-2 text-[10px]" style="color: var(--ink-500);">
          Sur ≥ {{ data.distance_distribution.min_iterations_for_difficult }} itérations distinctes.
        </p>
        <div v-if="data.difficult_coins.length === 0" class="text-xs" style="color: var(--ink-500);">
          Aucune pièce ne tombe sous le seuil — joli.
        </div>
        <ul v-else class="space-y-2">
          <li
            v-for="c in data.difficult_coins.slice(0, 8)"
            :key="c.eurio_id"
            class="flex items-baseline justify-between gap-2 text-xs"
          >
            <span class="truncate font-mono" style="color: var(--ink);">
              {{ c.eurio_id }}
            </span>
            <div class="flex flex-shrink-0 items-baseline gap-2 tabular-nums">
              <span :style="{ color: tintForR1(c.mean_live_r_at_1) }">
                {{ pct(c.mean_live_r_at_1) }}
              </span>
              <span class="text-[10px]" style="color: var(--ink-400);">
                ({{ c.n_iterations }})
              </span>
            </div>
          </li>
        </ul>
      </article>

      <!-- Distance distribution -->
      <article
        class="rounded-lg border p-4"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <p class="mb-3 text-[11px] font-medium uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
          Cosines aug ↔ réel ({{ data.distance_distribution.total }})
        </p>
        <div v-if="data.distance_distribution.total === 0" class="text-xs" style="color: var(--ink-500);">
          Aucun cache aug↔réel calculé.
        </div>
        <div v-else class="space-y-2">
          <div
            v-for="bin in data.distance_distribution.bins"
            :key="bin.range"
            class="flex items-center gap-2 text-xs"
          >
            <span class="w-20 font-mono tabular-nums" style="color: var(--ink-500);">{{ bin.range }}</span>
            <div class="relative h-2 flex-1 overflow-hidden rounded-full" style="background: var(--surface-1);">
              <div
                class="absolute inset-y-0 left-0 rounded-full"
                :style="{
                  width: `${(bin.count / maxBinCount) * 100}%`,
                  background: 'var(--indigo-700)',
                }"
              />
            </div>
            <span class="w-8 text-right tabular-nums" style="color: var(--ink);">
              {{ bin.count }}
            </span>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>
