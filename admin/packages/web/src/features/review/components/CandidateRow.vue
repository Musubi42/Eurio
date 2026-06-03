<script setup lang="ts">
import { CheckCircle2 } from 'lucide-vue-next'
import type { ReviewCandidate } from '../composables/useReviewApi'

defineProps<{
  candidate: ReviewCandidate
  index: number
  focused: boolean
  /** Override le numéro raccourci par un libellé court (ex. "★" pour la
   *  cible eBay). Le score à droite est masqué quand un badge est posé. */
  badge?: string | null
  /** Le crop actif est assigné à ce candidat (contexte lot uniquement).
   *  Quand true : fond + icône vert sur la pill action, micro-animation
   *  au clic. Ne casse pas le comportement "single" quand non fourni. */
  assigned?: boolean
}>()

defineEmits<{
  (e: 'focus'): void
}>()
</script>

<template>
  <!-- Micro-animation au clic : scale 0.97 → 1 (confirmation geste).
       La classe `active:scale-[0.97]` Tailwind suffit ; on ajoute une
       transition pour le retour fluide. -->
  <button
    type="button"
    class="flex w-full items-stretch gap-3 rounded-md border px-3 py-2 text-left transition-all active:scale-[0.97]"
    :style="{
      borderColor: assigned
        ? 'var(--success)'
        : focused
          ? 'var(--indigo-700)'
          : 'var(--surface-3)',
      background: assigned
        ? 'color-mix(in srgb, var(--success) 8%, var(--surface))'
        : focused
          ? 'color-mix(in srgb, var(--indigo-700) 6%, var(--surface))'
          : 'var(--surface)',
      boxShadow: assigned
        ? 'none'
        : focused
          ? '0 0 0 3px color-mix(in srgb, var(--indigo-700) 14%, transparent)'
          : 'none',
    }"
    @click="$emit('focus')"
  >
    <!-- Numero raccourci ou badge spécial -->
    <span
      class="flex h-7 w-7 shrink-0 items-center justify-center rounded-md font-mono text-[11px] font-semibold"
      :style="{
        background: assigned
          ? 'var(--success)'
          : focused
            ? 'var(--indigo-700)'
            : 'var(--surface-1)',
        color: assigned || focused ? 'var(--surface)' : 'var(--ink-500)',
      }"
    >
      {{ badge ?? index + 1 }}
    </span>

    <!-- Thumb canonique -->
    <img
      :src="candidate.canonical_thumb_url"
      :alt="candidate.eurio_id"
      class="h-12 w-12 shrink-0 rounded-md object-cover"
      style="background: var(--surface-1);"
    />

    <!-- Identité + score -->
    <div class="min-w-0 flex-1">
      <p class="truncate font-mono text-[12px] font-medium" style="color: var(--ink);">
        {{ candidate.eurio_id }}
      </p>
      <p class="mt-0.5 truncate text-[11px]" style="color: var(--ink-500);">
        {{ candidate.label }}
      </p>
    </div>

    <!-- Score (masqué quand un badge est posé — la "cible" n'a pas de
         score Dino, ce serait trompeur de l'afficher) -->
    <div v-if="!badge" class="shrink-0 text-right">
      <p
        class="font-mono text-[14px] font-semibold tabular-nums"
        :style="{
          color: candidate.score >= 0.75
            ? 'var(--success)'
            : candidate.score >= 0.5
              ? 'var(--gold-600)'
              : 'var(--ink-400)',
        }"
      >
        {{ candidate.score.toFixed(2) }}
      </p>
      <p class="font-mono text-[9px] uppercase tracking-wider" style="color: var(--ink-400);">
        score
      </p>
    </div>

    <!-- Pill "Sélec." / "✓ validé" (visuel uniquement, le clic est capté
         par la row entière) — affiché quand badge est posé pour parité
         visuelle avec DinoSuggestions. État vert si assigned. -->
    <span
      v-else
      class="flex shrink-0 items-center gap-1 rounded-md px-2 font-mono text-[10px] uppercase tracking-wider transition-all duration-150"
      :style="{
        background: assigned ? 'var(--success)' : 'var(--indigo-700)',
        color: 'var(--surface)',
      }"
    >
      <CheckCircle2 v-if="assigned" class="h-3 w-3" />
      {{ assigned ? 'validé' : 'Sélec.' }}
    </span>
  </button>
</template>
