<script setup lang="ts">
import LayerSection from '../components/LayerSection.vue'
import PreviewGrid from '../components/PreviewGrid.vue'
import SaveRecipeModal from '../components/SaveRecipeModal.vue'
import StagedCoinsList from '../components/StagedCoinsList.vue'
import {
  createRecipe,
  fetchAugmentationSchema,
  fetchRecipes,
  postPreview,
  stageForTraining,
} from '../composables/useAugmentationApi'
import { useRecipeState } from '../composables/useRecipeState'
import { useStagedCoins } from '../composables/useStagedCoins'
import { checkMlApi } from '@/features/training/composables/useTrainingApi'
import { fetchZoneMap } from '@/features/confusion/composables/useConfusionMap'
import type { ConfusionZone } from '@/shared/supabase/types'
import type {
  AugmentationSchemaResponse,
  Layer,
  PreviewImage,
  Recipe,
  RecipeRow,
} from '../types'
import {
  ArrowLeft,
  ArrowRight,
  Loader2,
  RefreshCw,
  Save,
  Sparkles,
  SplitSquareHorizontal,
  Wifi,
  WifiOff,
  X,
} from 'lucide-vue-next'
import { computed, onMounted, onUnmounted, reactive, ref, watch, type UnwrapNestedRefs } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

// ─── API status ─────────────────────────────────────────────────────────

const apiStatus = ref<'checking' | 'online' | 'offline'>('checking')

async function refreshApiStatus(opts: { showProbe?: boolean } = {}) {
  if (opts.showProbe) apiStatus.value = 'checking'
  const online = await checkMlApi()
  apiStatus.value = online ? 'online' : 'offline'
}

let apiInterval: ReturnType<typeof setInterval> | null = null

// ─── Staged coins + zones ───────────────────────────────────────────────

const { coins, active, activeIndex, setActive } = useStagedCoins(20)
const zoneByEurioId = ref<Record<string, ConfusionZone | null>>({})
const statusByEurioId = ref<Record<string, 'pending' | 'done' | 'error'>>({})
const coinRecipeAssignment = ref<Record<string, string | null>>({})

async function loadZones() {
  try {
    const map = await fetchZoneMap()
    const out: Record<string, ConfusionZone | null> = {}
    for (const c of coins.value) {
      out[c.eurio_id] = map.get(c.eurio_id)?.zone ?? null
    }
    zoneByEurioId.value = out
  } catch {
    // Non-fatal, zones stay empty.
  }
}

watch(coins, loadZones, { immediate: false })

// ─── Schema + recipes catalog ───────────────────────────────────────────

const schema = ref<AugmentationSchemaResponse | null>(null)
const customRecipes = ref<RecipeRow[]>([])
const loadingSchema = ref(true)
const schemaError = ref<string | null>(null)

async function loadCatalog() {
  if (apiStatus.value !== 'online') return
  loadingSchema.value = true
  schemaError.value = null
  try {
    const [s, rs] = await Promise.all([fetchAugmentationSchema(), fetchRecipes()])
    schema.value = s
    customRecipes.value = rs
    // Seed slot A with the orange default once we have the schema.
    if (!slotA.loaded) {
      slotA.state.loadRecipe(s.default_recipe, 'orange')
      slotA.state.ensureLayersFromSchema(s.layers)
      slotA.loaded = true
    }
  } catch (err) {
    schemaError.value = err instanceof Error ? err.message : 'Failed to load'
  } finally {
    loadingSchema.value = false
  }
}

// ─── Slot state (A + B for compare mode) ────────────────────────────────
//
// We wrap each slot in `reactive` so nested refs (from `useRecipeState`) are
// automatically unwrapped both at runtime and in vue-tsc's template typing.
// In script-land, `slot.loading = true` writes directly; in templates,
// `slot.loading` reads as `boolean`. No `.value` plumbing in the consumer.

// State composable returns refs; `reactive()` unwraps them nested, so we
// declare the Slot view with UnwrapNestedRefs to match the runtime shape.
type UnwrappedRecipeState = UnwrapNestedRefs<ReturnType<typeof useRecipeState>>

