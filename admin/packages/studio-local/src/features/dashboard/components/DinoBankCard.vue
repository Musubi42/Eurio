<script setup lang="ts">
/**
 * « Où en est la banque DINO », sur l'accueil ADMIN.
 *
 * Elle répond à une seule question, celle qu'on se pose vraiment devant cet
 * écran : **est-ce que ça vaut le coup de relancer maintenant ?** D'où un
 * chiffre mis en avant — le travail humain accumulé depuis le dernier build —
 * et pas une « santé sur 100 » qui ne dirait quoi faire de rien.
 *
 * TROIS ÉTATS, JAMAIS CONFONDUS
 * ------------------------------
 * « à jour », « en retard de N », et « jamais bâtie ». Le troisième est le pire,
 * et c'est celui qu'un compteur à zéro déguiserait en premier. Le backend le
 * distingue déjà (`is_stale` est vrai quand `built_at` est nul) ; la carte le
 * dit avec ses mots.
 *
 * LE DROIT DESSINE, LA MACHINE ACTIVE
 * ------------------------------------
 * `showHeavyGesture` (scope `review:arbitrate`) décide qu'on affiche le bouton ;
 * `canRunHeavy` (l'API ML locale répond) décide qu'il est cliquable. Masquer
 * n'est pas désarmer — cf. `useHeavyGate`, corrigé en revue le 2026-08-24.
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Database, Loader2, RefreshCw, AlertTriangle } from 'lucide-vue-next'

import { useHeavyGate } from '@/shared/composables/useHeavyGate'
import {
  fetchDinoDrift,
  fetchRebuildStatus,
  startDinoRebuild,
  type DinoDrift,
  type RebuildStatus,
} from '../api/dino'

const { canRunHeavy, showHeavyGesture } = useHeavyGate()

const drift = ref<DinoDrift | null>(null)
const driftError = ref<string | null>(null)
const job = ref<RebuildStatus | null>(null)
const starting = ref(false)
const startError = ref<string | null>(null)

const running = computed(() => job.value?.status === 'running')

async function loadDrift() {
  try {
    drift.value = await fetchDinoDrift()
    driftError.value = null
  } catch (e) {
    // On n'affiche PAS un écart de zéro quand on n'a pas pu mesurer : « à
    // jour » et « je ne sais pas » se liraient pareil, et c'est exactement la
    // panne muette qu'on essaie d'éviter ici.
    drift.value = null
    driftError.value = e instanceof Error ? e.message : String(e)
  }
}

async function loadJob() {
  job.value = await fetchRebuildStatus()
}

async function onRebuild() {
  starting.value = true
  startError.value = null
  try {
    job.value = await startDinoRebuild()
  } catch (e) {
    startError.value = e instanceof Error ? e.message : String(e)
  } finally {
    starting.value = false
  }
}

// Poll uniquement pendant qu'un job tourne, et on recharge l'écart à la fin :
// c'est le seul moment où il change de lui-même.
let timer: ReturnType<typeof setInterval> | null = null
// 🔴 L'intervalle est posé AVANT le premier chargement, et un drapeau garde le
// démontage. Créé après l'`await`, il échappait à `onUnmounted` quand on
// quittait la page pendant les deux requêtes initiales : un poll de 3 s fuyait
// alors sur un composant mort, pour le reste de la vie de l'onglet.
let unmounted = false
onMounted(() => {
  timer = setInterval(async () => {
    if (unmounted || !running.value) return
    const avant = job.value?.status
    await loadJob()
    if (avant === 'running' && job.value?.status !== 'running') await loadDrift()
  }, 3000)
  void Promise.all([loadDrift(), loadJob()])
})
onUnmounted(() => {
  unmounted = true
  if (timer) clearInterval(timer)
})

const bati = computed(() => {
  const at = drift.value?.built_at
  if (!at) return null
  const d = new Date(at)
  return Number.isNaN(d.getTime()) ? at : d.toLocaleString('fr-FR')
})

const etapeLabel: Record<string, string> = {
  anchors: 'reconstruction des ancres',
  predictions: 'recalcul des prédictions',
  done: 'terminé',
}

// ─── Progression et temps restant ──────────────────────────────────────────
//
// Le rebuild dure ~1 h en deux étapes, et rien ne le disait : le canonique ne
// voit rien (le backfill pousse à la FIN), et le journal du job vit sur la
// machine de calcul. Un job d'une heure sans signal est indiscernable d'un job
// bloqué — mesuré le 2026-08-24, il a fallu `lsof` sur le processus pour
// retrouver sa base scratch et y compter les lignes. Le worker écrit donc sa
// progression en base, et c'est elle qu'on lit ici.
const pourcent = computed(() => {
  const j = job.value
  if (!j?.n_total || !j.n_done) return null
  return Math.min(100, Math.round((j.n_done / j.n_total) * 100))
})

/** Temps restant, extrapolé de la cadence OBSERVÉE sur cette étape.
 *
 * Pas d'estimation a priori : la cadence dépend de la machine et de l'encodeur
 * (mesuré 157 ms/crop sur ce Mac en vitl14, quand la doc annonçait 84 ms). Une
 * durée annoncée d'avance qui se trompe du simple au double vaut moins que pas
 * de durée du tout. Ici on ne promet rien tant qu'on n'a pas vu le job avancer.
 */
