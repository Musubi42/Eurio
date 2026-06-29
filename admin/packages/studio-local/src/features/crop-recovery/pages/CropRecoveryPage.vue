<script setup lang="ts">
// Front d'analyse du banc crop-recovery (docs/work-in-progress/crop-recovery/).
// Choisit un run de stratégie, montre les métriques D1/D2/D3 vs critères, et une grille
// de cas (raw + cercles : rouge=baseline, vert=choisi, bleu=gold).
import { computed, onMounted, ref } from 'vue'
import CaseCard from '../components/CaseCard.vue'
import { ML_API } from '@/shared/api/ml-api'

type Metrics = Record<string, Record<string, number>>
const runs = ref<{ strategy: string; n_cases: number }[]>([])
const datasets = ref<Record<string, number>>({})
const current = ref<string | null>(null)
const tau = ref(0.55)
const metrics = ref<Metrics>({})
const cases = ref<any[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const fDataset = ref('all')
const fEmu = ref(false)
const fStatus = ref('all') // all | pass | fail
const limit = ref(120)

const filtered = computed(() =>
  cases.value
    .filter((c) => fDataset.value === 'all' || c.dataset === fDataset.value)
    .filter((c) => !fEmu.value || c.emu_globe)
    .filter((c) => fStatus.value === 'all' || (fStatus.value === 'pass') === c.passed)
    .slice(0, limit.value),
)

// Critères pré-enregistrés (BENCHMARK §6) → coloration.
const criteria: Record<string, (m: Metrics) => { ok: boolean; txt: string } | null> = {
  'D2 récup EMU/globe ≥70%': (m) =>
    m.D2 ? { ok: m.D2.recovery_emu_globe >= 70, txt: `${m.D2.recovery_emu_globe.toFixed(0)}% (base ${m.D2.baseline_emu_globe?.toFixed(0)}%)` } : null,
  'D3a rétention success ≥98%': (m) =>
    m.D3a ? { ok: m.D3a.retention >= 98, txt: `${m.D3a.retention.toFixed(0)}%` } : null,
  'D3b faux-accept ≤2%': (m) =>
    m.D3b ? { ok: m.D3b.false_accept <= 2, txt: `${m.D3b.false_accept.toFixed(0)}%` } : null,
  'D1 IoU médian ≥0.80': (m) =>
    m.D1 ? { ok: m.D1['iou_median'] >= 0.8, txt: `${m.D1['iou_median'].toFixed(2)} (base ${m.D1['baseline_iou_median'].toFixed(2)})` } : null,
}
const criteriaRows = computed(() =>
  Object.entries(criteria).map(([k, fn]) => ({ k, res: fn(metrics.value) })).filter((r) => r.res),
)

async function loadRuns() {
  const r = await fetch(`${ML_API}/crop-recovery/runs`)
  const d = await r.json()
  runs.value = d.runs
  datasets.value = d.datasets
  if (!current.value && runs.value.length) selectRun(runs.value[runs.value.length - 1].strategy)
}

async function selectRun(strategy: string) {
  loading.value = true
  error.value = null
  current.value = strategy
  try {
    const r = await fetch(`${ML_API}/crop-recovery/run/${encodeURIComponent(strategy)}`)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const d = await r.json()
    tau.value = d.tau
    metrics.value = d.metrics
    cases.value = d.cases
  } catch (e) {
    error.value = `${e instanceof Error ? e.message : e} — API :8042 lancée ? bench buildé ?`
  } finally {
    loading.value = false
  }
}

onMounted(loadRuns)
</script>

<template>
  <div class="cr">
    <header>
      <h1>Crop recovery — banc</h1>
      <p class="sub">
        Cercles : <b class="r">rouge</b> = crop prod (baseline) · <b class="g">vert</b> = choisi (argmax score)
        · <b class="b">bleu</b> = gold humain. Bord vert = passe le gate (τ={{ tau }}).
        <RouterLink to="/crop-recovery/by-raw" class="lnk">→ vue par image brute</RouterLink>
      </p>
    </header>

    <div class="runs">
      <span class="muted">Run :</span>
      <button v-for="r in runs" :key="r.strategy" class="rbtn" :class="{ on: r.strategy === current }"
              @click="selectRun(r.strategy)">{{ r.strategy }} <span class="n">({{ r.n_cases }})</span></button>
      <span class="muted ds">Jeux : <template v-for="(n, k) in datasets" :key="k">{{ k }}={{ n }} </template></span>
    </div>

    <p v-if="error" class="err">{{ error }}</p>

    <table v-if="criteriaRows.length" class="crit">
      <tr v-for="row in criteriaRows" :key="row.k">
        <td>{{ row.k }}</td>
        <td :class="row.res!.ok ? 'ok' : 'ko'">{{ row.res!.ok ? '✅' : '❌' }} {{ row.res!.txt }}</td>
      </tr>
    </table>

    <div class="bar">
      <label>Jeu
        <select v-model="fDataset">
          <option value="all">tous</option>
          <option v-for="(_, k) in datasets" :key="k" :value="k">{{ k }}</option>
        </select>
      </label>
      <label><input v-model="fEmu" type="checkbox" /> EMU/globe</label>
      <label>État
        <select v-model="fStatus">
          <option value="all">tous</option>
          <option value="pass">passe</option>
          <option value="fail">échoue</option>
        </select>
      </label>
      <span class="muted">{{ filtered.length }} affichés (max {{ limit }})</span>
    </div>

    <p v-if="loading" class="muted">Chargement…</p>
    <div v-else class="grid">
      <CaseCard v-for="c in filtered" :key="c.case_id" :c="c" :tau="tau" :ml-api="ML_API" />
    </div>
  </div>
</template>

<style scoped>
.cr { padding: 1.1rem 1.4rem; }
h1 { font-size: 1.2rem; margin: 0; }
.sub { color: #777; font-size: 0.82rem; margin: 0.25rem 0 0; }
.r { color: #e74c3c; } .g { color: #2ecc71; } .b { color: #3498db; }
.lnk { color: #2563eb; margin-left: 0.4rem; }
.muted { color: #999; }
.runs { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin: 0.9rem 0; font-size: 0.84rem; }
.rbtn { border: 1px solid #ddd; background: #fff; border-radius: 7px; padding: 0.3rem 0.7rem; cursor: pointer; }
.rbtn.on { border-color: #1f9d55; background: #eafaf0; font-weight: 600; }
.rbtn .n { color: #999; }
.ds { margin-left: auto; }
.crit { border-collapse: collapse; margin: 0.4rem 0 0.8rem; font-size: 0.84rem; }
.crit td { padding: 0.25rem 0.8rem; border: 1px solid #eee; }
.crit .ok { color: #1f9d55; } .crit .ko { color: #c0392b; }
.bar { display: flex; align-items: center; gap: 1.1rem; margin: 0.5rem 0 0.9rem; font-size: 0.84rem; color: #555; }
.bar label { display: flex; gap: 0.35rem; align-items: center; }
.err { color: #c0392b; background: #fdecea; padding: 0.6rem 0.9rem; border-radius: 8px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 10px; }
</style>
