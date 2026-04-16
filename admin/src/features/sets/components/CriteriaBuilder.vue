<script setup lang="ts">
import type { IssueType, SetCriteria } from '@/shared/supabase/types'
import { computed } from 'vue'
import {
  EUROZONE_COUNTRIES,
  FACE_VALUES,
  MICRO_STATES,
  PSEUDO_COUNTRIES,
  formatFaceValue,
} from '../constants/countries'
import { useCoinSeries } from '../composables/useCoinSeries'

const props = defineProps<{
  modelValue: SetCriteria | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: SetCriteria]
}>()

const criteria = computed<SetCriteria>(() => props.modelValue ?? {})

function patch(update: Partial<SetCriteria>) {
  // Strip undefined keys to keep the JSONB clean
  const next = { ...criteria.value, ...update }
  for (const k of Object.keys(next) as (keyof SetCriteria)[]) {
    const v = next[k]
    if (
      v === undefined
      || v === null
      || (Array.isArray(v) && v.length === 0)
      || v === ''
    ) {
      delete next[k]
    }
  }
  emit('update:modelValue', next)
}

// ───────── Countries ─────────
const selectedCountries = computed(() => {
  const v = criteria.value.country
  if (!v) return new Set<string>()
  return new Set(Array.isArray(v) ? v : [v])
})

function toggleCountry(code: string) {
  const set = new Set(selectedCountries.value)
  if (set.has(code)) set.delete(code)
  else set.add(code)
  const arr = [...set]
  if (arr.length === 0) patch({ country: undefined })
  else if (arr.length === 1) patch({ country: arr[0] })
  else patch({ country: arr })
}

// ───────── Issue type ─────────
const ISSUE_TYPES: { value: IssueType; label: string }[] = [
  { value: 'circulation',      label: 'Circulation' },
  { value: 'commemo-national', label: 'Commémo nationale' },
  { value: 'commemo-common',   label: 'Commémo commune' },
]

const selectedIssueType = computed(() => {
  const v = criteria.value.issue_type
  if (!v) return null
  return Array.isArray(v) ? v[0] : v
})

function setIssueType(t: IssueType | null) {
  patch({ issue_type: t ?? undefined })
}

// ───────── Year ─────────
const yearIsCurrent = computed(() => criteria.value.year === 'current')
const yearNumber = computed(() =>
  typeof criteria.value.year === 'number' ? criteria.value.year : null,
)

function setYearNumber(val: string) {
  const n = parseInt(val, 10)
  if (isNaN(n)) patch({ year: undefined })
  else patch({ year: n })
}

function setYearCurrent(current: boolean) {
  patch({ year: current ? 'current' : undefined })
}

// ───────── Denominations ─────────
const selectedDenoms = computed(() => new Set(criteria.value.denomination ?? []))

function toggleDenom(v: number) {
  const set = new Set(selectedDenoms.value)
  if (set.has(v)) set.delete(v)
  else set.add(v)
  patch({ denomination: [...set].sort((a, b) => a - b) })
}

// ───────── Series ─────────
const { series: allSeries } = useCoinSeries()
const seriesGrouped = computed(() => {
  const groups: Record<string, typeof allSeries.value> = {}
  for (const s of allSeries.value) {
    const country = s.country.toUpperCase()
    if (!groups[country]) groups[country] = []
    groups[country].push(s)
  }
  return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b))
})

function setSeriesId(id: string) {
  patch({ series_id: id || undefined })
}

// ───────── is_withdrawn ─────────
function setWithdrawn(val: boolean | null) {
  patch({ is_withdrawn: val === null ? undefined : val })
}

// ───────── distinct_by ─────────
function setDistinctBy(val: boolean) {
  patch({ distinct_by: val ? 'country' : undefined })
}
</script>

