<script setup lang="ts">
// Tiroir §C3 — eBay : sourcing & funnel (fusion des anciens §C3 + §C3b).
// Une seule table par coin qui suit tout le tunnel eBay : scrape → crop →
// routing → review → training-eligible → sources réelles. Rows multi-lignes
// (row-card) : identité + sourcing, funnel lu comme une phrase, actions.
// Chaque coin deep-linke vers le studio bench filtré sur la pièce
// (`/bench/runs/<run>?eurio_id=<coin>`). On NE réimplémente PAS le bench.

import DrawerSection from '@/features/lab/components/DrawerSection.vue'
import {
  useCohortFunnelStatusQuery,
  useTriggerCoinEbayScrapeMutation,
  useTriggerCohortEbayScrapeMutation,
} from '@/features/lab/composables/useLabQueries'
import type { CohortFunnelCoin, CohortSummary, DrawerState } from '@/features/lab/types'
import { ArrowUpRight, Crop as CropIcon, Filter, Loader2, RefreshCw, Search } from 'lucide-vue-next'
import { computed, ref } from 'vue'

const props = defineProps<{
  cohortId: string
  cohort: CohortSummary
}>()

const statusQuery = useCohortFunnelStatusQuery(() => props.cohortId)
const scrape = useTriggerCohortEbayScrapeMutation(() => props.cohortId)
const coinScrape = useTriggerCoinEbayScrapeMutation(() => props.cohortId)

const status = computed(() => statusQuery.data.value ?? null)
const loading = computed(() => statusQuery.isPending.value)
const perCoin = computed<CohortFunnelCoin[]>(() => status.value?.per_coin ?? [])
const groups = computed(() => status.value?.head.groups ?? [])
const minReal = computed(() => status.value?.min_real_sources ?? 15)
const quota = computed(() => status.value?.quota ?? null)
const nonScrapable = computed(() => status.value?.non_scrapable ?? [])

const totals = computed(() => {
  const pc = perCoin.value
  const sum = (f: (c: CohortFunnelCoin) => number) => pc.reduce((a, c) => a + f(c), 0)
  return {
    listings: sum(c => c.n_source_images),
    crops: sum(c => c.n_crops),
    review: sum(c => c.n_review_single + c.n_review_lot),
    pending: sum(c => c.n_pending),
    rejected: sum(c => c.n_rejected),
  }
})
// Pièces scrapables sous le seuil de sources réelles → candidates au rescrape.
const flaggedCount = computed(
  () => perCoin.value.filter(c => c.scrapable && !c.enough).length,
)

const state = computed<DrawerState>(() => {
  if (scrape.isPending.value) return 'running'
  if (loading.value || !status.value) return 'empty'
  if (totals.value.listings === 0) return 'empty'
  return totals.value.pending > 0 ? 'partial' : 'ready'
})

const summary = computed(() => {
  if (loading.value || !status.value) return 'Chargement…'
  const t = totals.value
  if (t.listings === 0) return 'Aucun listing scrapé pour cette cohort'
  const flag = flaggedCount.value > 0 ? ` · ${flaggedCount.value} sous ${minReal.value} réels` : ''
  const non = nonScrapable.value.length > 0 ? ` · ${nonScrapable.value.length} hors eBay` : ''
  return `${fmt(t.listings)} → ${fmt(t.crops)} crops → ${fmt(t.review)} en review${flag}${non}`
})

function fmt(n: number): string {
  return n.toLocaleString('fr-FR')
}
function groupLabel(g: { country: string | null; year: number | null }): string {
  const y = g.year != null ? String(g.year) : 'toutes années'
  return `${g.country ?? '?'} · ${y}`
}

// Deep-link vers le studio bench, pré-filtré sur la pièce (run le plus récent).
function benchLink(c: CohortFunnelCoin, hash: '#filter' | '#crop') {
  return { path: `/bench/runs/${c.latest_run_id}`, query: { eurio_id: c.eurio_id }, hash }
}

// ── Scrape cohort (consomme le quota eBay — confirmation) ──────────────────
const quotaInsufficient = computed(() => quota.value?.ok === false)
const scrapeDisabled = computed(() => scrape.isPending.value || quotaInsufficient.value)
const triggered = ref<string | null>(null)

