<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  AlertTriangle, Crop, Inbox, MousePointerClick,
} from 'lucide-vue-next'
import {
  type BenchRunCropsGroupSummary,
  type BenchRunCropsQuery,
  type BenchRunCropsResponse,
  fetchBenchRunCrops,
} from '../composables/useBenchApi'
import BenchCropAnalytics from './BenchCropAnalytics.vue'
import BenchCropEvidenceCard from './BenchCropEvidenceCard.vue'

const props = defineProps<{ runId: string }>()

// ── State ─────────────────────────────────────────────────────────────────
// `baseData` : 1er appel sans filtre — sert pour la grid des recherches
// et la metrics bar globale. Cache stable, ne change pas au fil des
// filtres pour ne pas faire "shrink" la liste quand on sélectionne.
// `data` : appel courant avec filtres — alimente analytics column +
// cards grid (summary recalculé sur le scope du groupe sélectionné).
const baseData = ref<BenchRunCropsResponse | null>(null)
const data = ref<BenchRunCropsResponse | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

const selectedGroupId = ref<string | null>(null)
const selectedMethod = ref<string | null>(null)
const selectedStatus = ref<string | null>(null)
const selectedQualityBucket = ref<string | null>(null)
const undercropOnly = ref(false)
const sort = ref<NonNullable<BenchRunCropsQuery['sort']>>('undercrop_first')

const LIMIT = 60
const offset = ref(0)

// ── Derived ───────────────────────────────────────────────────────────────
// summary : du dataset filtré quand un groupe est sélectionné, sinon du base.
const summary = computed(() => data.value?.summary ?? baseData.value?.summary ?? null)
// groups : toujours depuis baseData (vue stable).
const groups = computed(() => baseData.value?.groups ?? [])
const cards = computed(() => data.value?.cards ?? [])
const cardsTotal = computed(() => data.value?.cards_total ?? 0)
// totaux globaux (metrics bar) — toujours sur baseData.
const globalSummary = computed(() => baseData.value?.summary ?? null)

const selectedGroup = computed<BenchRunCropsGroupSummary | null>(() =>
  groups.value.find(g => g.group_id === selectedGroupId.value) ?? null,
)

// Translate a quality bucket label ("'.2–.4'") → quality_min/max for query.
const qualityRange = computed<[number, number] | null>(() => {
  if (!selectedQualityBucket.value || !summary.value) return null
  const b = summary.value.quality_histogram.find(
    x => x.label === selectedQualityBucket.value,
  )
  return b ? [b.range_lo, b.range_hi] : null
})

const queryParams = computed<BenchRunCropsQuery>(() => {
  const q: BenchRunCropsQuery = {
    limit: LIMIT,
    offset: offset.value,
    sort: sort.value,
  }
  if (selectedGroup.value) {
    if (selectedGroup.value.country) q.country = selectedGroup.value.country
    if (selectedGroup.value.year != null) q.year = selectedGroup.value.year
  }
  if (selectedMethod.value) q.method = selectedMethod.value
  if (selectedStatus.value) q.status = selectedStatus.value
  if (qualityRange.value) {
    q.quality_min = qualityRange.value[0]
    q.quality_max = qualityRange.value[1]
  }
  if (undercropOnly.value) q.undercrop_only = true
  return q
})

// ── Effects ───────────────────────────────────────────────────────────────
async function load() {
  loading.value = true
  error.value = null
  try {
    // Charge uniquement la baseData (sans filtre) pour la metrics bar +
    // la grid des recherches. Pas de groupe sélectionné par défaut —
    // l'utilisateur choisit, comme en mode Filter.
    baseData.value = await fetchBenchRunCrops(props.runId, { limit: 1 })
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    baseData.value = null
  } finally {
    loading.value = false
  }
}