const restant = computed<string | null>(() => {
  const j = job.value
  if (!j?.n_total || !j.n_done || !j.started_at) return null
  const debut = Date.parse(j.started_at.replace(' ', 'T') + 'Z')
  if (Number.isNaN(debut)) return null
  const ecoule = (Date.now() - debut) / 1000
  if (ecoule < 20 || j.n_done < 50) return null   // trop tôt pour extrapoler
  const parCrop = ecoule / j.n_done
  const secondes = (j.n_total - j.n_done) * parCrop
  if (secondes < 60) return 'moins d\'une minute'
  return `~${Math.round(secondes / 60)} min`
})
</script>

<template>
  <section
    class="rounded-lg border px-4 py-3"
    :style="{ borderColor: 'var(--surface-3)', background: 'var(--surface)' }"
  >
    <header class="flex items-baseline justify-between gap-3">
      <p
        class="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--indigo-700);"
      >
        <Database class="h-3 w-3" />
        Banque DINO
      </p>
      <p v-if="drift" class="font-mono text-[10px]" style="color: var(--ink-400);">
        {{ drift.anchors_kind }} · {{ drift.encoder_version }}
      </p>
    </header>

    <!-- Mesure impossible : on le DIT, on ne montre pas un zéro rassurant. -->
    <p
      v-if="driftError"
      class="mt-2 inline-flex items-start gap-1.5 text-[11px]"
      style="color: var(--gold-600);"
    >
      <AlertTriangle class="mt-0.5 h-3 w-3 shrink-0" />
      Écart non mesurable — {{ driftError }}
    </p>

    <template v-else-if="drift">
      <p
        v-if="!drift.built_at"
        class="mt-2 text-[13px] font-semibold"
        style="color: var(--gold-600);"
      >
        Jamais bâtie sur cette base.
      </p>
      <template v-else>
        <p class="mt-2 flex items-baseline gap-2">
          <span
            class="font-display text-2xl font-semibold tabular-nums"
            :style="{ color: drift.is_stale ? 'var(--gold-600)' : 'var(--ink)' }"
          >{{ drift.n_crops_validated_since }}</span>
          <span class="text-[12px]" style="color: var(--ink-500);">
            crops triés depuis le dernier build
            <template v-if="drift.n_classes_touched_since">
              · {{ drift.n_classes_touched_since }} classes
            </template>
          </span>
        </p>
        <ul class="mt-1.5 flex flex-col gap-0.5 text-[11px]" style="color: var(--ink-500);">
          <li v-if="drift.n_predictions_stale">
            <strong>{{ drift.n_predictions_stale }}</strong> prédictions répondent sur
            une banque qui n'existe plus
          </li>
          <li v-if="drift.n_assets_without_prediction">
            <strong>{{ drift.n_assets_without_prediction }}</strong> crops sans aucune
            prédiction
          </li>
          <li v-if="!drift.is_stale" style="color: var(--success);">
            À jour — rien à gagner à relancer.
          </li>
        </ul>

        <!-- Séparé de la liste ci-dessus, et c'est délibéré : ces classes ne se
             réparent PAS par un rebuild. Leurs crops sont écartés par le
             plancher de similarité — le modèle ne les reconnaît pas comme les
             leurs. C'est un sujet d'enrichissement, pas de bouton. Mélangé aux
             autres, ce nombre réclamerait à vie une heure de calcul sans effet. -->
        <p
          v-if="drift.n_classes_would_gain_anchor"
          class="mt-1.5 text-[11px]"
          style="color: var(--ink-400);"
        >
          <strong>{{ drift.n_classes_would_gain_anchor }}</strong> classes ont des
          photos validées qu'aucune ancre ne porte — leurs crops ressemblent trop
          peu à leur canonique. Un rebuild n'y change rien.
        </p>
        <p class="mt-1.5 font-mono text-[10px]" style="color: var(--ink-400);">
          build {{ drift.build_id?.slice(0, 12) }} · {{ bati }} ·
          {{ drift.n_classes }} classes / {{ drift.n_rows }} ancres
        </p>
      </template>
    </template>

    <p v-else class="mt-2 text-[11px]" style="color: var(--ink-400);">…chargement.</p>

    <!-- Le geste. Dessiné par le DROIT, activé par la MACHINE. -->
    <div v-if="showHeavyGesture" class="mt-3 flex flex-wrap items-center gap-2">
      <button
        type="button"
        class="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider transition-colors disabled:cursor-not-allowed disabled:opacity-45"
        :style="{ background: 'var(--indigo-700)', color: 'var(--surface)' }"
        :disabled="!canRunHeavy || running || starting"
        :title="canRunHeavy
          ? 'Rebâtit les ancres puis recalcule les prédictions (~20 min)'
          : 'Disponible seulement sur la machine qui fait tourner l\'API ML locale'"
        @click="onRebuild"
      >
        <Loader2 v-if="running || starting" class="h-3 w-3 animate-spin" />
        <RefreshCw v-else class="h-3 w-3" />
        {{ running ? 'rebuild en cours' : 'relancer le rebuild' }}
      </button>

      <span v-if="running && job?.step" class="text-[11px]" style="color: var(--ink-500);">
        {{ etapeLabel[job.step] ?? job.step }}
        <template v-if="pourcent !== null">
          · <span class="font-mono tabular-nums">{{ job.n_done }} / {{ job.n_total }}</span>
          <span v-if="restant"> · {{ restant }}</span>
        </template>
        <template v-else>…</template>
      </span>
      <span
        v-else-if="job?.status === 'failed'"
        class="inline-flex items-center gap-1 text-[11px]"
        style="color: var(--danger);"
      >
        <AlertTriangle class="h-3 w-3" /> dernier rebuild en échec — {{ job.error }}
      </span>
      <span
        v-else-if="job?.status === 'done' && job.build_id"
        class="font-mono text-[10px]"
        style="color: var(--success);"
      >
        dernier rebuild OK · {{ job.n_anchors }} ancres
      </span>
      <span v-else-if="!canRunHeavy" class="text-[11px]" style="color: var(--ink-400);">
        machine de calcul éteinte — le chiffre reste juste, le geste attend.
      </span>

      <span v-if="startError" class="text-[11px]" style="color: var(--danger);">
        {{ startError }}
      </span>
    </div>

    <!-- La barre, en pleine largeur sous la ligne d'état. Absente tant que le
         worker n'a rien reporté : une barre à 0 % qui ne bouge pas est pire
         qu'une absence de barre — elle affirme un avancement nul. -->
    <div
      v-if="running && pourcent !== null"
      class="mt-2 h-1 w-full overflow-hidden rounded-full"
      style="background: var(--surface-1);"
    >
      <div
        class="h-full rounded-full transition-[width] duration-700"
        :style="{ width: `${pourcent}%`, background: 'var(--indigo-700)' }"
      />
    </div>
  </section>
</template>