interface Slot {
  state: UnwrappedRecipeState
  loaded: boolean
  recipeId: string | null
  images: PreviewImage[]
  runId: string | null
  seed: number
  durationMs: number
  loading: boolean
  error: string | null
}

function newSlot(): Slot {
  const state = useRecipeState({ layers: [] }) as unknown as UnwrappedRecipeState
  return reactive({
    state,
    loaded: false,
    recipeId: null as string | null,
    images: [] as PreviewImage[],
    runId: null as string | null,
    seed: 42,
    durationMs: 0,
    loading: false,
    error: null as string | null,
  }) as Slot
}

function resetSlot(slot: Slot): void {
  slot.state.loadRecipe({ layers: [] }, 'default')
  slot.loaded = false
  slot.recipeId = null
  slot.images = []
  slot.runId = null
  slot.seed = 42
  slot.durationMs = 0
  slot.loading = false
  slot.error = null
}

const slotA = newSlot()
const slotB = newSlot()
const compareMode = ref(false)
const fixSeed = ref(true)
const sharedSeed = ref(42)
const previewCount = ref(16)

function toggleCompare() {
  if (!compareMode.value) {
    // Enter compare: clone A → B.
    slotB.state.loadRecipe(
      JSON.parse(JSON.stringify(slotA.state.current)) as Recipe,
      `${slotA.state.baselineName} (clone)`,
    )
    if (schema.value) slotB.state.ensureLayersFromSchema(schema.value.layers)
    slotB.loaded = true
    slotB.recipeId = slotA.recipeId
    slotB.seed = slotA.seed
  } else {
    resetSlot(slotB)
  }
  compareMode.value = !compareMode.value
}

// ─── Preset handling ────────────────────────────────────────────────────

function loadPresetIntoSlot(slot: Slot, presetName: string) {
  if (!schema.value) return
  const zonePresets: Record<string, Recipe> = {
    green: schema.value.default_recipe, // placeholder — true green comes from schema? no, only `default_recipe` = orange
  }
  // The schema API returns only the orange default_recipe; green/red are hard
  // to replicate client-side without duplicating bounds. Solution: load any
  // "zone" preset as a clone of custom recipes matching that zone, or fall
  // back to default_recipe if none exist.
  if (presetName === 'orange') {
    slot.state.loadRecipe(schema.value.default_recipe, 'orange')
    slot.state.ensureLayersFromSchema(schema.value.layers)
    slot.recipeId = null
    return
  }
  // Check if a custom recipe with this exact name exists first.
  const exact = customRecipes.value.find(r => r.name === presetName)
  if (exact) {
    slot.state.loadRecipe(exact.config, exact.name)
    slot.state.ensureLayersFromSchema(schema.value.layers)
    slot.recipeId = exact.id
    return
  }
  // Pick the most recent recipe for this zone as a proxy.
  const byZone = customRecipes.value.find(r => r.zone === presetName)
  if (byZone) {
    slot.state.loadRecipe(byZone.config, byZone.name)
    slot.state.ensureLayersFromSchema(schema.value.layers)
    slot.recipeId = byZone.id
    return
  }
  // No recipe for this zone → fall back to orange default, mark zone intent.
  slot.state.loadRecipe(schema.value.default_recipe, presetName)
  slot.state.ensureLayersFromSchema(schema.value.layers)
  slot.recipeId = null
  // silence unused zonePresets
  void zonePresets
}

// Accessible list of presets for the <select>: zones + custom recipes.
const presetOptions = computed<{ group: 'zone' | 'custom', name: string, label: string }[]>(() => {
  const zones = (['green', 'orange', 'red'] as const).map(z => ({
    group: 'zone' as const,
    name: z,
    label: `Zone ${z}`,
  }))
  const custom = customRecipes.value.map(r => ({
    group: 'custom' as const,
    name: r.id,
    label: `${r.name}${r.zone ? ` · ${r.zone}` : ''}`,
  }))
  return [...zones, ...custom]
})

