<script setup lang="ts">
import { computed } from 'vue'
import type { BenchRunCropsSummary } from '../composables/useBenchApi'

const props = defineProps<{
  summary: BenchRunCropsSummary
  selectedMethod: string | null
  selectedStatus: string | null
  selectedQualityBucket: string | null  // bucket label or null
}>()

const emit = defineEmits<{
  (e: 'select-method', method: string | null): void
  (e: 'select-status', status: string | null): void
  (e: 'select-quality', label: string | null): void
}>()

const hasQuality = computed(() =>
  props.summary.quality_histogram.some(b => b.n > 0),
)

const maxBucketCount = computed(() => Math.max(
  1, ...props.summary.quality_histogram.map(b => b.n),
))

function methodSwatch(name: string): string {
  if (name.includes('manual')) return 'var(--ink-400)'
  if (name.includes('hough')) return 'var(--gold-700)'
  if (name.startsWith('yolo+bbox')) return 'var(--indigo-300)'
  return 'var(--indigo-700)'  // merged / yolo / other
}

function bucketKind(lo: number): 'low' | 'mid' | 'high' {
  if (lo < 0.4) return 'low'
  if (lo < 0.6) return 'mid'
  return 'high'
}

function toggleMethod(m: string) {
  emit('select-method', props.selectedMethod === m ? null : m)
}
function toggleStatus(s: string) {
  emit('select-status', props.selectedStatus === s ? null : s)
}
function toggleQuality(label: string) {
  emit('select-quality', props.selectedQualityBucket === label ? null : label)
}
</script>

<template>
  <aside class="analytics">
    <!-- Diagnostic signal block -->
    <div v-if="summary.diagnostic.note" class="signal">
      <div class="signal__lbl">Diagnostic</div>
      <p class="signal__note">{{ summary.diagnostic.note }}</p>
    </div>
    <div v-else-if="summary.n_undercrops > 0" class="signal signal--muted">
      <div class="signal__lbl">Diagnostic</div>
      <p class="signal__note">
        <b>{{ summary.n_undercrops }}</b> undercrops sur
        <b>{{ summary.n_crops }}</b> crops ({{ summary.pct_undercrops.toFixed(1) }} %).
        Pas de concentration nette par méthode.
      </p>
    </div>

    <!-- Quality histogram (only if any quality_score known) -->
    <div v-if="hasQuality" class="panel">
      <div class="panel__title">
        Quality score
        <span class="panel__count">
          σ {{ summary.quality_std?.toFixed(2) ?? '—' }} · n={{ summary.n_crops }}
        </span>
      </div>
      <div class="histo">
        <div class="histo__caption">
          <span class="histo__quart">
            médiane <b>{{ summary.quality_median?.toFixed(2) ?? '—' }}</b>
          </span>
        </div>
        <div class="histo__bars">
          <button
            v-for="b in summary.quality_histogram"
            :key="b.label"
            class="histo__bar-btn"
            :class="{ active: selectedQualityBucket === b.label }"
            @click="toggleQuality(b.label)"
          >
            <div
              class="histo__bar"
              :class="`histo__bar--${bucketKind(b.range_lo)}`"
              :style="{ height: `${(b.n / maxBucketCount) * 100}%` }"
            ></div>
            <div class="histo__bar-label">{{ b.label }}</div>
          </button>
        </div>
        <div class="histo__axis">
          <span>0.0</span><span>0.5</span><span>1.0</span>
        </div>
      </div>
    </div>
    <div v-else class="panel panel--empty">
      <div class="panel__title">Quality score</div>
      <p class="panel__empty-note">
        Pas de quality_score persisté pour ce run — filtre indisponible.
      </p>
    </div>

    <!-- Method ventilation -->
    <div class="panel">
      <div class="panel__title">
        Méthode de détection
        <span class="panel__count">cliquable</span>
      </div>
      <div class="methods">
        <button
          v-for="m in summary.methods"
          :key="m.method"
          class="method-row"
          :class="{ active: selectedMethod === m.method }"
          :style="{ '--m-pct': `${m.pct}%` }"
          @click="toggleMethod(m.method)"
        >
          <span class="method-row__swatch" :style="{ background: methodSwatch(m.method) }"></span>
          <span class="method-row__name">{{ m.method }}</span>
          <span v-if="m.n_undercrops > 0" class="method-row__under">
            ▲ {{ m.n_undercrops }}
          </span>
          <span class="method-row__ratio">
            <b>{{ m.n }}</b> · {{ m.pct.toFixed(0) }} %
          </span>
        </button>
      </div>
    </div>

    <!-- Status filter -->
    <div v-if="summary.statuses.length" class="panel">
      <div class="panel__title">Résolution</div>
      <div class="statuses">
        <button
          class="status-chip"
          :class="{ active: selectedStatus == null }"
          @click="emit('select-status', null)"
        >
          tout <span class="status-chip__n">{{ summary.n_crops }}</span>
        </button>
        <button
          v-for="s in summary.statuses"
          :key="s.status"
          class="status-chip"
          :class="{ active: selectedStatus === s.status }"
          @click="toggleStatus(s.status)"
        >
          {{ s.status }} <span class="status-chip__n">{{ s.n }}</span>
        </button>
      </div>
    </div>

    <!-- Threshold info -->
    <div class="threshold-note">
      seuil undercrop : aire bbox / min(raw)² &lt;
      <code>{{ summary.undercrop_threshold.toFixed(2) }}</code>
      <span class="threshold-note__sub">
        (ajustable via <code>?undercrop_threshold=</code>)
      </span>
    </div>
  </aside>
