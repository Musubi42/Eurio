<script setup lang="ts">
// Dashboard de triage /review — entrée unique vers les 2 voies de
// review : queue manuelle + auto-accept heuristique. (CCProxy/Claude
// retiré — décision PO : on ne garde que manuel + auto-accept.)
//
// Pas un mode parmi d'autres mais le hub. Les pages filles
// (/review/manual, /review/auto-accept) sont les outils ; cette page
// donne la vision globale.
//
// Design : table de travail d'un numismate. Plateaux d'examen
// numérotés en chiffres romains, chiffres héros en Fraunces italique,
// ruban de répartition fin sous les cards. Cohérent avec
// AutoAcceptReviewPage.vue mais avec une emphase éditoriale plus
// marquée (c'est la page d'accueil de la zone).

import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowUpRight,
  Eye,
  Wand2,
  RotateCcw,
} from 'lucide-vue-next'
import { fetchTriageStats, type TriageStats } from '../composables/useReviewApi'

const router = useRouter()
const status = ref<'loading' | 'ready' | 'error'>('loading')
const error = ref<string | null>(null)
const stats = ref<TriageStats | null>(null)

async function load() {
  status.value = 'loading'
  error.value = null
  try {
    stats.value = await fetchTriageStats()
    status.value = 'ready'
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
    status.value = 'error'
  }
}

onMounted(load)

// ─── Dérivés ─────────────────────────────────────────────────────────────

const manualCount = computed(() => {
  // Compteur de la LANE manuelle persistée (WS1) — exactement le filtre que sert
  // /review/manual (lane='manual' OR NULL, single, open). Garantit que la carte ==
  // ce que le reviewer voit. L'ancien calcul (n_pending − handled, par verdict) se
  // dégradait : quand tous les pending étaient partiels/divergents (désormais manual),
  // rest=0 → fallback sur n_pending → la carte affichait 142 « manuels » alors que
  // la page manual était vide. Bug PO 2026-06-15.
  return stats.value?.by_lane.manual ?? 0
})

const autoCount = computed(() => stats.value?.by_verdict.auto_candidate ?? 0)

const segments = computed(() => {
  if (!stats.value || stats.value.n_pending === 0) return []
  const total = stats.value.n_pending
  const v = stats.value.by_verdict
  const raw = [
    { key: 'auto_candidate', label: 'Auto-acceptables', value: v.auto_candidate, color: 'var(--success)' },
    { key: 'partial',        label: 'Partiels',         value: v.partial,        color: 'var(--gold-600)' },
    { key: 'divergent',      label: 'Divergents',       value: v.divergent,      color: 'var(--danger)' },
    { key: 'unknown',        label: 'Hors scope',       value: v.unknown,        color: 'var(--ink-300)' },
  ]
  return raw.map((s) => ({ ...s, pct: (s.value / total) * 100 }))
})

function go(path: string) {
  void router.push(path)
}

function fmt(n: number): string {
  return n.toLocaleString('fr-FR')
}
</script>

