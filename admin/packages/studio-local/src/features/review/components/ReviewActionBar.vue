<script setup lang="ts">
/**
 * La barre d'action de la review — dans le lexique de celui qui trie.
 *
 * ⛔ « SKIP / REJECT / VALIDATE » A DISPARU, POUR TOUT LE MONDE.
 * Le §6 d'`ACCUEIL-AMI.md` pose que le lexique d'un collectionneur s'applique
 * « partout où un ami lit » — et cette barre est le seul endroit de l'app où il
 * agit vraiment. Trois verbes anglais y décrivaient un geste de pipeline, pas ce
 * qu'il fait.
 *
 * Traduit pour TOUS et non pour le seul ami, délibérément. Deux libellés pour un
 * même bouton, c'est deux vocabulaires à tenir, deux captures d'écran à
 * expliquer, et une conversation d'aide où personne ne parle du même bouton. Le
 * français ne coûte rien à l'arbitre : c'est déjà la langue du reste de l'app.
 *
 * ⛔ LES RACCOURCIS NE BOUGENT PAS. `N` / `R` / `⏎` sont dans les doigts de
 * l'arbitre depuis 3 809 décisions. Renommer un libellé est gratuit ; déplacer
 * une touche coûte une erreur de tri à chaque réflexe.
 */
import { CornerDownLeft } from 'lucide-vue-next'
import type { ReviewFace } from '../composables/useReviewApi'

defineProps<{
  face: ReviewFace
  canValidate: boolean
  focusedEurioId: string | null
  // Raison du blocage quand canValidate est faux (tooltip + ligne d'aide).
  validateHint?: string | null
}>()

defineEmits<{
  (e: 'face', value: ReviewFace): void
  (e: 'validate'): void
  (e: 'reject'): void
  (e: 'skip'): void
}>()

const FACE_ITEMS: { key: ReviewFace; label: string; hint: string }[] = [
  { key: 'obverse', label: 'Avers', hint: 'O' },
  { key: 'reverse', label: 'Revers', hint: 'V' },
  { key: 'unknown', label: 'Inconnu', hint: 'U' },
]
</script>

<template>
  <div
    class="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-4 border-t px-6 py-3"
    style="border-color: var(--surface-3); background: color-mix(in srgb, var(--surface) 96%, transparent); backdrop-filter: blur(6px);"
  >
    <!-- Face radio -->
    <div class="flex items-center gap-3">
      <span
        class="font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--ink-500);"
      >
        Face
      </span>
      <div class="inline-flex rounded-md border" style="border-color: var(--surface-3);">
        <button
          v-for="opt in FACE_ITEMS"
          :key="opt.key"
          type="button"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] transition-colors"
          :style="{
            background: face === opt.key ? 'var(--indigo-700)' : 'var(--surface)',
            color: face === opt.key ? 'var(--surface)' : 'var(--ink-700)',
          }"
          @click="$emit('face', opt.key)"
        >
          {{ opt.label }}
          <span
            class="font-mono text-[9px] uppercase tracking-wider"
            :style="{ color: face === opt.key ? 'var(--gold-soft)' : 'var(--ink-400)' }"
          >
            {{ opt.hint }}
          </span>
        </button>
      </div>
    </div>

    <!-- Actions principales -->
    <div class="flex items-center gap-2">
      <span
        v-if="!canValidate && validateHint"
        class="mr-1 text-[10px] italic"
        style="color: var(--ink-400);"
      >
        {{ validateHint }}
      </span>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] transition-all"
        style="background: var(--surface-1); color: var(--ink-700); border: 1px solid var(--surface-3);"
        data-coach="passer"
        title="Repousser cette image : elle reviendra à quelqu'un d'autre · N"
        @click="$emit('skip')"
      >
        Passer
        <span class="font-mono text-[9px] uppercase tracking-wider opacity-60">N</span>
      </button>

      <button
        type="button"
        class="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px] font-medium transition-all"
        :style="{
          borderColor: 'var(--danger)',
          color: 'var(--danger)',
          background: 'color-mix(in srgb, var(--danger) 6%, var(--surface))',
        }"
        title="Cette image est inutilisable (floue, coupée, plusieurs pièces) · R"
        @click="$emit('reject')"
      >
        Écarter
        <span class="font-mono text-[9px] uppercase tracking-wider opacity-70">R</span>
      </button>

      <button
        type="button"
        class="inline-flex items-center gap-2 rounded-md px-4 py-1.5 text-[13px] font-semibold transition-all"
        :disabled="!canValidate"
        :style="{
          background: canValidate ? 'var(--indigo-700)' : 'var(--surface-2)',
          color: canValidate ? 'var(--surface)' : 'var(--ink-400)',
          cursor: canValidate ? 'pointer' : 'not-allowed',
        }"
        :title="canValidate
          ? `Ranger cette image dans : ${focusedEurioId}`
          : (validateHint ?? 'Choisis d\'abord une pièce')"
        @click="$emit('validate')"
      >
        Ranger
        <CornerDownLeft class="h-3.5 w-3.5" />
      </button>
    </div>
  </div>
</template>
