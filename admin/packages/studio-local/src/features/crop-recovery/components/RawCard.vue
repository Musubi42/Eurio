<script setup lang="ts">
// Une IMAGE BRUTE et tous les crops qu'on en tire (1 si single, N si lot).
// Haut : le raw + un cercle vert numéroté par crop produit (repère visuel des pièces ratées).
// Bas : le VRAI crop 224 normalisé (servi par l'API) de chaque pièce, avec score / passe / IoU.
import { onMounted, ref, watch } from 'vue'

type Cand = { cx: number; cy: number; r: number; source: string; score: number; iou_gold?: number }
type Case = {
  case_id: string
  dataset: string
  emu_globe: boolean
  gold_circle: [number, number, number] | null
  candidates: Cand[]
  chosen_idx: number
  chosen_score: number
  baseline_score: number | null
  passed: boolean
}

const props = defineProps<{
  rawKey: string
  cases: Case[]
  tau: number
  mlApi: string
  showBaseline: boolean
}>()

const canvas = ref<HTMLCanvasElement | null>(null)
const RAW = 380

function chosen(c: Case): Cand {
  return c.candidates[c.chosen_idx]
}
function cropUrl(c: Case): string {
  const k = chosen(c)
  const q = new URLSearchParams({ key: props.rawKey, cx: String(k.cx), cy: String(k.cy), r: String(k.r) })
  return `${props.mlApi}/crop-recovery/crop?${q.toString()}`
}

function draw() {
  const cv = canvas.value
  if (!cv) return
  const ctx = cv.getContext('2d')!
  const img = new Image()
  img.crossOrigin = 'anonymous'
  img.onload = () => {
    const nw = img.naturalWidth, nh = img.naturalHeight
    const s = Math.min(RAW / nw, RAW / nh)
    const ox = (RAW - nw * s) / 2, oy = (RAW - nh * s) / 2
    ctx.fillStyle = '#111'; ctx.fillRect(0, 0, RAW, RAW)
    ctx.drawImage(img, ox, oy, nw * s, nh * s)
    props.cases.forEach((c, i) => {
      const k = chosen(c)
      const x = ox + k.cx * s, y = oy + k.cy * s, r = k.r * s
      if (props.showBaseline) {
        const b = c.candidates.find((q) => q.source === 'baseline')
        if (b) {
          ctx.beginPath(); ctx.setLineDash([4, 4]); ctx.strokeStyle = '#e74c3c'; ctx.lineWidth = 1.5
          ctx.arc(ox + b.cx * s, oy + b.cy * s, b.r * s, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([])
        }
      }
      ctx.beginPath(); ctx.strokeStyle = c.passed ? '#2ecc71' : '#e67e22'; ctx.lineWidth = 2.5
      ctx.arc(x, y, r, 0, Math.PI * 2); ctx.stroke()
      // badge numéro
      ctx.fillStyle = c.passed ? '#2ecc71' : '#e67e22'
      ctx.beginPath(); ctx.arc(x, y - r, 9, 0, Math.PI * 2); ctx.fill()
      ctx.fillStyle = '#111'; ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
      ctx.fillText(String(i + 1), x, y - r)
    })
  }
  img.onerror = () => {
    ctx.fillStyle = '#222'; ctx.fillRect(0, 0, RAW, RAW)
    ctx.fillStyle = '#888'; ctx.font = '12px sans-serif'; ctx.fillText('raw introuvable', 14, RAW / 2)
  }
  img.src = `${props.mlApi}/crop-recovery/raw?key=${encodeURIComponent(props.rawKey)}`
}

onMounted(draw)
watch(() => [props.rawKey, props.showBaseline, props.cases.map((c) => c.chosen_idx).join()], draw)

const nPass = () => props.cases.filter((c) => c.passed).length
</script>

<template>
  <div class="rawcard">
    <div class="hero">
      <canvas ref="canvas" :width="RAW" :height="RAW" />
      <div class="hdr">
        <span class="ds">{{ cases[0].dataset }}<template v-if="cases[0].emu_globe"> · EMU/globe</template></span>
        <span class="cnt" :class="{ multi: cases.length > 1 }">
          {{ cases.length }} crop{{ cases.length > 1 ? 's' : '' }} · {{ nPass() }} ✓
        </span>
      </div>
    </div>

    <div class="crops">
      <figure v-for="(c, i) in cases" :key="c.case_id" :class="{ pass: c.passed, fail: !c.passed }">
        <span class="num">{{ i + 1 }}</span>
        <img :src="cropUrl(c)" loading="lazy" alt="crop" />
        <figcaption>
          <b :class="c.passed ? 'g' : 'o'">{{ chosen(c).score.toFixed(2) }}</b>
          <span v-if="chosen(c).iou_gold != null" class="iou">IoU {{ chosen(c).iou_gold!.toFixed(2) }}</span>
        </figcaption>
      </figure>
    </div>
  </div>
</template>

<style scoped>
.rawcard { border: 1px solid #e2e2e2; border-radius: 12px; overflow: hidden; background: #fff; display: flex; flex-direction: column; }
.hero { position: relative; background: #111; }
canvas { display: block; width: 100%; height: auto; }
.hdr { position: absolute; top: 0; left: 0; right: 0; display: flex; justify-content: space-between; padding: 6px 8px; font-size: 0.72rem; }
.hdr .ds { color: #cdd; background: rgba(0,0,0,0.45); padding: 2px 6px; border-radius: 6px; }
.hdr .cnt { color: #ddd; background: rgba(0,0,0,0.45); padding: 2px 6px; border-radius: 6px; }
.hdr .cnt.multi { color: #ffd36b; font-weight: 600; }
.crops { display: flex; flex-wrap: wrap; gap: 8px; padding: 9px; background: #fafafa; }
figure { margin: 0; position: relative; border: 2px solid #ccc; border-radius: 8px; overflow: hidden; width: 104px; background: #111; }
figure.pass { border-color: #2ecc71; } figure.fail { border-color: #e67e22; }
figure img { display: block; width: 104px; height: 104px; object-fit: cover; }
.num { position: absolute; top: 3px; left: 3px; background: rgba(0,0,0,0.6); color: #fff; font-size: 0.68rem; font-weight: 700; border-radius: 50%; width: 17px; height: 17px; display: flex; align-items: center; justify-content: center; }
figcaption { font-size: 0.72rem; padding: 3px 5px; background: #1b1b1b; color: #ccc; display: flex; justify-content: space-between; gap: 5px; }
.g { color: #2ecc71; } .o { color: #e67e22; }
.iou { color: #9aa; }
</style>