async function reload() {
  // Ne charge le scope du groupe que si un est sélectionné. Sinon, vide.
  if (!selectedGroupId.value) {
    data.value = null
    return
  }
  loading.value = true
  try {
    data.value = await fetchBenchRunCrops(props.runId, queryParams.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

watch([selectedGroupId, selectedMethod, selectedStatus, selectedQualityBucket,
       undercropOnly, sort], () => {
  offset.value = 0
  reload()
})

onMounted(load)

// ── Handlers ──────────────────────────────────────────────────────────────
function selectGroup(id: string) {
  selectedGroupId.value = selectedGroupId.value === id ? null : id
}
function onSelectMethod(m: string | null) {
  selectedMethod.value = m
}
function onSelectStatus(s: string | null) {
  selectedStatus.value = s
}
function onSelectQuality(label: string | null) {
  selectedQualityBucket.value = label
}
function setSort(s: NonNullable<BenchRunCropsQuery['sort']>) {
  sort.value = s
}
function nextPage() {
  if (offset.value + LIMIT < cardsTotal.value) {
    offset.value += LIMIT
    reload()
  }
}
function prevPage() {
  if (offset.value > 0) {
    offset.value = Math.max(0, offset.value - LIMIT)
    reload()
  }
}
</script>

<template>
  <div class="crop-panel">
    <!-- Loading / error states -->
    <div v-if="loading && !data" class="state">
      <p class="state__msg">Chargement des crops…</p>
    </div>
    <div v-else-if="error && !data" class="state">
      <div class="state__error">
        <p class="state__title">Crops indisponibles</p>
        <p class="state__detail">{{ error }}</p>
      </div>
    </div>

    <div v-else-if="globalSummary" class="crop-panel__body">
      <!-- ░ METRICS BAR (globale — toujours sur baseData) ░ -->
      <section>
        <h2 class="eyebrow">
          Bilan crop du run — {{ globalSummary.n_groups }} recherches eBay
          <span class="eyebrow__rule"></span>
        </h2>
        <div class="metrics">
          <div class="metric">
            <div class="metric__label">Raws</div>
            <div class="metric__value">{{ globalSummary.n_raws.toLocaleString() }}</div>
            <div class="metric__sub">images source</div>
          </div>
          <div class="metric">
            <div class="metric__label">Crops</div>
            <div class="metric__value">{{ globalSummary.n_crops.toLocaleString() }}</div>
            <div class="metric__sub" v-if="globalSummary.n_raws">
              {{ (globalSummary.n_crops / globalSummary.n_raws).toFixed(2) }} / raw
            </div>
          </div>
          <div class="metric">
            <div class="metric__label">Undercrop suspects</div>
            <div class="metric__value metric__value--danger">
              {{ globalSummary.n_undercrops.toLocaleString() }}
            </div>
            <div class="metric__sub">
              {{ globalSummary.pct_undercrops.toFixed(1) }} % des crops
            </div>
            <div class="metric__bar">
              <i class="metric__bar-fill--danger"
                 :style="{ width: `${Math.min(100, globalSummary.pct_undercrops)}%` }"></i>
            </div>
          </div>
          <div class="metric">
            <div class="metric__label">Méthode dominante</div>
            <div class="metric__value metric__value--indigo metric__value--mono">
              {{ globalSummary.methods[0]?.method ?? '—' }}
            </div>
            <div class="metric__sub" v-if="globalSummary.methods.length">
              {{ globalSummary.methods.slice(0, 3).map(m =>
                  `${m.method.replace(/^yolo\+/, '')} ${m.pct.toFixed(0)}%`).join(' · ') }}
            </div>
          </div>
          <div class="metric">
            <div class="metric__label">Quality moyen</div>
            <div class="metric__value metric__value--gold">
              {{ globalSummary.quality_mean != null
                ? globalSummary.quality_mean.toFixed(2) : '—' }}
            </div>
            <div v-if="globalSummary.quality_mean != null" class="metric__sub">
              σ {{ globalSummary.quality_std?.toFixed(2) ?? '—' }} ·
              méd {{ globalSummary.quality_median?.toFixed(2) ?? '—' }}
            </div>
            <div v-else class="metric__sub" style="color: var(--ink-300);">
              non calculé sur ce run
            </div>
          </div>
          <div class="metric">
            <div class="metric__label">À reviewer</div>
            <div class="metric__value">
              {{ globalSummary.statuses.find(s => s.status === 'needs_review')?.n
                  ?? 0 }}
            </div>
            <div class="metric__sub" v-if="globalSummary.n_crops">
              {{ (((globalSummary.statuses.find(s => s.status === 'needs_review')?.n ?? 0)
                    / globalSummary.n_crops) * 100).toFixed(1) }} %
            </div>
          </div>
        </div>
      </section>

      <!-- ░ RECHERCHES GRID ░ -->
      <section class="searches">
        <h2 class="eyebrow">
          {{ groups.length }} recherches eBay — choisis-en une pour drill
          <span class="eyebrow__rule"></span>
        </h2>
        <div class="search-grid"
             :style="`grid-template-columns: repeat(${Math.min(groups.length, 6)}, 1fr);`">
          <button
            v-for="g in groups"
            :key="g.group_id"
            class="search-card"
            :class="{ active: selectedGroupId === g.group_id }"
            @click="selectGroup(g.group_id)"
          >
            <div class="search-card__head">
              <div>
                <div class="search-card__year">{{ g.year ?? '?' }}</div>
                <div class="search-card__meta">
                  {{ g.country ?? '?' }} · {{ g.denomination?.toFixed(0) ?? '?' }} €
                </div>
              </div>
              <span
                v-if="g.n_undercrops > 0"
                class="search-card__pill"
                :title="`${g.n_undercrops} undercrops`"
              >
                <AlertTriangle class="h-2.5 w-2.5" />
                {{ g.n_undercrops }}
              </span>
            </div>
            <div class="search-card__bottom">
              <b>{{ g.n_raws }}</b><span>raws</span>
              <span class="search-card__arrow">→</span>
              <b>{{ g.n_crops }}</b><span>crops</span>
            </div>
          </button>
        </div>
      </section>

      <!-- ░ Hint when no group selected ░ -->
      <div v-if="!selectedGroup" class="hint">
        <MousePointerClick class="h-6 w-6" style="color: var(--ink-300);" />
        <p class="hint__msg">
          Choisis une recherche ci-dessus<br>
          pour voir ses crops en détail.
        </p>
      </div>

      <!-- ░ DETAIL PANEL ░ -->
      <section v-else class="detail">
        <header class="detail__header">
          <Crop class="h-4 w-4" style="color: var(--ink-400);" />
          <span class="detail__lbl">Recherche eBay</span>
          <span class="detail__name">
            {{ selectedGroup.country ?? '?' }} ·
            {{ selectedGroup.denomination?.toFixed(0) ?? '?' }} € ·
            {{ selectedGroup.year ?? '?' }}
          </span>
          <span v-if="selectedGroup.n_undercrops > 0" class="detail__chip">
            <span class="detail__chip-dot"></span>
            {{ selectedGroup.n_undercrops }} undercrops ·
            {{ (selectedGroup.n_undercrops / selectedGroup.n_crops * 100).toFixed(0) }} %
          </span>
        </header>

        <div class="detail__body">
          <!-- Left: analytics (summary garanti non-null par v-if) -->
          <BenchCropAnalytics
            v-if="summary"
            :summary="summary"
            :selected-method="selectedMethod"
            :selected-status="selectedStatus"
            :selected-quality-bucket="selectedQualityBucket"
            @select-method="onSelectMethod"
            @select-status="onSelectStatus"
            @select-quality="onSelectQuality"
          />
          <div v-else class="analytics-loading">
            <p class="analytics-loading__msg">chargement…</p>
          </div>

          <!-- Right: evidence grid -->
          <div class="evidence">
            <div class="evidence__bar">
              <Inbox class="h-4 w-4" style="color: var(--ink-400);" />
              <h3 class="evidence__title">Crops</h3>
              <span class="evidence__meta">· <b>{{ cardsTotal }}</b> résultats</span>

              <label class="evidence__under-toggle">
                <input type="checkbox" v-model="undercropOnly" />
                undercrops only
              </label>

              <div class="sort-toggle">
                <button :class="{ active: sort === 'quality_asc' }"
                        @click="setSort('quality_asc')">q ↑</button>
                <button :class="{ active: sort === 'undercrop_first' }"
                        @click="setSort('undercrop_first')">undercrop d'abord</button>
                <button :class="{ active: sort === 'recent' }"
                        @click="setSort('recent')">récent</button>
              </div>
            </div>

            <div class="evidence__body">
              <div v-if="loading" class="evidence__placeholder">
                <p class="evidence__placeholder-msg">chargement…</p>
              </div>
              <div v-else-if="!cards.length" class="evidence__placeholder">
                <MousePointerClick class="h-7 w-7" style="color: var(--ink-300);" />
                <p class="evidence__placeholder-msg">
                  Aucun crop ne correspond aux filtres.<br>
                  Essaye de retirer les filtres method/status/quality.
                </p>
              </div>
              <div v-else class="evidence__grid">
                <BenchCropEvidenceCard
                  v-for="c in cards"
                  :key="c.asset_id"
                  :card="c"
                />
              </div>
            </div>

            <footer class="evidence__pager">
              <span>
                {{ cards.length ? offset + 1 : 0 }}–{{ Math.min(offset + LIMIT, cardsTotal) }}
                / {{ cardsTotal }}
              </span>
              <div class="evidence__pager-btns">
                <button :disabled="offset === 0" @click="prevPage">← Précédent</button>
                <button :disabled="offset + LIMIT >= cardsTotal" @click="nextPage">Suivant →</button>
              </div>
            </footer>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.crop-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.crop-panel__body {
  display: flex;
  flex-direction: column;
  gap: 28px;
}

/* States */
.state {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  padding: 60px 24px;
}
.state__msg {
  font-family: var(--font-display);
  font-style: italic;
  color: var(--ink-400);
}
.state__error { max-width: 360px; text-align: center; }
.state__title {
  font-family: var(--font-display);
  font-style: italic;
  font-size: 17px;
  color: var(--danger);
}
.state__detail {
  margin-top: 6px;
  font-size: 13px;
  color: var(--ink-500);
}

/* Eyebrow */
.eyebrow {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 10.5px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.13em;
  color: var(--ink-400);
}
.eyebrow__rule {
  flex: 1;
  height: 1px;
  background: var(--surface-3);
  transform: translateY(1px);
}

/* Metrics */
.metrics {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  border: 1px solid var(--surface-3);
  border-radius: 18px;
  background: var(--surface);
  overflow: hidden;
}
.metric {
  position: relative;
  padding: 16px 18px 18px;
  border-right: 1px solid var(--surface-3);
}
.metric:last-child { border-right: 0; }
.metric__label {
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: var(--ink-400);
}
.metric__value {
  margin-top: 6px;
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 28px;
  line-height: 1;
  letter-spacing: -0.02em;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}
.metric__value--danger { color: var(--danger); }
.metric__value--indigo { color: var(--indigo-700); }
.metric__value--gold   { color: var(--gold-700); }
.metric__value--mono   { font-family: var(--font-mono); font-size: 18px; font-weight: 500; }
.metric__sub {
  margin-top: 4px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-400);
  font-variant-numeric: tabular-nums;
}
.metric__bar {
  margin-top: 10px;
  height: 3px;
  border-radius: 2px;
  background: var(--surface-2);
  overflow: hidden;
}
.metric__bar-fill--danger {
  display: block;
  height: 100%;
  background: var(--danger);
  border-radius: 2px;
}

/* Recherches grid */
.search-grid {
  display: grid;
  gap: 10px;
}
.search-card {
  position: relative;
  overflow: hidden;
  padding: 14px 16px;
  background: var(--surface);
  border: 1px solid var(--surface-3);
  border-radius: 14px;
  text-align: left;
  transition: transform 220ms cubic-bezier(0.16, 1, 0.3, 1),
              box-shadow 220ms cubic-bezier(0.16, 1, 0.3, 1),
              border-color 160ms;
}
.search-card:hover {
  transform: translateY(-1px);
  box-shadow: 0 1px 2px rgba(14, 14, 31, 0.04),
              0 1px 3px rgba(14, 14, 31, 0.02);
}
.search-card.active {
  border-color: var(--indigo-600);
  box-shadow: 0 1px 0 var(--indigo-600),
              0 10px 24px -14px var(--indigo-900);
}
.search-card__head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.search-card__year {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 26px;
  line-height: 1;
  letter-spacing: -0.02em;
  color: var(--ink);
}
.search-card.active .search-card__year { color: var(--indigo-700); }
.search-card__meta {
  margin-top: 4px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ink-400);
}
.search-card__pill {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 7px;
  border-radius: 999px;
  background: var(--danger-soft, rgba(209, 67, 67, 0.18));
  color: var(--danger);
  font-size: 10px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.search-card__bottom {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 11px;
  font-size: 11px;
  color: var(--ink-400);
}
.search-card__bottom b {
  font-family: var(--font-mono);
  font-weight: 500;
  color: var(--ink);
}
.search-card__arrow { color: var(--ink-300); }

/* Detail panel */
.detail {
  overflow: hidden;
  border: 1px solid var(--surface-3);
  border-radius: 20px;
  background: var(--surface);
}
.detail__header {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 14px 24px;
  border-bottom: 1px solid var(--surface-3);
}
.detail__lbl {
  font-size: 10.5px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.13em;
  color: var(--ink-400);
}
.detail__name {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 19px;
  letter-spacing: -0.01em;
  color: var(--ink);
}
.detail__chip {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--gold-100);
  color: var(--gold-700);
  font-size: 11px;
  font-weight: 600;
}
.detail__chip-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--gold-700);
}

