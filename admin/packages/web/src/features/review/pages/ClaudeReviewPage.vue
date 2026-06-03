<script setup lang="ts">
// Page d'acquittement humain des verdicts Claude vision (ccproxy).
//
// Flux : (1) un batch backend judge N items partial/divergent via Sonnet
// et écrit dans review_claude_verdicts ; (2) cette page liste les
// verdicts pending par catégorie (match / no_match / uncertain) ; (3)
// l'admin sélectionne les items à acquitter ou à rejeter.
//
// Acquitter = écrire la décision finale dans review_queue avec
// decided_by='claude_ack_human'. Rejeter = marquer le verdict comme vu
// et le sortir de la liste (l'item reste en queue manuelle si verdict
// ≠ match, ou repart pour décision humaine si verdict = match).
//
// Style aligné sur AutoAcceptReviewPage : même header, même grid de cards
// crop ↔ canonical, mêmes tokens. La signature spécifique CCProxy : badge
// modèle + confidence, toggle 3-tabs, 2 actions (acquit vert + reject).

import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  Check,
  CheckSquare,
  Loader2,
  PlayCircle,
  RotateCcw,
  Square,
  X,
} from 'lucide-vue-next'
import {
  ackClaudeVerdicts,
  fetchClaudePendingAcks,
  runClaudeBatch,
  type ClaudePendingItem,
  type ClaudeVerdict,
} from '../composables/useReviewApi'
import ReviewCard from '../components/ReviewCard.vue'

type Status = 'loading' | 'ready' | 'submitting' | 'batching' | 'error' | 'done'

const router = useRouter()
const route = useRoute()
// Scope cohort optionnel (§C4b) — restreint la liste pending ET le batch
// Claude aux coins de la cohort. Piloté par `?cohort=<id>`.
const cohortId = computed(() =>
  typeof route.query.cohort === 'string' && route.query.cohort
    ? route.query.cohort
    : null,
)
const status = ref<Status>('loading')
const error = ref<string | null>(null)
const items = ref<ClaudePendingItem[]>([])
const byVerdict = ref<Record<string, number>>({})
const totalPending = ref(0)
const selected = ref<Set<string>>(new Set())
const lastAck = ref<{ committed: number; rejected: number } | null>(null)
const batchInfo = ref<{ judged: number; skipped: number } | null>(null)

const tab = ref<ClaudeVerdict>('match')

// Taille de batch contrôlable, persistée entre sessions.
const STORAGE_BATCH_LIMIT = 'eurio:ccproxy:batchLimit'
const batchLimit = ref<number>(
  Number(localStorage.getItem(STORAGE_BATCH_LIMIT)) || 50,
)
// Approx ~3.7s par item sur Sonnet (bench chunk 2).
const batchEtaLabel = computed(() => {
  const sec = Math.round(batchLimit.value * 3.7)
  if (sec < 60) return `~${sec} s`
  return `~${Math.ceil(sec / 60)} min`
})
function onBatchLimitChange(e: Event) {
  const v = Number((e.target as HTMLInputElement).value)
  if (!Number.isFinite(v)) return
  const clamped = Math.max(1, Math.min(500, Math.round(v)))
  batchLimit.value = clamped
  localStorage.setItem(STORAGE_BATCH_LIMIT, String(clamped))
}

const selectedCount = computed(() => selected.value.size)
const total = computed(() => items.value.length)
const allSelected = computed(
  () => total.value > 0 && selectedCount.value === total.value,
)

// L'action 'ack' (commit décision finale) n'a de sens que sur les match.
const canAck = computed(() => tab.value === 'match')

function toggleAll() {
  if (allSelected.value) selected.value = new Set()
  else selected.value = new Set(items.value.map((it) => it.review_id))
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
  lastAck.value = null
  try {
    const r = await fetchClaudePendingAcks({ verdict: tab.value, limit: 500, cohortId: cohortId.value })
    items.value = r.items
    byVerdict.value = r.by_verdict
    totalPending.value = r.total_pending
    // Pré-sélection : tout coché pour match (workflow batch validation),
    // rien de coché pour no_match/uncertain (vue audit, l'admin pioche).
    selected.value = tab.value === 'match'
      ? new Set(r.items.map((it) => it.review_id))
      : new Set()
    status.value = 'ready'
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
    status.value = 'error'
  }
}

async function switchTab(next: ClaudeVerdict) {
  if (tab.value === next) return
  tab.value = next
  await load()
}

async function submit(action: 'ack' | 'reject') {
  if (selectedCount.value === 0) return
  status.value = 'submitting'
  error.value = null
  try {
    const ids = Array.from(selected.value)
    const r = await ackClaudeVerdicts(ids, action)
    lastAck.value = { committed: r.committed, rejected: r.rejected }
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
    status.value = 'ready'
  }
}

