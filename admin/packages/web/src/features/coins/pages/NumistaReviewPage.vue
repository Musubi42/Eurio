<script setup lang="ts">
import { useNumistaReview, type ReviewItem } from '../composables/useNumistaReview'
import { Check, CircleAlert, SkipForward, WifiOff } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'

const { stats, loading, error, saving, fetchQueue, resolve, pending, resolved, skipped } = useNumistaReview()

type Tab = 'pending' | 'resolved' | 'skipped'
const activeTab = ref<Tab>('pending')
const selected = ref<ReviewItem | null>(null)

const tabItems = computed(() => {
  if (activeTab.value === 'pending') return pending.value
  if (activeTab.value === 'resolved') return resolved.value
  return skipped.value
})

function selectItem(item: ReviewItem) {
  selected.value = item
}

function isSelected(item: ReviewItem) {
  return selected.value?.numista_id === item.numista_id
}

async function pick(eurio_id: string | null) {
  if (!selected.value || saving.value) return
  const numista_id = selected.value.numista_id
  await resolve(numista_id, eurio_id)
  // Auto-advance to next pending
  const nextPending = pending.value.find(i => i.numista_id !== numista_id)
  selected.value = nextPending ?? null
}

function countryFlag(code: string) {
  return code.toUpperCase().replace(/./g, c =>
    String.fromCodePoint(c.charCodeAt(0) + 127397)
  )
}

