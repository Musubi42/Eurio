<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { fetchWikipediaMatrix, type WikiMatrixResponse, type WikiMatrixCell } from '../composables/useReferentialApi'

const data = ref<WikiMatrixResponse | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    data.value = await fetchWikipediaMatrix()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
})

function cell(country: string, year: number): WikiMatrixCell | null {
  return data.value?.cells[country]?.[String(year)] ?? null
}

// Couleur = statut de POSSESSION vs ce que Wikipédia recense.
function cellStyle(c: WikiMatrixCell | null): string {
  if (!c || (c.e_count === 0 && c.g_count === 0 && c.n_db === 0)) {
    return 'background: var(--surface-2); color: var(--ink-300);'
  }
  const expected = c.e_count
  if (expected === 0) {
    // Wikipédia : pas d'émission nationale cette année (tiret).
    return 'background: var(--surface); color: var(--ink-300);'
  }
  if (c.n_db >= expected) {
    return 'background: color-mix(in srgb, var(--success) 14%, var(--surface)); color: var(--success);'
  }
  if (c.n_db > 0) {
    return 'background: color-mix(in srgb, var(--warning, #d97706) 14%, var(--surface)); color: var(--warning, #d97706);'
  }
  return 'background: color-mix(in srgb, var(--danger) 12%, var(--surface)); color: var(--danger);'
}

function cellLabel(c: WikiMatrixCell | null): string {
  if (!c) return ''
  if (c.e_count === 0 && c.g_count === 0) return c.n_db === 0 ? '' : '–'
  if (c.e_count === 0) return '–'
  return c.e_planned ? `(${c.e_count})` : String(c.e_count)
}

function cellTitle(country: string, year: number, c: WikiMatrixCell | null): string {
  if (!c) return `${country} ${year}`
  const parts = [`${country} ${year}`]
  parts.push(`Wikipédia : ${c.e_count} nationale(s)${c.e_planned ? ' planifiée(s)' : ''}`)
  if (c.g_count > 0) parts.push(`+ ${c.g_count} commune(s)`)
  parts.push(`possédées en base : ${c.n_db}`)
  return parts.join(' · ')
}
</script>

<template>
  <div class="space-y-6 p-6">
    <header class="space-y-1">
      <RouterLink to="/referential" class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">← Référentiel</RouterLink>
      <h1 class="font-display text-2xl italic font-semibold" style="color: var(--indigo-700);">
        Matrice Wikipédia (DE)
      </h1>
      <p class="text-sm" style="color: var(--ink-500);">
        Vue d'ensemble des commémoratives 2 € par pays × année (source :
        de.wikipedia, <code>2-Euro-Gedenkmünzen</code>), avec marqueur de
        possession vs eurio.db. Montre aussi le non-émis (–) et le planifié (n).
      </p>
    </header>

    <p v-if="loading" class="text-sm" style="color: var(--ink-500);">Chargement…</p>
    <p v-else-if="error" class="text-sm" style="color: var(--danger);">{{ error }}</p>

    <template v-else-if="data">
      <div class="flex flex-wrap gap-4">
        <div class="rounded-lg border p-4" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Émissions nationales (Wikipédia)</div>
          <div class="font-mono text-xl" style="color: var(--ink-900);">{{ data.summary.total_wiki_national }}</div>
        </div>
        <div class="rounded-lg border p-4" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Possédées (eurio.db)</div>
          <div class="font-mono text-xl" style="color: var(--indigo-700);">{{ data.summary.total_owned }}</div>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-4 text-xs" style="color: var(--ink-500);">
        <span class="flex items-center gap-1"><span class="inline-block h-3 w-3 rounded" style="background: color-mix(in srgb, var(--success) 30%, var(--surface));" /> on possède tout</span>
        <span class="flex items-center gap-1"><span class="inline-block h-3 w-3 rounded" style="background: color-mix(in srgb, var(--warning, #d97706) 30%, var(--surface));" /> partiel</span>
        <span class="flex items-center gap-1"><span class="inline-block h-3 w-3 rounded" style="background: color-mix(in srgb, var(--danger) 30%, var(--surface));" /> manquant</span>
        <span class="flex items-center gap-1"><span class="inline-block h-3 w-3 rounded" style="background: var(--surface-2);" /> hors zone / non émis</span>
        <span>(n) = planifié · – = aucune émission</span>
      </div>

      <div class="rounded-lg border overflow-auto" style="border-color: var(--surface-3); background: var(--surface); max-height: 75vh;">
        <table class="text-xs" style="border-collapse: separate; border-spacing: 0;">
          <thead>
            <tr>
              <th class="sticky left-0 top-0 z-20 px-2 py-2 text-left font-semibold" style="background: var(--surface-2); color: var(--ink-700);">Pays</th>
              <th v-for="y in data.years" :key="y" class="sticky top-0 z-10 px-2 py-2 text-center font-mono" style="background: var(--surface-2); color: var(--ink-700); min-width: 2.6rem;">{{ y }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="country in data.countries" :key="country">
              <th class="sticky left-0 z-10 px-2 py-1 text-left font-mono font-semibold" style="background: var(--surface-2); color: var(--ink-900);">{{ country }}</th>
              <td
                v-for="y in data.years"
                :key="y"
                class="px-2 py-1 text-center font-mono"
                :style="cellStyle(cell(country, y))"
                :title="cellTitle(country, y, cell(country, y))"
              >
                {{ cellLabel(cell(country, y)) }}<sup v-if="cell(country, y)?.g_count" style="color: var(--indigo-700);">G</sup>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>
