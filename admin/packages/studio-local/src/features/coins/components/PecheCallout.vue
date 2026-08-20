<script setup lang="ts">
// « DINO a repéré N crops pour cette classe » — la porte vers la pêche, posée
// sur la page d'une pièce.
//
// Ce qu'elle répare : jusqu'ici, savoir qu'une classe avait de la matière
// dormante demandait d'ouvrir une cohorte, ou de le deviner. Or la plupart des
// classes pauvres se croisent hors de toute cohorte — c'est là qu'on aimerait
// pouvoir les nourrir, pas trois semaines plus tard quand un préflight refuse.
//
// Elle compte à la MAILLE CLASSE (`design_group_id` d'une courante, `eurio_id`
// d'une commémorative), parce que c'est la maille à laquelle l'entraînement, le
// préflight et la banque raisonnent tous. Une pièce peut avoir un crop et sa
// classe en avoir quarante.
//
// Les trois populations ne sont JAMAIS additionnées : deux sont déjà dans une
// file, la troisième n'est dans aucune — et c'est celle-là qu'un écran ne doit
// pas taire.

import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Loader2 } from 'lucide-vue-next'
import {
  fetchDinoCandidates, type DinoCandidatesSummary,
} from '@/features/review/composables/useReviewApi'
import { reflagAssetsNeedsReview } from '../composables/useCoinAssets'

const props = defineProps<{
  /** La classe de la pièce : son design_group_id, ou son eurio_id à défaut. */
  classId: string
}>()

const summary = ref<DinoCandidatesSummary | null>(null)
const wide = ref<DinoCandidatesSummary | null>(null)   // le même, au Top 3
const loading = ref(false)
const enqueuing = ref(false)
const msg = ref<string | null>(null)

async function load() {
  if (!props.classId) { summary.value = null; wide.value = null; return }
  loading.value = true
  try {
    // Deux lectures : ce que le modèle propose en premier, et ce qu'un filet
    // plus large ramènerait. Montrer les deux évite la conclusion fausse
    // « il n'y a rien » quand il n'y a rien EN TOP-1.
    const [top1, top3] = await Promise.all([
      fetchDinoCandidates(props.classId, { rank: 1 }),
      fetchDinoCandidates(props.classId, { rank: 3 }),
    ])
    summary.value = top1
    wide.value = top3
  } finally {
    loading.value = false
  }
}
watch(() => props.classId, load, { immediate: true })

const nTop1 = computed(
  () => (summary.value ? summary.value.n_open_single + summary.value.n_open_lot : 0),
)
const nTop3 = computed(
  () => (wide.value ? wide.value.n_open_single + wide.value.n_open_lot : 0),
)
const nOrphans = computed(() => summary.value?.n_orphans ?? 0)
/** Rien en top-1, rien en top-3, rien hors file : la classe n'a pas de matière. */
const empty = computed(
  () => summary.value !== null && nTop1.value === 0 && nTop3.value === 0 && nOrphans.value === 0,
)

const router = useRouter()
function fish(rank: number) {
  void router.push({
    path: '/review/peche',
    query: { class: props.classId, dino_rank: String(rank), tri: 'dino' },
  })
}

// Enfiler : une ÉCRITURE, sur ce clic seulement. Elle part au canonique
// (writer unique) — la même route que le re-flag de la galerie juste au-dessus.
async function enqueueOrphans() {
  const ids = summary.value?.orphan_asset_ids ?? []
  if (!ids.length || enqueuing.value) return
  enqueuing.value = true
  msg.value = null
  try {
    const res = await reflagAssetsNeedsReview(ids)
    msg.value = `${res.n_reflagged} crop(s) enfilé(s) — ils sont maintenant pêchables.`
    await load()
  } catch (err) {
    msg.value = `Échec : ${err instanceof Error ? err.message : String(err)}`
  } finally {
    enqueuing.value = false
  }
}
</script>

