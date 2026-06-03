<script setup lang="ts">
// Colonne droite partagée par SingleReviewView et les pages lot.
// Affiche : la pièce proposée (theme-match, source_images.target_eurio_id)
// en haut, puis selon
// le mode : (auto) Top N candidats + DinoSuggestions + badge sélection
// libre + hint si aucun candidat ; (free) FreeSelectorPanel inline.
//
// Props normalisées pour qu'un crop lot puisse alimenter le même
// composant que la queue single (cf. Chunk 2 du refacto unifié).

import type { ReviewCandidate } from '../composables/useReviewApi'
import type { CoinSearchEntry } from '../composables/useCoinsSearch'
import type { DinoSuggestion } from '../composables/useDinoSuggestions'
import CandidateRow from './CandidateRow.vue'
import DinoSuggestions from './DinoSuggestions.vue'
import FreeSelectorPanel from './FreeSelectorPanel.vue'

defineProps<{
  /** Pièce proposée par le theme-match (pré-sélectionnée par défaut).
   *  Null si le matcher n'a pas tranché (verdict ambigu) ou source legacy
   *  (scans manuels). */
  target: ReviewCandidate | null
  /** Top N candidats auto-name. */
  candidates: ReviewCandidate[]
  /** Pièces du groupe (2 € commémo, même pays + année) — affichées
   *  quand il n'y a pas de proposition (verdict theme-match ambigu).
   *  Optionnel : la page lot ne les passe pas. */
  groupCandidates?: ReviewCandidate[]
  /** Mode de la colonne — 'auto' affiche Top N + Dino, 'free' affiche
   *  le FreeSelectorPanel inline. */
  mode: 'auto' | 'free'
  /** Index du candidat Top N actuellement focused (null = aucun ou
   *  c'est la cible qui est focused). */
  focusedCandidateIdx: number | null
  /** Sélection libre en attente (affichée comme badge en mode auto si
   *  ≠ cible). Forme minimale {eurio_id, label}. */
  freeSearchCandidate: { eurio_id: string; label: string } | null
  /** L'un OU l'autre pour DinoSuggestions selon le contexte (single
   *  utilise reviewId, lot utilise assetId). */
  reviewId?: string | null
  assetId?: string | null
  /** eurio_id assigné au crop actif (contexte lot uniquement).
   *  Quand fournie, l'item correspondant apparaît "sélectionné/validé"
   *  (fond vert + icône check). Non fourni = comportement single inchangé. */
  assignedEurioId?: string | null
}>()

const emit = defineEmits<{
  (e: 'target-focus'): void
  (e: 'candidate-focus', idx: number): void
  (e: 'dino-select', suggestion: DinoSuggestion): void
  (e: 'free-select', entry: CoinSearchEntry): void
  (e: 'group-select', candidate: ReviewCandidate): void
}>()
</script>

