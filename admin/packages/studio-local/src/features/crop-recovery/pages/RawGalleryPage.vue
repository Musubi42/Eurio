<script setup lang="ts">
// Vue « par image brute » du banc crop-recovery : une image brute = une carte, avec le raw
// en haut et TOUS les crops qu'on en tire en dessous (1 si single, N si lot). Permet de juger
// d'un coup la complétude (pièces ratées sur un lot) et la qualité par crop.
// Réutilise les runs du banc ; le crop affiché = le candidat CHOISI de la stratégie sélectionnée.
import { computed, onMounted, ref } from 'vue'
import RawCard from '../components/RawCard.vue'
import { ML_API } from '@/shared/api/ml-api'

const runs = ref<{ strategy: string; n_cases: number }[]>([])
const datasets = ref<Record<string, number>>({})
const current = ref<string | null>(null)
const tau = ref(0.55)
const cases = ref<any[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const fDataset = ref('all')
const fEmu = ref(false)
const fMulti = ref(false) // multi-pièces seulement (≥2 crops / raw)
const fStatus = ref('all') // all | allpass | anyfail
const showBaseline = ref(false)
const limit = ref(60)

// Regroupe les cas par image brute (raw_key).
const groups = computed(() => {
  const by = new Map<string, any[]>()
  for (const c of cases.value) {
    if (fDataset.value !== 'all' && c.dataset !== fDataset.value) continue
    if (fEmu.value && !c.emu_globe) continue
    if (!by.has(c.raw_key)) by.set(c.raw_key, [])
    by.get(c.raw_key)!.push(c)
  }
  let arr = Array.from(by.entries()).map(([rawKey, cs]) => ({ rawKey, cs }))
  if (fMulti.value) arr = arr.filter((g) => g.cs.length > 1)
  if (fStatus.value === 'allpass') arr = arr.filter((g) => g.cs.every((c) => c.passed))
  if (fStatus.value === 'anyfail') arr = arr.filter((g) => g.cs.some((c) => !c.passed))
  // lots d'abord (plus instructifs), puis par nombre de crops décroissant
  arr.sort((a, b) => b.cs.length - a.cs.length)
  return arr
})
const shown = computed(() => groups.value.slice(0, limit.value))

const totals = computed(() => {
  const g = groups.value
  return {
    raws: g.length,
    multi: g.filter((x) => x.cs.length > 1).length,
    crops: g.reduce((s, x) => s + x.cs.length, 0),
  }
})

async function loadRuns() {
  const r = await fetch(`${ML_API}/crop-recovery/runs`)
  const d = await r.json()
  runs.value = d.runs
  datasets.value = d.datasets
  // défaut = A:score_search si présent, sinon le dernier run.
  const a = runs.value.find((x) => x.strategy === 'A:score_search')
  selectRun(a ? a.strategy : runs.value[runs.value.length - 1]?.strategy)
}

async function selectRun(strategy?: string) {
  if (!strategy) return
  loading.value = true
  error.value = null
  current.value = strategy
  try {
    const r = await fetch(`${ML_API}/crop-recovery/run/${encodeURIComponent(strategy)}`)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const d = await r.json()
    tau.value = d.tau
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
      <h1>Crop recovery — par image brute</h1>
      <p class="sub">
        Une image brute = une carte : le <b>raw</b> en haut (cercle <b class="g">vert</b> = crop produit,
        <b class="o">orange</b> = échoue le gate), les <b>crops 224 réels</b> en dessous. Une pièce sans
        cercle = ratée. <RouterLink to="/crop-recovery" class="lnk">→ vue par cas / métriques</RouterLink>
      </p>
    </header>

    <div class="runs">
      <span class="muted">Découpage :</span>
      <button v-for="r in runs" :key="r.strategy" class="rbtn" :class="{ on: r.strategy === current }"
              @click="selectRun(r.strategy)">{{ r.strategy }}</button>
    </div>

    <p v-if="error" class="err">{{ error }}</p>

    <div class="bar">
      <label>Jeu
        <select v-model="fDataset">
          <option value="all">tous</option>
          <option v-for="k in Object.keys(datasets)" :key="k" :value="k">{{ k }}</option>
        </select>
      </label>
      <label><input v-model="fEmu" type="checkbox" /> EMU/globe</label>
      <label><input v-model="fMulti" type="checkbox" /> multi-pièces</label>
      <label>État
        <select v-model="fStatus">
          <option value="all">tous</option>
          <option value="allpass">tout passe</option>
          <option value="anyfail">≥1 échoue</option>
        </select>
      </label>
      <label><input v-model="showBaseline" type="checkbox" /> cercle baseline</label>
      <span class="muted">
        {{ totals.raws }} raws · {{ totals.multi }} multi · {{ totals.crops }} crops
        (affiche {{ shown.length }})
      </span>
    </div>

    <p v-if="loading" class="muted">Chargement…</p>
    <div v-else class="grid">
      <RawCard v-for="g in shown" :key="g.rawKey" :raw-key="g.rawKey" :cases="g.cs"
               :tau="tau" :ml-api="ML_API" :show-baseline="showBaseline" />
    </div>
  </div>
</template>

<style scoped>
.cr { padding: 1.1rem 1.4rem; }
h1 { font-size: 1.2rem; margin: 0; }
.sub { color: #777; font-size: 0.82rem; margin: 0.25rem 0 0; }
.g { color: #2ecc71; } .o { color: #e67e22; }
.lnk { color: #2563eb; margin-left: 0.4rem; }
.muted { color: #999; }
.runs { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin: 0.9rem 0; font-size: 0.84rem; }
.rbtn { border: 1px solid #ddd; background: #fff; border-radius: 7px; padding: 0.3rem 0.7rem; cursor: pointer; }
.rbtn.on { border-color: #1f9d55; background: #eafaf0; font-weight: 600; }
.bar { display: flex; flex-wrap: wrap; align-items: center; gap: 1.1rem; margin: 0.5rem 0 0.9rem; font-size: 0.84rem; color: #555; }
.bar label { display: flex; gap: 0.35rem; align-items: center; }
.err { color: #c0392b; background: #fdecea; padding: 0.6rem 0.9rem; border-radius: 8px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(400px, 1fr)); gap: 14px; }
</style>
