<script setup lang="ts">
// Variante inline du sélecteur libre — vit dans la colonne droite du
// SingleReviewView quand le mode est "free", remplaçant les Top N
// candidats + DinoSuggestions. Cascade pays → dénom → année + résultats
// en liste de rows (même style que DinoSuggestions standard) avec hover
// preview au-dessus.
//
// Le modal CoinSearchModal continue d'exister pour LotReviewDetailPage,
// où la place dans la colonne droite est déjà prise par les crop cards.

import { computed, ref, watch } from 'vue'
import { Search } from 'lucide-vue-next'
import {
  DENOMINATIONS, EURO_COUNTRIES, searchCoins, YEAR_RANGE,
  type CoinSearchEntry,
} from '../composables/useCoinsSearch'
import CoinHoverPreview from './CoinHoverPreview.vue'

const emit = defineEmits<{
  (e: 'select', entry: CoinSearchEntry): void
}>()

// ─── State cascade ──────────────────────────────────────────────────────

const country = ref<string | null>(null)
const denomination = ref<string | null>(null)
const year = ref<number | null>(null)
const results = ref<CoinSearchEntry[]>([])
const loading = ref(false)

const COMMON_YEARS = computed<(number | null)[]>(() => {
  const out: (number | null)[] = [null]
  for (let y = YEAR_RANGE.max; y >= YEAR_RANGE.min; y--) out.push(y)
  return out
})

const selectedCountryMeta = computed(
  () => EURO_COUNTRIES.find((c) => c.code === country.value) ?? null,
)

const showCascadeHint = computed(
  () => (!country.value || !denomination.value) && results.value.length === 0,
)

watch([country, denomination, year], async () => {
  if (!country.value || !denomination.value) {
    results.value = []
    return
  }
  loading.value = true
  try {
    results.value = await searchCoins({
      country: country.value,
      denomination: denomination.value,
      year: year.value,
      limit: 60,
    })
  } finally {
    loading.value = false
  }
})

// ─── Pickers ────────────────────────────────────────────────────────────

function pickCountry(code: string) {
  country.value = country.value === code ? null : code
}
function pickDenomination(value: string) {
  denomination.value = denomination.value === value ? null : value
}
function pickYear(y: number | null) {
  year.value = year.value === y ? null : y
}

// ─── Hover preview ──────────────────────────────────────────────────────

const hoveredKey = ref<string | null>(null)
const hoveredRect = ref<DOMRect | null>(null)
const hoveredEntry = ref<CoinSearchEntry | null>(null)

function onRowEnter(entry: CoinSearchEntry, e: MouseEvent) {
  const target = e.currentTarget as HTMLElement | null
  if (!target) return
  hoveredKey.value = entry.eurio_id
  hoveredRect.value = target.getBoundingClientRect()
  hoveredEntry.value = entry
}
function onRowLeave(eurioId: string) {
  if (hoveredKey.value === eurioId) {
    hoveredKey.value = null
    hoveredRect.value = null
    hoveredEntry.value = null
  }
}
</script>

