<script setup lang="ts">
// Validation humaine du gold denom ambigu (C7 pilier 2, levier #1 du handoff).
// DEUX AXES orthogonaux :
//   A — Dénomination (ce que la probe apprend) : 2€ / indéterminable / pas-2€(kind)
//   B — Qualité du crop : flag "crop pas bon" + raison (exclu du training, feedback détecteur)
// Le verdict humain est persisté côté ML dans state/denom_bench/human_validation.jsonl.
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

const ML_API = 'http://127.0.0.1:8042'

type Tax = { code: string; label: string }
type Item = {
  asset_id: string
  sp: string
  score: number
  seed_label: string
  seed_kind: string | null
  seed_conf: string
  seed_note: string | null
  human_label: string | null
  human_kind: string | null
  human_crop_bad: boolean
  human_crop_reason: string | null
}

const items = ref<Item[]>([])
const negKinds = ref<Tax[]>([])
const cropReasons = ref<Tax[]>([])
const idx = ref(0)
const loading = ref(false)
const error = ref<string | null>(null)
const saving = ref(false)
const hideValidated = ref(false)

// Axe B — état local du crop courant (pré-rempli depuis le verdict humain existant).
const cropBad = ref(false)
const cropReason = ref<string | null>(null)

const current = computed<Item | null>(() => items.value[idx.value] ?? null)
const validatedCount = computed(() => items.value.filter((i) => i.human_label).length)

watch(current, (it) => {
  cropBad.value = it?.human_crop_bad ?? false
  cropReason.value = it?.human_crop_reason ?? null
})

async function load() {
  loading.value = true
  error.value = null
  try {
    const r = await fetch(`${ML_API}/denom-gold/pending`)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const d = await r.json()
    items.value = d.items
    negKinds.value = d.neg_kinds
    cropReasons.value = d.crop_reasons
    const first = items.value.findIndex((i) => !i.human_label)
    idx.value = first >= 0 ? first : 0
  } catch (e) {
    error.value = `ML API non jointe (${ML_API}) — ${e instanceof Error ? e.message : e}`
  } finally {
    loading.value = false
  }
}

function cropUrl(it: Item) {
  return `${ML_API}/denom-gold/crop/${it.asset_id}`
}

function negKindLabel(code: string | null) {
  return negKinds.value.find((k) => k.code === code)?.label ?? code ?? ''
}

// Axe A — commit : POST le verdict dénomination AVEC l'état axe B courant.
async function commit(label: 'pos' | 'neg' | 'unk', kind: string | null = null) {
  const it = current.value
  if (!it || saving.value) return
  saving.value = true
  try {
    const r = await fetch(`${ML_API}/denom-gold/label`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        asset_id: it.asset_id,
        label,
        kind,
        crop_bad: cropBad.value,
        crop_reason: cropBad.value ? cropReason.value : null,
      }),
    })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    it.human_label = label
    it.human_kind = kind
    it.human_crop_bad = cropBad.value
    it.human_crop_reason = cropBad.value ? cropReason.value : null
    next()
  } catch (e) {
    error.value = `Échec sauvegarde — ${e instanceof Error ? e.message : e}`
  } finally {
    saving.value = false
  }
}

function toggleCropBad() {
  cropBad.value = !cropBad.value
  if (!cropBad.value) cropReason.value = null
}

function go(delta: number) {
  const n = items.value.length
  if (!n) return
  idx.value = (idx.value + delta + n) % n
}
function next() {
  const nextUnval = items.value.findIndex((i, k) => k > idx.value && !i.human_label)
  if (nextUnval >= 0) idx.value = nextUnval
  else go(1)
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'ArrowRight') go(1)
  else if (e.key === 'ArrowLeft') go(-1)
  else if (e.key === '1') commit('pos')
  else if (e.key === '3') commit('unk')
  else if (e.key.toLowerCase() === 'b') toggleCropBad()
}

