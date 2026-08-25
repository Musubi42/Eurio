<script setup lang="ts">
/**
 * Le RENDU de la section « images d'évaluation » — sans réseau, sans gating.
 *
 * Séparé de `EvalImagesSection.vue` pour une seule raison : la maquette
 * (`/coins/eval-images/maquette`) monte CE composant sur fixtures. Ce qu'on y
 * regarde est donc ce qu'on livre — c'est la discipline d'un écran d'admin
 * (l'intention de R1 sans le détour par le proto, qui ne couvre que l'app
 * Android).
 *
 * Deux gestes par photo, et ils ne disent pas la même chose :
 *  - **remap** — cette photo montre une autre pièce (un FAIT à corriger) ;
 *  - **garder / écarter** — cette photo est-elle exploitable comme juge (un
 *    AVIS). Distinct de `class_level_only`, qui est un fait sur le label.
 *
 * ⚠️ Les captures sont rendues MÉLANGÉES, un seul pool. `bundle_source` est
 * affiché en détail sur la vignette comme PROVENANCE, jamais comme axe de
 * regroupement (décision PO du 2026-08-25).
 */
import {
  Ban,
  CalendarClock,
  CheckCircle2,
  ImageOff,
  Loader2,
  Microscope,
  PencilLine,
  RotateCcw,
} from 'lucide-vue-next'
import { computed, ref } from 'vue'

import type { EvalDecision, ScanCapture, ScanCorpusResponse } from '../composables/useScanCorpus'

const props = defineProps<{
  data: ScanCorpusResponse | null
  loading: boolean
  error: string | null
  /** `capture_id` dont une action est en vol (vignette désactivée). */
  pending: string | null
}>()

const emit = defineEmits<{
  (e: 'decide', capture: ScanCapture, decision: EvalDecision): void
  (e: 'remap', capture: ScanCapture, eurioId: string, reason: string): void
}>()

/** `capture_id` dont le formulaire de remap est ouvert. */
const remapOpen = ref<string | null>(null)
const remapTarget = ref('')
const remapReason = ref('')
/** `capture_id` dont on regarde le RAW plutôt que le crop. */
const showRaw = ref<Set<string>>(new Set())

const captures = computed(() => props.data?.captures ?? [])

function openRemap(c: ScanCapture) {
  remapOpen.value = remapOpen.value === c.capture_id ? null : c.capture_id
  remapTarget.value = c.eurio_id
  remapReason.value = ''
}

function submitRemap(c: ScanCapture) {
  const target = remapTarget.value.trim()
  if (!target || target === c.eurio_id) return
  emit('remap', c, target, remapReason.value.trim())
  remapOpen.value = null
}

function toggleRaw(c: ScanCapture) {
  const next = new Set(showRaw.value)
  if (next.has(c.capture_id)) next.delete(c.capture_id)
  else next.add(c.capture_id)
  showRaw.value = next
}

function imageFor(c: ScanCapture): string {
  return showRaw.value.has(c.capture_id) ? c.raw_url : c.crop_url
}

function borderColor(c: ScanCapture): string {
  if (c.eval_decision === 'exclude') return 'var(--danger)'
  if (c.eval_decision === 'keep') return 'var(--success)'
  if (c.class_level_only || !c.is_exact_match) return 'var(--warning)'
  return 'var(--surface-3)'
}

/** Date lisible ; ⚠️ heure LOCALE du device, sans fuseau — on ne fabrique pas
 *  un `Z` qu'on ne sait pas vrai, donc on n'affiche pas de fuseau non plus. */
function shortDate(iso: string): string {
  return iso.replace('T', ' ').slice(0, 16)
}
</script>

