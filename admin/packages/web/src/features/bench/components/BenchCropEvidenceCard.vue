<script setup lang="ts">
import { computed, ref } from 'vue'
import { ExternalLink, ImageOff } from 'lucide-vue-next'
import {
  type BenchRunCropCard,
  resolveBenchImageUrl,
  shortEurio,
} from '../composables/useBenchApi'

const props = defineProps<{ card: BenchRunCropCard }>()

// État local : track broken images for graceful fallback.
const rawBroken = ref(false)
const cropBroken = ref(false)

const rawUrl = computed(() => resolveBenchImageUrl(props.card.raw_url))
const cropUrl = computed(() => resolveBenchImageUrl(props.card.crop_url))

const dims = computed(() => {
  const b = props.card.bbox
  if (!b || !b.w || !b.h) return null
  return `${Math.round(b.w)}×${Math.round(b.h)}`
})

const methodCls = computed(() => {
  const m = props.card.detection_method ?? ''
  if (m.includes('manual')) return 'method-manual'
  if (m.includes('hough')) return 'method-hough'
  if (m.startsWith('yolo+bbox')) return 'method-bbox'
  return 'method-merged'
})

const statusCls = computed(() => {
  const s = props.card.resolution_status ?? ''
  if (s === 'needs_review') return 'status-needs'
  if (s.startsWith('auto')) return 'status-auto'
  if (s === 'manual') return 'status-manual'
  if (s === 'rejected') return 'status-rejected'
  return 'status-other'
})

const areaPct = computed(() => {
  const a = props.card.area_ratio
  return a == null ? null : (a * 100).toFixed(1)
})
</script>

<template>
  <article class="card" :class="{ 'card--warn': card.is_undercrop_suspect }">
    <!-- Warning ribbon -->
    <div v-if="card.is_undercrop_suspect" class="card__ribbon">
      undercrop suspect
    </div>

    <!-- Raw image with bbox overlay -->
    <div class="card__stage">
      <img
        v-if="rawUrl && !rawBroken"
        :src="rawUrl"
        class="card__raw"
        loading="lazy"
        alt="raw eBay"
        @error="rawBroken = true"
      />
      <div v-else class="card__fallback">
        <ImageOff class="h-7 w-7" style="color: var(--ink-300);" />
        <span class="text-[10px]" style="color: var(--ink-400);">raw absent</span>
      </div>

      <!-- Bbox overlay (only if pct known) -->
      <div
        v-if="card.bbox_pct"
        class="card__bbox"
        :class="{ 'card__bbox--warn': card.is_undercrop_suspect }"
        :data-dims="dims"
        :style="{
          left: `${card.bbox_pct.x}%`,
          top: `${card.bbox_pct.y}%`,
          width: `${card.bbox_pct.w}%`,
          height: `${card.bbox_pct.h}%`,
        }"
      ></div>

      <!-- Crop result chip in bottom-right -->
      <div class="card__crop-chip" :title="`crop ${card.crop_width ?? '?'}×${card.crop_height ?? '?'}`">
        <span class="card__crop-chip-arrow">→</span>
        <img
          v-if="cropUrl && !cropBroken"
          :src="cropUrl"
          loading="lazy"
          alt="crop"
          @error="cropBroken = true"
        />
        <ImageOff v-else class="h-3.5 w-3.5" style="color: var(--ink-400);" />
      </div>
    </div>

    <!-- Meta -->
    <div class="card__meta">
      <div class="card__row">
        <span class="badge" :class="methodCls">
          {{ card.detection_method ?? 'unknown' }}
        </span>
        <span v-if="areaPct != null" class="area-ratio" :title="`bbox / min(raw)²`">
          ar <b>{{ areaPct }}%</b>
        </span>
        <span class="badge badge--status" :class="statusCls">
          {{ card.resolution_status ?? '—' }}
        </span>
      </div>

      <p v-if="card.listing_title" class="card__title" :title="card.listing_title">
        {{ card.listing_title }}
      </p>

      <div class="card__foot">
        <span class="card__id" :title="card.asset_id">
          {{ card.asset_id.slice(0, 8) }}
        </span>
        <span class="card__sep">·</span>
        <span>crop {{ card.crop_index }}</span>
        <span v-if="card.target_eurio_id" class="card__target"
              :title="card.target_eurio_id">
          → {{ shortEurio(card.target_eurio_id) }}
        </span>
        <a
          v-if="card.listing_url"
          :href="card.listing_url"
          target="_blank"
          rel="noopener noreferrer"
          class="card__ebay"
          @click.stop
        >
          <ExternalLink class="h-3 w-3" /> eBay
        </a>
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
  transition: transform 180ms cubic-bezier(0.16, 1, 0.3, 1),
              box-shadow 180ms cubic-bezier(0.16, 1, 0.3, 1);
}
.card:hover {
  transform: translateY(-2px);
  box-shadow: 0 2px 6px rgba(14, 14, 31, 0.05),
              0 8px 24px rgba(14, 14, 31, 0.06);
}
.card--warn {
  border-color: var(--danger);
  box-shadow: 0 0 0 1px var(--danger-soft, rgba(209, 67, 67, 0.18));
}

