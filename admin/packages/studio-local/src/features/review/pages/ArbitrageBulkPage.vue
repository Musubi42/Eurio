<script setup lang="ts">
// La vue bulk d'arbitrage — la seconde moitié de la boucle de review
// collaborative (lot 8). Un ami tranche, sa décision part en quarantaine
// (`peer_review_decisions`, D7) ; ici l'arbitre relit ce qu'il a produit et
// approuve en un geste.
//
// C'est `AutoAcceptReviewPage` avec une AUTRE SOURCE : même grille
// `lg:grid-cols-2` de `ReviewCard` (crop ↔ canonique de la classe décidée),
// même garde `BULK_CONFIRM_THRESHOLD`, plus trois choses qui lui sont propres :
// des onglets par personne, un scroll infini, et le tri de D8.
//
// ─── Le tri, et pourquoi il n'est pas cosmétique (D8) ───────────────────────
// Tout coché par défaut SAUF les désaccords avec DINO, placés en tête et NON
// cochés. « Tout validé par défaut » sur un scroll infini est un tampon en
// caoutchouc : le geste devient « je scrolle vite et je clique OK ». Or 62,6 %
// des décisions rejoignent DINO top-1 (67,3 % avec le re-rank pays) : les deux
// tiers concordants peuvent défiler vite, et le tiers restant — celui où
// l'humain contredit la machine, donc celui où il y a quelque chose à
// apprendre — exige un geste positif.
//
// Le tri est fait par le SERVEUR (`ORDER BY concords`), pas ici : trié côté
// client, il ne survivrait pas à la pagination — la page 2 rejouerait des
// concordances déjà vues et laisserait des désaccords derrière.

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowLeft,
  Check,
  CheckSquare,
  Loader2,
  Square,
  X,
} from 'lucide-vue-next'

import ReviewCard from '../components/ReviewCard.vue'
import {
  usePeerArbitrationApi,
  type BatchResult,
  type PeerDecision,
  type ReviewerStat,
} from '../composables/usePeerArbitrationApi'

type Status = 'loading' | 'ready' | 'submitting' | 'error'

const router = useRouter()
const api = usePeerArbitrationApi()

const PAGE_SIZE = 60
// Même garde-fou que l'auto-accept : au-delà, le bouton demande un second clic
// dans une fenêtre de 4 s. Une écriture massive ne doit jamais tenir à un clic.
const BULK_CONFIRM_THRESHOLD = 50
const BULK_CONFIRM_WINDOW_MS = 4000

const status = ref<Status>('loading')
const error = ref<string | null>(null)
const items = ref<PeerDecision[]>([])
const total = ref(0)
const loadingMore = ref(false)
const reviewers = ref<ReviewerStat[]>([])
const activeReviewer = ref<string | null>(null)
const selected = ref<Set<string>>(new Set())
const lastResult = ref<{ verb: 'approuvées' | 'rejetées'; result: BatchResult } | null>(null)

const selectedCount = computed(() => selected.value.size)
const allSelected = computed(
  () => items.value.length > 0 && selectedCount.value === items.value.length,
)
const hasMore = computed(() => items.value.length < total.value)
/** Les onglets : seules les personnes qui ont quelque chose en attente. */
const tabs = computed(() => reviewers.value.filter((r) => r.pending > 0))

function labelDino(it: PeerDecision): { text: string; color: string } {
  if (it.dino_state === 'concords') return { text: 'DINO d\'accord', color: 'var(--success)' }
  if (it.dino_state === 'disagrees') return { text: 'DINO en désaccord', color: 'var(--danger)' }
  return { text: 'DINO muet', color: 'var(--ink-400)' }
}

/** Cochée par défaut ⇔ DINO confirme. Le reste demande un geste (D8). */
function defaultSelected(it: PeerDecision): boolean {
  return it.dino_state === 'concords'
}

function toggle(id: string) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

function toggleAll() {
  selected.value = allSelected.value
    ? new Set()
    : new Set(items.value.map((it) => it.id))
}