async function onScrape() {
  const est = quota.value?.estimate ?? '?'
  const ok = window.confirm(
    `Lancer un scrape eBay scopé à « ${props.cohort.name} » ?\n\n`
    + `Estimation ~${est} appels Browse API (consomme ton quota eBay).\n`
    + `Le run tourne en arrière-plan ; reviens reviewer dans /review.`,
  )
  if (!ok) return
  triggered.value = null
  const res = await scrape.mutateAsync()
  triggered.value = res.run_id
}

// Rescrape ciblé par pièce. On suit la pièce en cours + le run lancé.
const scrapingCoin = ref<string | null>(null)
const coinTriggered = ref<Record<string, string>>({})

async function onRescrape(c: CohortFunnelCoin) {
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
</script>

<template>
  <DrawerSection
    number="C3"
    title="eBay — sourcing & funnel"
    :state="state"
    :summary="summary"
  >
    <template #body>
      <div v-if="loading" class="text-xs" style="color: var(--ink-400);">
        Chargement du statut eBay…
      </div>
      <template v-else-if="status">
        <!-- Ruban funnel cohort + action scrape -->
        <div class="ribbon">
          <div class="ribbon__cell">
            <span class="ribbon__n">{{ fmt(totals.listings) }}</span>
            <span class="ribbon__lbl">listings retenus</span>
          </div>
          <span class="ribbon__arr">→</span>
          <div class="ribbon__cell">
            <span class="ribbon__n">{{ fmt(totals.crops) }}</span>
            <span class="ribbon__lbl">crops extraits</span>
          </div>
          <span class="ribbon__arr">→</span>
          <div class="ribbon__cell ribbon__cell--accent">
            <span class="ribbon__n">{{ fmt(totals.review) }}</span>
            <span class="ribbon__lbl">en review</span>
          </div>
          <div class="ribbon__aside">
            <span><b>{{ totals.pending }}</b> pending</span>
            <span v-if="totals.rejected"><b>{{ totals.rejected }}</b> rejetés</span>
          </div>
        </div>

        <!-- Barre d'action scrape cohort -->
        <div class="mt-3 flex flex-wrap items-center gap-3">
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

        <!-- Liste de row-cards par coin -->
        <div class="mt-3 overflow-hidden rounded-md border" style="border-color: var(--surface-3);">
          <div
            v-for="c in perCoin"
            :key="c.eurio_id"
            class="coin"
          >
            <!-- L1 : identité + sourcing -->
            <div class="coin__l1">
              <span class="coin__id">
                <span
                  v-if="!c.scrapable"
                  class="coin__badge"
                  title="hors découverte groupée eBay — Numista-only"
                >Numista-only</span>
                {{ c.eurio_id }}
              </span>
              <span class="coin__sources">
                <span class="coin__src">train <b>{{ c.n_training_eligible }}</b></span>
                <span class="coin__sep">·</span>
                <span
                  class="coin__src"
                  :title="c.enough ? `≥ ${minReal} sources réelles` : `sous le seuil (${minReal}) — rescrape conseillé`"
                >réels
                  <b :style="{ color: c.enough ? 'var(--success)' : 'var(--warning)', fontWeight: 600 }">
                    {{ c.n_real_sources }}<span v-if="!c.enough"> ⚠</span>
                  </b>
                </span>
              </span>
            </div>

            <!-- L2 : funnel (phrase) -->
            <div class="coin__funnel">
              <template v-if="c.n_source_images > 0">
                <b>{{ c.n_source_images }}</b> listings
                <span class="coin__arr">→</span>
                <b>{{ c.n_crops }}</b> crops
                <span class="coin__arr">→</span>
                <b style="color: var(--indigo-700);">{{ c.n_review_single + c.n_review_lot }}</b> review
                <span class="coin__dot">·</span>
                <span :style="{ color: c.n_pending > 0 ? 'var(--warning)' : 'var(--ink-400)' }">
                  {{ c.n_pending }} pending
                </span>
                <template v-if="c.n_rejected">
                  <span class="coin__dot">·</span>
                  <span style="color: var(--ink-500);">{{ c.n_rejected }} rejeté</span>
                </template>
              </template>
              <span v-else style="color: var(--ink-400);">aucun listing scrapé</span>
            </div>

            <!-- L3 : actions -->
            <div class="coin__actions">
              <button
                v-if="c.scrapable"
                type="button"
                class="coin__btn"
                :disabled="scrapingCoin !== null"
                :style="{ opacity: scrapingCoin !== null ? 0.5 : 1, cursor: scrapingCoin !== null ? 'not-allowed' : 'pointer' }"
                :title="`Rescrape eBay ciblé sur ${c.eurio_id} (consomme le quota)`"
                @click="onRescrape(c)"
              >
                <Loader2 v-if="scrapingCoin === c.eurio_id" class="h-3 w-3 animate-spin" />
                <RefreshCw v-else class="h-3 w-3" />
                <span v-if="coinTriggered[c.eurio_id]" class="font-mono">{{ coinTriggered[c.eurio_id].slice(0, 6) }}</span>
                <span v-else>rescrape</span>
              </button>
              <span v-else class="coin__muted">hors découverte eBay</span>

              <template v-if="c.latest_run_id">
                <RouterLink
                  :to="benchLink(c, '#filter')"
                  class="coin__audit"
                  :title="`Audit filtres theme-matcher${c.n_runs > 1 ? ' — vu sur ' + c.n_runs + ' runs, lien vers le dernier' : ''}`"
                >
                  <Filter class="h-3 w-3" /> filtres <ArrowUpRight class="h-2.5 w-2.5" />
                </RouterLink>
                <RouterLink :to="benchLink(c, '#crop')" class="coin__audit coin__audit--muted" title="Audit crops (forensics)">
                  <CropIcon class="h-3 w-3" /> crops
                </RouterLink>
              </template>
              <span v-else-if="c.scrapable" class="coin__muted">pas encore scrapé</span>
            </div>
          </div>
        </div>

        <!-- Bloc Découverte (head pré-attribution, maille recherche) -->
        <details class="mt-3 head">
          <summary class="head__summary">
            Découverte — {{ groups.length }} recherches (annonces brutes → retenues, pré-attribution)
          </summary>
          <div class="mt-2 overflow-hidden rounded-md border" style="border-color: var(--surface-3);">
            <table class="w-full text-xs">
              <thead>
                <tr style="background: var(--surface-1); color: var(--ink-500);">
                  <th class="px-3 py-1.5 text-left font-medium">recherche</th>
                  <th class="px-2 py-1.5 text-right font-medium" title="recherches Browse (× marketplaces/langues)">srch</th>
                  <th class="px-2 py-1.5 text-right font-medium" title="N0 — itemSummaries bruts">brut</th>
                  <th class="px-2 py-1.5 text-right font-medium" title="N3 — retenus après accept_listing">retenus</th>
                  <th class="px-2 py-1.5 text-left font-medium" title="rejets attribuables au groupe (par raison)">jetés (raisons)</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="g in groups"
                  :key="`${g.country}-${g.year}-${g.kind}`"
                  class="border-t"
                  style="border-color: var(--surface-3);"
                >
                  <td class="px-3 py-1.5" style="color: var(--ink);">
                    {{ groupLabel(g) }}
                    <span
                      class="ml-1 rounded px-1 py-0.5 text-[9px] uppercase"
                      :style="g.kind === 'standard'
                        ? 'background: var(--gold-100); color: var(--gold-700);'
                        : 'background: var(--surface-2); color: var(--ink-400);'"
                    >{{ g.kind === 'standard' ? 'std' : 'comm' }}</span>
                  </td>
                  <td class="px-2 py-1.5 text-right tabular-nums" style="color: var(--ink-500);">{{ g.n_searches }}</td>
                  <td class="px-2 py-1.5 text-right tabular-nums" style="color: var(--ink);">{{ g.n_summaries }}</td>
                  <td class="px-2 py-1.5 text-right tabular-nums" style="color: var(--ink);">{{ g.n_kept_results }}</td>
                  <td class="px-2 py-1.5" style="color: var(--ink-500);">
                    <span v-if="g.n_discarded_attributed === 0" style="color: var(--ink-400);">—</span>
                    <template v-else>
                      <span
                        v-for="d in g.discarded_by_reason.slice(0, 3)"
                        :key="d.reason"
                        class="mr-1 inline-block rounded px-1 py-0.5 text-[10px]"
                        style="background: var(--surface-2); color: var(--ink-500); font-family: var(--font-mono);"
                      >{{ d.reason }} {{ d.n }}</span>
                    </template>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="mt-2 text-[10px]" style="color: var(--ink-400);">
            <strong>brut</strong> = annonces renvoyées par eBay ; <strong>retenus</strong> = après
            <code>accept_listing</code> + theme-match. L'écart = listings filtrés (maille recherche,
            pré-attribution). Les <strong>jetés</strong> itemisés ne couvrent que les rejets
            rattachables au groupe ; le reste est dans l'écart brut→retenus.
          </p>
        </details>

        <p class="mt-3 text-[10px]" style="color: var(--ink-400);">
          <strong>train</strong> = crops marqués training-eligible en review ;
          <strong>réels</strong> = sources distinctes (obverse + eBay reviewé),
          <span style="color: var(--warning);">⚠ sous {{ minReal }}</span> = l'augmentation
          gonflerait → <strong>rescrape</strong>. Clique <strong>filtres</strong> pour auditer le
          theme-matcher (ou <strong>crops</strong> pour la forensics), puis tranche dans
          <RouterLink to="/review" style="text-decoration: underline;">/review</RouterLink> (§C4).
        </p>
      </template>
      <div v-else class="text-xs" style="color: var(--danger);">
        Erreur de chargement du statut eBay.
      </div>
    </template>
  </DrawerSection>
