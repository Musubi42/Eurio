<script setup lang="ts">
// Page ONE-SHOT (non câblée dans la nav) — audit du gate anti-fragment C7.
// Montre chaque crop éjecté + son score face_scores + le palier τ. L'humain
// tague coin/fragment pour quantifier combien de VRAIS 2€ sont tués.
import { computed, onMounted, ref } from 'vue'

const ML_API = 'http://127.0.0.1:8042'

type Item = {
  name: string
  score: number
  r: number
  ejected: boolean
  source_ref: string
  listing_title: string | null
  source_url: string | null
  verdict: string | null
}

const items = ref<Item[]>([])
const tau = ref(0.55)
const loading = ref(false)
const error = ref<string | null>(null)
const onlyEjected = ref(true)
const onlyBig = ref(false)
const bigR = 120

const filtered = computed(() =>
  items.value.filter(
    (i) => (!onlyEjected.value || i.ejected) && (!onlyBig.value || i.r >= bigR),
  ),
)
const ejectedCount = computed(() => items.value.filter((i) => i.ejected).length)
const coinTagged = computed(() => items.value.filter((i) => i.verdict === 'coin').length)
const fragTagged = computed(() => items.value.filter((i) => i.verdict === 'fragment').length)
// Parmi ce que l'humain a tagué « coin », combien sont éjectés (= faux-rejets confirmés) ?
const coinEjected = computed(
  () => items.value.filter((i) => i.verdict === 'coin' && i.ejected).length,
)

async function load() {
  loading.value = true
  error.value = null
  try {
    const r = await fetch(`${ML_API}/fragment-audit/items`)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const d = await r.json()
    items.value = d.items
    tau.value = d.tau
  } catch (e) {
    error.value = `${e instanceof Error ? e.message : e} — as-tu lancé scripts.prep_fragment_audit ?`
  } finally {
    loading.value = false
  }
}

function cropUrl(it: Item) {
  return `${ML_API}/fragment-audit/crop/${it.name}`
}

async function cycle(it: Item) {
  const nextV = it.verdict === null ? 'coin' : it.verdict === 'coin' ? 'fragment' : null
  const prev = it.verdict
  it.verdict = nextV
  try {
    const r = await fetch(`${ML_API}/fragment-audit/tag`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: it.name, verdict: nextV }),
    })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
  } catch (e) {
    it.verdict = prev
    error.value = `Échec tag — ${e instanceof Error ? e.message : e}`
  }
}

onMounted(load)
</script>

<template>
  <div class="fa">
    <header class="head">
      <div>
        <h1>Audit gate anti-fragment — crops éjectés</h1>
        <p class="sub">
          Chaque crop a été <strong>généré par le détecteur</strong> puis scoré par la probe coin-ness.
          <strong>Sous τ = {{ tau }}</strong> → éjecté (bordure rouge). Clique : 1× = <b>coin</b> (vert),
          2× = <b>fragment</b> (gris), 3× = rien. But : compter combien de vrais 2 € sont tués.
        </p>
      </div>
      <div class="stats">
        <div><span class="big">{{ ejectedCount }}</span><span class="muted"> éjectés / {{ items.length }}</span></div>
        <div class="tally">
          ✅ coins tagués : <b>{{ coinTagged }}</b> (dont <b class="bad">{{ coinEjected }}</b> éjectés)
          · 🩶 fragments : {{ fragTagged }}
        </div>
      </div>
    </header>

    <div class="bar">
      <label><input v-model="onlyEjected" type="checkbox" /> éjectés seulement</label>
      <label><input v-model="onlyBig" type="checkbox" /> gros cercles (r≥{{ bigR }})</label>
      <span class="muted">{{ filtered.length }} affichés · triés par score décroissant</span>
      <button class="lite" @click="load">↻ recharger</button>
    </div>

    <p v-if="error" class="err">{{ error }}</p>
    <p v-else-if="loading" class="muted">Chargement…</p>

    <div v-else class="grid">
      <button
        v-for="it in filtered"
        :key="it.name"
        class="cell"
        :class="[it.ejected ? 'ej' : 'ok', it.verdict ? `v-${it.verdict}` : '']"
        :title="`${it.listing_title || ''}\nscore ${it.score} · r ${it.r} · ${it.source_ref}`"
        @click="cycle(it)"
      >
        <img :src="cropUrl(it)" alt="crop" loading="lazy" />
        <span class="score">{{ it.score.toFixed(2) }}</span>
        <span class="r">r{{ it.r }}</span>
        <span v-if="it.verdict" class="vmark">{{ it.verdict === 'coin' ? '✅' : '🩶' }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.fa { padding: 1.25rem 1.5rem; }
.head { display: flex; justify-content: space-between; gap: 1rem; align-items: flex-start; }
.head h1 { font-size: 1.2rem; margin: 0; }
.sub { color: #777; font-size: 0.83rem; margin: 0.3rem 0 0; max-width: 80ch; }
.stats { text-align: right; white-space: nowrap; }
.stats .big { font-size: 1.5rem; font-weight: 700; }
.muted { color: #999; }
.tally { font-size: 0.82rem; margin-top: 0.3rem; }
.bad { color: #c0392b; }
.bar { display: flex; align-items: center; gap: 1.2rem; margin: 0.9rem 0; font-size: 0.84rem; color: #555; }
.bar label { display: flex; gap: 0.35rem; align-items: center; cursor: pointer; }
.lite { margin-left: auto; border: 1px solid #ddd; background: #fff; border-radius: 7px; padding: 0.3rem 0.7rem; cursor: pointer; }
.err { color: #c0392b; background: #fdecea; padding: 0.6rem 0.9rem; border-radius: 8px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); gap: 8px; }
.cell { position: relative; padding: 0; border: 3px solid #bbb; border-radius: 10px; overflow: hidden; cursor: pointer; background: #111; aspect-ratio: 1; }
.cell img { width: 100%; height: 100%; object-fit: cover; display: block; }
.cell.ej { border-color: #e74c3c; }
.cell.ok { border-color: #27ae60; }
.cell.v-coin { box-shadow: inset 0 0 0 3px #1f9d55; border-color: #1f9d55; }
.cell.v-fragment { opacity: 0.45; }
.score { position: absolute; left: 0; bottom: 0; background: rgba(0,0,0,0.72); color: #fff; font-size: 0.74rem; padding: 1px 5px; border-top-right-radius: 6px; }
.r { position: absolute; right: 0; bottom: 0; background: rgba(0,0,0,0.55); color: #ddd; font-size: 0.66rem; padding: 1px 4px; border-top-left-radius: 6px; }
.vmark { position: absolute; top: 2px; right: 3px; font-size: 0.9rem; }
</style>