async function load(reset = true) {
  if (reset) {
    status.value = 'loading'
    items.value = []
    selected.value = new Set()
    lastResult.value = null
  }
  error.value = null
  try {
    const [page, stats] = await Promise.all([
      api.fetchPending({
        limit: PAGE_SIZE,
        offset: reset ? 0 : items.value.length,
        reviewer: activeReviewer.value,
      }),
      reset ? api.fetchReviewerStats() : Promise.resolve(reviewers.value),
    ])
    reviewers.value = stats
    total.value = page.total
    items.value = reset ? page.items : [...items.value, ...page.items]
    const next = new Set(selected.value)
    for (const it of page.items) if (defaultSelected(it)) next.add(it.id)
    selected.value = next
    status.value = 'ready'
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
    status.value = 'error'
  }
}

async function loadMore() {
  if (loadingMore.value || !hasMore.value || status.value !== 'ready') return
  loadingMore.value = true
  try {
    await load(false)
  } finally {
    loadingMore.value = false
  }
}

// Scroll infini : une sentinelle en bas de grille. `rootMargin` généreux pour
// que la page suivante arrive avant que l'arbitre atteigne le vide.
const sentinel = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null

onMounted(() => {
  void load()
  observer = new IntersectionObserver(
    (entries) => { if (entries.some((e) => e.isIntersecting)) void loadMore() },
    { rootMargin: '600px' },
  )
  watch(sentinel, (el, prev) => {
    if (prev) observer?.unobserve(prev)
    if (el) observer?.observe(el)
  }, { immediate: true })
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  if (confirmTimer) clearTimeout(confirmTimer)
})

function selectReviewer(token: string | null) {
  if (activeReviewer.value === token) return
  activeReviewer.value = token
  void load()
}

// ─── Confirmation à deux clics ─────────────────────────────────────────────

const confirmArmed = ref<'approve' | 'reject' | null>(null)
let confirmTimer: ReturnType<typeof setTimeout> | null = null

function armConfirm(which: 'approve' | 'reject') {
  confirmArmed.value = which
  if (confirmTimer) clearTimeout(confirmTimer)
  confirmTimer = setTimeout(() => {
    confirmArmed.value = null
    confirmTimer = null
  }, BULK_CONFIRM_WINDOW_MS)
}

function disarmConfirm() {
  if (confirmTimer) clearTimeout(confirmTimer)
  confirmTimer = null
  confirmArmed.value = null
}

async function submit(which: 'approve' | 'reject') {
  if (selectedCount.value === 0 || status.value === 'submitting') return
  if (selectedCount.value >= BULK_CONFIRM_THRESHOLD && confirmArmed.value !== which) {
    armConfirm(which)
    return
  }
  disarmConfirm()
  status.value = 'submitting'
  error.value = null
  const ids = Array.from(selected.value)
  try {
    const result = which === 'approve'
      ? await api.approveBatch(ids)
      : await api.rejectBatch(ids)
    lastResult.value = { verb: which === 'approve' ? 'approuvées' : 'rejetées', result }
    // Ne retirer QUE ce que le serveur dit avoir traité : un item en échec
    // (409 « déjà arbitrée ») doit rester visible avec sa raison, sinon on
    // croit avoir tranché ce qui ne l'a pas été.
    const done = new Set([
      ...(result.approved ?? []),
      ...(result.rejected ?? []),
      ...(result.superseded ?? []),
    ])
    items.value = items.value.filter((it) => !done.has(it.id))
    total.value = Math.max(0, total.value - done.size)
    const next = new Set(selected.value)
    for (const id of done) next.delete(id)
    selected.value = next
    reviewers.value = await api.fetchReviewerStats()
    status.value = 'ready'
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
    status.value = 'ready'
  }
}

function backToCabinet() {
  void router.push('/review')
}