<template>
  <div class="space-y-6">

    <!-- ══ Countries ══ -->
    <section>
      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-[10px] font-medium uppercase tracking-widest"
            style="color: var(--ink-500);">
          Pays
          <span v-if="selectedCountries.size > 0"
                class="ml-2 font-mono"
                style="color: var(--gold-deep);">
            {{ selectedCountries.size }} sélectionné{{ selectedCountries.size > 1 ? 's' : '' }}
          </span>
        </h3>
      </div>

      <div class="space-y-2">
        <div>
          <p class="mb-1.5 text-[10px] uppercase tracking-wider" style="color: var(--ink-400);">
            Eurozone (21)
          </p>
          <div class="grid grid-cols-7 gap-1">
            <button
              v-for="c in EUROZONE_COUNTRIES"
              :key="c.code"
              type="button"
              class="group relative flex flex-col items-center gap-0.5 rounded-md border px-1 py-1.5 transition-all"
              :style="selectedCountries.has(c.code)
                ? 'border-color: var(--gold); background: var(--gold-soft)'
                : 'border-color: var(--surface-3); background: var(--surface)'"
              :title="c.name"
              @click="toggleCountry(c.code)"
            >
              <span class="text-lg leading-none">{{ c.flag }}</span>
              <span class="font-mono text-[9px] font-bold" style="color: var(--ink);">
                {{ c.code }}
              </span>
            </button>
          </div>
        </div>

        <div>
          <p class="mb-1.5 text-[10px] uppercase tracking-wider" style="color: var(--ink-400);">
            Micro-états
          </p>
          <div class="grid grid-cols-7 gap-1">
            <button
              v-for="c in MICRO_STATES"
              :key="c.code"
              type="button"
              class="flex flex-col items-center gap-0.5 rounded-md border px-1 py-1.5 transition-all"
              :style="selectedCountries.has(c.code)
                ? 'border-color: var(--gold); background: var(--gold-soft)'
                : 'border-color: var(--surface-3); background: var(--surface)'"
              :title="c.name"
              @click="toggleCountry(c.code)"
            >
              <span class="text-lg leading-none">{{ c.flag }}</span>
              <span class="font-mono text-[9px] font-bold" style="color: var(--ink);">
                {{ c.code }}
              </span>
            </button>
            <button
              v-for="c in PSEUDO_COUNTRIES"
              :key="c.code"
              type="button"
              class="flex flex-col items-center gap-0.5 rounded-md border px-1 py-1.5 transition-all"
              :style="selectedCountries.has(c.code)
                ? 'border-color: var(--gold); background: var(--gold-soft)'
                : 'border-color: var(--surface-3); background: var(--surface)'"
              :title="c.name"
              @click="toggleCountry(c.code)"
            >
              <span class="text-lg leading-none">{{ c.flag }}</span>
              <span class="font-mono text-[9px] font-bold" style="color: var(--ink);">
                {{ c.code }}
              </span>
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- ══ Issue type ══ -->
    <section>
      <h3 class="mb-2 text-[10px] font-medium uppercase tracking-widest"
          style="color: var(--ink-500);">
        Type d'émission
      </h3>
      <div class="grid grid-cols-3 gap-2">
        <button
          v-for="t in ISSUE_TYPES"
          :key="t.value"
          type="button"
          class="rounded-md border px-3 py-2 text-xs font-medium transition-all"
          :style="selectedIssueType === t.value
            ? 'border-color: var(--indigo-700); background: var(--indigo-700); color: white'
            : 'border-color: var(--surface-3); background: var(--surface); color: var(--ink)'"
          @click="setIssueType(selectedIssueType === t.value ? null : t.value)"
        >
          {{ t.label }}
        </button>
      </div>
    </section>

    <!-- ══ Year ══ -->
    <section>
      <h3 class="mb-2 text-[10px] font-medium uppercase tracking-widest"
          style="color: var(--ink-500);">
        Année
      </h3>
      <div class="flex items-center gap-3">
        <input
          type="number"
          :value="yearNumber ?? ''"
          :disabled="yearIsCurrent"
          placeholder="2007"
          min="1999"
          max="2099"
          class="w-28 rounded-md border px-3 py-2 font-mono text-sm outline-none focus:ring-2 disabled:opacity-40"
          style="border-color: var(--surface-3); background: var(--surface); color: var(--ink); --tw-ring-color: var(--indigo-700);"
          @input="setYearNumber(($event.target as HTMLInputElement).value)"
        />
        <span class="text-xs" style="color: var(--ink-400);">ou</span>
        <label class="inline-flex cursor-pointer items-center gap-2 text-sm" style="color: var(--ink);">
          <input
            type="checkbox"
            :checked="yearIsCurrent"
            class="h-4 w-4 rounded accent-indigo-700"
            @change="setYearCurrent(($event.target as HTMLInputElement).checked)"
          />
          Année courante (<code class="font-mono">current</code>)
        </label>
      </div>
    </section>

    <!-- ══ Denominations ══ -->
    <section>
      <h3 class="mb-2 text-[10px] font-medium uppercase tracking-widest"
          style="color: var(--ink-500);">
        Valeur faciale
      </h3>
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="v in FACE_VALUES"
          :key="v"
          type="button"
          class="rounded-md border px-3 py-1.5 font-mono text-xs font-medium transition-all"
          :style="selectedDenoms.has(v)
            ? 'border-color: var(--gold); background: var(--gold-soft); color: var(--ink)'
            : 'border-color: var(--surface-3); background: var(--surface); color: var(--ink-500)'"
          @click="toggleDenom(v)"
        >
          {{ formatFaceValue(v) }}
        </button>
      </div>
    </section>

    <!-- ══ Series ══ -->
    <section>
      <h3 class="mb-2 text-[10px] font-medium uppercase tracking-widest"
          style="color: var(--ink-500);">
        Série spécifique
      </h3>
      <select
        :value="criteria.series_id ?? ''"
        class="w-full rounded-md border px-3 py-2 text-sm outline-none focus:ring-2"
        style="border-color: var(--surface-3); background: var(--surface); color: var(--ink); --tw-ring-color: var(--indigo-700);"
        @change="setSeriesId(($event.target as HTMLSelectElement).value)"
      >
        <option value="">— Toutes les séries —</option>
        <optgroup
          v-for="[country, list] in seriesGrouped"
          :key="country"
          :label="country"
        >
          <option v-for="s in list" :key="s.id" :value="s.id">
            {{ s.designation }}
            <template v-if="s.minting_ended_at">
              ({{ new Date(s.minting_started_at).getFullYear() }}–{{ new Date(s.minting_ended_at).getFullYear() }})
            </template>
            <template v-else>
              ({{ new Date(s.minting_started_at).getFullYear() }}–présent)
            </template>
          </option>
        </optgroup>
      </select>
      <p class="mt-1 text-[10px]" style="color: var(--ink-400);">
        Ne s'applique qu'aux pièces de circulation. Les commémos ont <code>series_id = NULL</code>.
      </p>
    </section>

    <!-- ══ Flags ══ -->
    <section class="space-y-2">
      <h3 class="text-[10px] font-medium uppercase tracking-widest"
          style="color: var(--ink-500);">
        Options avancées
      </h3>

      <!-- distinct_by -->
      <label class="flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-all"
             :style="criteria.distinct_by === 'country'
               ? 'border-color: var(--gold); background: var(--gold-soft)'
               : 'border-color: var(--surface-3); background: var(--surface)'">
        <input
          type="checkbox"
          :checked="criteria.distinct_by === 'country'"
          class="mt-0.5 h-4 w-4 rounded"
          @change="setDistinctBy(($event.target as HTMLInputElement).checked)"
        />
        <div class="flex-1">
          <p class="text-xs font-medium" style="color: var(--ink);">
            Un exemplaire par pays (<code>distinct_by=country</code>)
          </p>
          <p class="text-[10px]" style="color: var(--ink-500);">
            Ex. « Tour de la zone euro » — une seule pièce par pays compte.
          </p>
        </div>
      </label>

      <!-- is_withdrawn -->
      <div class="rounded-md border p-3"
           style="border-color: var(--surface-3); background: var(--surface);">
        <p class="mb-1.5 text-xs font-medium" style="color: var(--ink);">
          Statut de retrait (<code>is_withdrawn</code>)
        </p>
        <div class="flex gap-2">
          <button
            type="button"
            class="rounded-md border px-3 py-1 text-xs transition-all"
            :style="criteria.is_withdrawn === undefined
              ? 'border-color: var(--indigo-700); background: var(--indigo-700); color: white'
              : 'border-color: var(--surface-3); color: var(--ink-500)'"
            @click="setWithdrawn(null)"
          >
            Ignorer
          </button>
          <button
            type="button"
            class="rounded-md border px-3 py-1 text-xs transition-all"
            :style="criteria.is_withdrawn === true
              ? 'border-color: var(--danger); background: var(--danger); color: white'
              : 'border-color: var(--surface-3); color: var(--ink-500)'"
            @click="setWithdrawn(true)"
          >
            Retirées uniquement
          </button>
          <button
            type="button"
            class="rounded-md border px-3 py-1 text-xs transition-all"
            :style="criteria.is_withdrawn === false
              ? 'border-color: var(--success); background: var(--success); color: white'
              : 'border-color: var(--surface-3); color: var(--ink-500)'"
            @click="setWithdrawn(false)"
          >
            En circulation
          </button>
        </div>
      </div>
    </section>

    <!-- ══ JSON preview (debug) ══ -->
    <details class="rounded-md border p-2"
             style="border-color: var(--surface-3); background: var(--surface-1);">
      <summary class="cursor-pointer text-[10px] font-mono uppercase tracking-widest"
               style="color: var(--ink-500);">
        JSON criteria
      </summary>
      <pre class="mt-2 overflow-x-auto font-mono text-[10px]" style="color: var(--ink-700);">{{ JSON.stringify(criteria, null, 2) }}</pre>
    </details>
  </div>
</template>
