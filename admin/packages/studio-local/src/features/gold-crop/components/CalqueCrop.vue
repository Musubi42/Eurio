<script setup lang="ts">
// Le calque de tracé : un raw, l'ellipse d'or par-dessus, et zéro à N cercles.
//
// Extrait de `VignetteOr` quand la planche comparative est arrivée : elle
// dessine exactement la même scène (mêmes pixels natifs, même `viewBox`), avec
// en plus le cercle du bras jugé. Deux copies du même SVG auraient dérivé — et
// une planche de contrôle qui dessine autrement que la page de référence ne
// contrôle plus rien.
//
// ⚠️ L'angle attendu est en DEGRÉS (convention `cv2.fitEllipse`, comme
// `AnnotationOr.theta_deg`). Les runs du banc, eux, le portent en RADIANS :
// la conversion se fait chez l'appelant, jamais ici.
import { computed } from 'vue'

export interface EllipseTracee {
  cx: number
  cy: number
  a: number
  b: number
  thetaDeg: number
}

/** Un cercle de méthode : ce qu'un bras a proposé, avec sa couleur de légende. */
export interface CercleTrace {
  cx: number
  cy: number
  r: number
  couleur: string
  nom?: string
}

const props = withDefaults(
  defineProps<{
    url: string
    alt?: string
    largeur?: number | null
    hauteur?: number | null
    ellipse?: EllipseTracee | null
    cercles?: CercleTrace[]
    /** Bande du Boundary IoU (`d = 0,08·a`) : ce que le juge regardera. */
    montrerBande?: boolean
    /** Dessiner AUSSI le bord extérieur de la bande — la bande est un anneau. */
    bandeExterieure?: boolean
    /** Ce qui s'affiche à la place de l'or quand il n'y en a pas. */
    vide?: string
  }>(),
  { cercles: () => [], vide: 'indécidable' },
)

const L = computed(() => props.largeur ?? 900)
const H = computed(() => props.hauteur ?? 900)
const boite = computed(() => `0 0 ${L.value} ${H.value}`)
const trait = computed(() => Math.max(1.5, L.value / 350))
/** `d = 0,08·a` — la médiane mesurée du listel nu (D4). */
const D_FRAC = 0.08
</script>

<template>
  <div class="scene">
    <img :src="url" :alt="alt ?? ''" loading="lazy" />
    <svg v-if="ellipse || cercles.length" :viewBox="boite" preserveAspectRatio="xMidYMid meet">
      <template v-if="ellipse">
        <ellipse
          class="or"
          :cx="ellipse.cx" :cy="ellipse.cy" :rx="ellipse.a" :ry="ellipse.b"
          :transform="`rotate(${ellipse.thetaDeg} ${ellipse.cx} ${ellipse.cy})`"
          fill="none" stroke="#ffd166" :stroke-width="trait"
        />
        <ellipse
          v-if="montrerBande"
          class="bande"
          :cx="ellipse.cx" :cy="ellipse.cy"
          :rx="ellipse.a * (1 - D_FRAC)" :ry="ellipse.b * (1 - D_FRAC)"
          :transform="`rotate(${ellipse.thetaDeg} ${ellipse.cx} ${ellipse.cy})`"
          fill="none" stroke="#ffd166" :stroke-width="trait * 0.6"
          stroke-dasharray="8 8" opacity="0.55"
        />
        <ellipse
          v-if="montrerBande && bandeExterieure"
          class="bande"
          :cx="ellipse.cx" :cy="ellipse.cy"
          :rx="ellipse.a * (1 + D_FRAC)" :ry="ellipse.b * (1 + D_FRAC)"
          :transform="`rotate(${ellipse.thetaDeg} ${ellipse.cx} ${ellipse.cy})`"
          fill="none" stroke="#ffd166" :stroke-width="trait * 0.6"
          stroke-dasharray="8 8" opacity="0.55"
        />
      </template>
      <circle
        v-for="(c, i) in cercles" :key="`${c.nom ?? i}`"
        class="bras"
        :cx="c.cx" :cy="c.cy" :r="c.r"
        fill="none" :stroke="c.couleur" :stroke-width="trait"
      />
    </svg>
    <div v-else class="sans-or">{{ vide }}</div>
  </div>
</template>

<style scoped>
/* Fond SOMBRE sous l'image, et lui seul : le trait d'or doit se détacher du
   vide autour d'un raw qui n'est pas carré. */
.scene { position: relative; aspect-ratio: 1; background: var(--ink-700); }
.scene img { width: 100%; height: 100%; object-fit: contain; display: block; }
.scene svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.sans-or { position: absolute; inset: 0; display: grid; place-items: center;
           font-size: var(--text-xs); letter-spacing: 0.08em; text-transform: uppercase;
           color: var(--danger); }
</style>
