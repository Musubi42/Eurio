<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  fetchEbayFreshness,
  fetchEbayQuotaStatus,
  type EbayFreshnessItem,
  type EbayFreshnessResponse,
  type EbayQuotaStatus,
} from '../composables/useSourceDetail'

/**
 * EbayPilotPanel — page /sources/ebay : KPI quota + freshness queue
 * + slider batch size + estimation pré-run.
 *
 * Émet `request-run` avec la liste des `target_eurio_ids` choisis
 * + `dryRun` flag. La page parent fait le triggerSourceRun + le live polling.
 *
 * Décisions D-21 (batch=10 default), D-22 (HD systématique), D-27 (pre-flight).
 */

const props = defineProps<{
  inflight: 'run' | 'dry' | null
}>()

const emit = defineEmits<{
  'request-run': [payload: { dryRun: boolean; target_eurio_ids: string[] }]
}>()

const quota = ref<EbayQuotaStatus | null>(null)
const freshness = ref<EbayFreshnessResponse | null>(null)
const loading = ref(false)
const loadError = ref<string | null>(null)

const batchSize = ref(10)

async function loadAll() {
  loading.value = true
  loadError.value = null
  try {
    const [q, f] = await Promise.all([fetchEbayQuotaStatus(), fetchEbayFreshness(batchSize.value)])
    quota.value = q
    freshness.value = f
    if (!q && !f) {
      loadError.value = 'API ML indisponible (pas de fallback mock pour eBay).'
    }
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)
watch(batchSize, () => loadAll())

// Re-fetch quota après chaque run (parent peut appeler cette méthode via ref).
defineExpose({ refresh: loadAll })

const previewItems = computed<EbayFreshnessItem[]>(
  () => (freshness.value?.items ?? []).slice(0, Math.min(batchSize.value, 10)),
)

const estimateCalls = computed(() => {
  if (!quota.value) return 0
  return Math.round(quota.value.avg_calls_per_eurio_id * batchSize.value)
})

const estimateOk = computed(() => {
  if (!quota.value) return true
  return quota.value.remaining >= estimateCalls.value * 1.3
})

const maxSafeBatch = computed(() => {
  if (!quota.value) return 0
  const avg = quota.value.avg_calls_per_eurio_id || 7
  return Math.max(0, Math.floor(quota.value.remaining / (avg * 1.3)))
})

const quotaPct = computed(() => {
  if (!quota.value) return 0
  return Math.round((quota.value.calls_today / quota.value.limit) * 100)
})

function bucketColor(status: 'never' | 'stale' | 'fresh') {
  return status === 'never'
    ? 'var(--indigo-700)'
    : status === 'stale'
      ? 'var(--warning)'
      : 'var(--success)'
}

function onClickRun(dryRun: boolean) {
  const items = (freshness.value?.items ?? []).slice(0, batchSize.value)
  emit('request-run', { dryRun, target_eurio_ids: items.map((i) => i.eurio_id) })
}
</script>

<template>
  <section
    class="rounded-lg border px-5 py-4"
    style="border-color: var(--surface-3); background: var(--surface);"
  >
    <header class="mb-4 flex items-baseline justify-between gap-4">
      <h3 class="text-sm font-medium" style="color: var(--ink);">
        Pilotage eBay — enrichissement par freshness queue
      </h3>
      <button
        class="text-xs underline"
        style="color: var(--ink-500);"
        @click="loadAll"
      >
        Rafraîchir
      </button>
    </header>

    <div v-if="loadError" class="mb-3 text-xs" style="color: var(--danger);">
      {{ loadError }} — assurez-vous que l'API ML tourne ({{ '`go-task ml:api`' }}).
    </div>

    <!-- ═══ Row 1 : KPI quota + buckets ═══ -->
    <div class="mb-5 grid gap-4 md:grid-cols-2">
      <!-- Quota du jour -->
      <div
        class="rounded-md border px-4 py-3"
        style="border-color: var(--surface-2); background: var(--surface-1);"
      >
        <div class="mb-1 text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
          Quota Browse API · {{ quota?.period ?? '—' }}
        </div>
        <div v-if="quota" class="flex items-baseline gap-2">
          <span class="text-2xl font-semibold tabular-nums" style="color: var(--ink);">
            {{ quota.calls_today.toLocaleString() }}
          </span>
          <span class="text-xs" style="color: var(--ink-500);">
            / {{ quota.limit.toLocaleString() }} ({{ quotaPct }}%)
          </span>
        </div>
        <div v-else class="text-xs" style="color: var(--ink-400);">—</div>
        <div class="mt-2 h-1.5 overflow-hidden rounded" style="background: var(--surface-3);">
          <div
            class="h-full transition-all"
            :style="{
              width: quotaPct + '%',
              background: quota?.exhausted ? 'var(--danger)' : 'var(--indigo-500)',
            }"
          ></div>
        </div>
        <div class="mt-1 text-[11px]" style="color: var(--ink-500);">
          Restant : <strong class="tabular-nums">{{ (quota?.remaining ?? 0).toLocaleString() }}</strong>
          · moy. {{ quota?.avg_calls_per_eurio_id?.toFixed(1) ?? '—' }} calls/pièce
        </div>
      </div>

      <!-- Buckets -->
      <div
        class="rounded-md border px-4 py-3"
        style="border-color: var(--surface-2); background: var(--surface-1);"
      >
        <div class="mb-2 text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
          État de l'enrichissement (commémo 2€ non-EU)
        </div>
        <div class="grid grid-cols-3 gap-3 text-center">
          <div>
            <div class="text-xl font-semibold tabular-nums" :style="{ color: bucketColor('never') }">
              {{ freshness?.buckets.never ?? 0 }}
            </div>
            <div class="text-[10px] uppercase" style="color: var(--ink-500);">jamais</div>
          </div>
          <div>
            <div class="text-xl font-semibold tabular-nums" :style="{ color: bucketColor('stale') }">
              {{ freshness?.buckets.stale_90d ?? 0 }}
            </div>
            <div class="text-[10px] uppercase" style="color: var(--ink-500);">stale > 90j</div>
          </div>
          <div>
            <div class="text-xl font-semibold tabular-nums" :style="{ color: bucketColor('fresh') }">
              {{ freshness?.buckets.fresh ?? 0 }}
            </div>
            <div class="text-[10px] uppercase" style="color: var(--ink-500);">fresh</div>
          </div>
        </div>
        <div class="mt-2 text-[11px]" style="color: var(--ink-500);">
          Total cible : <strong>{{ freshness?.buckets.total ?? 0 }}</strong>
        </div>
      </div>
    </div>

    <!-- ═══ Row 2 : Batch slider + estimation + buttons ═══ -->
    <div
      class="mb-4 rounded-md border px-4 py-4"
      style="border-color: var(--surface-2); background: var(--surface-1);"
    >
      <div class="mb-2 flex items-baseline justify-between">
        <label class="text-xs font-medium" style="color: var(--ink);">
          Taille du batch : <span class="tabular-nums">{{ batchSize }}</span>
        </label>
        <span class="text-[11px]" style="color: var(--ink-500);">
          Recommandé : 10 (D-21)
        </span>
      </div>
      <input
        v-model.number="batchSize"
        type="range"
        min="1"
        max="30"
        step="1"
        class="w-full"
        :disabled="props.inflight !== null"
      />
      <div class="mt-3 flex flex-wrap items-baseline gap-3 text-xs">
        <span style="color: var(--ink-500);">
          Estimation : <strong style="color: var(--ink);" class="tabular-nums">{{ estimateCalls }}</strong> calls
        </span>
        <span style="color: var(--ink-500);">
          Restant : <strong style="color: var(--ink);" class="tabular-nums">{{ (quota?.remaining ?? 0).toLocaleString() }}</strong>
        </span>
        <span
          v-if="estimateOk"
          class="rounded px-2 py-0.5 text-[10px] uppercase"
          style="background: color-mix(in srgb, var(--success) 15%, var(--surface-1)); color: var(--success);"
        >
          ✓ OK
        </span>
        <span
          v-else
          class="rounded px-2 py-0.5 text-[10px] uppercase"
          style="background: color-mix(in srgb, var(--warning) 15%, var(--surface-1)); color: var(--warning);"
        >
          Insuffisant — réduisez à ≤{{ maxSafeBatch }}
        </span>
      </div>

      <div class="mt-4 flex flex-wrap gap-2">
        <button
          class="rounded-md px-4 py-1.5 text-xs font-medium transition-colors"
          :style="{
            background: estimateOk ? 'var(--indigo-700)' : 'var(--surface-3)',
            color: estimateOk ? 'white' : 'var(--ink-400)',
            cursor: !estimateOk || props.inflight ? 'not-allowed' : 'pointer',
          }"
          :disabled="!estimateOk || props.inflight !== null"
          @click="onClickRun(false)"
        >
          {{ props.inflight === 'run' ? 'En cours…' : `Run · ${batchSize} pièces` }}
        </button>
        <button
          class="rounded-md border px-4 py-1.5 text-xs font-medium transition-colors"
          style="border-color: var(--surface-3); color: var(--ink); background: var(--surface);"
          :style="{ cursor: props.inflight ? 'not-allowed' : 'pointer' }"
          :disabled="props.inflight !== null"
          @click="onClickRun(true)"
        >
          {{ props.inflight === 'dry' ? 'Dry…' : 'Dry-run (1 call/pièce)' }}
        </button>
      </div>
    </div>

    <!-- ═══ Row 3 : Preview prochain batch ═══ -->
    <div>
      <div class="mb-2 text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
        Prochaines pièces dans la queue ({{ previewItems.length }})
      </div>
      <ul v-if="previewItems.length" class="space-y-1.5">
        <li
          v-for="item in previewItems"
          :key="item.eurio_id"
          class="flex items-baseline justify-between rounded border px-3 py-1.5 text-xs"
          style="border-color: var(--surface-2); background: var(--surface-1);"
        >
          <div class="flex items-baseline gap-2">
            <span
              class="rounded px-1.5 py-0.5 text-[9px] uppercase font-mono"
              :style="{
                background: 'color-mix(in srgb, ' + bucketColor(item.status) + ' 15%, var(--surface-1))',
                color: bucketColor(item.status),
              }"
            >
              {{ item.status }}
            </span>
            <span class="font-mono" style="color: var(--ink);">{{ item.eurio_id }}</span>
          </div>
          <span style="color: var(--ink-500);" class="tabular-nums">
            {{ item.n_images }} img · {{ item.n_crops }} crops
          </span>
        </li>
      </ul>
      <div v-else class="text-xs" style="color: var(--ink-400);">
        Aucune pièce. Lance d'abord <code style="background: var(--surface-1); padding: 1px 4px;">go-task ml:bootstrap-coins</code>.
      </div>
    </div>
  </section>
</template>
