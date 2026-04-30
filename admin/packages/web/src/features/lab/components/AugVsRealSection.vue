<script setup lang="ts">
import { ML_API } from '@/features/training/composables/useTrainingApi'
import {
  useAugVsRealQuery,
  useRecomputeAugVsRealMutation,
} from '@/features/lab/composables/useLabQueries'
import type { AugVsRealCoin } from '@/features/lab/types'
import { Loader2, RotateCcw } from 'lucide-vue-next'
import { computed, ref } from 'vue'

const props = defineProps<{
  cohortId: string
  iterationId: string
}>()

const cohortId = computed(() => props.cohortId)
const iterationId = computed(() => props.iterationId)

const augVsRealQuery = useAugVsRealQuery(cohortId, iterationId)
const recompute = useRecomputeAugVsRealMutation(cohortId, iterationId)

const data = computed(() => augVsRealQuery.data.value ?? null)
const summary = computed(() => data.value?.summary ?? null)
const perCoin = computed<AugVsRealCoin[]>(() => data.value?.per_coin ?? [])

// Click-to-expand: which coin's gallery is open
const expandedEurioId = ref<string | null>(null)
function toggleExpand(eurioId: string) {
  expandedEurioId.value = expandedEurioId.value === eurioId ? null : eurioId
}

const expandedCoin = computed<AugVsRealCoin | null>(() => {
  if (!expandedEurioId.value) return null
  return perCoin.value.find(c => c.eurio_id === expandedEurioId.value) ?? null
})

function imgUrl(rel: string): string {
  return `${ML_API}/${rel}`
}

function formatPct(v: number | null | undefined, digits = 3): string {
  if (v == null) return '—'
  return v.toFixed(digits)
}

