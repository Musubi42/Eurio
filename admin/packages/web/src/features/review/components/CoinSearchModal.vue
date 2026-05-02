<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Search, X } from 'lucide-vue-next'
import {
  DENOMINATIONS,
  EURO_COUNTRIES,
  fuzzySearchCoins,
  searchCoins,
  YEAR_RANGE,
  type CoinSearchEntry,
} from '../composables/useCoinsSearch'

defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'select', entry: CoinSearchEntry): void
}>()

// ─── State ──────────────────────────────────────────────────────────────

const country = ref<string | null>(null)
const denomination = ref<string | null>(null)
const year = ref<number | null>(null)

const fuzzyMode = ref(false)
const fuzzyQuery = ref('')
const fuzzyInput = ref<HTMLInputElement | null>(null)

const results = ref<CoinSearchEntry[]>([])
const loading = ref(false)

const COMMON_YEARS = [
  null, // = toutes
  ...rangeYears(YEAR_RANGE.min, YEAR_RANGE.max),
]

function rangeYears(start: number, end: number): number[] {
  const out: number[] = []
  for (let y = end; y >= start; y--) out.push(y)
  return out
}

// ─── Loaders ────────────────────────────────────────────────────────────

watch([country, denomination, year], async () => {
  if (fuzzyMode.value) return
  if (!country.value || !denomination.value) {
    results.value = []
    return
  }
  loading.value = true
  results.value = await searchCoins({
    country: country.value,
    denomination: denomination.value,
    year: year.value,
    limit: 24,
  })
  loading.value = false
})

watch(fuzzyQuery, async (q) => {
  if (!fuzzyMode.value) return
  if (q.trim().length < 2) {
    results.value = []
    return
  }
  loading.value = true
  results.value = await fuzzySearchCoins(q)
  loading.value = false
})

// ─── Actions ────────────────────────────────────────────────────────────

function pickCountry(code: string) {
  fuzzyMode.value = false
  country.value = country.value === code ? null : code
}

function pickDenomination(value: string) {
  denomination.value = denomination.value === value ? null : value
}

function pickYear(y: number | null) {
  year.value = year.value === y ? null : y
}

function pickResult(entry: CoinSearchEntry) {
  emit('select', entry)
}

function reset() {
  country.value = null
  denomination.value = null
  year.value = null
  fuzzyMode.value = false
  fuzzyQuery.value = ''
  results.value = []
}

function enterFuzzyMode() {
  reset()
  fuzzyMode.value = true
  void nextTick(() => fuzzyInput.value?.focus())
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    emit('close')
    e.preventDefault()
    return
  }
  if (e.key === '/' && !fuzzyMode.value) {
    enterFuzzyMode()
    e.preventDefault()
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
})

// ─── Derived ────────────────────────────────────────────────────────────

const selectedCountryMeta = computed(() =>
  EURO_COUNTRIES.find((c) => c.code === country.value) ?? null,
)