<template>
  <aside class="flex min-h-0 flex-col overflow-hidden">
    <!-- Pièce proposée : la pièce attribuée au listing par le theme-match.
         Toujours affichée (mode-agnostic), pré-sélectionnée par défaut.
         ~80 % des reviews valident la proposition → un clic gagné.
         Si assignedEurioId == target.eurio_id → overlay "validé" vert. -->
    <section
      v-if="target"
      class="mb-3 flex flex-col gap-1.5"
    >
      <p
        class="flex items-baseline justify-between font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--gold-600);"
      >
        <span>Pièce proposée</span>
        <span class="opacity-60">attribuée au listing</span>
      </p>
      <!-- Wrapper "assigné" : fond + bordure vert quand cette cible est l'assignation active -->
      <div
        class="relative rounded-md transition-all duration-150"
        :class="{ 'assigned-highlight': assignedEurioId === target.eurio_id }"
        :style="assignedEurioId === target.eurio_id ? {
          outline: '2px solid var(--success)',
          outlineOffset: '1px',
          borderRadius: '8px',
        } : {}"
      >
        <CandidateRow
          :candidate="target"
          :index="0"
          :badge="assignedEurioId === target.eurio_id ? '✓' : '★'"
          :focused="freeSearchCandidate?.eurio_id === target.eurio_id"
          :assigned="assignedEurioId === target.eurio_id"
          @focus="emit('target-focus')"
        />
      </div>
    </section>

    <!-- Mode AUTO : Top N + Dino + freeSearchCandidate banner -->
    <template v-if="mode === 'auto'">
      <div class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
        <!-- Pièces du groupe : quand le theme-match n'a pas tranché
             (verdict ambigu → pas de proposition), toutes les sœurs
             commémo du groupe (dénom, pays, année) sont sélectionnables
             d'un clic — évite la recherche libre. -->
        <section
          v-if="!target && (groupCandidates?.length ?? 0) > 0"
          class="flex flex-col gap-2"
        >
          <p
            class="flex items-baseline justify-between font-mono text-[10px] uppercase tracking-wider"
            style="color: var(--gold-600);"
          >
            <span>Pièces du groupe</span>
            <span class="opacity-60">theme-match indécis</span>
          </p>
          <CandidateRow
            v-for="c in groupCandidates"
            :key="'grp-' + c.eurio_id"
            :candidate="c"
            :index="0"
            badge="◆"
            :focused="freeSearchCandidate?.eurio_id === c.eurio_id"
            @focus="emit('group-select', c)"
          />
        </section>

        <p
          class="flex items-baseline justify-between font-mono text-[10px] uppercase tracking-wider"
          style="color: var(--ink-500);"
        >
          <span>
            <span style="color: var(--indigo-700);">Top {{ candidates.length }}</span>
            <span class="ml-1 opacity-60">candidats auto-name</span>
          </span>
          <span class="opacity-60">1 – 5</span>
        </p>

        <div class="flex flex-col gap-2">
          <!-- Wrapper "assigné" par candidat : highlight vert si assignedEurioId correspond -->
          <div
            v-for="(c, idx) in candidates"
            :key="c.eurio_id + idx"
            class="relative rounded-md transition-all duration-150"
            :style="[
              { animation: `fade-in 200ms ease-out ${idx * 30}ms backwards` },
              assignedEurioId === c.eurio_id ? {
                outline: '2px solid var(--success)',
                outlineOffset: '1px',
                borderRadius: '8px',
              } : {},
            ]"
          >
            <CandidateRow
              :candidate="c"
              :index="idx"
              :focused="focusedCandidateIdx === idx && !freeSearchCandidate"
              :assigned="assignedEurioId === c.eurio_id"
              @focus="emit('candidate-focus', idx)"
            />
          </div>
        </div>

        <DinoSuggestions
          v-if="reviewId"
          :review-id="reviewId"
          variant="standard"
          :assigned-eurio-id="assignedEurioId"
          @select="(s) => emit('dino-select', s)"
        />
        <DinoSuggestions
          v-else-if="assetId"
          :asset-id="assetId"
          variant="standard"
          :assigned-eurio-id="assignedEurioId"
          @select="(s) => emit('dino-select', s)"
        />

        <article
          v-if="freeSearchCandidate && freeSearchCandidate.eurio_id !== target?.eurio_id"
          class="mt-2 rounded-md border-2 border-dashed px-3 py-2"
          :style="{
            borderColor: 'var(--gold-600)',
            background: 'color-mix(in srgb, var(--gold-600) 6%, var(--surface))',
          }"
        >
          <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--gold-600);">
            Sélection libre
          </p>
          <p class="mt-1 font-mono text-[12px]" style="color: var(--ink);">
            {{ freeSearchCandidate.eurio_id }}
          </p>
          <p class="mt-0.5 text-[11px]" style="color: var(--ink-500);">
            {{ freeSearchCandidate.label }}
          </p>
        </article>

        <p
          v-if="!candidates.length"
          class="rounded-md border-2 border-dashed px-4 py-6 text-center text-[12px]"
          style="border-color: var(--surface-3); color: var(--ink-400);"
        >
          Pas de candidat auto.<br />
          Touche <kbd
            class="mx-1 inline-block rounded px-1.5 py-0.5 font-mono text-[10px]"
            style="background: var(--surface-1); border: 1px solid var(--surface-3);"
          >F</kbd> pour la sélection libre.
        </p>
      </div>
    </template>

    <!-- Mode LIBRE : cascade pays/dénom/année + résultats inline -->
    <template v-else>
      <FreeSelectorPanel
        class="min-h-0 flex-1"
        @select="(e) => emit('free-select', e)"
      />
    </template>
  </aside>
</template>