/* Pas de max-height : on laisse le panel s'étendre, la scroll se fait au
   niveau du conteneur page (`<div class="overflow-y-auto">` parent). Ça
   évite le double-scroll, et garde le panel "naturel" en hauteur. La
   colonne analytics devient `position: sticky` pour rester visible quand
   on scrolle la grid de cards. */
.detail__body {
  display: grid;
  grid-template-columns: 312px 1fr;
  align-items: start;
}

/* Evidence column — pas d'overflow interne, on grow et la page scrolle. */
.evidence {
  display: flex;
  flex-direction: column;
  min-width: 0;  /* défensif : empêche la grid de déborder */
}
.evidence__bar {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 13px 22px;
  background: var(--surface);
  border-bottom: 1px solid var(--surface-3);
}
.evidence__title {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
}
.evidence__meta { font-size: 11px; color: var(--ink-400); }
.evidence__meta b {
  color: var(--ink-500);
  font-family: var(--font-mono);
  font-weight: 500;
}
.evidence__under-toggle {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--ink-500);
  cursor: pointer;
  user-select: none;
}
.evidence__under-toggle input { accent-color: var(--indigo-700); }

.sort-toggle {
  display: inline-flex;
  align-items: center;
  overflow: hidden;
  border: 1px solid var(--surface-3);
  border-radius: 8px;
}
.sort-toggle button {
  padding: 5px 10px;
  font-size: 11px;
  color: var(--ink-500);
  border-right: 1px solid var(--surface-3);
  background: transparent;
}
.sort-toggle button:last-child { border-right: 0; }
.sort-toggle button.active { background: var(--ink); color: var(--surface); }

