<script setup lang="ts">
// Grille de récupération des crops rejetés (scopée cohort via ?cohort=<id>).
//
// Beaucoup de rejets manuels ne sont que des cadrages ratés qu'un re-crop
// aurait sauvés. Cette vue liste tout ce qui a été rejeté, laisse l'admin
// (dé)sélectionner d'un clic — tout sél./désél. en tête — puis « Remettre en
// queue » : les crops choisis repassent open/needs_review et reviennent en
// tête de la queue manuelle, où l'éditeur de re-crop existant prend le relais.
//
// Pas de raccourcis clavier : sélection à la souris, comme l'auto-accept.

import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  CheckSquare,
  Loader2,
  RotateCcw,
  Square,
} from 'lucide-vue-next'
import {
  fetchRejectedCrops,
  restoreRejected,
  type RejectedCrop,
} from '../composables/useReviewApi'

type Status = 'loading' | 'ready' | 'submitting' | 'done' | 'error'

const router = useRouter()
const route = useRoute()
// Scope cohort optionnel — restreint la liste aux coins de la cohort.
const cohortId = computed(() =>
  typeof route.query.cohort === 'string' && route.query.cohort
    ? route.query.cohort
    : null,
)

const status = ref<Status>('loading')
const error = ref<string | null>(null)
const items = ref<RejectedCrop[]>([])
const selected = ref<Set<string>>(new Set())
const restoredCount = ref(0)

const selectedCount = computed(() => selected.value.size)
const total = computed(() => items.value.length)
const allSelected = computed(
  () => total.value > 0 && selectedCount.value === total.value,
)

function toggleAll() {
  selected.value = allSelected.value
    ? new Set()
    : new Set(items.value.map((it) => it.review_id))
}

function toggle(id: string) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

// Étiquette lisible de la raison de rejet (image_assets.quality_reason).
const REASON_LABEL: Record<string, string> = {
  not_a_coin: 'pas une pièce',
  too_low_quality: 'qualité trop basse',
  rejected_in_review: 'rejet manuel',
}
function reasonLabel(reason: string | null): string {
  if (!reason) return 'rejeté'
  return REASON_LABEL[reason] ?? reason
}

async function load() {
  status.value = 'loading'
  error.value = null
  try {
    items.value = await fetchRejectedCrops(cohortId.value)
    selected.value = new Set()
    status.value = 'ready'
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
    status.value = 'error'
  }
}

async function submit() {
  if (selectedCount.value === 0) return
  status.value = 'submitting'
  error.value = null
  try {
    const ids = Array.from(selected.value)
    const r = await restoreRejected(ids)
    restoredCount.value = r.restored
    // Retire de la grille ce qui a été restauré ; ce qui a été skip
    // (déjà non-rejeté) reste affiché pour transparence.
    const restoredSet = new Set(ids.filter((id) => !r.skipped.includes(id)))
    items.value = items.value.filter((it) => !restoredSet.has(it.review_id))
    selected.value = new Set()
    status.value = items.value.length === 0 ? 'done' : 'ready'
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
    status.value = 'ready'
  }
}

function backToCabinet() {
  void router.push('/review')
}

function goToManual() {
  const q = cohortId.value ? `?cohort=${encodeURIComponent(cohortId.value)}` : ''
  void router.push(`/review/manual${q}`)
}

