<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ImageOff, Loader2 } from 'lucide-vue-next'
import {
  type CropBenchCard,
  type CropBenchRecrop,
  fetchCropBenchRecrop,
  resolveCropBenchImg,
} from '../composables/useCropBenchApi'

const props = withDefaults(defineProps<{
  card: CropBenchCard
  compare?: boolean
  algo?: string
  label?: Record<string, string>   // {target: verdict} déjà enregistrés pour ce crop
}>(), { compare: true, algo: 'bbox_refine' })

const emit = defineEmits<{
  (e: 'label', payload: { target: string; verdict: 'good' | 'bad'; method: string | null; rRatio: number | null }): void
}>()

function verdictOf(target: string): string | undefined {
  return props.label?.[target]
}
function mark(target: string, verdict: 'good' | 'bad') {
  const isAlt = target !== 'actuel'
  emit('label', {
    target, verdict,
    method: isAlt ? (recrop.value?.method ?? null) : (props.card.detection_method || null),
    rRatio: isAlt ? (recrop.value?.r_ratio_oracle ?? null) : props.card.r_ratio,
  })
}

const overlayBroken = ref(false)
const cropBroken = ref(false)

const overlayUrl = computed(() =>
  resolveCropBenchImg(props.card.overlay_url, props.compare ? props.algo : undefined),
)
const cropUrl = computed(() => resolveCropBenchImg(props.card.crop_url))

const isDefect = computed(
  () => props.card.crop_class === 'undercrop' || props.card.crop_class === 'wrong',
)

const fmt = (v: number | null) => (v == null ? 'n/a' : v.toFixed(2))
const fillLabel = computed(() => (props.card.fill_ratio == null ? '—' : props.card.fill_ratio.toFixed(2)))

// --- Recrop alternatif (fitEllipse…) lazy ---
const recrop = ref<CropBenchRecrop | null>(null)
const recropLoading = ref(false)
const recropError = ref<string | null>(null)

async function loadRecrop() {
  if (!props.compare) return
  recropLoading.value = true
  recropError.value = null
  recrop.value = null
  try {
    recrop.value = await fetchCropBenchRecrop(props.card.asset_id, props.algo)
  } catch (e) {
    recropError.value = e instanceof Error ? e.message : String(e)
  } finally {
    recropLoading.value = false
  }
}

watch(
  () => [props.card.asset_id, props.compare, props.algo],
  () => { loadRecrop() },
  { immediate: true },
)

// Verdict de l'algo alternatif : note "overcrop" si r̂ trop grand.
const altVerdict = computed(() => {
  const rc = recrop.value
  if (!rc) return null
  if (!rc.ok || rc.r_ratio_oracle == null) return { sev: 'gray', txt: rc.reason || 'échec' }
  if (rc.r_ratio_oracle > 1.3) return { sev: 'amber', txt: `overcrop ${fmt(rc.r_ratio_oracle)}` }
  return { sev: rc.severity, txt: `r/r̂ ${fmt(rc.r_ratio_oracle)}` }
})

// Delta vs crop actuel (amélioration si on se rapproche de 1.0).
const improved = computed(() => {
  const cur = props.card.r_ratio
  const alt = recrop.value?.r_ratio_oracle
  if (cur == null || alt == null) return false
  return Math.abs(alt - 1) < Math.abs(cur - 1)
})
</script>