function applyPresetString(slot: Slot, value: string) {
  const match = presetOptions.value.find(p => `${p.group}:${p.name}` === value)
  if (!match) return
  if (match.group === 'zone') {
    loadPresetIntoSlot(slot, match.name)
  } else {
    const r = customRecipes.value.find(c => c.id === match.name)
    if (r && schema.value) {
      slot.state.loadRecipe(r.config, r.name)
      slot.state.ensureLayersFromSchema(schema.value.layers)
      slot.recipeId = r.id
    }
  }
}

// ─── Regenerate ─────────────────────────────────────────────────────────

async function regenerateSlot(slot: Slot) {
  if (!active.value) return
  slot.loading = true
  slot.error = null
  try {
    const seed = fixSeed.value ? sharedSeed.value : null
    const res = await postPreview({
      recipe: { ...slot.state.current, count: previewCount.value },
      eurio_id: active.value.eurio_id,
      count: previewCount.value,
      seed,
    })
    slot.images = res.images
    slot.runId = res.run_id
    slot.seed = res.seed ?? 0
    slot.durationMs = res.duration_ms
    statusByEurioId.value = {
      ...statusByEurioId.value,
      [active.value.eurio_id]: 'done',
    }
  } catch (err) {
    slot.error = err instanceof Error ? err.message : 'Échec génération'
    slot.images = []
    if (active.value) {
      statusByEurioId.value = {
        ...statusByEurioId.value,
        [active.value.eurio_id]: 'error',
      }
    }
  } finally {
    slot.loading = false
  }
}

async function regenerateAll() {
  if (!active.value) return
  const tasks: Promise<void>[] = [regenerateSlot(slotA)]
  if (compareMode.value) tasks.push(regenerateSlot(slotB))
  await Promise.all(tasks)
}

// Regenerate automatically when active coin changes and schema is ready.
watch(active, (coin) => {
  if (coin && schema.value && slotA.loaded) {
    void regenerateAll()
  }
})

// ─── Save recipe ────────────────────────────────────────────────────────

const saveModalOpenFor = ref<'A' | 'B' | null>(null)
const saveError = ref<string | null>(null)

async function submitSave(slotKey: 'A' | 'B', payload: { name: string, zone: string | null }) {
  const slot = slotKey === 'A' ? slotA : slotB
  saveError.value = null
  try {
    const created = await createRecipe({
      name: payload.name,
      zone: payload.zone,
      config: slot.state.current,
      based_on_recipe_id: slot.recipeId,
    })
    customRecipes.value = [created, ...customRecipes.value]
    slot.state.loadRecipe(created.config, created.name)
    if (schema.value) slot.state.ensureLayersFromSchema(schema.value.layers)
    slot.recipeId = created.id
    saveModalOpenFor.value = null
  } catch (err) {
    saveError.value = err instanceof Error ? err.message : 'Save failed'
  }
}

// ─── Handoff to training ────────────────────────────────────────────────

const handoffLoading = ref(false)
const handoffError = ref<string | null>(null)

// Assign the ACTIVE slot's recipe (if persisted) to all coins; can be
// refined per-coin via `coinRecipeAssignment` but v1 defaults to uniform.
async function sendToTraining() {
  if (!coins.value.length) return
  const activeSlot = compareMode.value ? slotB : slotA
  if (!activeSlot.recipeId) {
    handoffError.value = 'Sauvegarde d\'abord ta recette active avant d\'envoyer au training.'
    return
  }
  handoffLoading.value = true
  handoffError.value = null
  try {
    const items = coins.value.map(c => ({
      class_id: c.design_group_id || c.eurio_id,
      class_kind: (c.design_group_id ? 'design_group_id' : 'eurio_id') as
        'eurio_id' | 'design_group_id',
      aug_recipe_id: coinRecipeAssignment.value[c.eurio_id] ?? activeSlot.recipeId,
    }))
    await stageForTraining(items)
    router.push('/training')
  } catch (err) {
    handoffError.value = err instanceof Error ? err.message : 'Handoff failed'
  } finally {
    handoffLoading.value = false
  }
}

