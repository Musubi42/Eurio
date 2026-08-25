<script setup lang="ts">
/**
 * Section « Images d'évaluation » — page coin-detail (juge-et-banc, livrable 5).
 *
 * La fiche pièce montrait les canoniques Numista et les crops d'enrichissement.
 * Il lui manquait **ce qui juge la classe** : les captures device de
 * `scan_corpus.db`, celles sur lesquelles un modèle est NOTÉ. Sans elles, rien
 * à l'écran ne disait sur quoi le r@1 est calculé.
 *
 * Et les montrer ne suffisait pas. Trois dossiers du pull d'avril portaient des
 * slugs morts, tranchés **en regardant la photo** ; une quatrième ligne était
 * fausse (un dossier « 2007 » envoyé vers la pièce de 1999, parce que
 * l'appariement automatique ne distingue pas deux pièces d'un même groupe de
 * dessin). Ce geste s'écrivait dans un dictionnaire Python
 * (`ml/scripts/import_device_pull.py::EXTRA_MAPPING`) ; il se fait ici, sur la
 * photo. Et depuis le 2026-08-25, le PO veut aussi pouvoir dire, par photo, si
 * elle est **exploitable comme juge**.
 *
 * 🔴 GATING AU NIVEAU COMPOSANT — `v-if="HAS_LOCAL_ML_API"`. La route
 * `coins/:eurio_id` n'est PAS `meta.heavy` et ne doit pas le devenir : elle
 * griserait toute la fiche pièce en mode hébergé, alors que seule cette section
 * tape `:8042`.
 */
import { HAS_LOCAL_ML_API } from '@/shared/config/deploy-target'
import { onMounted, ref, watch } from 'vue'

import {
  fetchEvalCaptures,
  remapCapture,
  setEvalDecision,
  type EvalDecision,
  type ScanCapture,
  type ScanCorpusResponse,
} from '../composables/useScanCorpus'
import EvalImagesVue from './EvalImagesVue.vue'

const props = defineProps<{ eurioId: string }>()

const data = ref<ScanCorpusResponse | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const pending = ref<string | null>(null)

async function load() {
  if (!HAS_LOCAL_ML_API) return
  loading.value = true
  error.value = null
  try {
    data.value = await fetchEvalCaptures(props.eurioId)
  } catch (e) {
    data.value = null
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.eurioId, load)

/** Un rechargement complet après chaque geste : les compteurs de tête
 *  (gardées / écartées / à juger) et la maille sont calculés côté API — les
 *  rejouer à la main côté front les ferait dériver en silence. */
async function act(capture: ScanCapture, run: () => Promise<unknown>) {
  if (pending.value) return
  pending.value = capture.capture_id
  error.value = null
  try {
    await run()
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    pending.value = null
  }
}

function onDecide(capture: ScanCapture, decision: EvalDecision) {
  void act(capture, () => setEvalDecision(capture.capture_id, decision))
}

function onRemap(capture: ScanCapture, eurioId: string, reason: string) {
  void act(capture, () => remapCapture(capture.capture_id, eurioId, { reason }))
}
</script>

<template>
  <section v-if="HAS_LOCAL_ML_API" class="mt-6">
    <EvalImagesVue
      :data="data"
      :loading="loading"
      :error="error"
      :pending="pending"
      @decide="onDecide"
      @remap="onRemap"
    />
  </section>
</template>