<template>
  <div class="dash flex h-full flex-col overflow-y-auto">
    <!-- ═══ Header ═══ -->
    <header
      class="flex flex-wrap items-end justify-between gap-4 border-b px-10 pb-5 pt-7"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <div>
        <p
          class="font-mono text-[10px] uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          Cabinet — table de travail
        </p>
        <h1
          class="mt-1 font-display text-[44px] italic font-medium leading-none"
          style="color: var(--ink); letter-spacing: -0.02em;"
        >
          Review.
        </h1>
        <p class="mt-2 max-w-md text-sm" style="color: var(--ink-500);">
          Deux voies d'identification pour les images scrapées. Choisissez le plateau d'examen.
        </p>
      </div>

      <button
        type="button"
        class="reload-btn inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 font-mono text-[10px] uppercase transition-all"
        style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface-1); letter-spacing: var(--tracking-eyebrow);"
        :disabled="status === 'loading'"
        title="Recharger les stats"
        @click="load"
      >
        <RotateCcw
          class="h-3 w-3"
          :class="{ 'animate-spin': status === 'loading' }"
        />
        Recharger
      </button>
    </header>

    <!-- ═══ Body ═══ -->
    <section class="flex-1 px-10 py-9">
      <!-- Error state -->
      <div
        v-if="status === 'error'"
        class="flex flex-col items-center justify-center gap-3 py-24 text-center"
      >
        <p
          class="font-display text-4xl italic font-medium"
          style="color: var(--danger);"
        >
          Le cabinet est silencieux.
        </p>
        <p class="max-w-md text-sm" style="color: var(--ink-500);">
          {{ error }}
        </p>
        <button
          type="button"
          class="mt-4 inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px]"
          style="border-color: var(--surface-3); color: var(--ink-700); background: var(--surface-1);"
          @click="load"
        >
          Réessayer
        </button>
      </div>

      <template v-else>
        <!-- ─── Bandeau 3 plateaux ─── -->
        <div class="cards grid gap-5 lg:grid-cols-3" :class="{ 'is-loading': status === 'loading' }">
          <!-- I — QUEUE MANUELLE -->
          <article
            class="card card-active"
            :style="{ '--enter-delay': '40ms' }"
            @click="go('/review/manual')"
            role="link"
            tabindex="0"
            @keydown.enter="go('/review/manual')"
          >
            <header class="card-head">
              <span class="card-roman">I</span>
              <span class="card-eyebrow">Plateau primaire</span>
            </header>

            <div class="card-icon">
              <Eye :size="18" :stroke-width="1.4" />
            </div>

            <h2 class="card-title">Queue manuelle</h2>

            <div class="card-number-row">
              <span class="card-number" :class="{ 'is-skeleton': status === 'loading' }">
                {{ status === 'loading' ? '—' : fmt(manualCount) }}
              </span>
              <span class="card-number-unit">à trancher<br />à la main</span>
            </div>

            <p class="card-sub">
              <template v-if="status === 'loading'">Chargement…</template>
              <template v-else>
                <span class="font-mono tabular-nums" style="color: var(--ink-700);">{{ stats?.n_done_today ?? 0 }}</span>
                décidées aujourd'hui
                <span class="dot">·</span>
                <span class="font-mono tabular-nums" style="color: var(--ink-700);">{{ stats?.n_done_this_week ?? 0 }}</span>
                cette semaine
              </template>
            </p>

            <footer class="card-cta">
              <span class="card-cta-label">Entrer</span>
              <ArrowUpRight :size="14" :stroke-width="1.6" />
            </footer>
          </article>

          <!-- II — AUTO-ACCEPT -->
          <article
            class="card card-active card-gold"
            :style="{ '--enter-delay': '120ms' }"
            @click="go('/review/auto-accept')"
            role="link"
            tabindex="0"
            @keydown.enter="go('/review/auto-accept')"
          >
            <header class="card-head">
              <span class="card-roman">II</span>
              <span class="card-eyebrow">Plateau heuristique</span>
            </header>

            <div class="card-icon">
              <Wand2 :size="18" :stroke-width="1.4" />
            </div>

            <h2 class="card-title">Auto-accept</h2>

            <div class="card-number-row">
              <span class="card-number" :class="{ 'is-skeleton': status === 'loading' }">
                {{ status === 'loading' ? '—' : fmt(autoCount) }}
              </span>
              <span class="card-number-unit">prêts<br />à valider</span>
            </div>

            <p class="card-sub">
              <template v-if="status === 'loading'">Chargement…</template>
              <template v-else>
                Dino + texte convergent
                <span class="dot">·</span>
                <span class="font-mono tabular-nums" style="color: var(--ink-700);">{{ stats?.n_done_today_auto_dino ?? 0 }}</span>
                auto-acceptées aujourd'hui
              </template>
            </p>

            <footer class="card-cta">
              <span class="card-cta-label">
                {{ autoCount === 0 ? 'Aucun candidat' : `Réviser ${fmt(autoCount)}` }}
              </span>
              <ArrowUpRight v-if="autoCount > 0" :size="14" :stroke-width="1.6" />
            </footer>
          </article>

        </div>

        <!-- ─── Vision globale : ruban segmenté ─── -->
        <section v-if="status === 'ready'" class="ribbon-section mt-12">
          <header class="ribbon-head">
            <div>
              <p
                class="font-mono text-[10px] uppercase"
                style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
              >
                Vision globale · queue pending
              </p>
              <p
                class="mt-1 font-display text-[26px] italic font-medium leading-none"
                style="color: var(--ink); letter-spacing: -0.01em;"
              >
                {{ fmt(stats?.n_pending ?? 0) }}
                <span style="color: var(--ink-400);" class="not-italic font-mono text-xs ml-1.5 align-middle uppercase tracking-wider">items</span>
              </p>
            </div>

            <p
              class="hidden md:block max-w-sm text-right font-mono text-[10px] uppercase"
              style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow); line-height: 1.6;"
            >
              Répartition par verdict d'auto-validation.<br/>
              Les seuils vivent dans <code class="code">foundation/thresholds.py</code>.
            </p>
          </header>

          <!-- Ruban -->
          <div v-if="stats && stats.n_pending > 0" class="ribbon mt-4">
            <div
              v-for="(seg, i) in segments"
              :key="seg.key"
              class="ribbon-seg"
              :style="{
                width: seg.pct + '%',
                background: seg.color,
                '--seg-delay': (300 + i * 80) + 'ms',
              }"
              :title="`${seg.label} — ${fmt(seg.value)} (${seg.pct.toFixed(1)}%)`"
            />
          </div>
          <div v-else class="ribbon-empty mt-4">
            <p class="font-mono text-[10px] uppercase" style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);">
              Queue vide
            </p>
          </div>

          <!-- Légende -->
          <ul class="legend mt-5">
            <li v-for="seg in segments" :key="seg.key" class="legend-item">
              <span class="legend-swatch" :style="{ background: seg.color }" />
              <span class="legend-label">{{ seg.label }}</span>
              <span class="legend-value">{{ fmt(seg.value) }}</span>
              <span class="legend-pct">{{ seg.pct.toFixed(1) }}%</span>
            </li>
          </ul>
        </section>
      </template>
    </section>
  </div>