// ─── Lightbox ───────────────────────────────────────────────────────────

const lightbox = ref<{ url: string, index: number } | null>(null)

function closeLightbox() {
  lightbox.value = null
}

function onEscape(e: KeyboardEvent) {
  if (e.key === 'Escape') closeLightbox()
}

// ─── Lifecycle ──────────────────────────────────────────────────────────

onMounted(async () => {
  await refreshApiStatus({ showProbe: true })
  if (apiStatus.value === 'online') {
    await loadCatalog()
  }
  apiInterval = setInterval(() => refreshApiStatus(), 30000)
  window.addEventListener('keydown', onEscape)
})

onUnmounted(() => {
  if (apiInterval) clearInterval(apiInterval)
  window.removeEventListener('keydown', onEscape)
})

watch(apiStatus, async (status, prev) => {
  if (status === 'online' && prev !== 'online') {
    await loadCatalog()
  }
})

// ─── Helpers for template ───────────────────────────────────────────────

function slotPresetValue(slot: Slot): string {
  if (slot.recipeId) return `custom:${slot.recipeId}`
  const name = slot.state.baselineName
  if (['green', 'orange', 'red'].includes(name)) return `zone:${name}`
  return ''
}

function paramDirtyChecker(slot: Slot, layerIndex: number) {
  return (paramName: string) => slot.state.isParamDirty(layerIndex, paramName)
}

function layerForType(slot: Slot, type: string): { layer: Layer, index: number } | null {
  const idx = slot.state.current.layers.findIndex(l => l.type === type)
  if (idx < 0) return null
  return { layer: slot.state.current.layers[idx], index: idx }
}
</script>

