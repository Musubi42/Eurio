<script setup lang="ts">
// Une image du jeu d'or, avec son ellipse tracée par-dessus.
//
// Le tracé lui-même vit dans `CalqueCrop` depuis la planche comparative : elle
// dessine la même scène avec en plus le cercle du bras jugé, et deux copies du
// même SVG auraient fini par diverger. Ce composant garde ce qui lui est
// propre — la légende du jeu d'or.
import { computed } from 'vue'

import CalqueCrop from './CalqueCrop.vue'
import type { AnnotationOr } from '../composables/useGoldCropApi'
import { strateRetenue } from '../composables/useGoldCropApi'

const props = defineProps<{
  annotation: AnnotationOr
  /** Bande du Boundary IoU (`d = 0,08·a`) : ce que le juge regardera. */
  montrerBande?: boolean
}>()

const a = computed(() => props.annotation)
const ellipse = computed(() =>
  a.value.a != null && a.value.b != null && a.value.cx != null && a.value.cy != null
    ? { cx: a.value.cx, cy: a.value.cy, a: a.value.a, b: a.value.b,
        thetaDeg: a.value.theta_deg ?? 0 }
    : null,
)
const obliquite = computed(() =>
  a.value.a && a.value.b ? a.value.b / a.value.a : null,
)
</script>

<template>
  <figure class="vignette" :class="{ indecidable: a.indecidable === 1 }">
    <CalqueCrop
      :url="a.raw_url" :alt="a.asset_id"
      :largeur="a.width" :hauteur="a.height"
      :ellipse="ellipse" :montrer-bande="montrerBande"
    />
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
figcaption { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;
             padding: 0.4rem 0.55rem; font-size: var(--text-xs); color: var(--ink-700); }
.strate { font-variant-numeric: tabular-nums; }
.verdict { padding: 0 0.45rem; border-radius: 99px; font-weight: 600; }
.acc { background: var(--success-soft); color: var(--success); }
.rej { background: var(--danger-soft); color: var(--danger); }
.passe { margin-left: auto; color: var(--indigo-600); }
.doux { color: var(--ink-500); }
</style>
