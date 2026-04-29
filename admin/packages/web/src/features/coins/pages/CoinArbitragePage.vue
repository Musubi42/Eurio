<script setup lang="ts">
import { firstImageUrl } from '@/shared/utils/coin-images'
import { CheckCircle2, ChevronLeft, ChevronRight, ImageOff, Loader2, Scale, Upload } from 'lucide-vue-next'
import { onMounted } from 'vue'
import { useArbitrage } from '../composables/useArbitrage'

const {
  loading,
  syncing,
  syncError,
  currentIndex,
  currentEntry,
  total,
  resolved,
  pendingSync,
  syncedCount,
  loadData,
  getDecision,
  assign,
  markNone,
  skip,
  syncToSupabase,
  getCoin,
} = useArbitrage()

onMounted(() => loadData())

function prev() {
  if (currentIndex.value > 0) currentIndex.value--
}

function next() {
  if (currentIndex.value < total.value - 1) currentIndex.value++
}

function formatScore(score: number): string {
  return (score * 100).toFixed(0) + '%'
}
</script>

<template>
  <div class="p-8 max-w-5xl mx-auto">
    <!-- Header -->
    <div class="mb-6 flex items-start justify-between">
      <div>
        <div class="flex items-center gap-2">
          <Scale class="h-5 w-5" style="color: var(--indigo-700);" />
          <h1 class="font-display text-2xl italic font-semibold"
              style="color: var(--indigo-700);">
            Arbitrage Numista
          </h1>
        </div>
        <p class="mt-1 text-sm" style="color: var(--ink-500);">
          {{ resolved }}/{{ total }} résolus
          <template v-if="syncedCount > 0">
            · {{ syncedCount }} synced
          </template>
          <template v-if="pendingSync > 0">
            · <strong style="color: var(--warning);">{{ pendingSync }} à sync</strong>
          </template>
        </p>
      </div>

      <button
        :disabled="syncing || pendingSync === 0"
        class="flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors disabled:opacity-40"
        style="background: var(--indigo-700); color: white;"
        @click="syncToSupabase"
      >
        <Loader2 v-if="syncing" class="h-4 w-4 animate-spin" />
        <Upload v-else class="h-4 w-4" />
        Sync Supabase
        <span v-if="pendingSync > 0"
              class="rounded-full px-1.5 py-0.5 text-[10px] font-mono"
              style="background: rgba(255,255,255,0.2);">
          {{ pendingSync }}
        </span>
      </button>
    </div>

    <!-- Sync error -->
    <div v-if="syncError"
         class="mb-4 rounded-md px-4 py-3 text-sm"
         style="background: var(--danger-soft); color: var(--danger);">
      {{ syncError }}
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex flex-col items-center justify-center py-24 gap-3">
      <Loader2 class="h-8 w-8 animate-spin" style="color: var(--indigo-700);" />
      <p class="text-sm" style="color: var(--ink-400);">Chargement des candidats…</p>
    </div>

    <!-- Main content -->
    <template v-else-if="currentEntry">
      <!-- Progress bar -->
      <div class="mb-6 flex items-center gap-3">
        <div class="flex-1 h-1.5 rounded-full overflow-hidden" style="background: var(--surface-2);">
          <div
            class="h-full rounded-full transition-all duration-300"
            style="background: var(--indigo-700);"
            :style="{ width: `${(resolved / total) * 100}%` }"
          />
        </div>
        <span class="text-xs font-mono shrink-0" style="color: var(--ink-400);">
          {{ currentIndex + 1 }}/{{ total }}
        </span>
      </div>

      <!-- Synced overlay indicator -->
      <div v-if="getDecision(currentEntry.numista_id).synced"
           class="mb-4 flex items-center gap-2 rounded-md px-4 py-2 text-sm"
           style="background: rgba(47, 169, 113, 0.1); color: var(--success);">
        <CheckCircle2 class="h-4 w-4" />
        Déjà synchronisé dans Supabase
      </div>

      <!-- ROW 1 : Source Numista -->
      <div class="rounded-lg border p-5 mb-4"
           style="border-color: var(--surface-3); background: var(--surface);">
        <p class="text-[10px] uppercase tracking-widest font-medium mb-3"
           style="color: var(--ink-400);">
          Source Numista
        </p>
        <div class="flex gap-5">
          <!-- Source image from ML API -->
          <div class="w-28 h-28 shrink-0 rounded-lg overflow-hidden flex items-center justify-center"
               style="background: var(--surface-1);">
            <img
              :src="`http://127.0.0.1:8042/images/${currentEntry.numista_id}/source`"
              :alt="currentEntry.numista_name"
              class="w-full h-full object-cover"
              @error="(e) => (e.target as HTMLImageElement).style.display = 'none'"
            />
          </div>
          <!-- Data -->
          <div class="flex-1 min-w-0">
            <h2 class="text-lg font-semibold leading-snug" style="color: var(--ink);">
              {{ currentEntry.numista_name }}
            </h2>
            <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm" style="color: var(--ink-500);">
              <span>
                <span class="font-medium" style="color: var(--ink-400);">Pays</span>
                {{ currentEntry.country }}
              </span>
              <span>
                <span class="font-medium" style="color: var(--ink-400);">Année</span>
                {{ currentEntry.year }}
              </span>
              <span>
                <span class="font-medium" style="color: var(--ink-400);">Numista ID</span>
                <span class="font-mono">{{ currentEntry.numista_id }}</span>
              </span>
            </div>
            <p v-if="currentEntry.numista_theme" class="mt-2 text-sm italic" style="color: var(--ink-400);">
              « {{ currentEntry.numista_theme }} »
            </p>
          </div>
        </div>
      </div>

      <!-- ROW 2 : Candidats Eurio -->
      <div class="grid grid-cols-2 gap-4 mb-6">
        <button
          v-for="(candidate, idx) in currentEntry.candidates"
          :key="candidate.eurio_id"
          class="rounded-lg border-2 p-4 text-left transition-all"
          :style="{
            borderColor:
              getDecision(currentEntry.numista_id).status === 'assigned'
              && getDecision(currentEntry.numista_id).chosen_eurio_id === candidate.eurio_id
                ? 'var(--gold)'
                : 'var(--surface-3)',
            background:
              getDecision(currentEntry.numista_id).status === 'assigned'
              && getDecision(currentEntry.numista_id).chosen_eurio_id === candidate.eurio_id
                ? 'var(--gold-soft)'
                : 'var(--surface)',
            boxShadow:
              getDecision(currentEntry.numista_id).status === 'assigned'
              && getDecision(currentEntry.numista_id).chosen_eurio_id === candidate.eurio_id
                ? 'var(--shadow-gold)'
                : 'var(--shadow-sm)',
          }"
          @click="assign(currentEntry.numista_id, candidate.eurio_id)"
        >
          <p class="text-[10px] uppercase tracking-widest font-medium mb-3"
             style="color: var(--ink-400);">
            Candidat {{ idx + 1 }}
            <span v-if="getDecision(currentEntry.numista_id).status === 'assigned'
                        && getDecision(currentEntry.numista_id).chosen_eurio_id === candidate.eurio_id"
                  class="ml-1.5 inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[9px] font-medium"
                  style="background: var(--gold); color: white;">
              <CheckCircle2 class="h-3 w-3" />
              choisi
            </span>
          </p>

          <!-- Coin image -->
          <div class="w-full aspect-square rounded-lg mb-3 flex items-center justify-center overflow-hidden"
               style="background: var(--surface-1);">
            <img
              v-if="getCoin(candidate.eurio_id) && firstImageUrl(getCoin(candidate.eurio_id)!)"
              :src="firstImageUrl(getCoin(candidate.eurio_id)!)!"
              :alt="candidate.eurio_id"
              class="h-full w-full object-contain p-3"
              loading="lazy"
            />
            <div v-else class="flex flex-col items-center gap-1" style="color: var(--ink-300);">
              <ImageOff class="h-6 w-6" />
              <span class="text-[10px] uppercase tracking-wider">pas d'image</span>
            </div>
          </div>

          <!-- Coin data -->
          <p class="text-xs font-mono break-all leading-snug" style="color: var(--ink);">
            {{ candidate.eurio_id }}
          </p>
          <p v-if="getCoin(candidate.eurio_id)?.theme"
             class="mt-1 text-sm leading-snug" style="color: var(--ink-500);">
            {{ getCoin(candidate.eurio_id)!.theme }}
          </p>
          <div class="mt-2 flex items-center gap-2">
            <span class="rounded-full px-2 py-0.5 text-[10px] font-mono font-medium"
                  :style="{
                    background: candidate.score >= 0.5 ? 'rgba(47,169,113,0.12)' : 'var(--surface-1)',
                    color: candidate.score >= 0.5 ? 'var(--success)' : 'var(--ink-400)',
                  }">
              score {{ formatScore(candidate.score) }}
            </span>
            <span v-if="getCoin(candidate.eurio_id)?.cross_refs?.numista_id"
                  class="rounded-full px-2 py-0.5 text-[10px] font-mono font-medium"
                  style="background: #059669; color: white;">
              N{{ getCoin(candidate.eurio_id)!.cross_refs.numista_id }}
            </span>
          </div>
        </button>
      </div>

      <!-- Actions row -->
      <div class="flex items-center justify-between">
        <div class="flex gap-2">
          <!-- Aucun -->
          <button
            class="rounded-md border px-3 py-1.5 text-xs font-medium transition-colors"
            :style="{
              background: getDecision(currentEntry.numista_id).status === 'none'
                ? 'var(--danger-soft)' : 'var(--surface)',
              color: getDecision(currentEntry.numista_id).status === 'none'
                ? 'var(--danger)' : 'var(--ink-500)',
              borderColor: getDecision(currentEntry.numista_id).status === 'none'
                ? 'var(--danger)' : 'var(--surface-3)',
            }"
            @click="markNone(currentEntry.numista_id)"
          >
            Aucun
          </button>
          <!-- Passer -->
          <button
            class="rounded-md border px-3 py-1.5 text-xs font-medium transition-colors"
            :style="{
              background: getDecision(currentEntry.numista_id).status === 'skipped'
                ? 'var(--warning-soft)' : 'var(--surface)',
              color: getDecision(currentEntry.numista_id).status === 'skipped'
                ? 'var(--warning)' : 'var(--ink-500)',
              borderColor: getDecision(currentEntry.numista_id).status === 'skipped'
                ? 'var(--warning)' : 'var(--surface-3)',
            }"
            @click="skip(currentEntry.numista_id)"
          >
            Passer
          </button>
        </div>

        <!-- Navigation -->
        <div class="flex items-center gap-2">
          <button
            :disabled="currentIndex === 0"
            class="flex items-center gap-1 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-30"
            style="border-color: var(--surface-3); color: var(--ink-500);"
            @click="prev"
          >
            <ChevronLeft class="h-3.5 w-3.5" />
            Préc.
          </button>
          <button
            :disabled="currentIndex === total - 1"
            class="flex items-center gap-1 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-30"
            style="border-color: var(--surface-3); color: var(--ink-500);"
            @click="next"
          >
            Suiv.
            <ChevronRight class="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