async function runBatch() {
  status.value = 'batching'
  error.value = null
  batchInfo.value = null
  try {
    const r = await runClaudeBatch({ limit: batchLimit.value, cohortId: cohortId.value })
    batchInfo.value = {
      judged: r.judged,
      skipped:
        r.skipped_already_judged + r.skipped_no_canonical + (r.skipped_not_open ?? 0),
    }
    await load()
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

// ─── Helpers UI ──────────────────────────────────────────────────────────

function verdictColor(v: ClaudeVerdict): string {
  switch (v) {
    case 'match': return 'var(--success)'
    case 'no_match': return 'var(--danger)'
    case 'uncertain': return 'var(--gold-600)'
    case 'error': return 'var(--ink-400)'
  }
}

function verdictLabel(v: ClaudeVerdict): string {
  switch (v) {
    case 'match': return 'match'
    case 'no_match': return 'no_match'
    case 'uncertain': return 'uncertain'
    case 'error': return 'error'
  }
}

function modelShort(m: string): string {
  // 'claude-sonnet-4-6' → 'sonnet 4.6'
  const match = /claude-(haiku|sonnet|opus)-(\d+)-(\d+)/.exec(m)
  if (!match) return m
  return `${match[1]} ${match[2]}.${match[3]}`
}
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
            CCProxy · acquittement Claude
          </h1>
          <p class="mt-0.5 text-xs" style="color: var(--ink-500);">
            Sonnet 4.6 propose, l'humain dispose — sélectionne puis acquitte ou rejette.
            <span
              v-if="cohortId"
              class="ml-1.5 rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider"
              style="background: color-mix(in srgb, var(--indigo-700) 12%, var(--surface)); color: var(--indigo-700);"
            >cohort · {{ cohortId }}</span>
          </p>
        </div>
      </div>

      <!-- Compteurs by_verdict -->
      <div
        v-if="status !== 'loading' && status !== 'error'"
        class="flex items-center gap-5 font-mono text-[11px] tabular-nums"
        style="color: var(--ink-500);"
      >
        <span>
          <span class="font-semibold" style="color: var(--success);">{{ byVerdict.match ?? 0 }}</span>
          <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">match</span>
        </span>
        <span>
          <span class="font-semibold" style="color: var(--danger);">{{ byVerdict.no_match ?? 0 }}</span>
          <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">no_match</span>
        </span>
        <span>
          <span class="font-semibold" style="color: var(--gold-600);">{{ byVerdict.uncertain ?? 0 }}</span>
          <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">uncertain</span>
        </span>
        <span class="opacity-50">·</span>
        <span>
          <span class="font-semibold" style="color: var(--ink);">{{ totalPending }}</span>
          <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">pending</span>
        </span>
      </div>
    </header>

    <!-- ═══ Sub-header : tabs + actions ═══ -->
    <div
      v-if="status === 'ready' || status === 'submitting' || status === 'batching'"
      class="flex flex-wrap items-center justify-between gap-3 border-b px-8 py-2.5"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <!-- Tabs -->
      <div class="flex items-center gap-3">
        <div
          class="inline-flex overflow-hidden rounded-md border"
          style="border-color: var(--surface-3); background: var(--surface-1);"
          role="tablist"
        >
          <button
            v-for="t in (['match', 'no_match', 'uncertain'] as ClaudeVerdict[])"
            :key="t"
            type="button"
            role="tab"
            :aria-selected="tab === t"
            class="tab-btn"
            :class="{ 'tab-active': tab === t }"
            :style="{
              '--tab-color': verdictColor(t),
            }"
            @click="switchTab(t)"
          >
            {{ verdictLabel(t) }}
            <span class="font-mono text-[10px] opacity-70 ml-1">
              {{ byVerdict[t] ?? 0 }}
            </span>
          </button>
        </div>

        <button
          v-if="total > 0"
          type="button"
          class="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] transition-colors"
          style="border-color: var(--surface-3); color: var(--ink-700); background: var(--surface-1);"
          @click="toggleAll"
        >
          <component :is="allSelected ? CheckSquare : Square" class="h-3 w-3" />
          {{ allSelected ? 'Tout désélectionner' : 'Tout sélectionner' }}
        </button>
      </div>

      <!-- Actions -->
      <div class="flex items-center gap-2">
        <div
          class="inline-flex items-center gap-1.5 rounded-md border pl-2.5 pr-1 py-0.5"
          style="border-color: var(--surface-3); background: var(--surface-1);"
        >
          <span class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-400);">
            batch
          </span>
          <input
            type="number"
            :value="batchLimit"
            min="1"
            max="500"
            step="10"
            class="batch-input font-mono text-[12px] font-semibold tabular-nums"
            :style="{ color: 'var(--indigo-700)' }"
            :disabled="status === 'batching' || status === 'submitting'"
            @change="onBatchLimitChange"
          />
          <span class="font-mono text-[9px]" style="color: var(--ink-400);">
            {{ batchEtaLabel }}
          </span>
          <button
            type="button"
            :disabled="status === 'batching' || status === 'submitting'"
            class="ml-1 inline-flex items-center gap-1 rounded-sm px-2 py-1 text-[11px] font-mono uppercase tracking-wider transition-colors"
            :style="{
              background: status === 'batching' ? 'var(--surface-3)' : 'var(--indigo-700)',
              color: status === 'batching' ? 'var(--ink-400)' : 'var(--surface)',
              cursor: status === 'batching' ? 'wait' : 'pointer',
            }"
            :title="`Lancer un batch de ${batchLimit} items`"
            @click="runBatch"
          >
            <Loader2 v-if="status === 'batching'" class="h-3 w-3 animate-spin" />
            <PlayCircle v-else class="h-3 w-3" />
            {{ status === 'batching' ? 'Batch…' : 'Run' }}
          </button>
        </div>

        <button
          v-if="canAck"
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
          @click="submit('ack')"
        >
          <Loader2 v-if="status === 'submitting'" class="h-3.5 w-3.5 animate-spin" />
          <Check v-else class="h-3.5 w-3.5" />
          Acquitter {{ selectedCount }}
        </button>

        <button
          type="button"
          :disabled="selectedCount === 0 || status === 'submitting'"
          class="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px] transition-all"
          :style="{
            'border-color': selectedCount === 0 ? 'var(--surface-3)' : 'var(--danger)',
            color: selectedCount === 0 ? 'var(--ink-400)' : 'var(--danger)',
            background: 'var(--surface-1)',
            cursor: selectedCount === 0 || status === 'submitting' ? 'not-allowed' : 'pointer',
          }"
          @click="submit('reject')"
        >
          <X class="h-3.5 w-3.5" />
          Rejeter {{ selectedCount }}
        </button>
      </div>
    </div>

    <!-- ═══ Feedback bar : ack/batch result ═══ -->
    <Transition name="feedback">
      <div
        v-if="lastAck"
        class="flex items-center gap-3 border-b px-8 py-2 text-[12px]"
        style="border-color: var(--surface-3); background: var(--success-soft); color: var(--ink-700);"
      >
        <Check class="h-4 w-4" :style="{ color: 'var(--success)' }" />
        <span>
          <strong>{{ lastAck.committed }}</strong> acquittés ·
          <strong>{{ lastAck.rejected }}</strong> rejetés.
        </span>
      </div>
    </Transition>
    <Transition name="feedback">
      <div
        v-if="batchInfo"
        class="flex items-center gap-3 border-b px-8 py-2 text-[12px]"
        style="border-color: var(--surface-3); background: var(--surface-1); color: var(--ink-700);"
      >
        <RotateCcw class="h-4 w-4" :style="{ color: 'var(--indigo-700)' }" />
        <span>
          Batch terminé · <strong>{{ batchInfo.judged }}</strong> jugés ·
          <strong>{{ batchInfo.skipped }}</strong> skipped.
        </span>
      </div>
    </Transition>

    <!-- ═══ Body ═══ -->
    <section class="flex-1 overflow-y-auto px-8 py-6">
      <!-- Loading -->
      <div
        v-if="status === 'loading'"
        class="flex h-full items-center justify-center"
      >
        <div class="flex flex-col items-center gap-3" style="color: var(--ink-500);">
          <Loader2 class="h-6 w-6 animate-spin" />
          <p class="text-sm">Chargement des verdicts en attente…</p>
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
        <p class="max-w-md text-center text-sm" style="color: var(--ink-500);">{{ error }}</p>
        <button
          type="button"
          class="mt-4 inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px]"
          style="border-color: var(--surface-3); color: var(--ink-700); background: var(--surface-1);"
          @click="load"
        >Réessayer</button>
      </div>

      <!-- Batching -->
      <div
        v-else-if="status === 'batching'"
        class="flex h-full flex-col items-center justify-center gap-4"
      >
        <Loader2 class="h-8 w-8 animate-spin" :style="{ color: 'var(--indigo-700)' }" />
        <p class="font-display text-2xl italic font-semibold" style="color: var(--indigo-700);">
          Claude examine la queue…
        </p>
        <p class="text-sm" style="color: var(--ink-500);">
          Sonnet 4.6 via ccproxy, ~3-5 s par item.
        </p>
      </div>

      <!-- Empty state -->
      <div
        v-else-if="items.length === 0"
        class="flex h-full flex-col items-center justify-center gap-4 text-center"
      >
        <p class="font-display text-3xl italic font-semibold" style="color: var(--indigo-700);">
          <template v-if="tab === 'match'">Aucun match en attente.</template>
          <template v-else-if="tab === 'no_match'">Aucun no_match en attente.</template>
          <template v-else>Aucun uncertain en attente.</template>
        </p>
        <p class="max-w-md text-sm" style="color: var(--ink-500);">
          <template v-if="totalPending === 0">
            La table verdicts Claude est vide. Lance un batch pour judger
            des items partial/divergent de la queue.
          </template>
          <template v-else>
            Aucun verdict dans cette catégorie — change d'onglet pour voir les autres.
          </template>
        </p>
        <button
          v-if="totalPending === 0"
          type="button"
          class="mt-2 inline-flex items-center gap-2 rounded-md px-4 py-2 text-[13px] font-semibold transition-all"
          style="background: var(--indigo-700); color: var(--surface);"
          @click="runBatch"
        >
          <PlayCircle class="h-4 w-4" />
          Lancer un batch de {{ batchLimit }} items
        </button>
        <button
          v-else
          type="button"
          class="mt-2 inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-mono uppercase tracking-wider transition-colors"
          style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface-1);"
          @click="runBatch"
        >
          <PlayCircle class="h-3 w-3" />
          Lancer un batch ({{ batchLimit }})
        </button>
      </div>

      <!-- Grid -->
      <div v-else class="grid gap-4 lg:grid-cols-2">
        <ReviewCard
          v-for="item in items"
          :key="item.review_id"
          :crop-url="item.crop_url"
          :canonical-url="item.target_thumb_url"
          :eurio-id="item.target_eurio_id"
          :target-label="item.target_label"
          :listing-title="item.listing_title"
          :listing-url="item.listing_url"
          :source="item.source"
          :selected="selected.has(item.review_id)"
          :accent-color="verdictColor(item.verdict)"
          @toggle="toggle(item.review_id)"
        >
          <template #metrics>
            <div class="flex flex-wrap items-center gap-2 text-[10px]">
              <span
                class="rounded-sm px-1.5 py-0.5 font-mono uppercase tracking-wider"
                :style="{
                  background: verdictColor(item.verdict),
                  color: 'var(--surface)',
                }"
              >{{ verdictLabel(item.verdict) }}</span>
              <span v-if="item.confidence !== null" class="font-mono tabular-nums" style="color: var(--ink-500);">
                <span style="color: var(--ink-400);">conf</span>
                <span class="ml-1 font-semibold" style="color: var(--ink-700);">{{ item.confidence.toFixed(2) }}</span>
              </span>
              <span v-if="item.face_detected" class="font-mono" style="color: var(--ink-500);">
                <span style="color: var(--ink-400);">face</span>
                <span class="ml-1 font-semibold" style="color: var(--ink-700);">{{ item.face_detected }}</span>
              </span>
              <span class="ml-auto font-mono italic" style="color: var(--ink-400);">
                {{ modelShort(item.model) }}
              </span>
            </div>
          </template>
        </ReviewCard>
      </div>
    </section>
  </div>
</template>

<style scoped>
.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 12px;
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-500);
  background: transparent;
  cursor: pointer;
  transition: all 140ms var(--ease-out);
  border: 0;
}
.tab-btn:hover { color: var(--ink-700); }
.tab-btn + .tab-btn { border-left: 0.5px solid var(--surface-3); }
.tab-active {
  color: var(--surface);
  background: var(--tab-color, var(--ink));
}

.batch-input {
  width: 48px;
  padding: 2px 4px;
  background: var(--surface);
  border: 1px solid var(--surface-3);
  border-radius: 3px;
  text-align: center;
}
.batch-input:focus {
  outline: 1px solid var(--indigo-700);
  outline-offset: 0;
}
.batch-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
/* Remove number spinner arrows (cleaner UI). */
.batch-input::-webkit-outer-spin-button,
.batch-input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
.batch-input { -moz-appearance: textfield; }

.feedback-enter-active,
.feedback-leave-active {
  transition: max-height 220ms var(--ease-out), opacity 220ms var(--ease-out);
  overflow: hidden;
}
.feedback-enter-from, .feedback-leave-to {
  max-height: 0;
  opacity: 0;
}
.feedback-enter-to, .feedback-leave-from {
  max-height: 40px;
  opacity: 1;
}
</style>
