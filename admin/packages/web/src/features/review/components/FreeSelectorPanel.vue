<script setup lang="ts">
// Sélecteur libre canonique — utilisé inline dans SingleReviewView
// (colonne droite quand mode='free') et dans les pages lot
// (LotReviewDetailPage / LotDetailDrawer) en remplacement de la liste
// Isolates quand un assign est en cours. Cascade pays → dénom → année
// par défaut, ou mode texte fuzzy via raccourci `/`.

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Search } from 'lucide-vue-next'
import {
  DENOMINATIONS, EURO_COUNTRIES, fuzzySearchCoins, searchCoins, searchCoinsByText, YEAR_RANGE,
  type CoinSearchEntry,
} from '../composables/useCoinsSearch'
import CoinHoverPreview from './CoinHoverPreview.vue'

const props = withDefaults(defineProps<{
  /** Active la nav clavier (codes ISO + grilles fléchées). Le callsite single
   *  ne l'active qu'en mode='free' ; les pages lot restent souris (défaut). */
  enableKbdNav?: boolean
}>(), { enableKbdNav: false })

const emit = defineEmits<{
  (e: 'select', entry: CoinSearchEntry): void
}>()

// ─── State cascade ──────────────────────────────────────────────────────

const country = ref<string | null>(null)
const denomination = ref<string | null>(null)
const year = ref<number | null>(null)
const results = ref<CoinSearchEntry[]>([])
const loading = ref(false)

// ─── State fuzzy ────────────────────────────────────────────────────────

const fuzzyMode = ref(false)
const fuzzyQuery = ref('')
const fuzzyInput = ref<HTMLInputElement | null>(null)

const COMMON_YEARS = computed<(number | null)[]>(() => {
  const out: (number | null)[] = [null]
  for (let y = YEAR_RANGE.max; y >= YEAR_RANGE.min; y--) out.push(y)
  return out
})

const selectedCountryMeta = computed(
  () => EURO_COUNTRIES.find((c) => c.code === country.value) ?? null,
)

const showCascadeHint = computed(
  () => !fuzzyMode.value && (!country.value || !denomination.value) && results.value.length === 0,
)
const showFuzzyHint = computed(
  () => fuzzyMode.value && fuzzyQuery.value.trim().length < 2 && results.value.length === 0,
)