.evidence__body {
  padding: 20px 22px 22px;
}
.evidence__grid {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(auto-fill, minmax(248px, 1fr));
  align-content: start;
}
.evidence__placeholder {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  text-align: center;
}
.evidence__placeholder-msg {
  font-family: var(--font-display);
  font-style: italic;
  font-size: 13px;
  color: var(--ink-400);
}

.evidence__pager {
  position: sticky;
  bottom: 0;
  z-index: 4;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 22px;
  background: var(--surface);
  border-top: 1px solid var(--surface-3);
  font-size: 11px;
  color: var(--ink-400);
  font-variant-numeric: tabular-nums;
}
.evidence__pager-btns { display: flex; gap: 8px; }
.evidence__pager-btns button {
  padding: 2px 8px;
  border: 1px solid var(--surface-3);
  border-radius: 4px;
  background: transparent;
  color: var(--ink-500);
}
.evidence__pager-btns button:disabled { opacity: 0.4; }

/* Hint quand pas de groupe sélectionné */
.hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 56px 24px;
  text-align: center;
  background: var(--surface);
  border: 1px dashed var(--surface-3);
  border-radius: 18px;
}
.hint__msg {
  font-family: var(--font-display);
  font-style: italic;
  font-size: 14px;
  color: var(--ink-400);
  line-height: 1.4;
}

/* Loading placeholder in the analytics column slot. */
.analytics-loading {
  padding: 40px 24px;
  background: var(--surface-1);
  border-right: 1px solid var(--surface-3);
}
.analytics-loading__msg {
  font-family: var(--font-display);
  font-style: italic;
  color: var(--ink-400);
  font-size: 13px;
}
</style>