<template>
  <article class="card" :class="[`sev-${card.severity}`, { 'card--defect': isDefect }]">
    <div v-if="isDefect" class="card__ribbon">{{ card.crop_class }}</div>

    <div class="card__stage" :class="{ 'card__stage--3': compare }">
      <!-- Pane 1 : overlay raw (R=pipeline, G=oracle, B=algo) -->
      <div class="pane pane--raw">
        <img v-if="overlayUrl && !overlayBroken" :src="overlayUrl" class="pane__img"
             loading="lazy" alt="raw + cercles" @error="overlayBroken = true" />
        <div v-else class="pane__fallback">
          <ImageOff class="h-6 w-6" style="color: var(--ink-300);" />
          <span class="text-[10px]" style="color: var(--ink-400);">raw absent</span>
        </div>
        <span v-if="!card.has_bbox" class="pane__warn" title="bbox non stockée — overlay approximatif">⚠ no bbox</span>
      </div>

      <!-- Pane 2 : crop actuel (Hough) -->
      <div class="pane pane--crop">
        <a v-if="cropUrl && !cropBroken" :href="cropUrl" target="_blank" rel="noopener" class="pane__link">
          <img :src="cropUrl" class="pane__img pane__img--crop" loading="lazy" alt="crop actuel" @error="cropBroken = true" />
        </a>
        <div v-else class="pane__fallback"><ImageOff class="h-6 w-6" style="color: var(--ink-300);" /></div>
        <span class="pane__tag" :class="`tag-${card.severity}`">actuel · {{ fmt(card.r_ratio) }}</span>
      </div>

      <!-- Pane 3 : crop algo alternatif (fitEllipse) -->
      <div v-if="compare" class="pane pane--alt">
        <div v-if="recropLoading" class="pane__fallback">
          <Loader2 class="h-5 w-5 spin" style="color: var(--ink-300);" />
        </div>
        <template v-else-if="recrop?.crop_b64">
          <a :href="recrop.crop_b64" target="_blank" rel="noopener" class="pane__link">
            <img :src="recrop.crop_b64" class="pane__img pane__img--crop" :alt="`crop ${algo}`" />
          </a>
          <span v-if="improved" class="pane__improved" title="se rapproche du vrai rim">▲</span>
        </template>
        <div v-else class="pane__fallback pane__fallback--fail">
          <span class="text-[10px]">{{ recrop?.reason || recropError || 'échec' }}</span>
        </div>
        <span v-if="altVerdict" class="pane__tag" :class="`tag-${altVerdict.sev}`">
          {{ algo }} · {{ altVerdict.txt }}
        </span>
      </div>
    </div>

    <div class="card__meta">
      <div class="card__row">
        <span class="rratio" :class="`rratio-${card.severity}`" title="crop actuel : r_pipe / r_probe">
          actuel <b>{{ fmt(card.r_ratio) }}</b>
        </span>
        <span v-if="compare && recrop" class="rratio" :class="`rratio-${altVerdict?.sev}`"
              :title="`${algo} : r / r_probe (oracle)`">
          {{ algo }} <b>{{ fmt(recrop.r_ratio_oracle) }}</b>
        </span>
        <span class="metric">fill <b>{{ fillLabel }}</b></span>
        <span class="bucket-chip">{{ card.bucket }}</span>
      </div>

      <!-- Gold labeling : juger chaque crop ✓ bon / ✗ mauvais -->
      <div class="card__labels">
        <span class="lbl-group">
          <span class="lbl-name">actuel</span>
          <button class="lbl-btn lbl-good" :class="{ on: verdictOf('actuel') === 'good' }"
                  title="crop actuel = bon" @click="mark('actuel', 'good')">✓</button>
          <button class="lbl-btn lbl-bad" :class="{ on: verdictOf('actuel') === 'bad' }"
                  title="crop actuel = mauvais" @click="mark('actuel', 'bad')">✗</button>
        </span>
        <span v-if="compare" class="lbl-group">
          <span class="lbl-name">{{ algo }}</span>
          <button class="lbl-btn lbl-good" :class="{ on: verdictOf(algo) === 'good' }"
                  :title="`crop ${algo} = bon`" @click="mark(algo, 'good')">✓</button>
          <button class="lbl-btn lbl-bad" :class="{ on: verdictOf(algo) === 'bad' }"
                  :title="`crop ${algo} = mauvais`" @click="mark(algo, 'bad')">✗</button>
        </span>
      </div>

      <div class="card__foot">
        <span class="card__id" :title="card.asset_id">{{ card.asset_id.slice(0, 8) }}</span>
        <span class="card__sep">·</span>
        <span class="badge-method">{{ card.detection_method || 'unknown' }}</span>
        <span class="card__loc">{{ card.country || '??' }} {{ card.year }}</span>
        <span v-if="card.eurio_id" class="card__eurio" :title="card.eurio_id">{{ card.eurio_id }}</span>
      </div>
    </div>
  </article>
</template>

<style scoped>
.card {
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--surface-3);
  background: var(--surface);
  border-radius: 14px;
  transition: transform 180ms cubic-bezier(0.16, 1, 0.3, 1), box-shadow 180ms cubic-bezier(0.16, 1, 0.3, 1);
}
.card:hover { transform: translateY(-2px); box-shadow: 0 2px 6px rgba(14,14,31,.05), 0 8px 24px rgba(14,14,31,.06); }
.card--defect { border-color: var(--danger); }
.card.sev-red { box-shadow: inset 0 0 0 1px rgba(209,67,67,.25); }

