<script setup lang="ts">
// Tiroir C3 — images eBay (chunk 03b).
// Read-only par coin : listings découverts, crops, crops training-eligible,
// + lancement d'un scrape scopé cohort (consomme le quota eBay — confirmation).

import DrawerSection from '@/features/lab/components/DrawerSection.vue'
import {
  useCohortEbayStatusQuery,
  useTriggerCoinEbayScrapeMutation,
  useTriggerCohortEbayScrapeMutation,
} from '@/features/lab/composables/useLabQueries'
import type { CohortEbayCoin, CohortSummary, DrawerState } from '@/features/lab/types'
import { Loader2, Search } from 'lucide-vue-next'
import { computed, ref } from 'vue'

const props = defineProps<{
  cohortId: string
  cohort: CohortSummary
}>()

const statusQuery = useCohortEbayStatusQuery(() => props.cohortId)
const scrape = useTriggerCohortEbayScrapeMutation(() => props.cohortId)
const coinScrape = useTriggerCoinEbayScrapeMutation(() => props.cohortId)

const status = computed(() => statusQuery.data.value ?? null)
const perCoin = computed(() => status.value?.per_coin ?? [])
const scrapableCoins = computed(() => perCoin.value.filter(c => c.scrapable))
const withCrops = computed(() => scrapableCoins.value.filter(c => c.n_crops > 0).length)
const minReal = computed(() => status.value?.min_real_sources ?? 15)
// Pièces scrapables sous le seuil de sources réelles → candidates au rescrape.
const flaggedCount = computed(() => scrapableCoins.value.filter(c => !c.enough).length)

// Rescrape ciblé par pièce (§C5). On suit la pièce en cours + le run lancé.
const scrapingCoin = ref<string | null>(null)
const coinTriggered = ref<Record<string, string>>({})

async function onRescrape(c: CohortEbayCoin) {
  const ok = window.confirm(
    `Rescrape eBay ciblé sur « ${c.eurio_id} » ?\n\n`
    + `Consomme ton quota eBay (résolu vers son groupe de découverte). `
    + `Le run tourne en arrière-plan ; reviens reviewer dans /review.`,
  )
  if (!ok) return
  scrapingCoin.value = c.eurio_id
  try {
    const res = await coinScrape.mutateAsync(c.eurio_id)
    coinTriggered.value = { ...coinTriggered.value, [c.eurio_id]: res.run_id }
  } catch (e) {
    alert(`Rescrape échoué : ${(e as Error).message}`)
  } finally {
    scrapingCoin.value = null
  }
}

const state = computed<DrawerState>(() => {
  if (scrape.isPending.value) return 'running'
  const n = scrapableCoins.value.length
  if (n === 0) return 'empty'
  if (withCrops.value === 0) return 'empty'
  if (withCrops.value === n) return 'ready'
  return 'partial'
})

const summary = computed(() => {
  if (!status.value) return 'Chargement…'
  const n = scrapableCoins.value.length
  const non = status.value.non_scrapable.length
  const nonTxt = non > 0 ? ` · ${non} hors eBay (Numista-only)` : ''
  const flagTxt = flaggedCount.value > 0
    ? ` · ${flaggedCount.value} sous ${minReal.value} réels`
    : ''
  return `${withCrops.value}/${n} pièces scrapables avec crops eBay${nonTxt}${flagTxt}`
})

const quota = computed(() => status.value?.quota ?? null)
const quotaInsufficient = computed(() => quota.value?.ok === false)
const scrapeDisabled = computed(
  () => scrape.isPending.value || quotaInsufficient.value,
)
const triggered = ref<string | null>(null)

async function onScrape() {
  const est = quota.value?.estimate ?? '?'
  const ok = window.confirm(
    `Lancer un scrape eBay scopé à « ${props.cohort.name} » ?\n\n` +
      `Estimation ~${est} appels Browse API (consomme ton quota eBay).\n` +
      `Le run tourne en arrière-plan ; reviens reviewer dans /review.`,
  )
  if (!ok) return
  triggered.value = null
  const res = await scrape.mutateAsync()
  triggered.value = res.run_id
}
</script>

