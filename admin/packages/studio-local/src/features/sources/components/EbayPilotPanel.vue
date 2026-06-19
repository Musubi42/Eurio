<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  fetchEbayFreshnessGroups,
  fetchEbayQuotaStatus,
  type DiscoveryGroupSpec,
  type EbayFreshnessGroupItem,
  type EbayFreshnessGroupsResponse,
  type EbayQuotaStatus,
} from '../composables/useSourceDetail'
import {
  discoveryCallCount,
  discoveryMarketplaces,
  useMarketplaceMap,
} from '../composables/useMarketplaceMap'
import MarketplaceMapModal from './MarketplaceMapModal.vue'
import MarketplaceBadge from './MarketplaceBadge.vue'

/**
 * EbayPilotPanel — page /sources/ebay : KPI quota + freshness queue
 * GROUPÉE (denom, pays, année) + slider batch + estimation pré-run.
 *
 * Une recherche eBay couvre tout un groupe : le batch se compte en
 * groupes, l'estimation de coût en pièces (un groupe = N commémos).
 *
 * Émet `request-run` avec les `discovery_groups` choisis + `dryRun`.
 */

const props = defineProps<{
  inflight: 'run' | 'dry' | null
}>()

const emit = defineEmits<{
  'request-run': [payload: { dryRun: boolean; discovery_groups: DiscoveryGroupSpec[] }]
}>()

const quota = ref<EbayQuotaStatus | null>(null)
const freshness = ref<EbayFreshnessGroupsResponse | null>(null)
const loading = ref(false)
const loadError = ref<string | null>(null)

const batchSize = ref(10)

const { map: marketplaceMap, load: loadMarketplaceMap } = useMarketplaceMap()
const mapModalOpen = ref(false)

async function loadAll() {
  loading.value = true
  loadError.value = null
  try {
    const [q, f] = await Promise.all([fetchEbayQuotaStatus(), fetchEbayFreshnessGroups(500)])
    quota.value = q
    freshness.value = f
    if (!q && !f) {
      loadError.value = 'API ML indisponible (pas de fallback mock pour eBay).'
    }
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadAll()
  loadMarketplaceMap()
})

// Re-fetch quota après chaque run (parent peut appeler cette méthode via ref).
defineExpose({ refresh: loadAll })

const callsPerEurio = computed(() => discoveryCallCount(marketplaceMap.value))
const discoveryMkts = computed(() => discoveryMarketplaces(marketplaceMap.value))

/** Les groupes effectivement sélectionnés = tête de la queue, taille `batchSize`. */
const selectedGroups = computed<EbayFreshnessGroupItem[]>(
  () => (freshness.value?.items ?? []).slice(0, batchSize.value),
)

/** Total des commémos couvertes par le batch (un groupe = N pièces). */
const totalCoins = computed(() =>
  selectedGroups.value.reduce((sum, g) => sum + g.n_coins, 0),
)

/** Aperçu affiché : 10 premiers groupes max pour rester compact. */
const previewGroups = computed(() => selectedGroups.value.slice(0, 10))

const maxBatch = computed(() => Math.min(50, freshness.value?.buckets.total ?? 30))

const estimateCalls = computed(() => {
  if (!quota.value) return 0
  return Math.round(quota.value.avg_calls_per_eurio_id * totalCoins.value)
})

const estimateOk = computed(() => {
  if (!quota.value) return true
  return quota.value.remaining >= estimateCalls.value * 1.3
})

/** Un run n'est lançable que s'il couvre au moins un groupe non vide. */
const hasGroups = computed(() => selectedGroups.value.length > 0 && totalCoins.value > 0)
const canRun = computed(() => hasGroups.value && estimateOk.value)

