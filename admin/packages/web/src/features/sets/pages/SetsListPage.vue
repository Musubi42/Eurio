<script setup lang="ts">
import { supabase } from '@/shared/supabase/client'
import type { Set, SetCategory, SetKind } from '@/shared/supabase/types'
import { Plus, RefreshCw, Search, X } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import SetEditDrawer from '../components/SetEditDrawer.vue'

const sets = ref<Set[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

// Drawer state
const drawerOpen = ref(false)
const drawerSetId = ref<string | null>(null)

// ───────── Filters ─────────
const search = ref('')
const filterCategory = ref<SetCategory | 'all'>('all')
const filterKind = ref<SetKind | 'all'>('all')
const filterActive = ref<'all' | 'active' | 'inactive'>('all')
const filterCountry = ref<string>('all')

const kindLabel: Record<SetKind, string> = {
  structural: 'Structurel',
  curated: 'Curé',
  parametric: 'Paramétré',
}

const categoryLabel: Record<SetCategory, string> = {
  country: 'Pays',
  theme: 'Thème',
  tier: 'Tier',
  personal: 'Personnel',
  hunt: 'Chasse',
}

// Countries dérivés des critères existants
const availableCountries = computed(() => {
  const set = new Set<string>()
  for (const s of sets.value) {
    const c = s.criteria?.country
    if (Array.isArray(c)) c.forEach(x => set.add(x.toUpperCase()))
    else if (c) set.add(c.toUpperCase())
  }
  return [...set].sort()
})

// ───────── Filtered list ─────────
const filteredSets = computed(() => {
  const q = search.value.trim().toLowerCase()

  return sets.value.filter(s => {
    // Search
    if (q) {
      const matchesId = s.id.toLowerCase().includes(q)
      const matchesName = s.name_i18n.fr?.toLowerCase().includes(q) ?? false
      if (!matchesId && !matchesName) return false
    }

    // Category
    if (filterCategory.value !== 'all' && s.category !== filterCategory.value) return false

    // Kind
    if (filterKind.value !== 'all' && s.kind !== filterKind.value) return false

    // Active
    if (filterActive.value === 'active' && !s.active) return false
    if (filterActive.value === 'inactive' && s.active) return false

    // Country
    if (filterCountry.value !== 'all') {
      const c = s.criteria?.country
      const countries = Array.isArray(c) ? c.map(x => x.toUpperCase()) : c ? [c.toUpperCase()] : []
      if (!countries.includes(filterCountry.value)) return false
    }

    return true
  })
})

const activeFilterCount = computed(() => {
  let count = 0
  if (search.value) count++
  if (filterCategory.value !== 'all') count++
  if (filterKind.value !== 'all') count++
  if (filterActive.value !== 'all') count++
  if (filterCountry.value !== 'all') count++
  return count
})

function resetFilters() {
  search.value = ''
  filterCategory.value = 'all'
  filterKind.value = 'all'
  filterActive.value = 'all'
  filterCountry.value = 'all'
}

// ───────── Data ─────────
async function fetchSets() {
  loading.value = true
  error.value = null

  const { data, error: err } = await supabase
    .from('sets')
    .select('*')
    .order('category')
    .order('display_order', { ascending: true })

  loading.value = false

  if (err) {
    error.value = err.message
    return
  }

  sets.value = (data ?? []) as Set[]
}

onMounted(fetchSets)

function openCreate() {
  drawerSetId.value = null
  drawerOpen.value = true
}

function openEdit(setId: string) {
  drawerSetId.value = setId
  drawerOpen.value = true
}

function handleSaved() {
  fetchSets()
}

function criteriaSummary(set: Set): string {
  if (!set.criteria) return set.kind === 'curated' ? '—' : '(vide)'
  const parts: string[] = []
  const c = set.criteria
  if (c.country) parts.push(Array.isArray(c.country) ? c.country.join(',') : c.country)
  if (c.issue_type) parts.push(Array.isArray(c.issue_type) ? c.issue_type.join('|') : c.issue_type)
  if (c.year !== undefined) parts.push(`year=${c.year}`)
  if (c.series_id) parts.push(c.series_id)
  if (c.denomination?.length) parts.push(`${c.denomination.join(',')}€`)
  if (c.distinct_by) parts.push(`distinct=${c.distinct_by}`)
  return parts.join(' · ') || '(vide)'
}
</script>

<template>
  <div class="p-8">
    <!-- Header -->
    <div class="mb-6 flex items-start justify-between">
      <div>
        <h1 class="font-display text-2xl italic font-semibold"
            style="color: var(--indigo-700);">
          Sets d'achievement
        </h1>
        <p class="mt-0.5 text-sm" style="color: var(--ink-500);">
          <span v-if="activeFilterCount > 0">
            <strong>{{ filteredSets.length }}</strong> sur {{ sets.length }} sets
            · <span style="color: var(--gold-deep);">{{ activeFilterCount }} filtre{{ activeFilterCount > 1 ? 's' : '' }}</span>
          </span>
          <span v-else>
            {{ sets.length }} set{{ sets.length !== 1 ? 's' : '' }} au total
          </span>
        </p>
      </div>
      <div class="flex items-center gap-2">
        <button
          @click="fetchSets"
          :disabled="loading"
          class="flex items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors hover:bg-surface-1 disabled:opacity-50"
          style="border-color: var(--surface-3); color: var(--ink-500);"
        >
          <RefreshCw class="h-4 w-4" :class="loading && 'animate-spin'" />
        </button>
        <button
          class="flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-opacity hover:opacity-90"
          style="background: var(--indigo-700); color: white;"
          @click="openCreate"
        >
          <Plus class="h-4 w-4" />
          Nouveau set
        </button>
      </div>
    </div>

    <!-- ═══ Filter bar ═══ -->
    <div class="mb-4 rounded-lg border p-3"
         style="border-color: var(--surface-3); background: var(--surface-1);">
      <div class="flex flex-wrap items-center gap-3">
        <!-- Search -->
        <div class="relative min-w-[240px] flex-1">
          <Search class="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2"
                  style="color: var(--ink-400);" />
          <input
            v-model="search"
            type="search"
            placeholder="id, nom…"
            class="w-full rounded-md border py-1.5 pl-8 pr-3 text-xs outline-none focus:ring-2"
            style="border-color: var(--surface-3); background: var(--surface); color: var(--ink); --tw-ring-color: var(--indigo-700);"
          />
        </div>

        <!-- Separator -->
        <div class="h-6 w-px" style="background: var(--surface-3);" />

        <!-- Kind chips -->
        <div class="flex items-center gap-1">
          <span class="text-[10px] font-medium uppercase tracking-wider" style="color: var(--ink-500);">
            Nature
          </span>
          <button
            class="rounded-md border px-2 py-1 text-[10px] font-medium transition-all"
            :style="filterKind === 'all'
              ? 'border-color: var(--indigo-700); background: var(--indigo-700); color: white'
              : 'border-color: var(--surface-3); color: var(--ink-500)'"
            @click="filterKind = 'all'"
          >
            Tout
          </button>
          <button
            v-for="k in (['structural','curated','parametric'] as const)"
            :key="k"
            class="rounded-md border px-2 py-1 text-[10px] font-medium transition-all"
            :style="filterKind === k
              ? 'border-color: var(--indigo-700); background: var(--indigo-700); color: white'
              : 'border-color: var(--surface-3); color: var(--ink-500)'"
            @click="filterKind = k"
          >
            {{ kindLabel[k] }}
          </button>
        </div>

        <!-- Separator -->
        <div class="h-6 w-px" style="background: var(--surface-3);" />

        <!-- Category select -->
        <div class="flex items-center gap-1.5">
          <span class="text-[10px] font-medium uppercase tracking-wider" style="color: var(--ink-500);">
            Catégorie
          </span>
          <select
            v-model="filterCategory"
            class="rounded-md border px-2 py-1 text-xs outline-none"
            style="border-color: var(--surface-3); background: var(--surface); color: var(--ink);"
          >
            <option value="all">— Toutes —</option>
            <option v-for="(label, val) in categoryLabel" :key="val" :value="val">
              {{ label }}
            </option>
          </select>
        </div>

        <!-- Country select -->
        <div v-if="availableCountries.length > 0" class="flex items-center gap-1.5">
          <span class="text-[10px] font-medium uppercase tracking-wider" style="color: var(--ink-500);">
            Pays
          </span>
          <select
            v-model="filterCountry"
            class="rounded-md border px-2 py-1 font-mono text-xs outline-none"
            style="border-color: var(--surface-3); background: var(--surface); color: var(--ink);"
          >
            <option value="all">— Tous —</option>
            <option v-for="c in availableCountries" :key="c" :value="c">{{ c }}</option>
          </select>
        </div>

        <!-- Active tri-state -->
        <div class="flex items-center gap-1">
          <span class="text-[10px] font-medium uppercase tracking-wider" style="color: var(--ink-500);">
            Statut
          </span>
          <button
            class="rounded-md border px-2 py-1 text-[10px] font-medium transition-all"
            :style="filterActive === 'all'
              ? 'border-color: var(--indigo-700); background: var(--indigo-700); color: white'
              : 'border-color: var(--surface-3); color: var(--ink-500)'"
            @click="filterActive = 'all'"
          >
            Tout
          </button>
          <button
            class="rounded-md border px-2 py-1 text-[10px] font-medium transition-all"
            :style="filterActive === 'active'
              ? 'border-color: var(--success); background: var(--success); color: white'
              : 'border-color: var(--surface-3); color: var(--ink-500)'"
            @click="filterActive = 'active'"
          >
            Actifs
          </button>
          <button
            class="rounded-md border px-2 py-1 text-[10px] font-medium transition-all"
            :style="filterActive === 'inactive'
              ? 'border-color: var(--ink-400); background: var(--ink-400); color: white'
              : 'border-color: var(--surface-3); color: var(--ink-500)'"
            @click="filterActive = 'inactive'"
          >
            Inactifs
          </button>
        </div>

        <!-- Reset -->
        <button
          v-if="activeFilterCount > 0"
          class="ml-auto flex items-center gap-1 rounded-md px-2 py-1 text-[10px] transition-colors hover:bg-surface-2"
          style="color: var(--ink-500);"
          @click="resetFilters"
        >
          <X class="h-3 w-3" />
          Réinitialiser
        </button>
      </div>
    </div>

    <!-- Error -->
    <div v-if="error"
         class="mb-4 rounded-md px-4 py-3 text-sm"
         style="background: var(--danger-soft); color: var(--danger);">
      {{ error }}
    </div>

    <!-- Loading -->
    <div v-if="loading" class="space-y-2">
      <div v-for="i in 5" :key="i"
           class="h-14 animate-pulse rounded-md"
           style="background: var(--surface-1);" />
    </div>

    <!-- Empty (no sets at all) -->
    <div v-else-if="sets.length === 0"
         class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed py-16"
         style="border-color: var(--surface-3);">
      <p class="font-display italic text-lg" style="color: var(--ink-400);">
        Aucun set pour l'instant
      </p>
      <p class="mt-1 text-sm" style="color: var(--ink-400);">
        Créez le premier set pour commencer.
      </p>
    </div>

    <!-- No match (filters too narrow) -->
    <div v-else-if="filteredSets.length === 0"
         class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed py-12"
         style="border-color: var(--surface-3);">
      <p class="font-display italic text-base" style="color: var(--ink-400);">
        Aucun résultat pour ces filtres
      </p>
      <button
        class="mt-3 flex items-center gap-1 rounded-md px-3 py-1.5 text-xs transition-colors hover:bg-surface-2"
        style="color: var(--indigo-700);"
        @click="resetFilters"
      >
        <X class="h-3 w-3" />
        Réinitialiser les filtres
      </button>
    </div>

    <!-- Table -->
    <div v-else class="overflow-hidden rounded-lg border" style="border-color: var(--surface-3);">
      <table class="w-full text-sm">
        <thead>
          <tr style="background: var(--surface-1); border-bottom: 1px solid var(--surface-3);">
            <th class="px-4 py-3 text-left font-medium text-xs uppercase tracking-wider"
                style="color: var(--ink-500);">Identifiant</th>
            <th class="px-4 py-3 text-left font-medium text-xs uppercase tracking-wider"
                style="color: var(--ink-500);">Nom</th>
            <th class="px-4 py-3 text-left font-medium text-xs uppercase tracking-wider"
                style="color: var(--ink-500);">Nature</th>
            <th class="px-4 py-3 text-left font-medium text-xs uppercase tracking-wider"
                style="color: var(--ink-500);">Catégorie</th>
            <th class="px-4 py-3 text-left font-medium text-xs uppercase tracking-wider"
                style="color: var(--ink-500);">Critères</th>
            <th class="px-4 py-3 text-right font-medium text-xs uppercase tracking-wider"
                style="color: var(--ink-500);">Ordre</th>
            <th class="px-4 py-3 text-center font-medium text-xs uppercase tracking-wider"
                style="color: var(--ink-500);">Statut</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(set, i) in filteredSets"
            :key="set.id"
            class="cursor-pointer transition-colors hover:bg-surface-1"
            :style="i < filteredSets.length - 1 ? 'border-bottom: 1px solid var(--surface-2)' : ''"
            @click="openEdit(set.id)"
          >
            <td class="px-4 py-3 font-mono text-xs" style="color: var(--ink-500);">
              {{ set.id }}
            </td>
            <td class="px-4 py-3 font-medium" style="color: var(--ink);">
              {{ set.name_i18n.fr }}
            </td>
            <td class="px-4 py-3">
              <span class="rounded-full px-2 py-0.5 text-xs font-medium"
                    style="background: var(--surface-2); color: var(--ink-500);">
                {{ kindLabel[set.kind] }}
              </span>
            </td>
            <td class="px-4 py-3 text-xs" style="color: var(--ink-500);">
              {{ categoryLabel[set.category] }}
            </td>
            <td class="px-4 py-3 font-mono text-[11px]" style="color: var(--ink-400);">
              {{ criteriaSummary(set) }}
            </td>
            <td class="px-4 py-3 text-right font-mono text-xs" style="color: var(--ink-400);">
              {{ set.display_order }}
            </td>
            <td class="px-4 py-3 text-center">
              <span
                class="inline-block h-2 w-2 rounded-full"
                :style="set.active
                  ? 'background: var(--success)'
                  : 'background: var(--ink-200)'"
                :title="set.active ? 'Actif' : 'Inactif'"
              />
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Edit drawer -->
    <SetEditDrawer
      :open="drawerOpen"
      :set-id="drawerSetId"
      @close="drawerOpen = false"
      @saved="handleSaved"
    />
  </div>
</template>