onMounted(() => {
  load()
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="denom-gold">
    <header class="dg-head">
      <div>
        <h1>Validation gold denom — crops ambigus</h1>
        <p class="sub">
          Axe A : <strong>est-ce un 2 € ?</strong> · Axe B : <strong>le crop est-il exploitable ?</strong>
          Les verdicts alimentent la probe dénomination (C7 pilier 2).
          Raccourcis : <kbd>1</kbd> 2€ · <kbd>3</kbd> indéterminable · <kbd>b</kbd> crop pas bon ·
          <kbd>←</kbd>/<kbd>→</kbd>.
        </p>
      </div>
      <div class="progress">
        <span class="big">{{ validatedCount }} / {{ items.length }}</span>
        <span class="muted">validés</span>
      </div>
    </header>

    <p v-if="error" class="err">{{ error }}</p>
    <p v-else-if="loading" class="muted">Chargement…</p>

    <div v-else-if="current" class="card">
      <div class="imgwrap">
        <img :key="current.asset_id" :src="cropUrl(current)" alt="crop" />
      </div>

      <div class="meta">
        <div class="row">
          <span class="pill" :class="`seed-${current.seed_label}`">
            proposé&nbsp;: {{ current.seed_label }}<template v-if="current.seed_kind"> · {{ current.seed_kind }}</template>
          </span>
          <span class="pill ghost">conf {{ current.seed_conf }}</span>
          <span class="pill ghost">bimetal {{ current.score.toFixed(1) }}</span>
          <span v-if="current.human_label" class="pill human">
            ✓ humain&nbsp;: {{ current.human_label }}<template v-if="current.human_kind"> · {{ negKindLabel(current.human_kind) }}</template><template v-if="current.human_crop_bad"> · ⚠ crop</template>
          </span>
        </div>
        <p v-if="current.seed_note" class="note">note (Claude) : {{ current.seed_note }}</p>

        <!-- Axe A — dénomination -->
        <div class="axis">
          <span class="axis-lbl">A · Dénomination</span>
          <div class="actions">
            <button class="btn pos" :disabled="saving" @click="commit('pos')">✓ Vrai 2 €</button>
            <button class="btn unk" :disabled="saving" @click="commit('unk')" title="Impossible de déterminer la dénomination (obscurci, flou, fragment) — PAS « je ne reconnais pas la pièce »">? Indéterminable</button>
          </div>
          <div class="neg-block">
            <span class="muted">✗ Pas un 2 € →</span>
            <button
              v-for="k in negKinds"
              :key="k.code"
              class="btn neg"
              :disabled="saving"
              @click="commit('neg', k.code)"
            >{{ k.label }}</button>
          </div>
        </div>

        <!-- Axe B — qualité du crop -->
        <div class="axis cropq" :class="{ on: cropBad }">
          <span class="axis-lbl">B · Qualité du crop</span>
          <label class="toggle">
            <input type="checkbox" :checked="cropBad" @change="toggleCropBad" />
            ⚠️ Crop pas bon
          </label>
          <div v-if="cropBad" class="reasons">
            <button
              v-for="rsn in cropReasons"
              :key="rsn.code"
              class="chip"
              :class="{ sel: cropReason === rsn.code }"
              @click="cropReason = rsn.code"
            >{{ rsn.label }}</button>
          </div>
          <p class="muted small">
            Un « 2 € mal croppé » reste un 2 € (axe A) mais est exclu du training (axe B).
            Coche avant de cliquer le verdict.
          </p>
        </div>

        <div class="nav">
          <button class="lite" @click="go(-1)">← Précédent</button>
          <span class="muted">{{ idx + 1 }} / {{ items.length }}</span>
          <button class="lite" @click="go(1)">Suivant →</button>
          <label class="chk"><input v-model="hideValidated" type="checkbox" /> masquer validés</label>
        </div>
        <p class="muted small">asset {{ current.asset_id }}</p>
      </div>
    </div>

    <p v-else class="muted">Aucun crop ambigu à valider 🎉</p>
  </div>
</template>

<style scoped>
.denom-gold { padding: 1.5rem; max-width: 980px; margin: 0 auto; }
.dg-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }
.dg-head h1 { font-size: 1.25rem; margin: 0; }
.sub { color: var(--color-text-muted, #777); font-size: 0.85rem; margin: 0.35rem 0 0; max-width: 70ch; }
.sub kbd { background: #eee; border-radius: 4px; padding: 0 5px; font-size: 0.8em; }
.progress { text-align: right; white-space: nowrap; }
.progress .big { font-size: 1.4rem; font-weight: 700; }
.progress .muted { display: block; font-size: 0.75rem; }
.muted { color: var(--color-text-muted, #888); }
.small { font-size: 0.72rem; }
.err { color: #c0392b; background: #fdecea; padding: 0.6rem 0.9rem; border-radius: 8px; }
.card { display: grid; grid-template-columns: 360px 1fr; gap: 1.5rem; margin-top: 1.25rem; align-items: start; }
.imgwrap { background: #111; border-radius: 12px; display: flex; align-items: center; justify-content: center; aspect-ratio: 1; overflow: hidden; }
.imgwrap img { width: 100%; height: 100%; object-fit: contain; }
.row { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.pill { font-size: 0.78rem; padding: 0.2rem 0.6rem; border-radius: 999px; background: #eee; }
.pill.ghost { background: #f4f4f5; color: #666; }
.pill.human { background: #1f9d55; color: #fff; }
.seed-pos { background: #d6f5e0; color: #1f7a44; }
.seed-neg { background: #fde2e1; color: #b03a36; }
.seed-unk { background: #fdf0d5; color: #97650a; }
.note { font-size: 0.8rem; color: #777; margin: 0.5rem 0 0; }
.axis { margin-top: 1.1rem; padding: 0.8rem 0.9rem; border: 1px solid #ececec; border-radius: 10px; }
.axis-lbl { display: block; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em; color: #999; margin-bottom: 0.55rem; }
.actions { display: flex; gap: 0.6rem; }
.neg-block { display: flex; flex-wrap: wrap; align-items: center; gap: 0.45rem; margin-top: 0.7rem; }
.btn { border: none; border-radius: 8px; padding: 0.55rem 1rem; font-weight: 600; cursor: pointer; font-size: 0.9rem; }
.btn:disabled { opacity: 0.5; cursor: default; }
.btn.pos { background: #1f9d55; color: #fff; }
.btn.unk { background: #e7c64b; color: #333; }
.btn.neg { background: #f0d4d2; color: #92302c; padding: 0.4rem 0.7rem; font-size: 0.82rem; }
.cropq.on { border-color: #e0a800; background: #fffaf0; }
.toggle { display: inline-flex; align-items: center; gap: 0.4rem; font-weight: 600; font-size: 0.9rem; cursor: pointer; }
.reasons { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.6rem; }
.chip { border: 1px solid #ddd; background: #fff; border-radius: 999px; padding: 0.3rem 0.7rem; font-size: 0.8rem; cursor: pointer; }
.chip.sel { background: #e0a800; color: #fff; border-color: #e0a800; }
.nav { display: flex; align-items: center; gap: 1rem; margin-top: 1.3rem; }
.lite { background: transparent; border: 1px solid #ddd; border-radius: 8px; padding: 0.35rem 0.8rem; cursor: pointer; }
.chk { font-size: 0.78rem; color: #777; margin-left: auto; display: flex; gap: 0.3rem; align-items: center; }
</style>