function shortName(r: ReviewerStat): string {
  return r.reviewer_name || r.reviewer_token.slice(0, 8)
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
          <h1 class="font-display text-lg italic font-semibold" style="color: var(--indigo-700);">
            Arbitrage · décisions des amis
          </h1>
          <p class="mt-0.5 text-xs" style="color: var(--ink-500);">
            Les désaccords avec DINO sont en tête et non cochés — le reste est coché.
          </p>
        </div>
      </div>

      <div
        v-if="status !== 'loading' && status !== 'error'"
        class="flex items-center gap-5 font-mono text-[11px] tabular-nums"
        style="color: var(--ink-500);"
      >
        <span>
          <span class="font-semibold" style="color: var(--indigo-700);">{{ items.length }}</span>
          <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">chargées</span>
        </span>
        <span class="opacity-50">·</span>
        <span>
          <span style="color: var(--ink-400);">sur</span>
          <span class="ml-1 font-semibold" style="color: var(--ink);">{{ total }}</span>
          <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">en attente</span>
        </span>
      </div>
    </header>

    <!-- ═══ Onglets par personne ═══ -->
    <div
      v-if="tabs.length > 1"
      class="flex flex-wrap items-center gap-2 border-b px-8 py-2"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <button
        type="button"
        class="tab"
        :class="{ 'tab-active': activeReviewer === null }"
        @click="selectReviewer(null)"
      >
        Tous
        <span class="tab-count">{{ tabs.reduce((n, r) => n + r.pending, 0) }}</span>
      </button>
      <button
        v-for="r in tabs"
        :key="r.reviewer_token"
        type="button"
        class="tab"
        :class="{ 'tab-active': activeReviewer === r.reviewer_token }"
        :title="`${r.approved} approuvées · ${r.rejected} rejetées sur ${r.total}`"
        @click="selectReviewer(r.reviewer_token)"
      >
        {{ shortName(r) }}
        <span class="tab-count">{{ r.pending }}</span>
      </button>
    </div>

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

      <div class="flex items-center gap-2">
        <button
          type="button"
          :disabled="selectedCount === 0 || status === 'submitting'"
          class="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px] transition-colors disabled:cursor-not-allowed disabled:opacity-50"
          style="border-color: var(--surface-3); color: var(--danger); background: var(--surface-1);"
          @click="submit('reject')"
          @mouseleave="disarmConfirm"
        >
          <X class="h-3.5 w-3.5" />
          <template v-if="confirmArmed === 'reject'">Confirmer le rejet de {{ selectedCount }} ?</template>
          <template v-else>Rejeter {{ selectedCount }}</template>
        </button>

        <button
          type="button"
          :disabled="selectedCount === 0 || status === 'submitting'"
          class="inline-flex items-center gap-2 rounded-md px-4 py-1.5 text-[12px] font-semibold transition-all"
          :style="{
            background: selectedCount === 0 || status === 'submitting'
              ? 'var(--surface-3)'
              : confirmArmed === 'approve' ? 'var(--danger)' : 'var(--success)',
            color: selectedCount === 0 || status === 'submitting' ? 'var(--ink-400)' : 'var(--surface)',
            cursor: selectedCount === 0 || status === 'submitting' ? 'not-allowed' : 'pointer',
          }"
          @click="submit('approve')"
          @mouseleave="disarmConfirm"
        >
          <Loader2 v-if="status === 'submitting'" class="h-3.5 w-3.5 animate-spin" />
          <Check v-else class="h-3.5 w-3.5" />
          <template v-if="confirmArmed === 'approve'">Confirmer {{ selectedCount }} décisions ?</template>
          <template v-else>
            Approuver {{ selectedCount }} décision{{ selectedCount > 1 ? 's' : '' }}
          </template>
        </button>
      </div>
    </div>

    <!-- ═══ Compte-rendu du dernier lot ═══ -->
    <div
      v-if="lastResult"
      class="border-b px-8 py-2 text-[12px]"
      style="border-color: var(--surface-3); background: var(--surface-1); color: var(--ink-700);"
    >
      <span class="font-semibold">
        {{ (lastResult.result.approved ?? lastResult.result.rejected ?? []).length }}
        {{ lastResult.verb }}.
      </span>
      <span v-if="lastResult.result.superseded?.length" class="ml-2" style="color: var(--gold-700);">
        {{ lastResult.result.superseded.length }} supersédée(s) — une voie locale avait déjà tranché.
      </span>
      <span v-if="lastResult.result.failed.length" class="ml-2" style="color: var(--danger);">
        {{ lastResult.result.failed.length }} en échec :
        {{ lastResult.result.failed.map((f) => f.detail).join(' · ') }}
      </span>
    </div>

    <!-- ═══ Body ═══ -->
    <section class="flex-1 overflow-y-auto px-8 py-6">
      <div v-if="status === 'loading'" class="flex h-full items-center justify-center">
        <div class="flex flex-col items-center gap-3" style="color: var(--ink-500);">
          <Loader2 class="h-6 w-6 animate-spin" />
          <p class="text-sm">Chargement des décisions…</p>
        </div>
      </div>

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
          @click="load()"
        >
          Réessayer
        </button>
      </div>

      <div
        v-else-if="items.length === 0"
        class="flex h-full flex-col items-center justify-center gap-3 text-center"
      >
        <p class="font-display text-3xl italic font-semibold" style="color: var(--indigo-700);">
          Rien à arbitrer.
        </p>
        <p class="max-w-md text-sm" style="color: var(--ink-500);">
          Aucune décision en quarantaine. Elle arrive dès qu'un ami tranche un crop —
          sa décision attend ici sans toucher le canonique.
        </p>
      </div>

      <template v-else>
        <p v-if="error" class="mb-3 text-[12px]" style="color: var(--danger);">{{ error }}</p>

        <div class="grid gap-4 lg:grid-cols-2">
          <ReviewCard
            v-for="item in items"
            :key="item.id"
            :crop-url="item.crop_url ?? ''"
            :canonical-url="item.canonical_url"
            :eurio-id="item.decided_eurio_id ?? '—'"
            :target-label="item.decided_label ?? item.action"
            :listing-title="item.listing_title"
            :listing-url="item.listing_url"
            :source="item.source"
            :selected="selected.has(item.id)"
            :accent-color="item.dino_state === 'concords' ? 'var(--success)' : 'var(--gold-600)'"
            @toggle="toggle(item.id)"
          >
            <template #metrics>
              <div
                class="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px]"
                style="color: var(--ink-500);"
              >
                <span :style="{ color: labelDino(item).color }">{{ labelDino(item).text }}</span>
                <span
                  v-if="item.dino_state === 'disagrees'"
                  :title="item.dino_top1_eurio_id ?? ''"
                  class="truncate"
                >
                  DINO : {{ item.dino_top1_label }}
                </span>
                <span style="color: var(--ink-400);">
                  {{ item.reviewer_name }} · {{ item.action }}
                </span>
              </div>
            </template>
          </ReviewCard>
        </div>

        <!-- Sentinelle du scroll infini -->
        <div ref="sentinel" class="h-10"></div>
        <p
          v-if="loadingMore"
          class="py-2 text-center font-mono text-[11px]"
          style="color: var(--ink-400);"
        >
          Chargement de la suite…
        </p>
        <p
          v-else-if="!hasMore"
          class="py-2 text-center font-mono text-[11px]"
          style="color: var(--ink-400);"
        >
          Fin de la file.
        </p>
      </template>
    </section>
  </div>
</template>

<style scoped>
.tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--surface-3);
  border-radius: 999px;
  padding: 3px 10px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-500);
  background: var(--surface-1);
}
.tab:hover { border-color: var(--ink-300); color: var(--ink-700); }
.tab-active {
  border-color: var(--indigo-700);
  color: var(--indigo-700);
  background: var(--surface);
}
.tab-count {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--ink-700);
}
</style>
