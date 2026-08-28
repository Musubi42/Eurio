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
.vignette { margin: 0; background: var(--surface-1, #1e2127); border: 1px solid var(--border, #2f343d);
            border-radius: 10px; overflow: hidden; }
.vignette.indecidable { opacity: 0.55; }
.scene { position: relative; aspect-ratio: 1; background: #0b0d10; }
.scene img { width: 100%; height: 100%; object-fit: contain; display: block; }
.scene svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.sans-or { position: absolute; inset: 0; display: grid; place-items: center;
           font-size: 0.75rem; letter-spacing: 0.08em; text-transform: uppercase;
           color: #f87171; }
figcaption { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;
             padding: 0.4rem 0.55rem; font-size: 0.72rem; }
.strate { font-variant-numeric: tabular-nums; }
.verdict { padding: 0 0.45rem; border-radius: 99px; font-weight: 600; }
.acc { background: rgba(74, 222, 128, 0.16); color: #4ade80; }
.rej { background: rgba(248, 113, 113, 0.16); color: #f87171; }
.passe { margin-left: auto; color: #60a5fa; }
.doux { color: var(--text-muted, #9aa3b2); }
</style>
