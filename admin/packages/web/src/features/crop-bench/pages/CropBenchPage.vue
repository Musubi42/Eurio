<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Columns3, Crop, RefreshCw, Shuffle, TriangleAlert } from 'lucide-vue-next'
import {
  type CropBenchCard as Card,
  type CropBenchLabels,
  type CropBenchStats,
  CropBenchApiError,
  fetchCropBenchLabels,
  fetchCropBenchSample,
  fetchCropBenchStats,
  postCropBenchLabel,
} from '../composables/useCropBenchApi'
import CropBenchCard from '../components/CropBenchCard.vue'

const stats = ref<CropBenchStats | null>(null)
const cards = ref<Card[]>([])
const totalMatched = ref(0)

const loading = ref(false)
const error = ref<string | null>(null)

// Filtres
const bucket = ref<string>('')
const listingType = ref<string>('')
const klass = ref<string>('')
const dinoClass = ref<string>('')
const bias = ref<string>('dino_bad')
const strata = ref<boolean>(false)
const n = ref<number>(30)
const seed = ref<number>(42)

const LISTING_TYPES = ['single_tight', 'single_small', 'multi_tight', 'multi_small', 'unknown']
const DINO_CLASSES = ['good', 'suspect', 'wrong']

// Comparaison détecteur alternatif. bbox_refine (Chunk 2) = raffinement du rim
// externe autour de la bbox connue (94 % good vs 80 % actuel). fitellipse /
// adaptive = plein cadre (Chunk 1, overcroppent les sets/lots).
const compare = ref<boolean>(true)
const algo = ref<string>('bbox_refine')
const ALGOS = [
  { value: 'bbox_refine', label: 'bbox_refine (rim, borné)' },
  { value: 'fitellipse', label: 'fitEllipse (plein cadre)' },
  { value: 'adaptive', label: 'adaptive (circularité)' },
]

const BUCKETS = ['bimetal_light', 'bimetal_textured', 'mono_light', 'mono_textured']
const CLASSES = ['undercrop', 'wrong', 'ok']
const BIASES = [
  { value: 'dino_bad', label: 'DINOv2 pires d\'abord' },
  { value: 'worst', label: 'Pires (r̂ croissant)' },
  { value: 'undercrop', label: 'Undercrops only' },
  { value: 'bimetal', label: 'Bimétal only' },
  { value: 'tilt', label: 'Plus ovales d\'abord' },
  { value: '', label: 'Aléatoire' },
]

// Overlay ellipse tilt (jaune) sur le raw.
const showTilt = ref<boolean>(false)

async function loadStats() {
  try {
    stats.value = await fetchCropBenchStats()
  } catch (e) {
    if (e instanceof CropBenchApiError) error.value = e.message
  }
}