.card__ribbon {
  position: absolute; top: 0; left: 0; z-index: 2;
  padding: 3px 9px; font-size: 10px; font-weight: 600;
  text-transform: uppercase; letter-spacing: .08em;
  border-bottom-right-radius: 8px; background: var(--danger); color: var(--surface);
}

.card__stage {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 3px; background: var(--surface-2);
}
.card__stage--3 { grid-template-columns: 1fr 1fr 1fr; }
.pane {
  position: relative;
  aspect-ratio: 1 / 1;            /* panneaux carrés → crop 224 entièrement visible */
  display: flex; align-items: center; justify-content: center;
  overflow: hidden;
  background: linear-gradient(135deg, var(--surface-2), var(--surface-1));
}
.pane__img { display: block; width: 100%; height: 100%; object-fit: contain; }
.pane__img--crop { object-fit: contain; }
.pane__link { display: contents; cursor: zoom-in; }
.pane__fallback { display: flex; flex-direction: column; align-items: center; gap: 4px; color: var(--ink-400); padding: 6px; text-align: center; }
.pane__fallback--fail { color: var(--danger); }
.pane__tag {
  position: absolute; bottom: 4px; left: 5px; right: 5px;
  padding: 1px 5px; font-size: 9px; font-weight: 600;
  border-radius: 4px; text-align: center;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.tag-red   { background: var(--danger); color: #fff; }
.tag-amber { background: #E8A23D; color: #fff; }
.tag-green { background: #1F6E48; color: #fff; }
.tag-gray  { background: rgba(14,14,31,.55); color: #fff; }
.pane__warn {
  position: absolute; top: 4px; right: 5px; padding: 1px 6px;
  font-size: 9px; font-weight: 600; color: #7A5320; background: #FBE7C5; border-radius: 4px;
}
.pane__improved {
  position: absolute; top: 4px; right: 5px;
  font-size: 13px; font-weight: 700; color: #1F6E48;
  text-shadow: 0 1px 2px rgba(0,0,0,.4);
}

.card__meta { display: flex; flex-direction: column; gap: 6px; padding: 9px 11px 11px; border-top: 1px solid var(--surface-2); }
.card__row { display: flex; align-items: center; gap: 6px; font-size: 11px; flex-wrap: wrap; }

.rratio { font-family: var(--font-mono); font-size: 10.5px; padding: 1px 6px; border-radius: 5px; font-variant-numeric: tabular-nums; }
.rratio b { font-weight: 700; }
.rratio-red   { background: var(--danger-soft, #f6dcd6); color: var(--danger); }
.rratio-amber { background: #FBE7C5; color: #7A5320; }
.rratio-green { background: #D8EFE0; color: #1F6E48; }
.rratio-gray  { background: var(--surface-2); color: var(--ink-400); }

.metric { font-family: var(--font-mono); font-size: 10.5px; color: var(--ink-400); font-variant-numeric: tabular-nums; }
.metric b { color: var(--ink-700); font-weight: 500; }
.bucket-chip { margin-left: auto; font-family: var(--font-mono); font-size: 9.5px; color: var(--ink-400); padding: 1px 6px; border-radius: 4px; background: var(--surface-2); }

.card__foot { display: flex; align-items: center; gap: 6px; font-family: var(--font-mono); font-size: 10px; color: var(--ink-400); flex-wrap: wrap; }
.card__id { color: var(--ink-500); }
.card__sep { color: var(--ink-300); }
.badge-method { color: var(--indigo-600); }
.card__loc { color: var(--ink-500); }
.card__eurio { margin-left: auto; color: var(--indigo-700); max-width: 120px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.card__labels { display: flex; gap: 16px; align-items: center; }
.lbl-group { display: inline-flex; align-items: center; gap: 5px; }
.lbl-name { font-family: var(--font-mono); font-size: 10px; color: var(--ink-400); min-width: 58px; }
.lbl-btn {
  width: 26px; height: 22px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--surface-3); background: var(--surface);
  font-size: 12px; font-weight: 700; line-height: 1; color: var(--ink-400);
  display: inline-flex; align-items: center; justify-content: center;
  transition: all 120ms;
}
.lbl-btn:hover { border-color: var(--ink-400); }
.lbl-good.on { background: #1F6E48; border-color: #1F6E48; color: #fff; }
.lbl-bad.on  { background: var(--danger); border-color: var(--danger); color: #fff; }

.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
