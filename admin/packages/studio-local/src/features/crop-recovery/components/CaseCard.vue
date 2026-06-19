<script setup lang="ts">
// Une vignette : le raw + les cercles superposés (canvas).
// rouge = baseline (crop prod) · vert = choisi (argmax score) · bleu = gold humain.
import { onMounted, ref, watch } from 'vue'

type Cand = { cx: number; cy: number; r: number; source: string; score: number; iou_gold?: number }
type Case = {
  case_id: string
  dataset: string
  raw_key: string
  emu_globe: boolean
  gold_circle: [number, number, number] | null
  is_fragment: boolean
  candidates: Cand[]
  chosen_idx: number
  chosen_score: number
  baseline_score: number | null
  passed: boolean
}

const props = defineProps<{ c: Case; tau: number; mlApi: string }>()
const canvas = ref<HTMLCanvasElement | null>(null)
const SIZE = 240

function circle(ctx: CanvasRenderingContext2D, x: number, y: number, r: number,
                color: string, dash: number[] = []) {
  ctx.beginPath()
  ctx.setLineDash(dash)
  ctx.strokeStyle = color
  ctx.lineWidth = 2.5
  ctx.arc(x, y, r, 0, Math.PI * 2)
  ctx.stroke()
  ctx.setLineDash([])
}

function draw() {
  const cv = canvas.value
  if (!cv) return
  const ctx = cv.getContext('2d')!
  const img = new Image()
  img.crossOrigin = 'anonymous'
  img.onload = () => {
    const nw = img.naturalWidth, nh = img.naturalHeight
    const s = Math.min(SIZE / nw, SIZE / nh)
    const ox = (SIZE - nw * s) / 2, oy = (SIZE - nh * s) / 2
    ctx.fillStyle = '#111'
    ctx.fillRect(0, 0, SIZE, SIZE)
    ctx.drawImage(img, ox, oy, nw * s, nh * s)
    const tx = (x: number, y: number, r: number) =>
      [ox + x * s, oy + y * s, r * s] as const
    const base = props.c.candidates.find((k) => k.source === 'baseline')
    const chosen = props.c.candidates[props.c.chosen_idx]
    if (base) circle(ctx, ...tx(base.cx, base.cy, base.r), '#e74c3c')
    if (props.c.gold_circle) {
      const [gx, gy, gr] = props.c.gold_circle
      circle(ctx, ...tx(gx, gy, gr), '#3498db', [5, 4])
    }
    if (chosen && chosen.source !== 'baseline')
      circle(ctx, ...tx(chosen.cx, chosen.cy, chosen.r), '#2ecc71')
  }
  img.onerror = () => {
    ctx.fillStyle = '#222'; ctx.fillRect(0, 0, SIZE, SIZE)
    ctx.fillStyle = '#888'; ctx.font = '11px sans-serif'
    ctx.fillText('raw introuvable', 12, SIZE / 2)
  }
  img.src = `${props.mlApi}/crop-recovery/raw?key=${encodeURIComponent(props.c.raw_key)}`
}

onMounted(draw)
watch(() => props.c.case_id, draw)
</script>

<template>
  <div class="card" :class="{ pass: c.passed, fail: !c.passed }">
    <canvas ref="canvas" :width="SIZE" :height="SIZE" />
    <div class="meta">
      <span class="tag">{{ c.dataset }}<template v-if="c.emu_globe"> · EMU/globe</template></span>
      <span class="scores">
        base <b>{{ (c.baseline_score ?? 0).toFixed(2) }}</b> →
        <b :class="c.passed ? 'g' : 'r'">{{ c.chosen_score.toFixed(2) }}</b>
        <template v-if="c.candidates[c.chosen_idx]?.iou_gold != null">
          · IoU {{ c.candidates[c.chosen_idx].iou_gold!.toFixed(2) }}
        </template>
      </span>
    </div>
  </div>
</template>

<style scoped>
.card { border: 2px solid #ccc; border-radius: 10px; overflow: hidden; background: #111; }
.card.pass { border-color: #2ecc71; }
.card.fail { border-color: #e74c3c; }
canvas { display: block; width: 100%; height: auto; }
.meta { background: #1b1b1b; color: #ddd; font-size: 0.72rem; padding: 4px 6px; display: flex; justify-content: space-between; gap: 6px; }
.tag { color: #9aa; white-space: nowrap; }
.g { color: #2ecc71; } .r { color: #e74c3c; }
</style>
