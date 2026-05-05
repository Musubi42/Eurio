<script setup lang="ts">
// Floating preview rendu au-dessus d'une ligne de pièce (Dino suggestion ou
// résultat sélecteur libre). Position : au-dessus de l'ancre, centré
// horizontalement, `pointer-events: none` pour ne jamais voler le focus.
//
// Si pas assez de place en haut (preview découperait au-dessus du
// viewport), on flippe en dessous. Comme on est en `position: fixed` +
// Teleport vers <body>, on échappe au scroll container parent.

import { computed } from 'vue'

const props = defineProps<{
  imageUrl: string | null
  eurioId: string
  /** Sous-label (ex : "France · 2 € commémo · 2008"). */
  label?: string | null
  /** Bounding rect de l'élément ancre, en coords viewport. */
  anchorRect: DOMRect
}>()

const PREVIEW_W = 220
const PREVIEW_H = 270 // approx (image carrée 220 + ~50 meta)
const GAP = 10
const SAFE_MARGIN = 8

const computedStyle = computed(() => {
  const r = props.anchorRect
  // Centré horizontalement sur l'ancre, clampé au viewport.
  const idealLeft = r.left + r.width / 2 - PREVIEW_W / 2
  const left = Math.max(
    SAFE_MARGIN,
    Math.min(window.innerWidth - PREVIEW_W - SAFE_MARGIN, idealLeft),
  )
  // Au-dessus par défaut, sinon flip en dessous si pas la place.
  const spaceAbove = r.top
  const top =
    spaceAbove >= PREVIEW_H + GAP
      ? r.top - GAP - PREVIEW_H
      : r.bottom + GAP
  return {
    left: `${left}px`,
    top: `${top}px`,
    width: `${PREVIEW_W}px`,
  }
})
</script>

<template>
  <Teleport to="body">
    <div
      class="coin-hover-preview pointer-events-none fixed z-[60] overflow-hidden rounded-lg border shadow-xl"
      :style="[
        computedStyle,
        { borderColor: 'var(--surface-3)', background: 'var(--surface)' },
      ]"
    >
      <div
        class="flex aspect-square items-center justify-center overflow-hidden"
        style="background: var(--surface-1);"
      >
        <img
          v-if="imageUrl"
          :src="imageUrl"
          :alt="eurioId"
          class="h-full w-full object-cover"
        />
        <span
          v-else
          class="font-mono text-[10px] uppercase tracking-wider"
          style="color: var(--ink-400);"
        >
          pas d'image
        </span>
      </div>
      <div class="px-3 py-2">
        <p
          class="font-mono text-[12px] font-semibold"
          style="color: var(--ink);"
        >
          {{ eurioId }}
        </p>
        <p
          v-if="label"
          class="mt-0.5 truncate text-[11px]"
          style="color: var(--ink-500);"
        >
          {{ label }}
        </p>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.coin-hover-preview {
  animation: coin-preview-in 120ms ease-out;
}

@keyframes coin-preview-in {
  from { opacity: 0; transform: translateY(2px); }
  to   { opacity: 1; transform: translateY(0); }
}
</style>