</template>

<style scoped>
.dash {
  background:
    radial-gradient(1200px 600px at 90% -10%, rgba(200,168,100,0.07), transparent 60%),
    radial-gradient(900px 500px at -10% 110%, rgba(26,27,75,0.05), transparent 60%),
    var(--surface);
}

/* ─── Cards ─────────────────────────────────────────────────────────────── */
.cards {
  --card-h: 280px;
}

.card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: var(--card-h);
  padding: 22px 22px 18px;
  border: 1px solid var(--surface-3);
  border-radius: 4px;
  background: var(--surface);
  cursor: pointer;
  isolation: isolate;
  overflow: hidden;
  transition:
    transform 320ms var(--ease-out),
    box-shadow 320ms var(--ease-out),
    border-color 220ms var(--ease-out),
    background 220ms var(--ease-out);
  opacity: 0;
  transform: translateY(10px);
  animation: card-rise 600ms var(--ease-out) var(--enter-delay, 0ms) forwards;
}

.cards.is-loading .card {
  animation-play-state: paused;
}

@keyframes card-rise {
  to { opacity: 1; transform: translateY(0); }
}

/* Subtle paper texture on every card via inner highlight + grain dots */
.card::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    radial-gradient(circle at 1px 1px, rgba(14,14,31,0.025) 1px, transparent 0);
  background-size: 3px 3px;
  pointer-events: none;
  z-index: 0;
}
.card > * { position: relative; z-index: 1; }

/* Hairline accent dans le coin haut-droit, comme un onglet de catalogue */
.card::after {
  content: '';
  position: absolute;
  top: 0;
  right: 22px;
  width: 1px;
  height: 18px;
  background: var(--ink-300);
  z-index: 0;
}

.card-active:hover {
  transform: translateY(-3px);
  border-color: var(--ink-300);
  box-shadow: 0 24px 48px -28px rgba(14,14,31,0.18),
              0 2px 0 0 var(--ink) inset;
}
.card-active:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--ink), 0 0 0 4px var(--surface);
}

.card-gold:hover {
  border-color: var(--gold-600);
  box-shadow: 0 24px 48px -28px rgba(184,151,78,0.32),
              0 2px 0 0 var(--gold-600) inset;
}

.card-indigo:hover {
  border-color: var(--indigo-700);
  box-shadow: 0 24px 48px -28px rgba(26,27,75,0.32),
              0 2px 0 0 var(--indigo-700) inset;
}
.card-indigo .card-roman { color: var(--indigo-700); }
.card-indigo .card-icon {
  color: var(--indigo-700);
  background: var(--indigo-50);
  border-color: var(--indigo-200);
}
.card-indigo .card-number { color: var(--indigo-700); }
.card-indigo:hover .card-cta { color: var(--indigo-700); }

.card-pending {
  cursor: not-allowed;
  background:
    repeating-linear-gradient(
      135deg,
      transparent 0 18px,
      rgba(199, 177, 119, 0.04) 18px 19px
    ),
    var(--surface-1);
  border-color: var(--surface-3);
  opacity: 0.92;
}
.card-pending:hover {
  /* Aucun lift — explicitement "pas encore disponible" */
  transform: translateY(0);
  border-color: var(--surface-3);
}
.card-pending .card-title,
.card-pending .card-number {
  color: var(--ink-500) !important;
}

/* ─── Card head ─────────────────────────────────────────────────────────── */
.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 4px;
}

.card-roman {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 22px;
  line-height: 1;
  color: var(--gold-600);
  letter-spacing: 0.02em;
}
.card-gold .card-roman { color: var(--gold-700); }
.card-pending .card-roman { color: var(--ink-300); }