</template>

<style scoped>
/* Ruban funnel */
.ribbon {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 16px;
  border: 1px solid var(--surface-3);
  border-radius: 8px;
  background: var(--surface);
}
.ribbon__cell { display: flex; flex-direction: column; gap: 2px; }
.ribbon__n {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 600;
  font-size: 26px;
  line-height: 1;
  color: var(--ink);
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums lining-nums;
}
.ribbon__cell--accent .ribbon__n { color: var(--indigo-700); }
.ribbon__lbl {
  font-family: var(--font-mono);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
}
.ribbon__arr { font-size: 18px; color: var(--ink-300); }
.ribbon__aside {
  margin-left: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: right;
  font-size: 11px;
  color: var(--ink-400);
}
.ribbon__aside b { font-family: var(--font-mono); color: var(--ink-500); }

/* Row-card par coin */
.coin {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 11px 14px;
  background: var(--surface);
}
.coin + .coin { border-top: 1px solid var(--surface-3); }
.coin__l1 {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}
.coin__id {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink);
  min-width: 0;
}
.coin__badge {
  margin-right: 4px;
  border-radius: 3px;
  padding: 1px 4px;
  font-size: 9px;
  text-transform: uppercase;
  background: var(--surface-2);
  color: var(--ink-400);
}
.coin__sources {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--ink-400);
  white-space: nowrap;
}
.coin__src b { color: var(--ink); font-variant-numeric: tabular-nums; }
.coin__sep { margin: 0 6px; color: var(--ink-300); }