function formatTs(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso.replace(' ', 'T') + 'Z').toLocaleString('fr-FR', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

function cosineColor(c: number | null | undefined): string {
  if (c == null) return 'var(--ink-400)'
  if (c >= 0.85) return 'var(--success)'
  if (c >= 0.70) return 'var(--warning)'
  return 'var(--danger)'
}

function cosineLabel(c: number | null | undefined): string {
  if (c == null) return ''
  if (c >= 0.85) return 'proche'
  if (c >= 0.70) return 'moyen'
  return 'distant'
}

const zoom = ref<string | null>(null)
function openZoom(url: string) { zoom.value = url }
function closeZoom() { zoom.value = null }

async function handleRecompute() {
  try {
    await recompute.mutateAsync()
  } catch (e) {
    alert(`Recompute échoué : ${(e as Error).message}`)
  }
}
</script>

<template>
  <section>
    <div class="mb-3 flex items-center justify-between">
      <div>
        <p
          class="text-[10px] font-medium uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          §4 Aug ↔ réelles (DINO)
          <span v-if="data" class="ml-2 font-mono normal-case" style="color: var(--ink-500);">
            {{ data.dino_version }}
          </span>
        </p>
        <p v-if="summary && summary.num_coins > 0" class="mt-0.5 text-xs" style="color: var(--ink-500);">
          {{ summary.num_coins }} pièce(s) ·
          cosine moyen <span class="font-mono">{{ formatPct(summary.mean_cosine) }}</span>
          (min <span class="font-mono">{{ formatPct(summary.min_cosine) }}</span>,
          max <span class="font-mono">{{ formatPct(summary.max_cosine) }}</span>) ·
          calculé {{ formatTs(data?.computed_at) }}
        </p>
        <p v-else-if="!augVsRealQuery.isLoading.value" class="mt-0.5 text-xs italic" style="color: var(--ink-500);">
          Pas de données — il faut des captures réelles ET un snapshot d'augmentations pour calculer.
        </p>
      </div>
      <button
        v-if="data"
        class="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs transition-colors hover:bg-[var(--surface-2)]"
        style="border-color: var(--surface-3); color: var(--ink);"
        :disabled="recompute.isPending.value"
        title="Force le recompute (ignore le cache)"
        @click="handleRecompute"
      >
        <Loader2 v-if="recompute.isPending.value" class="h-3 w-3 animate-spin" />
        <RotateCcw v-else class="h-3 w-3" />
        Recompute
      </button>
    </div>

    <div
      v-if="augVsRealQuery.isLoading.value && !data"
      class="flex items-center gap-2 text-sm"
      style="color: var(--ink-500);"
    >
      <Loader2 class="h-4 w-4 animate-spin" />
      Calcul DINO… (long au premier appel : chargement du modèle)
    </div>
    <div
      v-else-if="augVsRealQuery.error.value"
      class="rounded-md border px-3 py-2 text-xs"
      style="border-color: var(--danger); color: var(--ink);"
    >
      {{ (augVsRealQuery.error.value as Error).message }}
    </div>
    <div
      v-else-if="perCoin.length === 0"
      class="rounded-lg border-2 border-dashed px-6 py-8 text-center text-sm"
      style="border-color: var(--surface-3); color: var(--ink-500);"
    >
      Aucune pièce à afficher.
    </div>

    <div
      v-else
      class="overflow-hidden rounded-lg border"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b" style="border-color: var(--surface-3); background: var(--surface-1);">
            <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Pièce</th>
            <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">Captures</th>
            <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">Aug</th>
            <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">Cosine</th>
            <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Statut</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="coin in perCoin"
            :key="coin.eurio_id"
            class="cursor-pointer border-b transition-colors hover:bg-[color-mix(in_srgb,var(--indigo-700)_3%,var(--surface))]"
            style="border-color: var(--surface-3);"
            :style="expandedEurioId === coin.eurio_id ? 'background: color-mix(in srgb, var(--indigo-700) 5%, var(--surface));' : ''"
            @click="toggleExpand(coin.eurio_id)"
          >
            <td class="px-4 py-2">
              <div class="font-mono text-xs" style="color: var(--ink);">{{ coin.eurio_id }}</div>
              <div v-if="coin.numista_id" class="mt-0.5 text-[10px]" style="color: var(--ink-500);">
                n{{ coin.numista_id }}
              </div>
            </td>
            <td class="px-4 py-2 text-right font-mono tabular-nums" style="color: var(--ink);">
              {{ coin.num_real }}
            </td>
            <td class="px-4 py-2 text-right font-mono tabular-nums" style="color: var(--ink);">
              {{ coin.num_aug }}
            </td>
            <td class="px-4 py-2 text-right">
              <span
                v-if="coin.cosine != null"
                class="font-mono tabular-nums"
                :style="{ color: cosineColor(coin.cosine) }"
              >
                {{ formatPct(coin.cosine) }}
              </span>
              <span v-else style="color: var(--ink-400);">—</span>
            </td>
            <td class="px-4 py-2 text-xs">
              <span v-if="coin.skipped_reason" style="color: var(--ink-500);">
                skip · {{ coin.skipped_reason }}
              </span>
              <span v-else :style="{ color: cosineColor(coin.cosine) }">
                {{ cosineLabel(coin.cosine) }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Expanded gallery -->
    <div
      v-if="expandedCoin"
      class="mt-4 rounded-lg border p-4"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <p class="mb-3 font-mono text-xs" style="color: var(--ink);">
        {{ expandedCoin.eurio_id }}
        <span v-if="expandedCoin.numista_id" class="ml-1" style="color: var(--ink-500);">
          · n{{ expandedCoin.numista_id }}
        </span>
      </p>
      <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div>
          <p class="mb-1.5 text-[10px] font-medium uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            Captures réelles ({{ expandedCoin.real_samples.length }})
          </p>
          <div class="grid grid-cols-3 gap-1.5">
            <button
              v-for="rel in expandedCoin.real_samples"
              :key="rel"
              class="aspect-square overflow-hidden rounded border transition-transform hover:scale-105"
              style="border-color: var(--surface-3); background: var(--surface-1);"
              @click="openZoom(imgUrl(rel))"
            >
              <img
                :src="imgUrl(rel)"
                :alt="rel"
                class="h-full w-full object-cover"
                loading="lazy"
              />
            </button>
          </div>
        </div>
        <div>
          <p class="mb-1.5 text-[10px] font-medium uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            Augmentations ({{ expandedCoin.aug_samples.length }})
          </p>
          <div class="grid grid-cols-4 gap-1.5">
            <button
              v-for="rel in expandedCoin.aug_samples.slice(0, 12)"
              :key="rel"
              class="aspect-square overflow-hidden rounded border transition-transform hover:scale-105"
              style="border-color: var(--surface-3); background: var(--surface-1);"
              @click="openZoom(imgUrl(rel))"
            >
              <img
                :src="imgUrl(rel)"
                :alt="rel"
                class="h-full w-full object-cover"
                loading="lazy"
              />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Zoom overlay -->
    <div
      v-if="zoom"
      class="fixed inset-0 z-50 flex items-center justify-center p-8"
      style="background: rgba(0, 0, 0, 0.7);"
      @click="closeZoom"
    >
      <img :src="zoom" class="max-h-full max-w-full rounded-lg shadow-2xl" />
    </div>
  </section>
</template>