watch([country, denomination, year], async () => {
  if (fuzzyMode.value) return
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

watch(fuzzyQuery, async (q) => {
  if (!fuzzyMode.value) return
  if (q.trim().length < 2) {
    results.value = []
    return
  }
  loading.value = true
  try {
    results.value = await fuzzySearchCoins(q)
  } finally {
    loading.value = false
  }
})

// ─── Pickers ────────────────────────────────────────────────────────────

function pickCountry(code: string) {
  if (fuzzyMode.value) exitFuzzyMode()
  country.value = country.value === code ? null : code
}
function pickDenomination(value: string) {
  denomination.value = denomination.value === value ? null : value
}
function pickYear(y: number | null) {
  year.value = year.value === y ? null : y
}

// ─── Fuzzy toggle ───────────────────────────────────────────────────────

function enterFuzzyMode() {
  fuzzyMode.value = true
  country.value = null
  denomination.value = null
  year.value = null
  results.value = []
  fuzzyQuery.value = ''
  void nextTick(() => fuzzyInput.value?.focus())
}

function exitFuzzyMode() {
  fuzzyMode.value = false
  fuzzyQuery.value = ''
  results.value = []
}

// ─── Keyboard : nav cascade (codes ISO + grilles fléchées) ───────────────
// `/` active le mode fuzzy (toujours). La nav cascade n'est active que si
// `enableKbdNav` (callsite single en mode free). Capture phase + stopProp
// pour passer DEVANT les raccourcis globaux de /review (sinon taper « FI »
// déclencherait F=toggle, I=…). Cf. CircleCropEditor (même précédent capture).

type Zone = 'country' | 'denom' | 'year' | 'results'
const activeZone = ref<Zone>('country')
const isoBuffer = ref('')
const DEFAULT_DENOM_IDX = Math.max(0, DENOMINATIONS.findIndex((d) => d.value === '2eur-comm'))
const denomIdx = ref(DEFAULT_DENOM_IDX)
const yearIdx = ref(0)
const resultIdx = ref(0)
const resultsEl = ref<HTMLElement | null>(null)

// Reset du curseur résultats quand la liste change (nouvelle recherche).
watch(results, () => {
  resultIdx.value = 0
  if (props.enableKbdNav && activeZone.value === 'results') {
    void nextTick(showResultPreview)
  }
})

function availableZones(): Zone[] {
  const z: Zone[] = ['country']
  if (country.value) z.push('denom')
  if (country.value && denomination.value) z.push('year')
  if (results.value.length) z.push('results')
  return z
}

function cycleZone(dir: 1 | -1) {
  const zs = availableZones()
  const i = zs.indexOf(activeZone.value)
  activeZone.value = zs[((i < 0 ? 0 : i) + dir + zs.length) % zs.length]
}

function selectCountryKbd(code: string) {
  if (fuzzyMode.value) exitFuzzyMode()
  country.value = code
  // Pré-règle la dénomination sur la cible cohorte (2€ commémo) → résultats
  // immédiats. L'utilisateur ajuste ensuite avec ← / →.
  denomIdx.value = DEFAULT_DENOM_IDX
  denomination.value = DENOMINATIONS[DEFAULT_DENOM_IDX].value
  yearIdx.value = 0
  year.value = null
  activeZone.value = 'denom'
}

function pushIso(ch: string) {
  const next = (isoBuffer.value + ch).toUpperCase()
  if (EURO_COUNTRIES.some((c) => c.code === next)) { selectCountryKbd(next); isoBuffer.value = ''; return }
  if (EURO_COUNTRIES.some((c) => c.code.startsWith(next))) { isoBuffer.value = next; return }
  const solo = ch.toUpperCase()
  isoBuffer.value = EURO_COUNTRIES.some((c) => c.code.startsWith(solo)) ? solo : ''
}

function moveDenom(dir: 1 | -1) {
  denomIdx.value = Math.min(DENOMINATIONS.length - 1, Math.max(0, denomIdx.value + dir))
  denomination.value = DENOMINATIONS[denomIdx.value].value
}
function moveYear(dir: 1 | -1) {
  yearIdx.value = Math.min(COMMON_YEARS.value.length - 1, Math.max(0, yearIdx.value + dir))
  year.value = COMMON_YEARS.value[yearIdx.value]
}
function moveResult(dir: 1 | -1) {
  if (!results.value.length) return
  resultIdx.value = Math.min(results.value.length - 1, Math.max(0, resultIdx.value + dir))
  void nextTick(() => {
    (resultsEl.value?.children[resultIdx.value] as HTMLElement | undefined)
      ?.scrollIntoView({ block: 'nearest' })
    showResultPreview()
  })
}

// Réaffiche la même pop-up que le survol souris pour l'élément focusé au
// clavier — clé du geste : comparer visuellement la pièce au « crop à résoudre ».
function showResultPreview() {
  const entry = results.value[resultIdx.value]
  const el = resultsEl.value?.children[resultIdx.value] as HTMLElement | undefined
  if (!entry || !el) return
  hoveredKey.value = entry.eurio_id
  hoveredRect.value = el.getBoundingClientRect()
  hoveredEntry.value = entry
}
function clearPreview() {
  hoveredKey.value = null
  hoveredRect.value = null
  hoveredEntry.value = null
}

// Entrer/sortir de la zone Résultats au clavier (Tab) → ouvre/ferme la pop-up.
watch(activeZone, (z) => {
  if (!props.enableKbdNav) return
  if (z === 'results') void nextTick(showResultPreview)
  else clearPreview()
})

function onKeyCapture(e: KeyboardEvent) {
  if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
  if (e.metaKey || e.ctrlKey || e.altKey) return
  if (e.key === '/' && !fuzzyMode.value) { enterFuzzyMode(); e.preventDefault(); return }
  if (!props.enableKbdNav || fuzzyMode.value) return

  const consume = () => { e.preventDefault(); e.stopPropagation() }
  const k = e.key

  if (k === 'Tab') { cycleZone(e.shiftKey ? -1 : 1); consume(); return }
  if (k === 'Backspace') {
    if (activeZone.value === 'country' && isoBuffer.value) { isoBuffer.value = isoBuffer.value.slice(0, -1); consume() }
    return
  }
  if (/^[a-zA-Z]$/.test(k)) { activeZone.value = 'country'; pushIso(k); consume(); return }
  if (k === 'ArrowLeft' || k === 'ArrowRight') {
    const dir = k === 'ArrowRight' ? 1 : -1
    if (activeZone.value === 'denom') { moveDenom(dir); consume() }
    else if (activeZone.value === 'year') { moveYear(dir); consume() }
    return
  }
  if (k === 'ArrowDown' || k === 'ArrowUp') {
    if (activeZone.value === 'results') { moveResult(k === 'ArrowDown' ? 1 : -1); consume() }
    return
  }
  if (k === 'Enter') {
    if (activeZone.value === 'results' && results.value[resultIdx.value]) {
      emit('select', results.value[resultIdx.value]); consume()
    } else { cycleZone(1); consume() }
  }
}

onMounted(() => window.addEventListener('keydown', onKeyCapture, true))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeyCapture, true))

