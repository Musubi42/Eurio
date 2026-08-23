<script setup lang="ts">
// Page de revue des items que l'auto-accept déterministe (Dino + texte
// convergent) propose de décider. Charge la preview au mount, l'admin
// désélectionne ce qui lui semble douteux, puis confirme. Le backend
// re-valide chaque verdict avant écriture — un ID retiré entre temps
// de `auto_candidate` est silencieusement skip côté serveur.
//
// Pas de raccourcis clavier ici (cf. review single) : la review en grille
// est plus contemplative qu'une décision unitaire, on reste à la souris.

import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  Check,
  Loader2,
  Square,
  CheckSquare,
} from 'lucide-vue-next'
import {
  runAutoAccept,
  type AutoAcceptPreviewItem,
} from '../composables/useReviewApi'
import ReviewCard from '../components/ReviewCard.vue'
import { ML_API } from '@/features/training/composables/useTrainingApi'

// Les URLs de cette page viennent de l'API ML LOCALE (`safeFetch`, `:8042`) et
// sont relatives : c'est à elle de les résoudre, pas à `ReviewCard` (qui sert
// aussi l'arbitrage, dont les URLs viennent du VPS).
function mlUrl(url: string | null | undefined): string {
  if (!url) return ''
  return url.startsWith('http') ? url : `${ML_API}${url}`
}

type Status = 'loading' | 'ready' | 'submitting' | 'done' | 'error'

const router = useRouter()
const route = useRoute()
// Scope cohort optionnel (§C4b) — restreint la preview ET l'écriture aux
// coins de la cohort. Piloté par `?cohort=<id>` (depuis la page cohort).
const cohortId = computed(() =>
  typeof route.query.cohort === 'string' && route.query.cohort
    ? route.query.cohort
    : null,
)
const status = ref<Status>('loading')
const error = ref<string | null>(null)
const items = ref<AutoAcceptPreviewItem[]>([])
const counts = ref<Record<string, number>>({})
const processed = ref(0)
const selected = ref<Set<string>>(new Set())
const accepted = ref(0)

const selectedCount = computed(() => selected.value.size)
const total = computed(() => items.value.length)
const allSelected = computed(
  () => total.value > 0 && selectedCount.value === total.value,
)

function toggleAll() {
  if (allSelected.value) {
    selected.value = new Set()
  } else {
    selected.value = new Set(items.value.map((it) => it.review_id))
  }
}

function toggle(id: string) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

async function load() {
  status.value = 'loading'
  error.value = null
  try {
    const r = await runAutoAccept({ limit: 5000, dryRun: true, cohortId: cohortId.value })
    items.value = r.preview
    counts.value = r.by_category
    processed.value = r.processed
    selected.value = new Set(r.preview.map((it) => it.review_id))
    status.value = 'ready'
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
    status.value = 'error'
  }
}

// Garde-fou : au-delà de ce seuil, le bouton "Accepter" demande une
// seconde confirmation explicite (2-clic dans une fenêtre de 4 s) pour
// éviter une écriture massive accidentelle. Cf. chunk E.
const BULK_CONFIRM_THRESHOLD = 50
const BULK_CONFIRM_WINDOW_MS = 4000

const confirmArmed = ref(false)
let confirmTimer: ReturnType<typeof setTimeout> | null = null

function armConfirm() {
  confirmArmed.value = true
  if (confirmTimer) clearTimeout(confirmTimer)
  confirmTimer = setTimeout(() => {
    confirmArmed.value = false
    confirmTimer = null
  }, BULK_CONFIRM_WINDOW_MS)
}

function disarmConfirm() {
  if (confirmTimer) {
    clearTimeout(confirmTimer)
    confirmTimer = null
  }
  confirmArmed.value = false
}

async function submit() {
  if (selectedCount.value === 0) return
  // 2-clic obligatoire pour gros lots
  if (selectedCount.value >= BULK_CONFIRM_THRESHOLD && !confirmArmed.value) {
    armConfirm()
    return
  }
  disarmConfirm()
  status.value = 'submitting'
  error.value = null
  try {
    const ids = Array.from(selected.value)
    const r = await runAutoAccept({ limit: 5000, dryRun: false, reviewIds: ids, cohortId: cohortId.value })
    accepted.value = r.accepted
    status.value = 'done'
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
    status.value = 'ready'
  }
}

function backToCabinet() {
  void router.push('/review')
}

