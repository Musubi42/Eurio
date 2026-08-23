<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import {
  cropSrc,
  usePeerArbitrationApi,
  type PeerDecision,
  type ReviewerStat,
} from '@/features/review/composables/usePeerArbitrationApi'

const api = usePeerArbitrationApi()

const items = ref<PeerDecision[]>([])
const reviewers = ref<ReviewerStat[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref<Set<string>>(new Set())

const concordCount = computed(() => items.value.filter(i => i.concords).length)

async function load() {
  loading.value = true
  error.value = null
  try {
    const [page, stats] = await Promise.all([api.fetchPending(), api.fetchReviewerStats()])
    items.value = page.items
    reviewers.value = stats
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function setBusy(id: string, on: boolean) {
  const next = new Set(busy.value)
  if (on) next.add(id)
  else next.delete(id)
  busy.value = next
}

async function approve(item: PeerDecision) {
  setBusy(item.id, true)
  try {
    await api.approve(item.id)
    items.value = items.value.filter(i => i.id !== item.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    setBusy(item.id, false)
  }
}

async function reject(item: PeerDecision) {
  setBusy(item.id, true)
  try {
    await api.reject(item.id)
    items.value = items.value.filter(i => i.id !== item.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    setBusy(item.id, false)
  }
}

async function approveAllConcordant() {
  const concordant = items.value.filter(i => i.concords)
  for (const item of concordant) {
    await approve(item)
  }
}

onMounted(load)
</script>

<template>
  <div class="p-6 space-y-6">
    <header class="flex items-center justify-between">
      <div>
        <h1 class="text-xl font-semibold">Arbitrage pairs</h1>
        <p class="text-sm opacity-70">
          Décisions des amis reviewers à valider avant promotion au canonique.
        </p>
      </div>
      <div class="flex gap-2">
        <button
          class="px-3 py-1.5 rounded border text-sm disabled:opacity-40"
          :disabled="concordCount === 0"
          @click="approveAllConcordant"
        >
          Approuver concordants ({{ concordCount }})
        </button>
        <button class="px-3 py-1.5 rounded border text-sm" @click="load">Rafraîchir</button>
      </div>
    </header>

    <!-- Qualité par reviewer -->
    <section v-if="reviewers.length" class="flex flex-wrap gap-3">
      <div
        v-for="r in reviewers"
        :key="r.reviewer_token"
        class="px-3 py-2 rounded border text-sm"
      >
        <span class="font-medium">{{ r.reviewer_name }}</span>
        <span class="opacity-70">
          · {{ r.total }} total · {{ r.approved }} ✓ · {{ r.rejected }} ✗ ·
          {{ r.pending }} en attente
        </span>
      </div>
    </section>

    <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
    <p v-if="loading" class="text-sm opacity-70">Chargement…</p>
    <p v-else-if="!items.length" class="text-sm opacity-70">
      Rien à arbitrer. Les décisions des amis arrivent ici directement — le pont
      <code>publish</code>/<code>reconcile</code> n'existe plus (D1).
      <RouterLink to="/review/arbitrage" class="underline">Vue en lot</RouterLink>.
    </p>

    <!-- Grille d'arbitrage -->
    <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      <article
        v-for="item in items"
        :key="item.id"
        class="rounded border overflow-hidden flex flex-col"
      >
        <div class="aspect-square bg-black/5 flex items-center justify-center">
          <img
            v-if="item.crop_url"
            :src="cropSrc(item.crop_url)"
            class="max-h-full max-w-full object-contain"
            alt="crop"
          />
          <span v-else class="text-xs opacity-50">pas d'image</span>
        </div>
        <div class="p-3 space-y-2 text-sm flex-1">
          <div class="flex items-center justify-between">
            <span class="font-medium">{{ item.reviewer_name }}</span>
            <span
              class="text-xs px-1.5 py-0.5 rounded"
              :class="item.action === 'accept' ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'"
            >
              {{ item.action }}
            </span>
          </div>

          <div v-if="item.action === 'accept'">
            <div class="font-medium">{{ item.decided_label ?? item.decided_eurio_id }}</div>
            <div
              class="text-xs"
              :class="item.concords ? 'text-emerald-700' : 'text-amber-700'"
            >
              {{ item.concords ? '✓ concorde Dino' : '⚠ diverge du Dino' }}
              <template v-if="!item.concords && item.dino_top1_label">
                · Dino : {{ item.dino_top1_label }}
              </template>
            </div>
          </div>
          <div v-else class="text-xs opacity-70">
            Rejet{{ item.quality_reason ? ` · ${item.quality_reason}` : '' }}
          </div>

          <p v-if="item.notes" class="text-xs italic opacity-70">« {{ item.notes }} »</p>
        </div>
        <div class="p-3 pt-0 flex gap-2">
          <button
            class="flex-1 px-2 py-1.5 rounded bg-emerald-600 text-white text-sm disabled:opacity-40"
            :disabled="busy.has(item.id)"
            @click="approve(item)"
          >
            Approuver
          </button>
          <button
            class="flex-1 px-2 py-1.5 rounded border text-sm disabled:opacity-40"
            :disabled="busy.has(item.id)"
            @click="reject(item)"
          >
            Rejeter
          </button>
        </div>
      </article>
    </section>
  </div>
</template>