<template>
  <div>
    <header class="mb-2 flex flex-wrap items-center gap-2">
      <Microscope class="h-4 w-4" style="color: var(--indigo-700);" />
      <h3 class="font-display text-sm italic font-semibold" style="color: var(--indigo-700);">
        Images d'évaluation
      </h3>
      <span
        v-if="data && data.n_captures > 0"
        class="text-xs" style="color: var(--ink-400);"
        title="Les photos device sur lesquelles un modèle est NOTÉ pour cette classe. Ce ne sont ni des canoniques Numista, ni des crops d'enrichissement."
      >{{ data.n_captures }} photo{{ data.n_captures > 1 ? 's' : '' }}
        · classe <span class="font-mono">{{ data.class_id }}</span></span>
      <span
        v-if="data && data.n_captures > 0"
        class="text-[11px]" style="color: var(--ink-400);"
      >
        <span style="color: var(--success);">{{ data.n_kept }} gardée(s)</span> ·
        <span style="color: var(--danger);">{{ data.n_excluded }} écartée(s)</span> ·
        {{ data.n_undecided }} à juger
      </span>
    </header>

    <!-- La maille, dite à l'écran. Sans ça la section montre les photos d'une
         pièce sous le nom d'une autre. -->
    <p
      v-if="data && data.scope === 'design_group'"
      class="mb-2 rounded-md border px-3 py-2 text-[11px]"
      style="border-color: var(--warning); background: color-mix(in srgb, var(--warning) 6%, var(--surface)); color: var(--ink-200);"
    >
      {{ data.scope_note }}
      <span style="color: var(--ink-400);">
        ({{ data.n_exact_match }}/{{ data.n_captures }} montrent cette pièce précise)
      </span>
    </p>

    <!-- Loading -->
    <p v-if="loading" class="flex items-center gap-2 text-xs" style="color: var(--ink-400);">
      <Loader2 class="h-3.5 w-3.5 animate-spin" /> Chargement…
    </p>

    <!-- Error -->
    <p
      v-else-if="error"
      class="rounded-md border px-3 py-2 text-[11px]"
      style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);"
    >
      {{ error }}
    </p>

    <!-- Empty -->
    <p
      v-else-if="!captures.length"
      class="flex items-center gap-1.5 text-[11px]"
      style="color: var(--ink-400);"
    >
      <ImageOff class="h-3.5 w-3.5" />
      Aucune photo d'évaluation pour cette classe — elle n'est jugée par aucune
      capture device.
    </p>

    <!-- Vignettes : UN SEUL POOL, mélangé. Aucun regroupement par protocole. -->
    <template v-else>
      <p class="mb-2 text-[11px]" style="color: var(--ink-400);">
        Un seul pool d'évaluation, toutes séances confondues.
        <span style="color: var(--success);">Garder</span> /
        <span style="color: var(--danger);">écarter</span> = cette photo est-elle
        exploitable comme juge. <b>Remapper</b> = elle montre une autre pièce.
      </p>
      <div class="flex flex-wrap gap-2.5">
        <div
          v-for="c in captures"
          :key="c.capture_id"
          class="w-36 overflow-hidden rounded-md border"
          :style="{
            borderColor: borderColor(c),
            opacity: c.eval_decision === 'exclude' ? 0.55 : 1,
          }"
        >
          <button
            type="button"
            class="relative block h-36 w-36"
            style="background: var(--surface-1);"
            :title="showRaw.has(c.capture_id) ? 'Photo brute — clic pour revoir le crop' : 'Crop normalisé — clic pour voir la photo brute'"
            @click="toggleRaw(c)"
          >
            <img
              :src="imageFor(c)"
              loading="lazy"
              class="h-full w-full object-cover"
              :style="{ filter: c.eval_decision === 'exclude' ? 'grayscale(1)' : 'none' }"
            />
            <span
              class="absolute left-0 top-0 rounded-br-md px-1 text-[10px] font-semibold text-white"
              style="background: rgba(14,14,31,.65);"
            >{{ c.condition }}</span>
            <span
              v-if="showRaw.has(c.capture_id)"
              class="absolute right-0 top-0 rounded-bl-md px-1 text-[10px] font-semibold text-white"
              style="background: rgba(14,14,31,.65);"
            >raw</span>
          </button>

          <div class="px-1.5 py-1">
            <!-- Le FAIT : ce label ne vaut qu'à la classe -->
            <p
              v-if="c.class_level_only"
              class="text-[10px] font-medium"
              style="color: var(--warning);"
              title="Juste à la CLASSE, faux à la PIÈCE : le référentiel ne possède pas la pièce montrée. À exclure d'une notation stricte à la pièce."
            >⚠ classe seule</p>
            <p
              v-else-if="!c.is_exact_match"
              class="truncate text-[10px]"
              style="color: var(--warning);"
              :title="`Autre pièce du même groupe de dessin : ${c.eurio_id}`"
            >autre pièce du groupe</p>

            <!-- L'AVIS -->
            <p
              v-if="c.eval_decision"
              class="text-[10px] font-medium"
              :style="{ color: c.eval_decision === 'keep' ? 'var(--success)' : 'var(--danger)' }"
              :title="c.eval_decision_reason ?? ''"
            >
              {{ c.eval_decision === 'keep' ? 'gardée' : 'écartée' }}
              <span v-if="c.eval_decision_by" style="color: var(--ink-400);">
                · {{ c.eval_decision_by }}</span>
            </p>

            <!-- PROVENANCE : d'où vient la photo. Pas un axe d'analyse. -->
            <p
              class="mt-0.5 flex items-center gap-1 truncate text-[10px]"
              style="color: var(--ink-400);"
              :title="`Provenance : ${c.bundle_source ?? '∅'} · normaliseur ${c.normalize_method ?? '∅'} · ${c.captured_at}`"
            >
              <CalendarClock class="h-3 w-3 flex-shrink-0" />
              {{ shortDate(c.captured_at) }}
            </p>
            <p class="truncate font-mono text-[10px]" style="color: var(--ink-500);">
              {{ c.bundle_source ?? '∅' }} · {{ c.normalize_method ?? '∅' }}
            </p>

            <div class="mt-1 flex flex-wrap gap-1">
              <button
                v-if="c.eval_decision !== 'keep'"
                type="button" class="ev-btn ev-btn--keep" :disabled="pending === c.capture_id"
                title="Garder : photo exploitable comme juge"
                @click="emit('decide', c, 'keep')"
              ><CheckCircle2 class="h-3 w-3" /> garder</button>
              <button
                v-if="c.eval_decision !== 'exclude'"
                type="button" class="ev-btn ev-btn--ban" :disabled="pending === c.capture_id"
                title="Écarter : photo inexploitable comme juge (cadrage raté, pièce illisible, doublon)"
                @click="emit('decide', c, 'exclude')"
              ><Ban class="h-3 w-3" /> écarter</button>
              <button
                v-if="c.eval_decision"
                type="button" class="ev-btn" :disabled="pending === c.capture_id"
                title="Rouvrir l'avis (retour à « à juger »)"
                @click="emit('decide', c, null)"
              ><RotateCcw class="h-3 w-3" /> rouvrir</button>
              <button
                type="button" class="ev-btn" :disabled="pending === c.capture_id"
                title="Remapper : cette photo montre une autre pièce"
                @click="openRemap(c)"
              ><PencilLine class="h-3 w-3" /> remap</button>
            </div>

            <form
              v-if="remapOpen === c.capture_id"
              class="mt-1 flex flex-col gap-1"
              @submit.prevent="submitRemap(c)"
            >
              <input
                v-model="remapTarget" class="ev-input font-mono"
                placeholder="eurio_id cible" spellcheck="false"
              />
              <input v-model="remapReason" class="ev-input" placeholder="raison (journalisée)" />
              <button type="submit" class="ev-btn ev-btn--keep" :disabled="pending === c.capture_id">
                réattribuer
              </button>
              <p class="text-[10px]" style="color: var(--ink-400);">
                Refusé si l'<span class="font-mono">eurio_id</span> n'existe pas au référentiel.
              </p>
            </form>

            <p
              v-if="c.decisions.length"
              class="mt-1 text-[10px]" style="color: var(--ink-400);"
              :title="c.decisions.map((d) => `${d.decided_at} · ${d.kind} · ${d.old_value ?? '∅'} → ${d.new_value ?? '∅'} · ${d.decided_by ?? '?'}${d.reason ? ' · ' + d.reason : ''}`).join('\n')"
            >{{ c.decisions.length }} décision(s) journalisée(s)</p>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.ev-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 5px;
  border: 1px solid var(--surface-3);
  border-radius: 4px;
  font-size: 10px;
  color: var(--ink-500);
  background: var(--surface);
}
.ev-btn:disabled { opacity: 0.5; }
.ev-btn--keep:hover { border-color: var(--success); color: var(--success); }
.ev-btn--ban:hover { border-color: var(--danger); color: var(--danger); }
.ev-input {
  width: 100%;
  padding: 2px 4px;
  border: 1px solid var(--surface-3);
  border-radius: 4px;
  font-size: 10px;
  color: var(--ink-200);
  background: var(--surface);
}
</style>
