<script setup lang="ts">
// Tiroir §C4 — Review crops (scopé cohort).
// Trois plateaux (Queue manuelle / Auto-accept / CCProxy) avec compteurs
// restreints aux images eBay des coins de la cohort, qui ouvrent la review
// déjà filtrée (`?cohort=<id>`). Pas de traitement inline : on délègue aux
// pages /review existantes. Miroir compact du ReviewDashboardPage global.

import DrawerSection from '@/features/lab/components/DrawerSection.vue'
import { useCohortTriageStatsQuery } from '@/features/lab/composables/useLabQueries'
import type { DrawerState } from '@/features/lab/types'
import { ArrowUpRight, Bot, Eye, Package, RotateCcw, SkipForward, Wand2 } from 'lucide-vue-next'
import { computed } from 'vue'

const props = defineProps<{
  cohortId: string
}>()

const statsQuery = useCohortTriageStatsQuery(() => props.cohortId)
const stats = computed(() => statsQuery.data.value ?? null)
const loading = computed(() => statsQuery.isPending.value)

// WS1 : compteurs lus sur la LANE PERSISTÉE (review_queue.lane), plus aucune
// heuristique recalculée. Chaque carte ouvre la review filtrée sur sa lane →
// le compteur décroît à chaque décision dans cette lane.
const manualCount = computed(() => stats.value?.by_lane?.manual ?? 0)
const autoCount = computed(() => stats.value?.by_lane?.auto_accept ?? 0)
const claudeCount = computed(() => stats.value?.by_lane?.ccproxy ?? 0)
// Crops en review LOT (listings multi-pièces) — flow distinct du single.
const lotCount = computed(() => stats.value?.n_lot_crops ?? 0)
// Lots PAR LANE (F6 / B3) : on ne cache plus les lots manuels dans le fourre-tout.
// Les cartes I/II/III comptent les SINGLES de leur lane ; ce sont les lots de la
// même lane, surfacés en « +N lots » (et décomposés dans la carte IV).
const manualLots = computed(() => stats.value?.by_lane_lot?.manual ?? 0)
const autoLots = computed(() => stats.value?.by_lane_lot?.auto_accept ?? 0)
const ccproxyLots = computed(() => stats.value?.by_lane_lot?.ccproxy ?? 0)
function lotsNote(n: number): string | null {
  return n > 0 ? `+ ${fmt(n)} lots` : null
}
// Crops rejetés (récupérables via la grille) + items skippés (report dans la
// queue manuelle, informationnel). Surfacés en bande sous les plateaux.
const rejectedCount = computed(() => stats.value?.n_rejected ?? 0)
const skippedCount = computed(() => stats.value?.n_skipped ?? 0)
const recoverTo = computed(
  () => `/review/recover?cohort=${encodeURIComponent(props.cohortId)}`,
)

const plateaus = computed(() => [
  {
    key: 'manual',
    roman: 'I',
    eyebrow: 'Plateau primaire',
    title: 'Queue manuelle',
    icon: Eye,
    count: manualCount.value,
    unit: 'singles à trancher',
    subnote: lotsNote(manualLots.value),
    to: `/review/manual?cohort=${encodeURIComponent(props.cohortId)}&lane=manual`,
    accent: 'ink' as const,
  },
  {
    key: 'auto',
    roman: 'II',
    eyebrow: 'Plateau heuristique',
    title: 'Auto-accept',
    icon: Wand2,
    count: autoCount.value,
    unit: 'singles prêts à valider',
    subnote: lotsNote(autoLots.value),
    to: `/review/auto-accept?cohort=${encodeURIComponent(props.cohortId)}`,
    accent: 'gold' as const,
  },
  {
    key: 'ccproxy',
    roman: 'III',
    eyebrow: 'Plateau LLM',
    title: 'CCProxy',
    icon: Bot,
    count: claudeCount.value,
    unit: 'singles ambigus (LLM)',
    subnote: lotsNote(ccproxyLots.value),
    to: `/review/ccproxy?cohort=${encodeURIComponent(props.cohortId)}`,
    accent: 'indigo' as const,
  },
  {
    key: 'lot',
    roman: 'IV',
    eyebrow: 'Plateau lots',
    title: 'Lots',
    icon: Package,
    count: lotCount.value,
    // La review Lot vit dans ReviewPage (/review/manual, toggle Single|Lot via
    // ?mode=lot) — PAS sur /review (le hub global, qui ignore ?mode/?cohort).
    unit: 'crops en lots',
    // Décomposition par lane (B3) : la majorité des lots sont ccproxy/auto
    // (automatisables), peu sont manuels.
    subnote: lotCount.value > 0
      ? `${fmt(ccproxyLots.value)} ccproxy · ${fmt(autoLots.value)} auto · ${fmt(manualLots.value)} manuel`
      : null,
    to: `/review/manual?mode=lot&cohort=${encodeURIComponent(props.cohortId)}`,
    accent: 'gold' as const,
  },
])