.card-eyebrow {
  font-family: var(--font-mono);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
  white-space: nowrap;
}

.card-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 2px;
  background: var(--surface-1);
  color: var(--ink-700);
  border: 1px solid var(--surface-3);
}
.card-gold .card-icon {
  color: var(--gold-700);
  background: var(--gold-soft);
  border-color: var(--gold-300);
}
.card-pending .card-icon {
  color: var(--ink-400);
  background: var(--surface-2);
}

.card-title {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 28px;
  line-height: 1;
  color: var(--ink);
  letter-spacing: -0.015em;
  margin-top: 4px;
}

/* ─── Card number ───────────────────────────────────────────────────────── */
.card-number-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  margin-top: auto;
}

.card-number {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 76px;
  line-height: 0.88;
  color: var(--ink);
  letter-spacing: -0.04em;
  font-variant-numeric: tabular-nums lining-nums;
}
.card-gold .card-number { color: var(--indigo-700); }

.card-number.is-skeleton {
  color: var(--ink-300);
}

.card-number-unit {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
  line-height: 1.35;
  padding-bottom: 6px;
}

.card-sub {
  font-family: var(--font-ui);
  font-size: 12px;
  color: var(--ink-500);
  line-height: 1.55;
  min-height: 34px;
}
.card-sub .dot {
  color: var(--ink-300);
  margin: 0 4px;
}

/* ─── Card CTA ──────────────────────────────────────────────────────────── */
.card-cta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  padding-top: 12px;
  border-top: 1px solid var(--surface-3);
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-700);
  transition: color 200ms var(--ease-out), gap 200ms var(--ease-out);
}
.card-cta-label { font-weight: 600; }

.card-active:hover .card-cta {
  color: var(--ink);
  gap: 10px;
}
.card-gold:hover .card-cta {
  color: var(--gold-700);
}

.card-cta-disabled {
  color: var(--ink-400);
}

/* ─── Pending stamp ─────────────────────────────────────────────────────── */
.card-pending-stamp {
  position: absolute;
  top: 16px;
  right: 16px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 7px 3px 6px;
  border: 1px solid var(--gold-600);
  border-radius: 999px;
  font-family: var(--font-mono);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--gold-700);
  background: var(--surface);
  z-index: 2;
}

/* ─── Ribbon (vision globale) ──────────────────────────────────────────── */
.ribbon-section {
  border-top: 1px solid var(--surface-3);
  padding-top: 28px;
  opacity: 0;
  animation: card-rise 700ms var(--ease-out) 320ms forwards;
}

.ribbon-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
}
.code {
  font-family: var(--font-mono);
  font-size: 9px;
  background: var(--surface-1);
  padding: 1px 5px;
  border-radius: 2px;
  border: 1px solid var(--surface-3);
}

.ribbon {
  display: flex;
  width: 100%;
  height: 12px;
  border-radius: 999px;
  overflow: hidden;
  background: var(--surface-2);
  border: 1px solid var(--surface-3);
}
.ribbon-seg {
  height: 100%;
  transform: scaleX(0);
  transform-origin: left center;
  animation: seg-grow 700ms var(--ease-out) var(--seg-delay, 0ms) forwards;
}
@keyframes seg-grow {
  to { transform: scaleX(1); }
}

.ribbon-empty {
  height: 12px;
  border-radius: 999px;
  background: var(--surface-1);
  border: 1px dashed var(--surface-3);
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ─── Legend ────────────────────────────────────────────────────────────── */
.legend {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px 24px;
  list-style: none;
  padding: 0;
  margin: 0;
}
.legend-item {
  display: grid;
  grid-template-columns: 8px 1fr auto auto;
  align-items: center;
  gap: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--surface-3);
}
.legend-swatch {
  width: 8px;
  height: 8px;
  border-radius: 999px;
}
.legend-label {
  font-family: var(--font-ui);
  font-size: 12px;
  color: var(--ink-700);
}
.legend-value {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 18px;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  line-height: 1;
}
.legend-pct {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-400);
  letter-spacing: var(--tracking-eyebrow);
  text-transform: uppercase;
  min-width: 44px;
  text-align: right;
}

/* ─── Reload button ─────────────────────────────────────────────────────── */
.reload-btn:hover:not(:disabled) {
  border-color: var(--ink-300);
  color: var(--ink-700);
}
.reload-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* ─── Responsive tweaks ─────────────────────────────────────────────────── */
@media (max-width: 720px) {
  .cards { --card-h: 240px; }
  .card-number { font-size: 60px; }
  .card-title { font-size: 24px; }
}
</style>