/** Nombre de pièces qu'on peut encore traiter sans dépasser le quota. */
const maxSafeCoins = computed(() => {
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

watch(maxBatch, (m) => {
  if (batchSize.value > m) batchSize.value = Math.max(1, m)
})

function onClickRun(dryRun: boolean) {
  const discovery_groups = selectedGroups.value.map((g) => ({
    denomination: g.denomination,
    country: g.country,
    year: g.year,
  }))
  emit('request-run', { dryRun, discovery_groups })
}
</script>

<template>
  <section
    class="rounded-lg border px-5 py-4"
    style="border-color: var(--surface-3); background: var(--surface);"
  >
    <header class="mb-4 flex items-baseline justify-between gap-4">
      <h3 class="text-sm font-medium" style="color: var(--ink);">
        Pilotage eBay — découverte par groupe (pays · année)
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

    <!-- ═══ Bandeau : Stratégie d'extraction multi-marketplace ═══ -->
    <div
      class="mb-5 rounded-md border px-4 py-3"
      style="border-color: var(--surface-2); background: var(--surface-1);"
    >
      <div class="mb-1.5 text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
        Stratégie d'extraction
      </div>
      <p class="text-xs leading-relaxed" style="color: var(--ink);">
        Une recherche par groupe <span class="font-mono">(dénomination, pays, année)</span>
        <span style="color: var(--ink-500);"> — toutes les commémos-sœurs d'une même
        année sont ramenées d'un coup, puis attribuées à leur pièce par le theme-match.
        Routage uniforme <span class="font-mono">EBAY_DE</span> +
        <span class="font-mono">EBAY_ES</span>, chacun queryé dans sa langue native.</span>
      </p>
      <div class="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span class="text-xs" style="color: var(--ink-500);">
          Coût quota fixe :
          <strong class="tabular-nums" style="color: var(--ink);">
            {{ marketplaceMap ? callsPerEurio : '—' }}
          </strong>
          search calls/groupe
        </span>
        <button
          class="text-xs underline"
          style="color: var(--indigo-700);"
          @click="mapModalOpen = true"
        >
          voir la table complète
        </button>
      </div>
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

      <!-- Buckets groupes -->
      <div
        class="rounded-md border px-4 py-3"
        style="border-color: var(--surface-2); background: var(--surface-1);"
      >
        <div class="mb-2 text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
          Fraîcheur des groupes (commémo 2€ non-EU)
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
          Total groupes : <strong>{{ freshness?.buckets.total ?? 0 }}</strong>
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
          Batch : <span class="tabular-nums">{{ batchSize }}</span> groupe(s)
        </label>
        <span class="text-[11px]" style="color: var(--ink-500);">
          Max : {{ maxBatch }}
        </span>
      </div>
      <input
        v-model.number="batchSize"
        type="range"
        min="1"
        :max="maxBatch"
        step="1"
        class="w-full"
        :disabled="props.inflight !== null"
      />

      <!-- Carte de preview pré-run -->
      <div
        class="mt-3 rounded-md border px-3 py-2.5"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <div class="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
          <strong class="tabular-nums" style="color: var(--ink);">{{ batchSize }}</strong>
          <span style="color: var(--ink-500);">groupe(s)</span>
          <span style="color: var(--ink-400);">→</span>
          <strong class="tabular-nums" style="color: var(--ink);">{{ totalCoins }}</strong>
          <span style="color: var(--ink-500);">pièce(s) couverte(s)</span>
          <span style="color: var(--ink-400);">→</span>
          <strong class="tabular-nums" style="color: var(--ink);">~{{ estimateCalls }}</strong>
          <span style="color: var(--ink-500);">appels API estimés</span>
        </div>
        <div class="mt-1.5 flex flex-wrap items-baseline gap-3 text-[11px]">
          <span style="color: var(--ink-500);">
            Restant : <strong class="tabular-nums" style="color: var(--ink);">{{ (quota?.remaining ?? 0).toLocaleString() }}</strong>
          </span>
          <span
            v-if="!hasGroups"
            class="rounded px-2 py-0.5 text-[10px] uppercase"
            style="background: color-mix(in srgb, var(--danger) 15%, var(--surface-1)); color: var(--danger);"
          >
            Aucun groupe — queue vide ou API ML injoignable
          </span>
          <span
            v-else-if="estimateOk"
            class="rounded px-2 py-0.5 text-[10px] uppercase"
            style="background: color-mix(in srgb, var(--success) 15%, var(--surface-1)); color: var(--success);"
          >
            ✓ quota OK
          </span>
          <span
            v-else
            class="rounded px-2 py-0.5 text-[10px] uppercase"
            style="background: color-mix(in srgb, var(--warning) 15%, var(--surface-1)); color: var(--warning);"
          >
            Insuffisant — réduisez à ≤{{ maxSafeCoins }} pièces
          </span>
        </div>
      </div>

      <div class="mt-4 flex flex-wrap gap-2">
        <button
          class="rounded-md px-4 py-1.5 text-xs font-medium transition-colors"
          :style="{
            background: canRun ? 'var(--indigo-700)' : 'var(--surface-3)',
            color: canRun ? 'white' : 'var(--ink-400)',
            cursor: !canRun || props.inflight ? 'not-allowed' : 'pointer',
          }"
          :disabled="!canRun || props.inflight !== null"
          @click="onClickRun(false)"
        >
          {{ props.inflight === 'run' ? 'En cours…' : `Run · ${batchSize} groupes · ${totalCoins} pièces` }}
        </button>
        <button
          class="rounded-md border px-4 py-1.5 text-xs font-medium transition-colors"
          style="border-color: var(--surface-3); color: var(--ink); background: var(--surface);"
          :style="{ cursor: !hasGroups || props.inflight ? 'not-allowed' : 'pointer' }"
          :disabled="!hasGroups || props.inflight !== null"
          @click="onClickRun(true)"
        >
          {{ props.inflight === 'dry' ? 'Dry…' : 'Dry-run (search only)' }}
        </button>
      </div>
    </div>

    <!-- ═══ Row 3 : Preview prochains groupes ═══ -->
    <div>
      <div class="mb-2 text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
        Prochains groupes dans la queue ({{ previewGroups.length }} / {{ batchSize }})
      </div>
      <ul v-if="previewGroups.length" class="space-y-1.5">
        <li
          v-for="g in previewGroups"
          :key="g.country + '-' + g.year"
          class="flex items-baseline justify-between rounded border px-3 py-1.5 text-xs"
          style="border-color: var(--surface-2); background: var(--surface-1);"
        >
          <div class="flex items-center gap-2">
            <span
              class="rounded px-1.5 py-0.5 text-[9px] uppercase font-mono"
              :style="{
                background: 'color-mix(in srgb, ' + bucketColor(g.status) + ' 15%, var(--surface-1))',
                color: bucketColor(g.status),
              }"
            >
              {{ g.status }}
            </span>
            <span class="inline-flex gap-0.5">
              <MarketplaceBadge
                v-for="mkt in discoveryMkts"
                :key="mkt"
                :marketplace="mkt"
                size="sm"
              />
            </span>
            <span class="font-mono" style="color: var(--ink);">
              {{ g.country }} · {{ g.year }}
            </span>
            <span
              class="rounded px-1.5 py-0.5 text-[10px] tabular-nums"
              style="background: var(--surface-3); color: var(--ink-500);"
            >
              {{ g.n_coins }} pièce(s)
            </span>
          </div>
          <span style="color: var(--ink-500);" class="tabular-nums">
            {{ g.n_images }} img · {{ g.n_crops }} crops
          </span>
        </li>
      </ul>
      <div v-else class="text-xs" style="color: var(--ink-400);">
        Aucun groupe. Lance d'abord <code style="background: var(--surface-1); padding: 1px 4px;">go-task ml:bootstrap-coins</code>.
      </div>
    </div>

    <MarketplaceMapModal
      :open="mapModalOpen"
      :map="marketplaceMap"
      @close="mapModalOpen = false"
    />
  </section>
</template>