onMounted(load)
// Recharge si le scope cohort change dans l'URL.
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
            Auto-accept · revue avant écriture
          </h1>
          <p class="mt-0.5 text-xs" style="color: var(--ink-500);">
            Dino + texte convergent — désélectionne ce qui te semble douteux.
            <span
              v-if="cohortId"
              class="ml-1.5 rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider"
              style="background: color-mix(in srgb, var(--indigo-700) 12%, var(--surface)); color: var(--indigo-700);"
            >cohort · {{ cohortId }}</span>
          </p>
        </div>
      </div>

      <!-- Compteurs de la queue scannée -->
      <div
        v-if="status !== 'loading' && status !== 'error'"
        class="flex items-center gap-5 font-mono text-[11px] tabular-nums"
        style="color: var(--ink-500);"
      >
        <span>
          <span class="font-semibold" style="color: var(--indigo-700);">{{ counts.auto_candidate ?? 0 }}</span>
          <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">auto</span>
        </span>
        <span class="opacity-50">·</span>
        <span>
          <span class="font-semibold" style="color: var(--ink);">{{ counts.partial ?? 0 }}</span>
          <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">partial</span>
        </span>
        <span>
          <span class="font-semibold" style="color: var(--ink);">{{ counts.divergent ?? 0 }}</span>
          <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">divergent</span>
        </span>
        <span>
          <span class="font-semibold" style="color: var(--ink);">{{ counts.unknown ?? 0 }}</span>
          <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">unknown</span>
        </span>
        <span class="opacity-50">·</span>
        <span>
          <span style="color: var(--ink-400);">sur</span>
          <span class="ml-1 font-semibold" style="color: var(--ink);">{{ processed }}</span>
        </span>
      </div>
    </header>

    <!-- ═══ Sub-header : actions ═══ -->
    <div
      v-if="status === 'ready' || status === 'submitting'"
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
        :class="{ 'confirm-armed': confirmArmed }"
        :style="{
          background: selectedCount === 0 || status === 'submitting'
            ? 'var(--surface-3)'
            : confirmArmed
              ? 'var(--danger)'
              : 'var(--success)',
          color: selectedCount === 0 || status === 'submitting'
            ? 'var(--ink-400)'
            : 'var(--surface)',
          cursor: selectedCount === 0 || status === 'submitting' ? 'not-allowed' : 'pointer',
        }"
        @click="submit"
        @mouseleave="disarmConfirm"
      >
        <Loader2 v-if="status === 'submitting'" class="h-3.5 w-3.5 animate-spin" />
        <Check v-else class="h-3.5 w-3.5" />
        <template v-if="confirmArmed">
          Confirmer {{ selectedCount }} items ?
        </template>
        <template v-else>
          Accepter {{ selectedCount }} item{{ selectedCount > 1 ? 's' : '' }}
        </template>
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
          <p class="text-sm">Chargement de la preview…</p>
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

      <!-- Done -->
      <div
        v-else-if="status === 'done'"
        class="flex h-full flex-col items-center justify-center gap-4"
      >
        <p class="font-display text-5xl italic font-semibold" style="color: var(--success);">
          {{ accepted }} item{{ accepted > 1 ? 's' : '' }} décidé{{ accepted > 1 ? 's' : '' }}.
        </p>
        <p class="max-w-md text-center text-sm" style="color: var(--ink-500);">
          Marqués comme acceptés automatiquement (voie Dino + texte).
          Audit visible via la queue manuelle ou la console SQL.
        </p>
        <div class="mt-4 flex gap-2">
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px]"
            style="border-color: var(--surface-3); color: var(--ink-700); background: var(--surface-1);"
            @click="load"
          >
            Recharger une nouvelle vague
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] font-semibold"
            style="background: var(--indigo-700); color: var(--surface);"
            @click="backToCabinet"
          >
            <ArrowLeft class="h-3 w-3" />
            Retour au cabinet
          </button>
        </div>
      </div>

      <!-- Empty -->
      <div
        v-else-if="items.length === 0"
        class="flex h-full flex-col items-center justify-center gap-3 text-center"
      >
        <p class="font-display text-3xl italic font-semibold" style="color: var(--indigo-700);">
          Rien à auto-accepter pour l'instant.
        </p>
        <p class="max-w-md text-sm" style="color: var(--ink-500);">
          Aucun item de la queue n'a un verdict Dino + texte convergent.
          Repasse plus tard après une nouvelle ronde de scrapes, ou bascule
          en review manuelle.
        </p>
      </div>

      <!-- Grid de cards -->
      <div v-else class="grid gap-4 lg:grid-cols-2">
        <ReviewCard
          v-for="item in items"
          :key="item.review_id"
          :crop-url="mlUrl(item.crop_url)"
          :canonical-url="mlUrl(item.target_thumb_url)"
          :eurio-id="item.target_eurio_id"
          :target-label="item.target_label"
          :listing-title="item.listing_title"
          :listing-url="item.listing_url"
          :source="item.source"
          :selected="selected.has(item.review_id)"
          @toggle="toggle(item.review_id)"
        >
          <template #metrics>
            <div class="flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] tabular-nums" style="color: var(--ink-500);">
              <span v-if="item.sim !== null">
                <span style="color: var(--ink-400);">sim</span>
                <span class="ml-1 font-semibold" style="color: var(--ink-700);">{{ item.sim.toFixed(3) }}</span>
              </span>
              <span v-if="item.spread !== null">
                <span style="color: var(--ink-400);">spread</span>
                <span class="ml-1 font-semibold" style="color: var(--ink-700);">{{ item.spread.toFixed(3) }}</span>
              </span>
              <span v-if="item.face_detected">
                <span style="color: var(--ink-400);">face</span>
                <span class="ml-1 font-semibold" style="color: var(--ink-700);">{{ item.face_detected }}</span>
              </span>
            </div>
          </template>
        </ReviewCard>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* Bouton "Confirmer ?" armé : barre de progression CSS qui décompte la
   fenêtre BULK_CONFIRM_WINDOW_MS (4 s). Visuel pour signaler le timeout. */
.confirm-armed {
  position: relative;
  overflow: hidden;
}
.confirm-armed::after {
  content: '';
  position: absolute;
  left: 0;
  bottom: 0;
  height: 2px;
  width: 100%;
  background: rgba(255,255,255,0.5);
  transform-origin: left;
  animation: confirm-countdown 4s linear forwards;
}
@keyframes confirm-countdown {
  from { transform: scaleX(1); }
  to   { transform: scaleX(0); }
}
</style>

