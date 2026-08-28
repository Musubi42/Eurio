<script setup lang="ts">
// Une image du jeu d'or, avec son ellipse tracée par-dessus.
//
// L'ellipse est en pixels NATIFS du raw ; le SVG se cale dessus par un
// `viewBox` aux dimensions du raw, ce qui rend le tracé exact quel que soit
// l'affichage — même patron que `CircleCropEditor.vue`.
import { computed } from 'vue'

import type { AnnotationOr } from '../composables/useGoldCropApi'
import { strateRetenue } from '../composables/useGoldCropApi'

const props = defineProps<{
  annotation: AnnotationOr
  /** Bande du Boundary IoU (`d = 0,08·a`) : ce que le juge regardera. */
  montrerBande?: boolean
}>()

const a = computed(() => props.annotation)
const boite = computed(() => `0 0 ${a.value.width ?? 900} ${a.value.height ?? 900}`)
const trait = computed(() => Math.max(1.5, (a.value.width ?? 900) / 350))
const obliquite = computed(() =>
  a.value.a && a.value.b ? a.value.b / a.value.a : null,
)
</script>

<template>
  <figure class="vignette" :class="{ indecidable: a.indecidable === 1 }">
    <div class="scene">
      <img :src="a.raw_url" :alt="a.asset_id" loading="lazy" />
      <svg v-if="a.a" :viewBox="boite" preserveAspectRatio="xMidYMid meet">
        <ellipse
          :cx="a.cx" :cy="a.cy" :rx="a.a" :ry="a.b"
          :transform="`rotate(${a.theta_deg} ${a.cx} ${a.cy})`"
          fill="none" stroke="#ffd166" :stroke-width="trait"
        />
        <ellipse
          v-if="montrerBande"
          :cx="a.cx" :cy="a.cy" :rx="a.a! * 0.92" :ry="a.b! * 0.92"
          :transform="`rotate(${a.theta_deg} ${a.cx} ${a.cy})`"
          fill="none" stroke="#ffd166" :stroke-width="trait * 0.6"
          stroke-dasharray="8 8" opacity="0.55"
        />
      </svg>
      <div v-else class="sans-or">indécidable</div>
    </div>
    <figcaption>
      <span class="strate">{{ strateRetenue(a) }}</span>
      <span :class="['verdict', a.resolution_status === 'manual' ? 'acc' : 'rej']">
        {{ a.resolution_status === 'manual' ? 'accepté' : 'rejeté' }}
      </span>
      <span v-if="obliquite" class="doux" :title="'petit axe / grand axe'">
        b/a {{ obliquite.toFixed(3) }}
      </span>
      <span v-if="a.passe > 1" class="passe">passe {{ a.passe }}</span>
    </figcaption>
  </figure>
</template>

<style scoped>
.vignette { margin: 0; background: var(--surface-1); border: 1px solid var(--surface-3);
            border-radius: 10px; overflow: hidden; }
.vignette.indecidable { opacity: 0.55; }
/* Fond SOMBRE sous l'image, et lui seul : le trait d'or doit se détacher du
   vide autour d'un raw qui n'est pas carré. */
.scene { position: relative; aspect-ratio: 1; background: var(--ink-700); }
.scene img { width: 100%; height: 100%; object-fit: contain; display: block; }
.scene svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.sans-or { position: absolute; inset: 0; display: grid; place-items: center;
           font-size: var(--text-xs); letter-spacing: 0.08em; text-transform: uppercase;
           color: var(--danger); }
figcaption { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;
             padding: 0.4rem 0.55rem; font-size: var(--text-xs); color: var(--ink-700); }
.strate { font-variant-numeric: tabular-nums; }
.verdict { padding: 0 0.45rem; border-radius: 99px; font-weight: 600; }
.acc { background: var(--success-soft); color: var(--success); }
.rej { background: var(--danger-soft); color: var(--danger); }
.passe { margin-left: auto; color: var(--indigo-600); }
.doux { color: var(--ink-500); }
</style>