.card__ribbon {
  position: absolute;
  top: 0; left: 0; right: 0;
  z-index: 2;
  padding: 4px 10px;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  text-align: center;
  background: var(--danger);
  color: var(--surface);
}

.card__stage {
  position: relative;
  aspect-ratio: 1 / 1;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: linear-gradient(135deg, var(--surface-2), var(--surface-1));
}
.card--warn .card__stage {
  padding-top: 22px;
}

.card__raw {
  width: 88%;
  height: 88%;
  object-fit: contain;
  filter: drop-shadow(0 4px 12px rgba(14, 14, 31, 0.14));
}
.card__fallback {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.card__bbox {
  position: absolute;
  pointer-events: none;
  border: 1.5px dashed var(--gold-300);
  box-shadow: 0 0 0 1px rgba(14, 14, 31, 0.18),
              0 0 18px rgba(200, 168, 100, 0.4);
  border-radius: 2px;
}
.card__bbox--warn {
  border-color: var(--danger);
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.4),
              0 0 22px rgba(209, 67, 67, 0.55);
}
.card__bbox::after {
  content: attr(data-dims);
  position: absolute;
  top: -18px;
  left: 0;
  padding: 1px 5px;
  font-family: var(--font-mono);
  font-size: 9px;
  color: var(--gold-700);
  background: var(--surface);
  border-radius: 3px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
  white-space: nowrap;
}
.card__bbox--warn::after {
  color: var(--danger);
  font-weight: 600;
}

.card__crop-chip {
  position: absolute;
  bottom: 10px;
  right: 10px;
  width: 62px;
  height: 62px;
  border-radius: 50%;
  overflow: hidden;
  border: 2px solid var(--surface);
  background: var(--surface-1);
  box-shadow: 0 2px 6px rgba(14, 14, 31, 0.05),
              0 8px 24px rgba(14, 14, 31, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
}
.card__crop-chip img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.card__crop-chip-arrow {
  position: absolute;
  top: -9px;
  left: -12px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--ink);
  color: var(--surface);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(14, 14, 31, 0.04),
              0 1px 3px rgba(14, 14, 31, 0.02);
}

.card__meta {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 10px 12px 12px;
  border-top: 1px solid var(--surface-2);
}
.card__row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}

.badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 7px;
  border-radius: 5px;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.02em;
}
.method-merged { background: var(--indigo-700); color: var(--gold-300); }
.method-hough  { background: var(--gold-100); color: var(--gold-700); }
.method-bbox   { background: #E6E8F5; color: var(--indigo-700); }
.method-manual { background: var(--surface-2); color: var(--ink-500); }

.badge--status { margin-left: auto; }
.status-needs    { background: #FBE7C5; color: #7A5320; }
.status-auto     { background: #D8EFE0; color: #1F6E48; }
.status-manual   { background: var(--surface-2); color: var(--ink-500); }
.status-rejected { background: var(--danger-soft, #f6dcd6); color: var(--danger); }
.status-other    { background: var(--surface-2); color: var(--ink-400); }

.area-ratio {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--ink-400);
  font-variant-numeric: tabular-nums;
}
.area-ratio b { color: var(--ink-700); font-weight: 500; }
.card--warn .area-ratio b { color: var(--danger); }

.card__title {
  font-size: 11.5px;
  color: var(--ink-500);
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card__foot {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-400);
}
.card__id  { color: var(--ink-500); }
.card__sep { color: var(--ink-300); }
.card__target {
  margin-left: 4px;
  color: var(--indigo-700);
  max-width: 80px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.card__ebay {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--indigo-600);
}
.card__ebay:hover { text-decoration: underline; }
</style>