<template>
  <section
    class="flex h-full flex-col rounded-lg border px-3 py-3"
    :style="{
      borderColor: 'var(--surface-3)',
      background: 'color-mix(in srgb, var(--gold-600) 3%, var(--surface))',
    }"
  >
    <div class="shrink-0">
    <header class="flex items-baseline justify-between gap-3">
      <p
        class="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--gold-600);"
      >
        <Search class="h-3 w-3" />
        Sélection libre
      </p>
      <p
        v-if="selectedCountryMeta"
        class="font-mono text-[10px]"
        style="color: var(--ink-500);"
      >
        {{ selectedCountryMeta.code }} · {{ selectedCountryMeta.label }}
      </p>
    </header>

    <!-- 1. Pays — grille code-only, 7 cols × 4 rangées -->
    <div class="mt-3">
      <p
        class="mb-1.5 font-mono text-[9px] uppercase tracking-wider"
        style="color: var(--ink-500);"
      >
        <span style="color: var(--gold-600);">1.</span> Pays
      </p>
      <div class="grid grid-cols-7 gap-1">
        <button
          v-for="c in EURO_COUNTRIES"
          :key="c.code"
          type="button"
          class="flex items-center justify-center rounded border py-1 font-mono text-[10px] font-semibold tracking-wider transition-all"
          :title="c.label"
          :style="{
            borderColor: country === c.code ? 'var(--gold-600)' : 'var(--surface-3)',
            background: country === c.code
              ? 'color-mix(in srgb, var(--gold-600) 10%, var(--surface))'
              : 'var(--surface)',
            color: country === c.code ? 'var(--gold-600)' : 'var(--ink-700)',
            boxShadow: country === c.code ? '0 0 0 1px var(--gold-600)' : 'none',
          }"
          @click="pickCountry(c.code)"
        >
          {{ c.code }}
        </button>
      </div>
    </div>

    <!-- 2. Dénomination — pills wrap -->
    <div v-if="country" class="mt-3">
      <p
        class="mb-1.5 font-mono text-[9px] uppercase tracking-wider"
        style="color: var(--ink-500);"
      >
        <span style="color: var(--gold-600);">2.</span> Dénomination
      </p>
      <div class="flex flex-wrap gap-1">
        <button
          v-for="d in DENOMINATIONS"
          :key="d.value"
          type="button"
          class="rounded-full border px-2 py-0.5 text-[10px] transition-all"
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

    <!-- 3. Année — scroll horizontal -->
    <div v-if="country && denomination" class="mt-3">
      <p
        class="mb-1.5 font-mono text-[9px] uppercase tracking-wider"
        style="color: var(--ink-500);"
      >
        <span style="color: var(--gold-600);">3.</span> Année
        <span class="ml-1 normal-case tracking-normal opacity-60">(optionnel)</span>
      </p>
      <div class="years-scroll flex gap-1 overflow-x-auto pb-1">
        <button
          v-for="y in COMMON_YEARS"
          :key="y ?? 'all'"
          type="button"
          class="shrink-0 rounded border px-2 py-0.5 font-mono text-[10px] tabular-nums transition-all"
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

    </div><!-- /shrink-0 cascade -->

    <!-- ─── Résultats (scroll interne) ─── -->
    <div class="mt-3 min-h-0 flex-1 overflow-y-auto">
      <p
        v-if="loading"
        class="font-mono text-[10px]"
        style="color: var(--ink-400);"
      >
        …chargement.
      </p>

      <p
        v-else-if="showCascadeHint"
        class="rounded-md border-2 border-dashed px-3 py-4 text-center text-[11px]"
        style="border-color: var(--surface-3); color: var(--ink-400);"
      >
        Sélectionne un pays puis une dénomination.
      </p>

      <p
        v-else-if="!results.length"
        class="rounded-md border-2 border-dashed px-3 py-4 text-center text-[11px]"
        style="border-color: var(--surface-3); color: var(--ink-400);"
      >
        Aucune pièce ne correspond.
      </p>

      <ul v-else class="flex flex-col gap-1.5">
        <li
          v-for="r in results"
          :key="r.eurio_id"
          class="flex items-stretch gap-2.5 rounded-md border px-2 py-1.5 transition-colors"
          :style="{
            borderColor: 'var(--surface-3)',
            background: 'var(--surface)',
          }"
          @mouseenter="onRowEnter(r, $event)"
          @mouseleave="onRowLeave(r.eurio_id)"
        >
          <img
            v-if="r.canonical_thumb_url"
            :src="r.canonical_thumb_url"
            :alt="r.eurio_id"
            class="h-9 w-9 shrink-0 rounded-md object-cover"
            style="background: var(--surface-1);"
          />
          <div
            v-else
            class="h-9 w-9 shrink-0 rounded-md"
            style="background: var(--surface-1);"
          />

          <div class="min-w-0 flex-1">
            <p
              class="font-mono text-[11px] font-medium break-all"
              style="color: var(--ink); word-break: break-word;"
            >
              {{ r.eurio_id }}
            </p>
            <p
              class="mt-0.5 text-[10px]"
              style="color: var(--ink-500);"
            >
              {{ r.year }}<span v-if="r.is_commemorative" class="opacity-70"> · commémo</span>
            </p>
          </div>

          <button
            type="button"
            class="shrink-0 rounded-md px-2 font-mono text-[10px] uppercase tracking-wider transition-colors"
            :style="{
              background: 'var(--gold-600)',
              color: 'var(--surface)',
            }"
            @click="emit('select', r)"
          >
            Sélec.
          </button>
        </li>
      </ul>
    </div>

    <CoinHoverPreview
      v-if="hoveredEntry && hoveredRect"
      :image-url="hoveredEntry.canonical_thumb_url"
      :eurio-id="hoveredEntry.eurio_id"
      :label="hoveredEntry.label"
      :anchor-rect="hoveredRect"
    />
  </section>
</template>

<style scoped>
.years-scroll::-webkit-scrollbar {
  height: 4px;
}
.years-scroll::-webkit-scrollbar-thumb {
  background: var(--surface-3);
  border-radius: 2px;
}
</style>