// ─── Direct autocomplete (rescue cross-classe) ──────────────────────────
// Champ libre: saisie eurio_id ou mot-clé, dropdown inline, fermeture blur.

const directQuery = ref('')
const directResults = ref<CoinSearchEntry[]>([])
const directLoading = ref(false)
const showDirectDrop = ref(false)

let directDebounceTimer: ReturnType<typeof setTimeout> | null = null

watch(directQuery, (q) => {
  if (directDebounceTimer !== null) {
    clearTimeout(directDebounceTimer)
    directDebounceTimer = null
  }
  if (q.trim().length < 2) {
    directResults.value = []
    showDirectDrop.value = false
    return
  }
  directDebounceTimer = setTimeout(async () => {
    directLoading.value = true
    try {
      directResults.value = await searchCoinsByText(q, { limit: 20 })
      showDirectDrop.value = true
    } catch {
      directResults.value = []
      showDirectDrop.value = false
    } finally {
      directLoading.value = false
    }
  }, 300)
})

function onDirectSelect(entry: CoinSearchEntry) {
  emit('select', entry)
  directQuery.value = ''
  directResults.value = []
  showDirectDrop.value = false
}

function onDirectBlur() {
  // Délai pour laisser le clic sur un item se propager avant la fermeture.
  setTimeout(() => {
    showDirectDrop.value = false
  }, 150)
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
    <!-- ─── Recherche directe eurio_id / mot-clé (rescue cross-classe) ─── -->
    <div class="relative mb-3 shrink-0">
      <div
        class="flex items-center gap-2 rounded-md border px-2 py-1.5"
        :style="{ borderColor: 'var(--surface-3)', background: 'var(--surface-1)' }"
      >
        <Search class="h-3 w-3 shrink-0" style="color: var(--ink-500);" />
        <input
          v-model="directQuery"
          type="text"
          placeholder="eurio_id ou mot-clé…"
          class="flex-1 bg-transparent font-mono text-[11px] outline-none"
          style="color: var(--ink);"
          @blur="onDirectBlur"
        />
        <span
          v-if="directLoading"
          class="font-mono text-[9px]"
          style="color: var(--ink-400);"
        >…</span>
      </div>

      <!-- Dropdown résultats -->
      <div
        v-if="showDirectDrop && directResults.length"
        class="absolute left-0 right-0 z-20 mt-0.5 max-h-48 overflow-y-auto rounded-md border shadow-lg"
        :style="{ background: 'var(--surface)', borderColor: 'var(--surface-3)' }"
      >
        <button
          v-for="r in directResults"
          :key="r.eurio_id"
          type="button"
          class="flex w-full items-center gap-2 px-2 py-1.5 text-left transition-colors"
          :style="{ background: 'transparent' }"
          @mousedown.prevent
          @click="onDirectSelect(r)"
          @mouseover="($event.currentTarget as HTMLElement).style.background = 'var(--surface-1)'"
          @mouseleave="($event.currentTarget as HTMLElement).style.background = 'transparent'"
        >
          <img
            v-if="r.canonical_thumb_url"
            :src="r.canonical_thumb_url"
            :alt="r.eurio_id"
            class="h-7 w-7 shrink-0 rounded object-cover"
            style="background: var(--surface-2);"
          />
          <div
            v-else
            class="h-7 w-7 shrink-0 rounded"
            style="background: var(--surface-2);"
          />
          <div class="min-w-0 flex-1">
            <p
              class="truncate font-mono text-[11px] font-semibold"
              style="color: var(--ink);"
            >
              {{ r.eurio_id }}
            </p>
            <p
              class="truncate text-[10px]"
              style="color: var(--ink-500);"
            >
              {{ r.denomination }} · {{ r.year }}
            </p>
          </div>
        </button>
      </div>
    </div>

    <div class="shrink-0">
    <header class="flex items-baseline justify-between gap-3">
      <p
        class="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--gold-600);"
      >
        <Search class="h-3 w-3" />
        Sélection libre
      </p>
      <button
        v-if="fuzzyMode"
        type="button"
        class="font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--ink-500);"
        @click="exitFuzzyMode"
      >
        ← cascade
      </button>
      <p
        v-else-if="selectedCountryMeta"
        class="font-mono text-[10px]"
        style="color: var(--ink-500);"
      >
        {{ selectedCountryMeta.code }} · {{ selectedCountryMeta.label }}
      </p>
      <button
        v-else
        type="button"
        class="inline-flex items-center gap-1 font-mono text-[10px]"
        style="color: var(--ink-500);"
        title="Recherche texte"
        @click="enterFuzzyMode"
      >
        <kbd class="rounded px-1 py-0.5" style="background: var(--surface-1); border: 0.5px solid var(--surface-3); color: var(--ink-700);">/</kbd>
        texte
      </button>
    </header>

    <!-- Mode fuzzy : input texte plein largeur -->
    <div
      v-if="fuzzyMode"
      class="mt-3 flex items-center gap-2 rounded-md border px-2 py-1.5"
      :style="{ borderColor: 'var(--surface-3)', background: 'var(--surface)' }"
    >
      <Search class="h-3.5 w-3.5 shrink-0" style="color: var(--ink-500);" />
      <input
        ref="fuzzyInput"
        v-model="fuzzyQuery"
        type="text"
        placeholder="ex : BE 2 2002 · fr 50c · DE comm 2020"
        class="flex-1 bg-transparent font-mono text-[11px] outline-none"
        style="color: var(--ink);"
      />
    </div>

    <!-- 1. Pays — grille code-only, 7 cols × 4 rangées -->
    <div v-if="!fuzzyMode" class="mt-3">
      <p
        class="mb-1.5 font-mono text-[9px] uppercase tracking-wider"
        style="color: var(--ink-500);"
      >
        <span style="color: var(--gold-600);">1.</span> Pays
        <span
          v-if="enableKbdNav && isoBuffer"
          class="ml-1.5 rounded px-1 font-mono tracking-widest"
          style="background: var(--gold-600); color: var(--surface);"
        >⌨ {{ isoBuffer }}</span>
        <span
          v-else-if="enableKbdNav && activeZone === 'country'"
          class="ml-1.5 normal-case tracking-normal opacity-60"
        >tape le code pays…</span>
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
          v-for="(d, di) in DENOMINATIONS"
          :key="d.value"
          type="button"
          class="rounded-full border px-2 py-0.5 text-[10px] transition-all"
          :style="{
            borderColor: denomination === d.value ? 'var(--indigo-700)' : 'var(--surface-3)',
            color: denomination === d.value ? 'var(--surface)' : 'var(--ink-700)',
            background: denomination === d.value ? 'var(--indigo-700)' : 'var(--surface)',
            boxShadow: enableKbdNav && activeZone === 'denom' && denomIdx === di
              ? '0 0 0 2px var(--gold-600)' : 'none',
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
          v-for="(y, yi) in COMMON_YEARS"
          :key="y ?? 'all'"
          type="button"
          class="shrink-0 rounded border px-2 py-0.5 font-mono text-[10px] tabular-nums transition-all"
          :style="{
            borderColor: year === y ? 'var(--gold-600)' : 'var(--surface-3)',
            color: year === y ? 'var(--gold-600)' : 'var(--ink-700)',
            background: year === y
              ? 'color-mix(in srgb, var(--gold-600) 8%, var(--surface))'
              : 'var(--surface)',
            boxShadow: enableKbdNav && activeZone === 'year' && yearIdx === yi
              ? '0 0 0 2px var(--gold-600)' : 'none',
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
        v-else-if="showFuzzyHint"
        class="rounded-md border-2 border-dashed px-3 py-4 text-center text-[11px]"
        style="border-color: var(--surface-3); color: var(--ink-400);"
      >
        Tape au moins 2 caractères.
      </p>

      <p
        v-else-if="showCascadeHint"
        class="rounded-md border-2 border-dashed px-3 py-4 text-center text-[11px]"
        style="border-color: var(--surface-3); color: var(--ink-400);"
      >
        <template v-if="enableKbdNav">
          Tape le <strong>code pays</strong> (ex. <kbd class="mx-0.5 inline-block rounded px-1 font-mono text-[10px]" style="background: var(--surface-1); border: 0.5px solid var(--surface-3); color: var(--ink-700);">FI</kbd>),
          <kbd class="mx-0.5 inline-block rounded px-1 font-mono text-[10px]" style="background: var(--surface-1); border: 0.5px solid var(--surface-3); color: var(--ink-700);">Tab</kbd> entre zones,
          <kbd class="mx-0.5 inline-block rounded px-1 font-mono text-[10px]" style="background: var(--surface-1); border: 0.5px solid var(--surface-3); color: var(--ink-700);">← →</kbd> / <kbd class="mx-0.5 inline-block rounded px-1 font-mono text-[10px]" style="background: var(--surface-1); border: 0.5px solid var(--surface-3); color: var(--ink-700);">↑ ↓</kbd>,
          <kbd class="mx-0.5 inline-block rounded px-1 font-mono text-[10px]" style="background: var(--surface-1); border: 0.5px solid var(--surface-3); color: var(--ink-700);">⏎</kbd> sélectionne.<br />
        </template>
        Sélectionne un pays puis une dénomination<br />
        ou tape <kbd class="mx-1 inline-block rounded px-1 py-0.5 font-mono text-[10px]" style="background: var(--surface-1); border: 0.5px solid var(--surface-3); color: var(--ink-700);">/</kbd> pour la recherche texte.
      </p>

      <p
        v-else-if="!results.length"
        class="rounded-md border-2 border-dashed px-3 py-4 text-center text-[11px]"
        style="border-color: var(--surface-3); color: var(--ink-400);"
      >
        Aucune pièce ne correspond.
      </p>

      <ul v-else ref="resultsEl" class="flex flex-col gap-1.5">
        <li
          v-for="(r, ri) in results"
          :key="r.eurio_id"
          class="flex items-stretch gap-2.5 rounded-md border px-2 py-1.5 transition-colors"
          :style="{
            borderColor: enableKbdNav && activeZone === 'results' && resultIdx === ri
              ? 'var(--gold-600)' : 'var(--surface-3)',
            background: enableKbdNav && activeZone === 'results' && resultIdx === ri
              ? 'color-mix(in srgb, var(--gold-600) 7%, var(--surface))' : 'var(--surface)',
            boxShadow: enableKbdNav && activeZone === 'results' && resultIdx === ri
              ? '0 0 0 1px var(--gold-600)' : 'none',
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