const showResults = computed(() => results.value.length > 0)
const showCascadeHint = computed(
  () => !fuzzyMode.value && (!country.value || !denomination.value) && results.value.length === 0,
)
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-30 flex items-start justify-center px-6 pt-12"
    style="background: rgba(14,14,31,.65); backdrop-filter: blur(4px);"
    @click.self="emit('close')"
  >
    <article
      class="flex max-h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-lg border shadow-xl"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <!-- ═══ Header ═══ -->
      <header
        class="flex items-center justify-between gap-4 border-b px-5 py-3"
        style="border-color: var(--surface-2);"
      >
        <div>
          <h2
            class="font-display text-base italic font-semibold"
            style="color: var(--indigo-700);"
          >
            Sélecteur libre
          </h2>
          <p class="mt-0.5 text-[11px]" style="color: var(--ink-500);">
            Cascade pays → dénomination → année · ou
            <kbd
              class="mx-1 rounded px-1 py-0.5 font-mono text-[10px]"
              style="background: var(--surface-1); border: 1px solid var(--surface-3);"
            >/</kbd>
            pour combobox texte
          </p>
        </div>
        <button
          type="button"
          class="rounded-md p-1.5"
          style="color: var(--ink-500); background: var(--surface-1);"
          @click="emit('close')"
        >
          <X class="h-4 w-4" />
        </button>
      </header>

      <!-- ═══ Fuzzy combobox ═══ -->
      <div
        v-if="fuzzyMode"
        class="flex items-center gap-3 border-b px-5 py-3"
        style="border-color: var(--surface-2); background: var(--surface-1);"
      >
        <Search class="h-4 w-4" style="color: var(--ink-500);" />
        <input
          ref="fuzzyInput"
          v-model="fuzzyQuery"
          type="text"
          placeholder="ex : BE 2 2002 · fr 50c · DE comm 2020"
          class="flex-1 bg-transparent font-mono text-sm outline-none"
          style="color: var(--ink);"
        />
        <button
          type="button"
          class="font-mono text-[10px] uppercase tracking-wider"
          style="color: var(--ink-500);"
          @click="fuzzyMode = false"
        >
          Cascade visuelle →
        </button>
      </div>

      <!-- ═══ Cascade ═══ -->
      <div v-else class="flex flex-col gap-3 border-b px-5 py-4" style="border-color: var(--surface-2);">
        <!-- 1 — Pays (grille drapeaux) -->
        <div>
          <p class="mb-2 font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
            <span style="color: var(--indigo-700);">1.</span> Pays
            <span v-if="selectedCountryMeta" class="ml-1 normal-case tracking-normal" style="color: var(--ink-700);">
              · {{ selectedCountryMeta.flag }} {{ selectedCountryMeta.label }}
            </span>
          </p>
          <div class="grid grid-cols-7 gap-2">
            <button
              v-for="c in EURO_COUNTRIES"
              :key="c.code"
              type="button"
              class="flex flex-col items-center gap-1 rounded-md border px-2 py-2 transition-all"
              :style="{
                borderColor: country === c.code ? 'var(--indigo-700)' : 'var(--surface-3)',
                background: country === c.code
                  ? 'color-mix(in srgb, var(--indigo-700) 8%, var(--surface))'
                  : 'var(--surface)',
                boxShadow: country === c.code ? '0 0 0 2px color-mix(in srgb, var(--indigo-700) 18%, transparent)' : 'none',
              }"
              @click="pickCountry(c.code)"
            >
              <span class="text-lg leading-none">{{ c.flag }}</span>
              <span
                class="font-mono text-[10px] font-semibold tracking-wider"
                :style="{ color: country === c.code ? 'var(--indigo-700)' : 'var(--ink-700)' }"
              >
                {{ c.code }}
              </span>
            </button>
          </div>
        </div>

        <!-- 2 — Dénominations -->
        <div v-if="country">
          <p class="mb-2 font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
            <span style="color: var(--indigo-700);">2.</span> Dénomination
          </p>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="d in DENOMINATIONS"
              :key="d.value"
              type="button"
              class="rounded-full border px-3 py-1 text-[11px] transition-all"
              :style="{
                borderColor: denomination === d.value ? 'var(--indigo-700)' : 'var(--surface-3)',
                color: denomination === d.value ? 'var(--surface)' : 'var(--ink-700)',
                background: denomination === d.value ? 'var(--indigo-700)' : 'var(--surface)',
              }"
              @click="pickDenomination(d.value)"
            >
              {{ d.label }}
            </button>
          </div>
        </div>

        <!-- 3 — Années -->
        <div v-if="country && denomination">
          <p class="mb-2 font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
            <span style="color: var(--indigo-700);">3.</span> Année
            <span class="ml-1 normal-case tracking-normal opacity-60">(optionnel)</span>
          </p>
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="y in COMMON_YEARS"
              :key="y ?? 'all'"
              type="button"
              class="rounded-md border px-2 py-0.5 font-mono text-[11px] tabular-nums transition-all"
              :style="{
                borderColor: year === y ? 'var(--gold-600)' : 'var(--surface-3)',
                color: year === y ? 'var(--gold-600)' : 'var(--ink-700)',
                background: year === y
                  ? 'color-mix(in srgb, var(--gold-600) 8%, var(--surface))'
                  : 'var(--surface)',
              }"
              @click="pickYear(y)"
            >
              {{ y === null ? 'toutes' : y }}
            </button>
          </div>
        </div>
      </div>

      <!-- ═══ Résultats ═══ -->
      <div class="flex-1 overflow-y-auto px-5 py-4">
        <div
          v-if="loading"
          class="py-12 text-center text-sm"
          style="color: var(--ink-400);"
        >
          Chargement…
        </div>
        <div
          v-else-if="showResults"
          class="grid grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8"
        >
          <button
            v-for="r in results"
            :key="r.eurio_id"
            type="button"
            class="group flex flex-col items-stretch gap-1.5 overflow-hidden rounded-md border text-left transition-all hover:scale-[1.02]"
            style="border-color: var(--surface-3); background: var(--surface);"
            @click="pickResult(r)"
          >
            <div
              class="aspect-square overflow-hidden"
              style="background: var(--surface-1);"
            >
              <img
                :src="r.canonical_thumb_url"
                :alt="r.eurio_id"
                class="h-full w-full object-cover transition-transform group-hover:scale-105"
              />
            </div>
            <div class="px-2 pb-2">
              <p class="truncate font-mono text-[10px]" style="color: var(--ink-700);">
                {{ r.eurio_id }}
              </p>
              <p class="truncate text-[10px]" style="color: var(--ink-500);">
                {{ r.year }}
              </p>
            </div>
          </button>
        </div>
        <div
          v-else-if="showCascadeHint"
          class="rounded-lg border-2 border-dashed px-6 py-12 text-center"
          style="border-color: var(--surface-3);"
        >
          <p class="font-display text-sm italic" style="color: var(--ink-500);">
            Sélectionne d'abord un pays puis une dénomination
          </p>
          <p class="mt-2 text-[11px]" style="color: var(--ink-400);">
            ou tape <kbd
              class="mx-1 rounded px-1 py-0.5 font-mono text-[10px]"
              style="background: var(--surface-1); border: 1px solid var(--surface-3);"
            >/</kbd> pour rechercher en une ligne
          </p>
        </div>
        <div
          v-else
          class="rounded-lg border-2 border-dashed px-6 py-12 text-center"
          style="border-color: var(--surface-3);"
        >
          <p class="font-display text-sm italic" style="color: var(--ink-400);">
            Aucune pièce ne correspond.
          </p>
        </div>
      </div>

      <!-- ═══ Footer hints ═══ -->
      <footer
        class="flex items-center justify-between gap-2 border-t px-5 py-2 font-mono text-[10px] uppercase tracking-wider"
        style="border-color: var(--surface-2); color: var(--ink-400); background: var(--surface-1);"
      >
        <span>
          <kbd class="mr-1">↹</kbd> click thumb · sélection
        </span>
        <span>
          <kbd class="mr-1">Esc</kbd> fermer
        </span>
      </footer>
    </article>
  </div>
</template>

<style scoped>
kbd {
  display: inline-block;
  padding: 1px 5px;
  border: 1px solid var(--surface-3);
  border-radius: 3px;
  background: var(--surface);
  color: var(--ink-700);
  font-family: ui-monospace, SFMono-Regular, monospace;
}
</style>