.coin__funnel {
  font-size: 12.5px;
  color: var(--ink-500);
  font-variant-numeric: tabular-nums;
}
.coin__funnel b { color: var(--ink); font-weight: 600; }
.coin__arr { margin: 0 5px; color: var(--ink-300); }
.coin__dot { margin: 0 6px; color: var(--ink-300); }

.coin__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.coin__btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 10px;
  font-weight: 500;
  color: var(--indigo-700);
  background: color-mix(in srgb, var(--indigo-700) 9%, var(--surface));
  transition: background 160ms var(--ease-out, ease);
}
.coin__btn:hover { background: color-mix(in srgb, var(--indigo-700) 16%, var(--surface)); }
.coin__audit {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 10px;
  font-weight: 500;
  color: var(--indigo-700);
  text-decoration: none;
  background: color-mix(in srgb, var(--indigo-700) 8%, var(--surface));
  transition: background 160ms var(--ease-out, ease);
}
.coin__audit:hover { background: color-mix(in srgb, var(--indigo-700) 16%, var(--surface)); }
.coin__audit--muted { color: var(--ink-500); background: var(--surface-2); }
.coin__audit--muted:hover { background: var(--surface-3); }
.coin__muted { font-size: 10px; color: var(--ink-400); }

/* Découverte */
.head__summary {
  cursor: pointer;
  font-size: 11px;
  font-weight: 500;
  color: var(--ink-500);
  user-select: none;
}
.head__summary:hover { color: var(--ink); }
</style>