<template>
  <div class="p-8">
    <!-- ═══════════════════════ Header ═══════════════════════ -->
    <header class="mb-8">
      <div class="flex items-start justify-between gap-6">
        <div class="min-w-0 flex-1">
          <p
            class="mb-1 text-[10px] font-medium uppercase"
            style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
          >Phase 2 · ML scalability</p>
          <h1
            class="font-display text-3xl italic font-semibold leading-tight"
            style="color: var(--indigo-700);"
          >Augmentation Studio</h1>
          <p class="mt-1.5 max-w-xl text-sm leading-snug" style="color: var(--ink-500);">
            Calibre les recettes d'augmentation en direct — bouge les sliders,
            regénère la grille, valide à l'œil, sauvegarde pour le banc.
          </p>
        </div>

        <div class="flex flex-shrink-0 items-center gap-3">
          <div
            class="flex items-center gap-2 rounded-full border px-3 py-1.5"
            :style="{
              borderColor: apiStatus === 'online' ? 'var(--success)' : 'var(--surface-3)',
              background: apiStatus === 'online'
                ? 'color-mix(in srgb, var(--success) 8%, var(--surface))'
                : 'var(--surface)',
            }"
          >
            <template v-if="apiStatus === 'checking'">
              <Loader2 class="h-3.5 w-3.5 animate-spin" style="color: var(--ink-400);" />
              <span class="text-xs" style="color: var(--ink-400);">Connexion…</span>
            </template>
            <template v-else-if="apiStatus === 'online'">
              <Wifi class="h-3.5 w-3.5" style="color: var(--success);" />
              <span class="text-xs font-medium" style="color: var(--success);">API ML</span>
            </template>
            <template v-else>
              <WifiOff class="h-3.5 w-3.5" style="color: var(--ink-400);" />
              <span class="text-xs" style="color: var(--ink-400);">Hors-ligne</span>
            </template>
          </div>
        </div>
      </div>

      <div class="mt-6 h-px w-16" style="background: var(--gold);" />
    </header>

    <!-- ═══════════════════════ Offline ═══════════════════════ -->
    <div
      v-if="apiStatus === 'offline'"
      class="mb-6 rounded-lg border-2 border-dashed px-5 py-6 text-center"
      style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface));"
    >
      <WifiOff class="mx-auto mb-2 h-6 w-6" style="color: var(--danger);" />
      <p class="text-sm font-medium" style="color: var(--danger);">
        ML API non jointe (http://localhost:8042)
      </p>
      <p class="mt-1 text-xs" style="color: var(--ink-500);">
        Lance <code style="background: var(--surface-1); padding: 1px 4px; border-radius: 3px;">go-task ml:api</code>
        puis clique sur réessayer.
      </p>
      <button
        class="mt-3 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium"
        style="background: var(--ink); color: var(--surface);"
        @click="refreshApiStatus({ showProbe: true })"
      >
        <RefreshCw class="h-3 w-3" /> Réessayer
      </button>
    </div>

    <!-- ═══════════════════════ Empty state ═══════════════════════ -->
    <div
      v-else-if="apiStatus === 'online' && coins.length === 0"
      class="rounded-lg border-2 border-dashed px-5 py-12 text-center"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <Sparkles class="mx-auto mb-3 h-8 w-8" style="color: var(--ink-400);" />
      <p class="text-sm font-medium" style="color: var(--ink);">Aucune pièce stagée</p>
      <p class="mt-1 text-xs" style="color: var(--ink-500);">
        Va sur /coins, sélectionne jusqu'à 20 pièces, puis clique <span class="font-mono">Augmenter</span>.
      </p>
      <button
        class="mt-4 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium"
        style="background: var(--indigo-700); color: white;"
        @click="router.push('/coins')"
      >
        <ArrowRight class="h-3 w-3" /> Aller à /coins
      </button>
    </div>

    <!-- ═══════════════════════ Main layout ═══════════════════════ -->
    <template v-else-if="apiStatus === 'online'">
      <div class="flex items-center justify-between gap-3 mb-4">
        <p class="text-sm" style="color: var(--ink-500);">
          {{ coins.length }} pièce{{ coins.length > 1 ? 's' : '' }} stagée{{ coins.length > 1 ? 's' : '' }}
          <span v-if="active">· active : <span class="font-mono" style="color: var(--ink);">{{ active.eurio_id }}</span></span>
        </p>

        <div class="flex items-center gap-2">
          <label class="flex items-center gap-1.5 text-xs" style="color: var(--ink-500);">
            <input v-model="fixSeed" type="checkbox" class="accent-indigo-700" />
            fix seed
          </label>
          <input
            v-if="fixSeed"
            v-model.number="sharedSeed"
            type="number"
            class="w-16 rounded border px-1.5 py-0.5 font-mono text-[11px]"
            style="background: var(--surface-1); border-color: var(--surface-3); color: var(--ink);"
          />
          <input
            v-model.number="previewCount"
            type="number"
            min="1"
            max="64"
            class="w-14 rounded border px-1.5 py-0.5 font-mono text-[11px]"
            style="background: var(--surface-1); border-color: var(--surface-3); color: var(--ink);"
            title="Nombre de variantes (max 64)"
          />
          <button
            class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all"
            style="background: var(--indigo-700); color: white;"
            :disabled="!active || slotA.loading || slotB.loading"
            @click="regenerateAll"
          >
            <Loader2 v-if="slotA.loading || slotB.loading" class="h-3 w-3 animate-spin" />
            <RefreshCw v-else class="h-3 w-3" />
            Regenerate
          </button>
          <button
            class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium"
            :style="{
              background: compareMode ? 'var(--indigo-700)' : 'var(--surface-1)',
              color: compareMode ? 'white' : 'var(--ink)',
            }"
            @click="toggleCompare"
          >
            <SplitSquareHorizontal class="h-3 w-3" />
            {{ compareMode ? 'Quitter Compare' : 'Compare' }}
          </button>
        </div>
      </div>

      <div
        class="grid gap-4"
        :class="compareMode ? 'grid-cols-[240px_1fr_1fr]' : 'grid-cols-[240px_1fr_360px]'"
      >
        <!-- LEFT — Staged coins -->
        <StagedCoinsList
          :coins="coins"
          :active-index="activeIndex"
          :zone-by-eurio-id="zoneByEurioId"
          :status-by-eurio-id="statusByEurioId"
          @select="setActive"
        />

        <!-- CENTER — Slot A -->
        <section class="flex flex-col gap-3">
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-2 min-w-0">
              <span
                class="rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider"
                style="background: var(--ink); color: var(--surface);"
              >Slot A</span>
              <span class="truncate text-xs" style="color: var(--ink-500);">
                {{ slotA.state.baselineName }}
              </span>
              <span
                v-if="slotA.state.dirty"
                class="rounded px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider"
                style="background: var(--indigo-700); color: white;"
              >modifié</span>
              <span
                v-if="slotA.durationMs"
                class="font-mono text-[10px]"
                style="color: var(--ink-400);"
              >{{ slotA.durationMs }} ms</span>
            </div>
          </div>

          <PreviewGrid
            :images="slotA.images"
            :count="previewCount"
            :loading="slotA.loading"
            :error="slotA.error"
            @open-lightbox="(url, index) => (lightbox = { url, index })"
          />
        </section>

        <!-- RIGHT — Slot A configurator (OR Slot B in compare) -->
        <section v-if="!compareMode && schema" class="flex flex-col gap-3">
          <div class="flex flex-col gap-1">
            <label
              class="text-[10px] font-medium uppercase"
              style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
            >Preset / Recipe</label>
            <select
              :value="slotPresetValue(slotA)"
              class="rounded border px-2 py-1.5 text-xs"
              style="background: var(--surface-1); border-color: var(--surface-3); color: var(--ink);"
              @change="(e) => applyPresetString(slotA, (e.target as HTMLSelectElement).value)"
            >
              <option value="" disabled>— choisir —</option>
              <optgroup label="Zones">
                <option v-for="z in ['green', 'orange', 'red']" :key="z" :value="`zone:${z}`">
                  Zone {{ z }}
                </option>
              </optgroup>
              <optgroup v-if="customRecipes.length" label="Recettes sauvegardées">
                <option v-for="r in customRecipes" :key="r.id" :value="`custom:${r.id}`">
                  {{ r.name }}{{ r.zone ? ` · ${r.zone}` : '' }}
                </option>
              </optgroup>
            </select>
          </div>

          <div class="flex flex-col gap-2 max-h-[70vh] overflow-y-auto pr-1">
            <template v-for="layerSchema in schema.layers" :key="layerSchema.type">
              <LayerSection
                v-if="layerForType(slotA, layerSchema.type)"
                :schema="layerSchema"
                :layer="layerForType(slotA, layerSchema.type)!.layer"
                :layer-index="layerForType(slotA, layerSchema.type)!.index"
                :is-param-dirty="paramDirtyChecker(slotA, layerForType(slotA, layerSchema.type)!.index)"
                @update="(name, value) => slotA.state.updateParam(layerForType(slotA, layerSchema.type)!.index, name, value)"
              />
            </template>
          </div>

          <button
            v-if="slotA.state.dirty"
            class="flex items-center justify-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium"
            style="background: var(--indigo-700); color: white;"
            @click="saveModalOpenFor = 'A'"
          >
            <Save class="h-3 w-3" /> Save recipe…
          </button>
        </section>

        <!-- RIGHT (in compare) — Slot B preview + configurator stacked -->
        <section v-if="compareMode" class="flex flex-col gap-3">
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-2 min-w-0">
              <span
                class="rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider"
                style="background: var(--gold); color: var(--ink);"
              >Slot B</span>
              <span class="truncate text-xs" style="color: var(--ink-500);">
                {{ slotB.state.baselineName }}
              </span>
              <span
                v-if="slotB.state.dirty"
                class="rounded px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider"
                style="background: var(--indigo-700); color: white;"
              >modifié</span>
            </div>
          </div>

          <PreviewGrid
            :images="slotB.images"
            :count="previewCount"
            :loading="slotB.loading"
            :error="slotB.error"
            @open-lightbox="(url, index) => (lightbox = { url, index })"
          />

          <div v-if="schema" class="flex flex-col gap-2 max-h-[40vh] overflow-y-auto pr-1">
            <div class="flex flex-col gap-1">
              <label
                class="text-[10px] font-medium uppercase"
                style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
              >Preset Slot B</label>
              <select
                :value="slotPresetValue(slotB)"
                class="rounded border px-2 py-1.5 text-xs"
                style="background: var(--surface-1); border-color: var(--surface-3); color: var(--ink);"
                @change="(e) => applyPresetString(slotB, (e.target as HTMLSelectElement).value)"
              >
                <option value="" disabled>— choisir —</option>
                <optgroup label="Zones">
                  <option v-for="z in ['green', 'orange', 'red']" :key="z" :value="`zone:${z}`">
                    Zone {{ z }}
                  </option>
                </optgroup>
                <optgroup v-if="customRecipes.length" label="Recettes">
                  <option v-for="r in customRecipes" :key="r.id" :value="`custom:${r.id}`">
                    {{ r.name }}
                  </option>
                </optgroup>
              </select>
            </div>

            <template v-for="layerSchema in schema.layers" :key="layerSchema.type">
              <LayerSection
                v-if="layerForType(slotB, layerSchema.type)"
                :schema="layerSchema"
                :layer="layerForType(slotB, layerSchema.type)!.layer"
                :layer-index="layerForType(slotB, layerSchema.type)!.index"
                :is-param-dirty="paramDirtyChecker(slotB, layerForType(slotB, layerSchema.type)!.index)"
                @update="(name, value) => slotB.state.updateParam(layerForType(slotB, layerSchema.type)!.index, name, value)"
              />
            </template>

            <button
              v-if="slotB.state.dirty"
              class="flex items-center justify-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium"
              style="background: var(--indigo-700); color: white;"
              @click="saveModalOpenFor = 'B'"
            >
              <Save class="h-3 w-3" /> Save recipe B…
            </button>
          </div>
        </section>
      </div>

      <!-- ═══════════════════════ Footer actions ═══════════════════════ -->
      <div class="mt-6 flex items-center justify-between border-t pt-4" style="border-color: var(--surface-3);">
        <button
          class="flex items-center gap-1.5 text-xs"
          style="color: var(--ink-500);"
          @click="router.push('/coins')"
        >
          <ArrowLeft class="h-3 w-3" /> Retour /coins
        </button>

        <div class="flex items-center gap-3">
          <p v-if="handoffError" class="text-xs" style="color: var(--danger);">{{ handoffError }}</p>
          <button
            class="flex items-center gap-1.5 rounded-md px-4 py-2 text-sm font-medium"
            style="background: var(--indigo-700); color: white;"
            :disabled="!coins.length || handoffLoading"
            @click="sendToTraining"
          >
            <Loader2 v-if="handoffLoading" class="h-3 w-3 animate-spin" />
            <ArrowRight v-else class="h-3 w-3" />
            Envoyer au training
          </button>
        </div>
      </div>
    </template>

    <!-- ═══════════════════════ Save modal ═══════════════════════ -->
    <SaveRecipeModal
      :open="saveModalOpenFor === 'A'"
      :initial-zone="null"
      :based-on-name="slotA.state.baselineName"
      @close="saveModalOpenFor = null"
      @save="(p) => submitSave('A', p)"
    />
    <SaveRecipeModal
      :open="saveModalOpenFor === 'B'"
      :initial-zone="null"
      :based-on-name="slotB.state.baselineName"
      @close="saveModalOpenFor = null"
      @save="(p) => submitSave('B', p)"
    />

    <!-- ═══════════════════════ Lightbox ═══════════════════════ -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="lightbox"
          class="fixed inset-0 z-50 flex items-center justify-center"
          style="background: rgba(0,0,0,0.8);"
          @click.self="closeLightbox"
        >
          <button
            class="absolute top-4 right-4 rounded-full p-2"
            style="background: rgba(255,255,255,0.1); color: white;"
            @click="closeLightbox"
          >
            <X class="h-4 w-4" />
          </button>
          <img :src="lightbox.url" :alt="`Variation ${lightbox.index}`" class="max-h-[90vh] max-w-[90vw] rounded-md object-contain" />
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
