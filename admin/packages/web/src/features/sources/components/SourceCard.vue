<script setup lang="ts">
import { computed } from 'vue'
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Construction,
  Database,
  FileText,
  Globe,
  Image as ImageIcon,
  Newspaper,
  PencilRuler,
  Search,
  ShoppingBag,
  XCircle,
} from 'lucide-vue-next'
import type { Component } from 'vue'
import type { HealthState, SourceStatus } from '../composables/useSourcesApi'
import QuotaProgressBar from './QuotaProgressBar.vue'
import DeltaIndicator from './DeltaIndicator.vue'
import CliHintsBlock from './CliHintsBlock.vue'

const props = defineProps<{ source: SourceStatus }>()

const SOURCE_ICON: Record<string, Component> = {
  numista_match: Search,
  numista_enrich: PencilRuler,
  numista_images: ImageIcon,
  ebay: ShoppingBag,
  lmdlp: Newspaper,
  mdp: FileText,
  bce: Globe,
  wikipedia: Database,
}

const icon = computed(() => SOURCE_ICON[props.source.id] ?? Database)

// ─── Health pill ────────────────────────────────────────────────────────

const HEALTH_TONE: Record<HealthState, string> = {
  healthy: 'var(--success)',
  warning: 'var(--warning)',
  error: 'var(--danger)',
}

const HEALTH_LABEL: Record<HealthState, string> = {
  healthy: 'healthy',
  warning: 'attention',
  error: 'erreur',
}

const healthIcon = computed(() => {
  switch (props.source.health) {
    case 'healthy':
      return CheckCircle2
    case 'warning':
      return AlertTriangle
    case 'error':
      return XCircle
  }
  return CheckCircle2
})

// ─── Temporal formatting ────────────────────────────────────────────────

const lastFetchLabel = computed(() => {
  const days = props.source.temporal.days_since_last_run
  if (days === null) return 'Jamais fetché'
  if (days === 0) return "aujourd'hui"
  if (days === 1) return 'hier'
  return `il y a ${days} jours`
})

const lastFetchAbsoluteLabel = computed(() => {
  const iso = props.source.temporal.last_run_at
  if (!iso) return null
  const d = new Date(iso)
  const dd = String(d.getDate()).padStart(2, '0')
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const yyyy = d.getFullYear()
  return `${yyyy}-${mm}-${dd}`
})

const cadenceText = computed(() => {
  const c = props.source.temporal.expected_cadence_days
  if (c >= 365) return `tous les ${Math.round(c / 365)} an${c >= 730 ? 's' : ''}`
  if (c >= 30) return `tous les ${c} jours`
  return `tous les ${c} jours`
})

const overdueRatio = computed(() => {
  const days = props.source.temporal.days_since_last_run
  const cad = props.source.temporal.expected_cadence_days
  if (days === null || cad <= 0) return 0
  return days / cad
})
</script>