</template>

<style scoped>
.analytics {
  position: sticky;
  top: 0;                       /* sticky depuis le haut du grid parent */
  max-height: calc(100vh - 60px);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 22px;
  padding: 22px 22px 28px;
  background: var(--surface-1);
  border-right: 1px solid var(--surface-3);
}

.signal {
  position: relative;
  overflow: hidden;
  padding: 14px 16px;
  border-radius: 14px;
  background: var(--ink);
  color: var(--surface);
  box-shadow: 0 8px 24px rgba(26, 27, 75, 0.28);
}
.signal::before {
  content: "";
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at 110% -20%, rgba(200, 168, 100, 0.22), transparent 60%);
  pointer-events: none;
}
.signal--muted { background: var(--ink-700); }
.signal__lbl {
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.13em;
  color: var(--gold-300);
}
.signal__note {
  position: relative;
  margin-top: 6px;
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 13.5px;
  line-height: 1.4;
  color: var(--ink-200);
  letter-spacing: -0.005em;
}
.signal__note b {
  font-style: normal;
  font-family: var(--font-mono);
  font-weight: 500;
  color: var(--gold-300);
}

.panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.panel__title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 10.5px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.11em;
  color: var(--ink-400);
}
.panel__count {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-500);
  letter-spacing: 0;
}
.panel__empty-note {
  font-size: 11.5px;
  color: var(--ink-400);
  font-style: italic;
  font-family: var(--font-display);
  line-height: 1.4;
}

/* Histogram */
.histo {
  padding: 14px 14px 12px;
  background: var(--surface);
  border: 1px solid var(--surface-3);
  border-radius: 14px;
}
.histo__caption {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 10px;
}
.histo__quart {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 13px;
  color: var(--ink-500);
}
.histo__quart b {
  color: var(--ink);
  font-weight: 600;
  font-style: normal;
  font-family: var(--font-mono);
}
.histo__bars {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 5px;
  height: 72px;
  align-items: end;
}
.histo__bar-btn {
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  align-items: center;
  gap: 4px;
  height: 100%;
  transition: opacity 160ms;
}
.histo__bar-btn:hover { opacity: 0.78; }
.histo__bar {
  width: 100%;
  border-radius: 4px 4px 2px 2px;
  background: linear-gradient(to top, var(--indigo-500), var(--indigo-300));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.18);
}
.histo__bar--low { background: linear-gradient(to top, var(--danger), #E58A8A); }
.histo__bar--mid { background: linear-gradient(to top, var(--warning), #E8B071); }
.histo__bar-label {
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--ink-400);
}
.histo__bar-btn.active .histo__bar {
  box-shadow: 0 0 0 2px var(--ink),
              inset 0 1px 0 rgba(255, 255, 255, 0.25);
}
.histo__bar-btn.active .histo__bar-label {
  color: var(--ink);
  font-weight: 500;
}
.histo__axis {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--ink-300);
}

/* Methods */
.methods {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.method-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 12px;
  background: var(--surface);
  border: 1px solid var(--surface-3);
  border-radius: 11px;
  text-align: left;
  overflow: hidden;
  transition: all 160ms;
}
.method-row:hover { border-color: var(--ink-300); }
.method-row.active {
  border-color: var(--indigo-600);
  background: var(--indigo-50);
}
.method-row__swatch {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.method-row__name {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 500;
  color: var(--ink);
  text-transform: lowercase;
}
.method-row__under {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: 8px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--danger);
}
.method-row__ratio {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-400);
  font-variant-numeric: tabular-nums;
}
.method-row__ratio b { color: var(--ink); font-weight: 500; }
.method-row::after {
  content: "";
  position: absolute;
  left: 0;
  bottom: 0;
  height: 2px;
  width: var(--m-pct, 0%);
  background: var(--ink-200);
  transition: background 160ms;
}
.method-row.active::after { background: var(--indigo-600); }

/* Statuses */
.statuses {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  background: var(--surface);
  border: 1px solid var(--surface-3);
  border-radius: 999px;
  font-size: 11px;
  color: var(--ink-500);
  transition: all 140ms;
}
.status-chip:hover { border-color: var(--ink-300); color: var(--ink); }
.status-chip.active {
  background: var(--ink);
  color: var(--surface);
  border-color: var(--ink);
}
.status-chip__n {
  font-family: var(--font-mono);
  opacity: 0.7;
}

.threshold-note {
  margin-top: auto;
  padding-top: 12px;
  font-size: 10.5px;
  color: var(--ink-400);
  line-height: 1.4;
}
.threshold-note code {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--ink-500);
  background: var(--surface-2);
  padding: 1px 4px;
  border-radius: 3px;
}
.threshold-note__sub {
  display: block;
  margin-top: 2px;
  color: var(--ink-300);
}
</style>