const state = computed<DrawerState>(() => {
  if (loading.value || !stats.value) return 'empty'
  if (stats.value.n_pending === 0 && lotCount.value === 0) return 'ready'
  return 'partial'
})

const summary = computed(() => {
  if (loading.value || !stats.value) return 'Chargement…'
  if (stats.value.n_pending === 0 && lotCount.value === 0) return 'Tout reviewé pour cette cohort'
  return `${manualCount.value} à trancher · ${autoCount.value} auto · ${claudeCount.value} ambigus · ${lotCount.value} en lots`
})

function fmt(n: number): string {
  return n.toLocaleString('fr-FR')
}
</script>

<template>
  <DrawerSection
    number="C4"
    title="Review crops"
    :state="state"
    :summary="summary"
  >
    <template #body>
      <div v-if="loading" class="text-xs" style="color: var(--ink-400);">
        Chargement du triage…
      </div>
      <template v-else-if="stats">
        <div class="cards">
          <RouterLink
            v-for="p in plateaus"
            :key="p.key"
            :to="p.to"
            class="card"
            :class="`card--${p.accent}`"
          >
            <header class="card__head">
              <span class="card__roman">{{ p.roman }}</span>
              <span class="card__eyebrow">{{ p.eyebrow }}</span>
            </header>
            <div class="card__icon">
              <component :is="p.icon" :size="16" :stroke-width="1.5" />
            </div>
            <h3 class="card__title">{{ p.title }}</h3>
            <div class="card__number-row">
              <span class="card__number">{{ fmt(p.count) }}</span>
              <span class="card__unit">{{ p.unit }}</span>
            </div>
            <span v-if="p.subnote" class="card__subnote">{{ p.subnote }}</span>
            <footer class="card__cta">
              <span>{{ p.count === 0 ? 'Voir' : 'Entrer' }}</span>
              <ArrowUpRight :size="13" :stroke-width="1.6" />
            </footer>
          </RouterLink>
        </div>
        <div class="recover-strip">
          <RouterLink :to="recoverTo" class="recover-chip recover-chip--reject">
            <RotateCcw :size="13" :stroke-width="1.6" />
            <span class="recover-chip__num">{{ fmt(rejectedCount) }}</span>
            <span class="recover-chip__label">rejeté{{ rejectedCount > 1 ? 's' : '' }} à récupérer</span>
            <ArrowUpRight :size="12" :stroke-width="1.6" class="recover-chip__arrow" />
          </RouterLink>
          <div class="recover-chip recover-chip--skip">
            <SkipForward :size="13" :stroke-width="1.6" />
            <span class="recover-chip__num">{{ fmt(skippedCount) }}</span>
            <span class="recover-chip__label">skippé{{ skippedCount > 1 ? 's' : '' }} (dans la queue)</span>
          </div>
        </div>
        <p class="hint">
          Compteurs restreints aux pièces de la cohort. Cartes <strong>I-III</strong> =
          <strong>singles</strong> par lane (manuel / auto-accept / LLM) ; le « <strong>+N lots</strong> »
          sous chaque nombre = les lots de la MÊME lane (plus cachés). Carte <strong>IV Lots</strong>
          = tous les lots, décomposés par lane (la majorité sont ccproxy/auto = automatisables).
          Valider une pièce la rend éligible à l'entraînement (<strong>validés</strong> dans le tiroir eBay).
          Un <strong>rejet</strong> reste récupérable ; un <strong>skip</strong> revient seul dans la queue manuelle.
        </p>
      </template>
      <div v-else class="text-xs" style="color: var(--danger);">
        Erreur de chargement du triage.
      </div>
    </template>
  </DrawerSection>