<template>
  <article
    class="flex h-full flex-col overflow-hidden rounded-lg border transition-shadow hover:shadow-sm"
    :style="source.is_future
      ? 'border-color: var(--surface-3); background: repeating-linear-gradient(135deg, var(--surface), var(--surface) 12px, var(--surface-1) 12px, var(--surface-1) 13px); opacity: 0.78;'
      : 'border-color: var(--surface-3); background: var(--surface);'"
  >
    <!-- ─── Header ──────────────────────────────────────────────── -->
    <header
      class="flex items-start justify-between gap-3 border-b px-5 py-3.5"
      style="border-color: var(--surface-2);"
    >
      <div class="flex items-start gap-3">
        <div
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-md"
          :style="source.is_future
            ? 'background: var(--surface-2);'
            : `background: color-mix(in srgb, ${HEALTH_TONE[source.health]} 8%, var(--surface-1));`"
        >
          <component
            :is="icon"
            class="h-4 w-4"
            :style="source.is_future
              ? 'color: var(--ink-400);'
              : `color: ${HEALTH_TONE[source.health]};`"
          />
        </div>
        <div class="min-w-0">
          <h3
            class="font-display text-base font-semibold leading-tight"
            :style="source.is_future ? 'color: var(--ink-500);' : 'color: var(--ink);'"
          >
            {{ source.label }}
          </h3>
          <p class="mt-0.5 text-[11px]" style="color: var(--ink-500);">
            {{ source.subtitle }}
          </p>
        </div>
      </div>

      <!-- Status pill : "à venir" en mode future, sinon health pill + overdue -->
      <div class="flex shrink-0 flex-col items-end gap-1">
        <div
          v-if="source.is_future"
          class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium"
          :style="{
            borderColor: 'var(--ink-300)',
            color: 'var(--ink-500)',
            background: 'var(--surface-1)',
          }"
        >
          <Construction class="h-3 w-3" />
          à venir
        </div>

        <template v-else>
          <div
            class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium"
            :title="source.health_reason ?? undefined"
            :style="{
              borderColor: HEALTH_TONE[source.health],
              color: HEALTH_TONE[source.health],
              background: `color-mix(in srgb, ${HEALTH_TONE[source.health]} 6%, var(--surface))`,
            }"
          >
            <component :is="healthIcon" class="h-3 w-3" />
            {{ HEALTH_LABEL[source.health] }}
          </div>
          <div
            v-if="source.temporal.overdue"
            class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium"
            :style="{
              borderColor: 'var(--warning)',
              color: 'var(--warning)',
              background: 'color-mix(in srgb, var(--warning) 6%, var(--surface))',
            }"
            :title="`${source.temporal.days_since_last_run}j sans fetch (cadence ${source.temporal.expected_cadence_days}j)`"
          >
            <Clock class="h-2.5 w-2.5" />
            overdue ×{{ overdueRatio.toFixed(1) }}
          </div>
        </template>
      </div>
    </header>

    <!-- ─── Future placeholder (replaces all detail blocks) ────────── -->
    <section
      v-if="source.is_future"
      class="flex flex-1 flex-col items-center justify-center px-5 py-10 text-center"
    >
      <Construction class="mb-3 h-7 w-7" style="color: var(--ink-400);" />
      <p class="font-display text-sm italic" style="color: var(--ink-500);">
        Source planifiée
      </p>
      <p
        v-if="source.future_note"
        class="mt-2 max-w-md text-[11px] leading-relaxed"
        style="color: var(--ink-500);"
      >
        {{ source.future_note }}
      </p>
      <p
        class="mt-3 font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--ink-400);"
      >
        Cible — {{ source.coverage.total_target }} {{ source.coverage.unit }}
      </p>
    </section>

    <!-- Sentinel : tout le bloc principal est masqué en mode future -->
    <template v-if="!source.is_future">

    <!-- ─── Bloc 1 : Quota or "shared" notice ──────────────────────── -->
    <section class="border-b px-5 py-4" style="border-color: var(--surface-2);">
      <QuotaProgressBar v-if="source.quota" :quota="source.quota" :compact="true" />

      <p
        v-else-if="source.quota_group"
        class="font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--ink-500);"
      >
        Quota partagé · groupe
        <span class="font-medium normal-case tracking-normal" style="color: var(--ink);">
          {{ source.quota_group }}
        </span>
        <span class="ml-1 opacity-70">(voir bandeau ci-dessus)</span>
      </p>

      <p
        v-else
        class="font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--ink-500);"
      >
        Pas de quota
        <span class="ml-1 normal-case tracking-normal opacity-70">— scrape HTML</span>
      </p>
    </section>

    <!-- ─── Bloc 2 : Dernier fetch + Couverture ────────────────────── -->
    <section
      class="grid grid-cols-2 gap-4 border-b px-5 py-4"
      style="border-color: var(--surface-2);"
    >
      <!-- Dernier fetch -->
      <div>
        <p
          class="font-mono text-[10px] uppercase tracking-wider"
          style="color: var(--ink-500);"
        >
          Dernier fetch
        </p>
        <p class="mt-1 text-sm font-medium" style="color: var(--ink);">
          {{ lastFetchLabel }}
        </p>
        <p
          v-if="lastFetchAbsoluteLabel"
          class="font-mono text-[11px]"
          style="color: var(--ink-500);"
        >
          {{ lastFetchAbsoluteLabel }}
          <span v-if="source.temporal.last_run_kind">· {{ source.temporal.last_run_kind }}</span>
        </p>
        <p
          class="mt-1 text-[11px]"
          :style="source.temporal.overdue
            ? 'color: var(--warning); font-weight: 500;'
            : 'color: var(--ink-500);'"
        >
          Cadence cible : {{ cadenceText }}
        </p>
        <div class="mt-2">
          <DeltaIndicator
            :delta="source.temporal.delta"
            :has-price-delta="source.id === 'ebay'"
          />
        </div>
      </div>

      <!-- Couverture -->
      <div>
        <p
          class="font-mono text-[10px] uppercase tracking-wider"
          style="color: var(--ink-500);"
        >
          Couverture
        </p>
        <p class="mt-1 font-mono text-lg font-medium tabular-nums" style="color: var(--ink);">
          {{ source.coverage.enriched.toLocaleString('fr-FR') }}
          <span class="text-sm opacity-60">
            / {{ source.coverage.total_target.toLocaleString('fr-FR') }}
          </span>
        </p>
        <p class="font-mono text-[11px]" style="color: var(--ink-500);">
          {{ source.coverage.unit }}
        </p>

        <!-- Mini-bar coverage -->
        <div
          class="mt-2 overflow-hidden rounded-full"
          style="height: 4px; background: var(--surface-2);"
        >
          <div
            class="h-full rounded-full transition-[width] duration-500 ease-out"
            :style="{
              width: `${Math.min(100, source.coverage.pct)}%`,
              background: source.coverage.pct >= 80
                ? 'var(--success)'
                : source.coverage.pct >= 40
                  ? 'var(--gold-600)'
                  : 'var(--ink-300)',
            }"
          />
        </div>
        <p class="mt-1 font-mono text-[11px] tabular-nums" style="color: var(--ink-500);">
          {{ source.coverage.pct.toFixed(1) }}%
        </p>
      </div>
    </section>

    <!-- ─── Bloc 3 : CLI hints (expands to fill remaining height) ─── -->
    <div class="flex-1">
      <CliHintsBlock :hints="source.cli_hints" />
    </div>
    </template>
  </article>
</template>