onMounted(() => fetchQueue())
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- Header -->
    <div class="flex items-center justify-between border-b px-6 py-4"
         style="border-color: var(--border);">
      <div class="flex items-center gap-3">
        <CircleAlert class="h-5 w-5" style="color: var(--gold);" />
        <h1 class="text-lg font-semibold" style="color: var(--ink);">Revue Numista</h1>
        <span class="text-sm" style="color: var(--ink-light);">
          Résolution manuelle des correspondances ambiguës
        </span>
      </div>
      <div v-if="!loading && !error" class="flex items-center gap-4 text-sm" style="color: var(--ink-light);">
        <span><span class="font-semibold" style="color: var(--ink);">{{ stats.pending }}</span> en attente</span>
        <span><span class="font-semibold" style="color: var(--ink);">{{ stats.resolved }}</span> résolues</span>
        <span><span class="font-semibold" style="color: var(--ink);">{{ stats.skipped }}</span> ignorées</span>
      </div>
    </div>

    <!-- API offline -->
    <div v-if="error" class="flex flex-1 flex-col items-center justify-center gap-3 text-sm"
         style="color: var(--ink-light);">
      <WifiOff class="h-8 w-8 opacity-40" />
      <p>{{ error }}</p>
      <p class="text-xs opacity-60">Assurez-vous que <code>go-task ml:api</code> tourne sur le port 8042.</p>
      <button @click="fetchQueue"
              class="mt-2 rounded-md px-3 py-1.5 text-xs font-medium"
              style="background: var(--indigo-700); color: white;">
        Réessayer
      </button>
    </div>

    <!-- Loading -->
    <div v-else-if="loading" class="flex flex-1 items-center justify-center text-sm" style="color: var(--ink-light);">
      Chargement…
    </div>

    <!-- Content -->
    <div v-else class="flex flex-1 overflow-hidden">

      <!-- Left: list -->
      <div class="flex w-72 flex-shrink-0 flex-col border-r overflow-hidden"
           style="border-color: var(--border);">
        <!-- Tabs -->
        <div class="flex border-b text-xs font-medium" style="border-color: var(--border);">
          <button
            v-for="tab in (['pending', 'resolved', 'skipped'] as Tab[])"
            :key="tab"
            @click="activeTab = tab; selected = null"
            class="flex-1 px-2 py-2.5 transition-colors"
            :style="activeTab === tab
              ? 'border-bottom: 2px solid var(--indigo-700); color: var(--indigo-700); margin-bottom: -1px;'
              : 'color: var(--ink-light);'"
          >
            {{ tab === 'pending' ? `En attente (${stats.pending})` : tab === 'resolved' ? `Résolues (${stats.resolved})` : `Ignorées (${stats.skipped})` }}
          </button>
        </div>

        <!-- Empty state -->
        <div v-if="tabItems.length === 0" class="flex flex-1 items-center justify-center text-sm"
             style="color: var(--ink-light);">
          Aucun élément
        </div>

        <!-- Items -->
        <ul class="flex-1 overflow-y-auto divide-y" style="divide-color: var(--border);">
          <li
            v-for="item in tabItems"
            :key="item.numista_id"
            @click="selectItem(item)"
            class="flex cursor-pointer flex-col gap-0.5 px-4 py-3 transition-colors"
            :style="isSelected(item)
              ? 'background: rgba(79,70,229,0.06); box-shadow: inset 2px 0 0 var(--indigo-700);'
              : 'hover:background: var(--surface-hover);'"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="truncate text-sm font-medium" style="color: var(--ink);">
                {{ countryFlag(item.country) }} {{ item.numista_name }}
              </span>
              <span class="flex-shrink-0 text-xs" style="color: var(--ink-light);">{{ item.year }}</span>
            </div>
            <div class="flex items-center gap-2 text-xs" style="color: var(--ink-light);">
              <span>{{ item.candidates.length }} candidats</span>
              <span v-if="item.resolution?.eurio_id" class="flex items-center gap-1" style="color: var(--success);">
                <Check class="h-3 w-3" /> {{ item.resolution.eurio_id }}
              </span>
              <span v-else-if="item.resolution" style="color: var(--ink-light);">ignoré</span>
            </div>
          </li>
        </ul>
      </div>

      <!-- Right: detail -->
      <div class="flex flex-1 flex-col overflow-y-auto">
        <div v-if="!selected" class="flex flex-1 items-center justify-center text-sm" style="color: var(--ink-light);">
          Sélectionnez un élément dans la liste
        </div>

        <div v-else class="p-6 space-y-6">
          <!-- Numista info -->
          <div class="rounded-lg border p-4" style="border-color: var(--border);">
            <div class="flex gap-4">
              <div class="w-24 h-24 shrink-0 rounded-lg overflow-hidden flex items-center justify-center"
                   style="background: var(--surface);">
                <img
                  :src="`http://localhost:8042/images/${selected.numista_id}/source`"
                  :alt="selected.numista_name"
                  class="w-full h-full object-cover"
                  @error="(e) => (e.target as HTMLImageElement).style.display = 'none'"
                />
              </div>
              <div class="flex-1 min-w-0 space-y-1.5">
                <h2 class="text-base font-semibold leading-snug" style="color: var(--ink);">{{ selected.numista_name }}</h2>
                <div class="flex flex-wrap gap-3 text-sm" style="color: var(--ink-light);">
                  <span>{{ countryFlag(selected.country) }} {{ selected.country }}</span>
                  <span>{{ selected.year }}</span>
                  <span class="italic">{{ selected.numista_theme }}</span>
                </div>
                <a
                  :href="`https://en.numista.com/catalogue/pieces${selected.numista_id}.html`"
                  target="_blank"
                  rel="noopener"
                  class="inline-block text-xs underline"
                  style="color: var(--indigo-700);"
                >
                  Numista #{{ selected.numista_id }} ↗
                </a>
              </div>
            </div>
          </div>

          <!-- Current resolution -->
          <div v-if="selected.resolution" class="rounded-lg border px-4 py-3 flex items-center justify-between"
               :style="selected.resolution.eurio_id
                 ? 'border-color: var(--success); background: color-mix(in srgb, var(--success) 6%, white);'
                 : 'border-color: var(--border); background: var(--surface);'">
            <div class="text-sm">
              <span v-if="selected.resolution.eurio_id">
                Résolu : <span class="font-mono font-medium" style="color: var(--ink);">{{ selected.resolution.eurio_id }}</span>
              </span>
              <span v-else style="color: var(--ink-light);">Ignoré — aucune correspondance</span>
            </div>
            <button
              @click="pick(null)"
              class="text-xs underline"
              style="color: var(--ink-light);"
              :disabled="saving"
            >
              Changer
            </button>
          </div>

          <!-- Candidates -->
          <div>
            <h3 class="mb-3 text-sm font-medium" style="color: var(--ink);">
              Candidats ({{ selected.candidates.length }})
            </h3>
            <ul class="space-y-2">
              <li
                v-for="cand in selected.candidates"
                :key="cand.eurio_id"
                class="flex items-center justify-between rounded-lg border px-4 py-3"
                :style="selected.resolution?.eurio_id === cand.eurio_id
                  ? 'border-color: var(--success); background: color-mix(in srgb, var(--success) 6%, white);'
                  : 'border-color: var(--border);'"
              >
                <div class="flex flex-col gap-0.5">
                  <span class="font-mono text-sm" style="color: var(--ink);">{{ cand.eurio_id }}</span>
                  <span class="text-xs" style="color: var(--ink-light);">score {{ cand.score.toFixed(3) }}</span>
                </div>
                <button
                  @click="pick(cand.eurio_id)"
                  :disabled="saving"
                  class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50"
                  :style="selected.resolution?.eurio_id === cand.eurio_id
                    ? 'background: var(--success); color: white;'
                    : 'background: var(--indigo-700); color: white;'"
                >
                  <Check class="h-3 w-3" />
                  {{ selected.resolution?.eurio_id === cand.eurio_id ? 'Sélectionné' : 'Confirmer' }}
                </button>
              </li>
            </ul>
          </div>

          <!-- Skip -->
          <div class="pt-2 border-t" style="border-color: var(--border);">
            <button
              @click="pick(null)"
              :disabled="saving || (selected.resolution != null && selected.resolution.eurio_id == null)"
              class="flex items-center gap-2 text-sm transition-colors disabled:opacity-40"
              style="color: var(--ink-light);"
            >
              <SkipForward class="h-4 w-4" />
              {{ saving ? 'Enregistrement…' : 'Aucune correspondance — ignorer' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