</template>

<style scoped>
.cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
@media (max-width: 1100px) {
  .cards { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 720px) {
  .cards { grid-template-columns: 1fr; }
}

.card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 168px;
  padding: 14px 14px 12px;
  border: 1px solid var(--surface-3);
  border-radius: 6px;
  background: var(--surface);
  text-decoration: none;
  transition:
    transform 220ms var(--ease-out, ease),
    box-shadow 220ms var(--ease-out, ease),
    border-color 180ms var(--ease-out, ease);
}
.card:hover {
  transform: translateY(-2px);
  border-color: var(--ink-300);
  box-shadow: 0 18px 36px -26px rgba(14, 14, 31, 0.22);
}
.card--gold:hover { border-color: var(--gold-600); }
.card--indigo:hover { border-color: var(--indigo-700); }

.card__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.card__roman {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 16px;
  line-height: 1;
  color: var(--gold-600);
}
.card--ink .card__roman { color: var(--ink-500); }
.card--indigo .card__roman { color: var(--indigo-700); }
.card__eyebrow {
  font-family: var(--font-mono);
  font-size: 8.5px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
  white-space: nowrap;
}

.card__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 2px;
  background: var(--surface-1);
  color: var(--ink-700);
  border: 1px solid var(--surface-3);
}
.card--gold .card__icon {
  color: var(--gold-700);
  background: var(--gold-soft);
  border-color: var(--gold-300);
}
.card--indigo .card__icon {
  color: var(--indigo-700);
  background: var(--indigo-50);
  border-color: var(--indigo-200);
}

.card__title {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 18px;
  line-height: 1;
  color: var(--ink);
  letter-spacing: -0.01em;
}

.card__number-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  margin-top: auto;
}
.card__number {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 40px;
  line-height: 0.9;
  color: var(--ink);
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums lining-nums;
}
.card--gold .card__number { color: var(--indigo-700); }
.card--indigo .card__number { color: var(--indigo-700); }
.card__unit {
  font-family: var(--font-mono);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
  line-height: 1.3;
  padding-bottom: 4px;
  max-width: 90px;
}

.card__subnote {
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: var(--ink-400);
  margin-top: 2px;
  font-variant-numeric: tabular-nums;
}

.card__cta {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-top: 6px;
  padding-top: 9px;
  border-top: 1px solid var(--surface-3);
  font-family: var(--font-mono);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-700);
  transition: gap 180ms var(--ease-out, ease);
}
.card:hover .card__cta { gap: 8px; }

.recover-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
}
.recover-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 11px;
  border: 1px solid var(--surface-3);
  border-radius: 6px;
  background: var(--surface);
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-500);
  text-decoration: none;
  transition:
    border-color 160ms var(--ease-out, ease),
    transform 160ms var(--ease-out, ease);
}
.recover-chip__num {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 18px;
  line-height: 1;
  color: var(--ink);
  font-variant-numeric: tabular-nums lining-nums;
}
.recover-chip__arrow {
  margin-left: 2px;
  color: var(--ink-400);
}
.recover-chip--reject {
  cursor: pointer;
}
.recover-chip--reject:hover {
  border-color: var(--gold-600);
  transform: translateY(-1px);
}
.recover-chip--reject .recover-chip__num { color: var(--gold-700); }
.recover-chip--skip {
  color: var(--ink-400);
}

.hint {
  margin-top: 12px;
  font-size: 10px;
  line-height: 1.5;
  color: var(--ink-400);
}
</style>