<template>
  <section v-if="classId && !empty" class="peche">
    <div class="peche__h">
      <span class="eyebrow">Pêche DINO</span>
      <Loader2 v-if="loading" class="h-3 w-3 animate-spin" style="color: var(--ink-400);" />
      <span v-if="summary" class="peche__cls" :title="`Compté à la maille CLASSE : ${summary.bank_class_ids.join(', ')}`">
        {{ classId }}
      </span>
    </div>

    <p v-if="summary" class="peche__txt">
      Le modèle rattache <b>{{ nTop1 }}</b> crop<span v-if="nTop1 > 1">s</span> non validé<span v-if="nTop1 > 1">s</span>
      à cette classe
      <span class="peche__d">({{ summary.n_open_single }} à l'unité · {{ summary.n_open_lot }} en lots)</span>.
      <template v-if="nTop3 > nTop1">
        En élargissant au Top 3, <b>{{ nTop3 }}</b>.
      </template>
      <template v-if="summary.n_training_eligible">
        Cette classe compte déjà <b>{{ summary.n_training_eligible }}</b> photo<span v-if="summary.n_training_eligible > 1">s</span>
        au train.
      </template>
    </p>

    <div class="peche__actions">
      <button v-if="nTop1 > 0" type="button" class="btn btn--go" @click="fish(1)">
        Pêcher {{ nTop1 }} crop<span v-if="nTop1 > 1">s</span>
      </button>
      <button v-if="nTop3 > nTop1" type="button" class="btn" @click="fish(3)">
        Élargir au Top 3 ({{ nTop3 }})
      </button>
      <button
        v-if="nOrphans > 0"
        type="button"
        class="btn btn--warn"
        :disabled="enqueuing"
        :title="`${nOrphans} crop(s) en attente de review qui n'ont AUCUNE ligne de file ouverte : ils n'apparaissent nulle part, ni ici, ni dans la review. Les enfiler les rend tranchables.`"
        @click="enqueueOrphans"
      >
        <Loader2 v-if="enqueuing" class="h-3 w-3 animate-spin" />
        {{ nOrphans }} hors file — enfiler
      </button>
    </div>

    <p v-if="msg" class="peche__msg">{{ msg }}</p>
    <p class="peche__warn">
      Le modèle propose, il ne tranche pas : à marge ≥ 0,10, environ un standard
      sur vingt est faux (mesuré sur 217 crops le 2026-08-20).
    </p>
  </section>
</template>

<style scoped>
.peche {
  margin-top: 20px;
  padding: 14px 16px;
  border: 1px solid var(--surface-3);
  border-radius: 10px;
  background: var(--surface-1);
}
.peche__h { display: flex; align-items: center; gap: 9px; margin-bottom: 8px; }
.eyebrow {
  font-family: var(--font-mono);
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--indigo-700);
}
.peche__cls {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-400);
  cursor: help;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.peche__txt { font-size: 12.5px; color: var(--ink-600); line-height: 1.55; max-width: 66ch; }
.peche__txt b { color: var(--ink); font-weight: 600; }
.peche__d { font-family: var(--font-mono); font-size: 10.5px; color: var(--ink-400); }
.peche__actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 11px; }
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 12.5px;
  padding: 6px 13px;
  border-radius: 7px;
  border: 1px solid var(--ink-200);
  background: var(--surface);
  color: var(--ink);
  cursor: pointer;
}
.btn--go { background: var(--indigo-700); border-color: var(--indigo-700); color: var(--surface); }
.btn--warn { border-color: var(--warning); color: var(--warning); }
.btn:disabled { opacity: 0.45; cursor: not-allowed; }
.btn:focus-visible { outline: 2px solid var(--gold); outline-offset: 1px; }
.peche__msg { margin-top: 9px; font-family: var(--font-mono); font-size: 10.5px; color: var(--indigo-700); }
.peche__warn { margin-top: 9px; font-size: 11px; color: var(--ink-400); max-width: 64ch; line-height: 1.45; }
</style>