<template>
  <DrawerSection
    number="C3"
    title="Images eBay"
    :state="state"
    :summary="summary"
  >
    <template #body>
      <div v-if="statusQuery.isPending.value" class="text-xs" style="color: var(--ink-400);">
        Chargement du statut eBay…
      </div>
      <div v-else-if="status">
        <!-- Quota + action -->
        <div class="mb-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium"
            :disabled="scrapeDisabled"
            :style="{
              background: quotaInsufficient ? 'var(--surface-2)' : 'var(--indigo-700)',
              color: quotaInsufficient ? 'var(--ink-400)' : 'white',
              cursor: scrapeDisabled ? 'not-allowed' : 'pointer',
            }"
            @click="onScrape"
          >
            <Loader2 v-if="scrape.isPending.value" class="h-3.5 w-3.5 animate-spin" />
            <Search v-else class="h-3.5 w-3.5" />
            Lancer scrape eBay (cohort)
          </button>
          <span v-if="quota" class="text-[11px]" style="color: var(--ink-500);">
            ~{{ quota.estimate }} appels · {{ quota.remaining }}/{{ quota.limit }} restants
            <span v-if="quotaInsufficient" style="color: var(--danger);">· quota insuffisant</span>
          </span>
          <span
            v-if="triggered"
            class="rounded px-2 py-0.5 text-[10px] font-mono"
            style="background: color-mix(in srgb, var(--success) 12%, var(--surface)); color: var(--success);"
          >
            run {{ triggered.slice(0, 8) }} lancé →
            <RouterLink to="/review" style="text-decoration: underline;">review</RouterLink>
          </span>
        </div>

        <!-- Per-coin table -->
        <div class="overflow-hidden rounded-md border" style="border-color: var(--surface-3);">
          <table class="w-full text-xs">
            <thead>
              <tr style="background: var(--surface-1); color: var(--ink-500);">
                <th class="px-3 py-1.5 text-left font-medium">pièce</th>
                <th class="px-2 py-1.5 text-right font-medium" title="listings eBay découverts">listings</th>
                <th class="px-2 py-1.5 text-right font-medium" title="crops extraits">crops</th>
                <th class="px-2 py-1.5 text-right font-medium" title="crops training-eligible (reviewés OK)">train</th>
                <th
                  class="px-2 py-1.5 text-right font-medium"
                  :title="`sources réelles distinctes (obverse + eBay reviewé) ; flag sous ${minReal}`"
                >réels</th>
                <th class="px-2 py-1.5 text-right font-medium" title="rescrape eBay ciblé sur la pièce">action</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="c in perCoin"
                :key="c.eurio_id"
                class="border-t"
                style="border-color: var(--surface-3);"
              >
                <td class="px-3 py-1.5 font-mono" style="color: var(--ink);">
                  <span
                    v-if="!c.scrapable"
                    class="mr-1 rounded px-1 py-0.5 text-[9px] uppercase"
                    style="background: var(--surface-2); color: var(--ink-400);"
                    title="hors découverte groupée eBay — Numista-only"
                  >N/A</span>
                  {{ c.eurio_id }}
                </td>
                <td
                  class="px-2 py-1.5 text-right tabular-nums"
                  :style="{ color: c.n_listings > 0 ? 'var(--ink)' : 'var(--ink-400)' }"
                >{{ c.n_listings }}</td>
                <td
                  class="px-2 py-1.5 text-right tabular-nums"
                  :style="{ color: c.n_crops > 0 ? 'var(--ink)' : 'var(--ink-400)' }"
                >{{ c.n_crops }}</td>
                <td
                  class="px-2 py-1.5 text-right tabular-nums"
                  :style="{ color: c.n_training_eligible > 0 ? 'var(--success)' : 'var(--ink-400)' }"
                >{{ c.n_training_eligible }}</td>
                <td class="px-2 py-1.5 text-right tabular-nums">
                  <span
                    v-if="c.scrapable"
                    :title="c.enough ? `≥ ${minReal} sources réelles` : `sous le seuil (${minReal}) — rescrape conseillé`"
                    :style="{
                      color: c.enough ? 'var(--success)' : 'var(--warning)',
                      fontWeight: c.enough ? 400 : 600,
                    }"
                  >{{ c.n_real_sources }}<span v-if="!c.enough"> ⚠</span></span>
                  <span v-else style="color: var(--ink-400);">—</span>
                </td>
                <td class="px-2 py-1.5 text-right">
                  <button
                    v-if="c.scrapable"
                    type="button"
                    class="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium"
                    :disabled="scrapingCoin !== null"
                    :style="{
                      background: scrapingCoin !== null ? 'var(--surface-2)' : 'color-mix(in srgb, var(--indigo-700) 10%, var(--surface))',
                      color: scrapingCoin !== null ? 'var(--ink-400)' : 'var(--indigo-700)',
                      cursor: scrapingCoin !== null ? 'not-allowed' : 'pointer',
                    }"
                    :title="`Rescrape eBay ciblé sur ${c.eurio_id} (consomme le quota)`"
                    @click="onRescrape(c)"
                  >
                    <Loader2 v-if="scrapingCoin === c.eurio_id" class="h-3 w-3 animate-spin" />
                    <Search v-else class="h-3 w-3" />
                    <span v-if="coinTriggered[c.eurio_id]" class="font-mono">{{ coinTriggered[c.eurio_id].slice(0, 6) }}</span>
                    <span v-else>rescrape</span>
                  </button>
                  <span v-else style="color: var(--ink-400);" class="text-[10px]">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="mt-2 text-[10px]" style="color: var(--ink-400);">
          <strong>train</strong> = crops marqués training-eligible en review.
          <strong>réels</strong> = sources distinctes (obverse + eBay reviewé) ;
          <span style="color: var(--warning);">⚠ sous {{ minReal }}</span> = l'augmentation
          gonflerait artificiellement → clique <strong>rescrape</strong> pour chercher plus
          d'eBay sur cette pièce. Reviewe d'abord dans
          <RouterLink to="/review" style="text-decoration: underline;">/review</RouterLink>.
        </p>
      </div>
      <div v-else class="text-xs" style="color: var(--danger);">
        Erreur de chargement du statut eBay.
      </div>
    </template>
  </DrawerSection>
</template>