async function loadSample() {
  loading.value = true
  error.value = null
  try {
    const resp = await fetchCropBenchSample({
      n: n.value,
      bucket: bucket.value || null,
      listing_type: listingType.value || null,
      klass: klass.value || null,
      dino_class: dinoClass.value || null,
      bias: bias.value || null,
      strata: strata.value,
      seed: seed.value,
    })
    cards.value = resp.cards
    totalMatched.value = resp.total_matched
  } catch (e) {
    cards.value = []
    error.value = e instanceof CropBenchApiError ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function reshuffle() {
  seed.value = Math.floor(Math.random() * 100000)
  loadSample()
}

// --- Gold labeling ---
const labelsData = ref<CropBenchLabels | null>(null)

async function loadLabels() {
  try {
    labelsData.value = await fetchCropBenchLabels()
  } catch {
    /* backend down — silencieux, le banc reste utilisable en lecture */
  }
}

async function handleLabel(card: Card, payload: { target: string; verdict: 'good' | 'bad'; method: string | null; rRatio: number | null; dinoSim: number | null }) {
  try {
    labelsData.value = await postCropBenchLabel({
      asset_id: card.asset_id,
      target: payload.target,
      verdict: payload.verdict,
      algo: payload.target === 'actuel' ? undefined : algo.value,
      method: payload.method,
      r_ratio: payload.rRatio,
      dino_sim: payload.dinoSim,
    })
  } catch (e) {
    error.value = e instanceof CropBenchApiError ? e.message : String(e)
  }
}

const h2h = computed(() => labelsData.value?.head_to_head?.[algo.value] ?? null)

const generatedAt = computed(() => {
  if (!stats.value?.generated_at) return ''
  try {
    return new Date(stats.value.generated_at).toLocaleString('fr-FR')
  } catch {
    return stats.value.generated_at
  }
})

onMounted(async () => {
  await loadStats()
  await Promise.all([loadSample(), loadLabels()])
})
</script>

<template>
  <div class="page">
    <header class="page__head">
      <div class="page__title">
        <Crop class="h-5 w-5" style="color: var(--indigo-600);" />
        <h1>Crop Bench</h1>
        <span class="page__beta">oracle DINOv2 · gold stratifié</span>
      </div>
      <p class="page__sub">
        Banc de qualité du crop eBay. Pour chaque pièce :
        <b>raw + cercle <span class="legend-red">pipeline (cropé)</span> vs
        <span class="legend-green">vrai rim (oracle Otsu)</span></b>, puis le crop actuel.
        L'écart rouge↔vert <b>EST</b> l'undercrop — invisible sur le crop seul.
        <template v-if="compare">
          Colonne 3 = <b><span class="legend-blue">{{ algo }}</span></b> (cercle <span class="legend-orange">orange</span> sur l'overlay) :
          raffinement du rim externe, comparé au crop actuel.
        </template>
        <span v-if="generatedAt" class="page__diag">Diagnostic du {{ generatedAt }}.</span>
      </p>
    </header>

    <!-- Stats bar -->
    <section v-if="stats" class="stats">
      <div class="stats__cells">
        <div class="stat">
          <span class="stat__v">{{ stats.total }}</span>
          <span class="stat__k">crops eBay</span>
        </div>
        <div class="stat stat--danger">
          <span class="stat__v">{{ stats.dino_bad_pct }}%</span>
          <span class="stat__k">bad — DINOv2 (vrai)</span>
        </div>
        <div class="stat stat--muted" title="L'oracle géométrique Otsu ne voit que la taille du cercle, jamais le mauvais objet.">
          <span class="stat__v">{{ stats.undercrop_pct_judged }}%</span>
          <span class="stat__k">undercrop — géo (aveugle)</span>
        </div>
        <div class="stat stat--muted" title="Crops sans r_ratio → classés 'ok' par défaut par l'oracle Otsu.">
          <span class="stat__v">{{ stats.oracle_blind_pct }}%</span>
          <span class="stat__k">oracle Otsu muet</span>
        </div>
        <div class="stat">
          <span class="stat__v">{{ stats.dino_coverage_pct }}%</span>
          <span class="stat__k">couverture DINOv2</span>
        </div>
      </div>
      <!-- Table par TYPE DE LISTING (Chunk 2/3) — là où sont les vraies pannes -->
      <table class="bucket-table">
        <thead>
          <tr>
            <th>type de listing</th><th>n</th>
            <th title="bad = wrong + suspect (DINOv2)">DINO bad%</th>
            <th>wrong%</th><th>sim med</th>
            <th title="oracle géométrique — aveugle au mauvais objet">géo bad%</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in stats.listing_buckets" :key="b.bucket">
            <td class="bucket-table__name">{{ b.bucket }}</td>
            <td>{{ b.n }}</td>
            <td :class="{ 'cell--warn': (b.dino_bad_pct ?? 0) >= 20 }"><b>{{ b.dino_bad_pct ?? '—' }}</b></td>
            <td>{{ b.dino_wrong_pct ?? '—' }}</td>
            <td>{{ b.dino_sim_median ?? '—' }}</td>
            <td class="cell--muted">{{ (b.undercrop_pct + b.wrong_pct).toFixed(1) }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- Controls -->
    <section class="controls">
      <label class="ctrl">
        <span>Tri/biais</span>
        <select v-model="bias" @change="loadSample">
          <option v-for="b in BIASES" :key="b.value" :value="b.value">{{ b.label }}</option>
        </select>
      </label>
      <label class="ctrl">
        <span>Type listing</span>
        <select v-model="listingType" @change="loadSample">
          <option value="">tous</option>
          <option v-for="l in LISTING_TYPES" :key="l" :value="l">{{ l }}</option>
        </select>
      </label>
      <label class="ctrl">
        <span>DINOv2</span>
        <select v-model="dinoClass" @change="loadSample">
          <option value="">tous</option>
          <option v-for="d in DINO_CLASSES" :key="d" :value="d">{{ d }}</option>
        </select>
      </label>
      <label class="ctrl">
        <span>Bucket</span>
        <select v-model="bucket" @change="loadSample">
          <option value="">tous</option>
          <option v-for="b in BUCKETS" :key="b" :value="b">{{ b }}</option>
        </select>
      </label>
      <label class="ctrl">
        <span>Classe géo</span>
        <select v-model="klass" @change="loadSample">
          <option value="">toutes</option>
          <option v-for="c in CLASSES" :key="c" :value="c">{{ c }}</option>
        </select>
      </label>
      <label class="ctrl">
        <span>N</span>
        <select v-model.number="n" @change="loadSample">
          <option :value="10">10</option>
          <option :value="30">30</option>
          <option :value="60">60</option>
          <option :value="100">100</option>
        </select>
      </label>
      <button class="btn" :disabled="loading" @click="loadSample">
        <RefreshCw class="h-3.5 w-3.5" :class="{ spin: loading }" /> Recharger
      </button>
      <button class="btn btn--ghost" :disabled="loading || bias === 'worst' || bias === 'dino_bad'" @click="reshuffle"
              title="Nouveau tirage aléatoire (désactivé en tri 'pires')">
        <Shuffle class="h-3.5 w-3.5" /> Mélanger
      </button>
      <button class="btn" :class="strata ? '' : 'btn--ghost'" @click="strata = !strata; loadSample()"
              title="Échantillon équilibré entre strates listing_type — le mode à utiliser pour le gold (sinon les single_tight propres écrasent l'échantillon)">
        ⚖ stratifié {{ strata ? 'ON' : 'OFF' }}
      </button>
      <label class="ctrl" v-if="compare">
        <span>Détecteur</span>
        <select v-model="algo">
          <option v-for="a in ALGOS" :key="a.value" :value="a.value">{{ a.label }}</option>
        </select>
      </label>
      <button class="btn" :class="compare ? '' : 'btn--ghost'" @click="compare = !compare"
              title="Afficher la colonne détecteur alternatif">
        <Columns3 class="h-3.5 w-3.5" /> compare {{ compare ? 'ON' : 'OFF' }}
      </button>
      <button class="btn" :class="showTilt ? '' : 'btn--ghost'" @click="showTilt = !showTilt"
              title="Overlay ellipse jaune (fitEllipse tilt) sur le raw — nécessite que le backend supporte show_tilt=1">
        ◎ tilt {{ showTilt ? 'ON' : 'OFF' }}
      </button>
      <span class="controls__count">
        {{ cards.length }} / {{ totalMatched }} correspondants
      </span>
    </section>

    <!-- Error / empty / grid -->
    <div v-if="error" class="banner banner--error">
      <TriangleAlert class="h-4 w-4" /> {{ error }}
    </div>

    <div v-if="loading && !cards.length" class="placeholder">Chargement…</div>
    <div v-else-if="!loading && !cards.length && !error" class="placeholder">
      Aucun crop pour ces filtres.
    </div>

    <!-- Gold tally -->
    <section v-if="labelsData && labelsData.n_labels" class="gold">
      <span class="gold__total">Gold : <b>{{ labelsData.n_labels }}</b> labels</span>
      <span v-if="compare && h2h && h2h.n" class="gold__h2h">
        <b>{{ algo }}</b> vs actuel (n={{ h2h.n }}) —
        <span class="gold__win">{{ h2h.wins }} gagne</span> ·
        <span class="gold__loss">{{ h2h.losses }} régresse</span> ·
        {{ h2h.both_good }} tous bons · {{ h2h.both_bad }} tous mauvais
      </span>
    </section>

    <div class="grid" :class="{ 'grid--wide': compare }">
      <CropBenchCard v-for="c in cards" :key="c.asset_id" :card="c" :compare="compare" :algo="algo"
                     :show-tilt="showTilt"
                     :label="labelsData?.labels[c.asset_id]" @label="handleLabel(c, $event)" />
    </div>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 24px 28px 48px;
  max-width: 1500px;
  margin: 0 auto;
}
.page__title {
  display: flex;
  align-items: center;
  gap: 9px;
}
.page__title h1 {
  font-size: 19px;
  font-weight: 650;
  color: var(--ink-800);
}
.page__beta {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 5px;
  background: var(--surface-2);
  color: var(--ink-500);
}
.page__sub {
  margin-top: 6px;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--ink-500);
  max-width: 900px;
}
.legend-red { color: var(--danger); font-weight: 600; }
.legend-green { color: #1F6E48; font-weight: 600; }
.legend-blue { color: var(--indigo-600); font-weight: 600; }
.legend-orange { color: #C8761A; font-weight: 600; }
.page__diag { color: var(--ink-400); }

/* Stats */
.stats {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  align-items: flex-start;
  padding: 14px 16px;
  border: 1px solid var(--surface-3);
  border-radius: 12px;
  background: var(--surface);
}
.stats__cells { display: flex; gap: 22px; }
.stat { display: flex; flex-direction: column; }
.stat__v {
  font-size: 22px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--ink-800);
}
.stat__k { font-size: 11px; color: var(--ink-400); }
.stat--danger .stat__v { color: var(--danger); }
.stat--muted .stat__v { color: var(--ink-400); font-size: 17px; }
.stat--muted .stat__k { color: var(--ink-300); }
.cell--muted { color: var(--ink-300); }

.bucket-table {
  margin-left: auto;
  font-size: 11px;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
}
.bucket-table th {
  text-align: right;
  padding: 2px 8px;
  color: var(--ink-400);
  font-weight: 500;
  border-bottom: 1px solid var(--surface-2);
}
.bucket-table td {
  text-align: right;
  padding: 2px 8px;
  color: var(--ink-600);
}
.bucket-table__name { text-align: left; font-family: var(--font-mono); color: var(--ink-700); }
.cell--warn { color: var(--danger); font-weight: 600; }

/* Controls */
.controls {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
}
.ctrl { display: flex; flex-direction: column; gap: 3px; font-size: 11px; color: var(--ink-500); }
.ctrl select {
  font-size: 12px;
  padding: 5px 8px;
  border: 1px solid var(--surface-3);
  border-radius: 7px;
  background: var(--surface);
  color: var(--ink-700);
}
.btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 500;
  padding: 6px 12px;
  border-radius: 8px;
  border: 1px solid var(--indigo-600);
  background: var(--indigo-600);
  color: #fff;
  cursor: pointer;
}
.btn:disabled { opacity: 0.55; cursor: not-allowed; }
.btn--ghost {
  background: var(--surface);
  color: var(--ink-600);
  border-color: var(--surface-3);
}
.controls__count {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-400);
}
.spin { animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 9px;
  font-size: 12.5px;
}
.banner--error {
  background: var(--danger-soft, #f6dcd6);
  color: var(--danger);
}
.placeholder {
  padding: 40px;
  text-align: center;
  color: var(--ink-400);
  font-size: 13px;
}

.gold {
  display: flex; gap: 18px; align-items: center; flex-wrap: wrap;
  padding: 8px 14px; border-radius: 9px;
  background: var(--surface-2); font-size: 12px; color: var(--ink-600);
}
.gold__total b { color: var(--ink-800); }
.gold__h2h b { color: var(--indigo-700); }
.gold__win { color: #1F6E48; font-weight: 600; }
.gold__loss { color: var(--danger); font-weight: 600; }

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
  gap: 14px;
}
.grid--wide {
  grid-template-columns: repeat(auto-fill, minmax(620px, 1fr));
}
</style>
