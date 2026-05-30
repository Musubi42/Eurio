<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { fetchJoCoverage, type JoCoverageResponse } from '../composables/useReferentialApi'

const data = ref<JoCoverageResponse | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    data.value = await fetchJoCoverage()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
})

interface Cell { n_coins: number; n_jo: number; n_issued: number }

function cell(country: string, year: number): Cell | null {
  return data.value?.cells[country]?.[String(year)] ?? null
}

// Couleur de fond d'une cellule selon la couverture JO.
function cellStyle(c: Cell | null): string {
  if (!c || c.n_coins === 0) {
    return 'background: var(--surface-2); color: var(--ink-300);'
  }
  if (c.n_jo === 0) {
    return 'background: color-mix(in srgb, var(--danger) 12%, var(--surface)); color: var(--danger);'
  }
  if (c.n_jo < c.n_coins) {
    return 'background: color-mix(in srgb, var(--warning, #d97706) 14%, var(--surface)); color: var(--warning, #d97706);'
  }
  return 'background: color-mix(in srgb, var(--success) 14%, var(--surface)); color: var(--success);'
}

function cellLabel(c: Cell | null): string {
  if (!c || c.n_coins === 0) return ''
  return `${c.n_jo}/${c.n_coins}`
}

function cellTitle(country: string, year: number, c: Cell | null): string {
  if (!c || c.n_coins === 0) return `${country} ${year} — aucune commémorative`
  return `${country} ${year} — ${c.n_jo}/${c.n_coins} avis JO · ${c.n_issued} émise(s)`
}

const coveragePct = computed(() => {
  const s = data.value?.summary
  if (!s || s.total_coins === 0) return 0
  return Math.round((s.total_jo / s.total_coins) * 100)
})
</script>

<template>
  <div class="space-y-6 p-6">
    <header class="space-y-1">
      <RouterLink
        to="/referential"
        class="text-[10px] uppercase tracking-wider"
        style="color: var(--ink-500);"
      >← Référentiel</RouterLink>
      <h1 class="font-display text-2xl italic font-semibold" style="color: var(--indigo-700);">
        Couverture Journal Officiel
      </h1>
      <p class="text-sm" style="color: var(--ink-500);">
        Avis JO série C (source officielle) pour les commémoratives 2 € référencées.
        Filet de confiance : ce qu'on référence a-t-il bien sa fiche officielle ?
      </p>
    </header>

    <p v-if="loading" class="text-sm" style="color: var(--ink-500);">Chargement…</p>
    <p v-else-if="error" class="text-sm" style="color: var(--danger);">{{ error }}</p>

    <template v-else-if="data">
      <!-- Synthèse -->
      <div class="flex flex-wrap gap-4">
        <div class="rounded-lg border p-4" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Commémoratives</div>
          <div class="font-mono text-xl" style="color: var(--ink-900);">{{ data.summary.total_coins }}</div>
        </div>
        <div class="rounded-lg border p-4" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Avis JO</div>
          <div class="font-mono text-xl" style="color: var(--success);">{{ data.summary.total_jo }}</div>
        </div>
        <div class="rounded-lg border p-4" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Manquantes</div>
          <div class="font-mono text-xl" style="color: var(--danger);">{{ data.summary.total_gap }}</div>
        </div>
        <div class="rounded-lg border p-4" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Couverture</div>
          <div class="font-mono text-xl" style="color: var(--indigo-700);">{{ coveragePct }} %</div>
        </div>
      </div>

      <!-- Légende -->
      <div class="flex flex-wrap items-center gap-4 text-xs" style="color: var(--ink-500);">
        <span class="flex items-center gap-1">
          <span class="inline-block h-3 w-3 rounded" style="background: color-mix(in srgb, var(--success) 30%, var(--surface));" /> complet
        </span>
        <span class="flex items-center gap-1">
          <span class="inline-block h-3 w-3 rounded" style="background: color-mix(in srgb, var(--warning, #d97706) 30%, var(--surface));" /> partiel
        </span>
        <span class="flex items-center gap-1">
          <span class="inline-block h-3 w-3 rounded" style="background: color-mix(in srgb, var(--danger) 30%, var(--surface));" /> aucun avis JO
        </span>
        <span class="flex items-center gap-1">
          <span class="inline-block h-3 w-3 rounded" style="background: var(--surface-2);" /> rien cette année
        </span>
        <span>cellule = avis JO / pièces référencées</span>
      </div>

      <!-- Matrice -->
      <div class="rounded-lg border overflow-auto" style="border-color: var(--surface-3); background: var(--surface); max-height: 75vh;">
        <table class="text-xs" style="border-collapse: separate; border-spacing: 0;">
          <thead>
            <tr>
              <th
                class="sticky left-0 top-0 z-20 px-2 py-2 text-left font-semibold"
                style="background: var(--surface-2); color: var(--ink-700);"
              >Pays</th>
              <th
                v-for="y in data.years"
                :key="y"
                class="sticky top-0 z-10 px-2 py-2 text-center font-mono"
                style="background: var(--surface-2); color: var(--ink-700); min-width: 2.6rem;"
              >{{ y }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="country in data.countries" :key="country">
              <th
                class="sticky left-0 z-10 px-2 py-1 text-left font-mono font-semibold"
                style="background: var(--surface-2); color: var(--ink-900);"
              >{{ country }}</th>
              <td
                v-for="y in data.years"
                :key="y"
                class="px-2 py-1 text-center font-mono"
                :style="cellStyle(cell(country, y))"
                :title="cellTitle(country, y, cell(country, y))"
              >{{ cellLabel(cell(country, y)) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>