onMounted(load)
watch(cohortId, () => { void load() })
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- ═══ Header ═══ -->
    <header
      class="flex flex-wrap items-center justify-between gap-4 border-b px-8 py-3"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <div class="flex items-center gap-4">
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-mono uppercase tracking-wider transition-colors"
          style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface-1);"
          @click="backToCabinet"
        >
          <ArrowLeft class="h-3 w-3" />
          Cabinet
        </button>
        <div>
          <h1
            class="font-display text-lg italic font-semibold"
            style="color: var(--indigo-700);"
          >
            Récupérer les crops rejetés
          </h1>
          <p class="mt-0.5 text-xs" style="color: var(--ink-500);">
            Sélectionne ce qu'un re-crop sauverait — les crops choisis repassent
            en queue manuelle.
            <span
              v-if="cohortId"
              class="ml-1.5 rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider"
              style="background: color-mix(in srgb, var(--indigo-700) 12%, var(--surface)); color: var(--indigo-700);"
            >cohort · {{ cohortId }}</span>
          </p>
        </div>
      </div>

      <div
        v-if="status !== 'loading' && status !== 'error'"
        class="font-mono text-[11px] tabular-nums"
        style="color: var(--ink-500);"
      >
        <span class="font-semibold" style="color: var(--ink);">{{ total }}</span>
        <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">rejetés</span>
      </div>
    </header>

    <!-- ═══ Sub-header : actions ═══ -->
    <div
      v-if="(status === 'ready' || status === 'submitting') && total > 0"
      class="flex flex-wrap items-center justify-between gap-3 border-b px-8 py-2.5"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <button
        type="button"
        class="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] transition-colors"
        style="border-color: var(--surface-3); color: var(--ink-700); background: var(--surface-1);"
        @click="toggleAll"
      >
        <component :is="allSelected ? CheckSquare : Square" class="h-3 w-3" />
        {{ allSelected ? 'Tout désélectionner' : 'Tout sélectionner' }}
      </button>

      <button
        type="button"
        :disabled="selectedCount === 0 || status === 'submitting'"
        class="inline-flex items-center gap-2 rounded-md px-4 py-1.5 text-[12px] font-semibold transition-all"
        :style="{
          background: selectedCount === 0 || status === 'submitting'
            ? 'var(--surface-3)'
            : 'var(--success)',
          color: selectedCount === 0 || status === 'submitting'
            ? 'var(--ink-400)'
            : 'var(--surface)',
          cursor: selectedCount === 0 || status === 'submitting' ? 'not-allowed' : 'pointer',
        }"
        @click="submit"
      >
        <Loader2 v-if="status === 'submitting'" class="h-3.5 w-3.5 animate-spin" />
        <RotateCcw v-else class="h-3.5 w-3.5" />
        Remettre en queue {{ selectedCount }} crop{{ selectedCount > 1 ? 's' : '' }}
      </button>
    </div>

    <!-- ═══ Body ═══ -->
    <section class="flex-1 overflow-y-auto px-8 py-6">
      <!-- Loading -->
      <div
        v-if="status === 'loading'"
        class="flex h-full items-center justify-center"
      >
        <div class="flex flex-col items-center gap-3" style="color: var(--ink-500);">
          <Loader2 class="h-6 w-6 animate-spin" />
          <p class="text-sm">Chargement des crops rejetés…</p>
        </div>
      </div>

      <!-- Error -->
      <div
        v-else-if="status === 'error'"
        class="flex h-full flex-col items-center justify-center gap-3"
      >
        <p class="font-display text-2xl italic font-semibold" style="color: var(--danger);">
          Erreur de chargement.
        </p>
        <p class="max-w-md text-center text-sm" style="color: var(--ink-500);">
          {{ error }}
        </p>
        <button
          type="button"
          class="mt-4 inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px]"
          style="border-color: var(--surface-3); color: var(--ink-700); background: var(--surface-1);"
          @click="load"
        >
          Réessayer
        </button>
      </div>

      <!-- Done (plus rien à récupérer) -->
      <div
        v-else-if="status === 'done'"
        class="flex h-full flex-col items-center justify-center gap-4"
      >
        <p class="font-display text-5xl italic font-semibold" style="color: var(--success);">
          {{ restoredCount }} crop{{ restoredCount > 1 ? 's' : '' }} remis en queue.
        </p>
        <p class="max-w-md text-center text-sm" style="color: var(--ink-500);">
          Ils sont revenus en tête de la queue manuelle. Re-cadre-les puis valide
          la pièce.
        </p>
        <div class="mt-4 flex gap-2">
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] font-semibold"
            style="background: var(--indigo-700); color: var(--surface);"
            @click="goToManual"
          >
            Aller à la queue manuelle
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px]"
            style="border-color: var(--surface-3); color: var(--ink-700); background: var(--surface-1);"
            @click="backToCabinet"
          >
            <ArrowLeft class="h-3 w-3" />
            Retour au cabinet
          </button>
        </div>
      </div>

      <!-- Empty (aucun rejet) -->
      <div
        v-else-if="total === 0"
        class="flex h-full flex-col items-center justify-center gap-3 text-center"
      >
        <p class="font-display text-3xl italic font-semibold" style="color: var(--indigo-700);">
          Aucun crop rejeté{{ cohortId ? ' pour cette cohort' : '' }}.
        </p>
        <p class="max-w-md text-sm" style="color: var(--ink-500);">
          Rien à récupérer ici. Les rejets futurs apparaîtront dans cette grille.
        </p>
      </div>

      <!-- Grille de crops -->
      <div v-else class="recover-grid">
        <button
          v-for="item in items"
          :key="item.review_id"
          type="button"
          class="tile"
          :class="{ 'tile--selected': selected.has(item.review_id) }"
          @click="toggle(item.review_id)"
        >
          <div class="tile__img-wrap">
            <img :src="item.crop_url" :alt="item.target_label ?? 'crop'" class="tile__img" loading="lazy" />
            <span class="tile__check" :class="{ 'tile__check--on': selected.has(item.review_id) }">
              <CheckSquare v-if="selected.has(item.review_id)" class="h-3.5 w-3.5" />
              <Square v-else class="h-3.5 w-3.5" />
            </span>
          </div>
          <div class="tile__meta">
            <span class="tile__label" :title="item.target_label ?? item.target_eurio_id ?? ''">
              {{ item.target_label ?? item.target_eurio_id ?? '—' }}
            </span>
            <span class="tile__reason">{{ reasonLabel(item.quality_reason) }}</span>
          </div>
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.recover-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 14px;
}

.tile {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 6px;
  border: 1px solid var(--surface-3);
  border-radius: 8px;
  background: var(--surface);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 160ms var(--ease-out, ease),
    box-shadow 160ms var(--ease-out, ease),
    transform 160ms var(--ease-out, ease);
}
.tile:hover {
  border-color: var(--ink-300);
  transform: translateY(-1px);
}
.tile--selected {
  border-color: var(--success);
  box-shadow: 0 0 0 1px var(--success);
}

.tile__img-wrap {
  position: relative;
  aspect-ratio: 1 / 1;
  border-radius: 5px;
  overflow: hidden;
  background: var(--surface-1);
}
.tile__img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.tile__check {
  position: absolute;
  top: 5px;
  left: 5px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 5px;
  background: color-mix(in srgb, var(--surface) 80%, transparent);
  color: var(--ink-500);
  backdrop-filter: blur(2px);
}
.tile__check--on {
  background: var(--success);
  color: var(--surface);
}

.tile__meta {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 0 2px 2px;
  min-width: 0;
}
.tile__label {
  font-size: 11px;
  font-weight: 500;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tile__reason {
  font-family: var(--font-mono);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
}
</style>
