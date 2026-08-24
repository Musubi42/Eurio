<script setup lang="ts">
/**
 * Dashboard KPIs — en-tête identité + grille de cartes remplies par /stats/overview
 * (sections filtrées par scope côté serveur). Rapatrié d'admin-vps (R1). Léger
 * (eurio-api only) → marche en local ET en hébergé.
 * Fetch au mount + refresh manuel + auto-refresh 60s.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'

import { useEurioSession } from '@/stores/eurio-session'
import DinoBankCard from '../components/DinoBankCard.vue'
import { statsApi, type StatsOverview } from '../api/stats'

const session = useEurioSession()

const stats = ref<StatsOverview>({})
const loading = ref(true)
const error = ref<string | null>(null)
const lastUpdated = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    stats.value = await statsApi.overview()
    lastUpdated.value = new Date().toLocaleTimeString('fr-FR')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

interface Kpi {
  key: string
  label: string
  value: number | string
  sub: string
}

const cards = computed<Kpi[]>(() => {
  const s = stats.value
  const out: Kpi[] = []
  if (s.coins)
    out.push({
      key: 'coins',
      label: 'Coins',
      value: s.coins.total,
      sub: `${s.coins.needs_review} à revoir`,
    })
  if (s.sets)
    out.push({
      key: 'sets',
      label: 'Sets',
      value: s.sets.total,
      sub: `${s.sets.active} actifs`,
    })
  if (s.sources)
    out.push({
      key: 'sources',
      label: 'Sources',
      value: s.sources.total,
      sub: `${s.sources.runs_24h} runs / 24h`,
    })
  if (s.review)
    out.push({
      key: 'review',
      label: 'Review queue',
      value: s.review.total,
      sub: `${s.review.by_status.pending ?? 0} pending · ${s.review.by_status.claimed ?? 0} claimed`,
    })
  if (s.users)
    out.push({
      key: 'users',
      label: 'Users',
      value: s.users.total,
      sub: `${s.users.active} actifs`,
    })
  if (s.tokens)
    out.push({
      key: 'tokens',
      label: 'Mes tokens',
      value: s.tokens.mine_active,
      sub: `${s.tokens.mine_total} au total`,
    })
  return out
})

let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  load()
  timer = setInterval(load, 60_000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <section class="home">
    <header class="head">
      <div>
        <h2>Bienvenue {{ session.principal?.name || session.principal?.email }}</h2>
        <p class="lead">
          <span v-for="role in session.principal?.roles" :key="role" class="role">{{ role }}</span>
        </p>
      </div>
      <div class="refresh">
        <span v-if="lastUpdated" class="updated">maj {{ lastUpdated }}</span>
        <button :disabled="loading" @click="load">
          {{ loading ? '…' : 'Rafraîchir' }}
        </button>
      </div>
    </header>

    <p v-if="error" class="error">{{ error }}</p>

    <div class="kpis">
      <article v-for="c in cards" :key="c.key" class="kpi">
        <span class="kpi-label">{{ c.label }}</span>
        <span class="kpi-value">{{ c.value }}</span>
        <span class="kpi-sub">{{ c.sub }}</span>
      </article>
      <p v-if="!loading && cards.length === 0" class="empty">
        Aucune métrique disponible pour tes scopes.
      </p>
    </div>

    <!-- L'état de la machinerie, sous les KPI produit. Sa lecture est légère
         (SQL sur le canonique) : la carte s'affiche Mac éteint, seul son bouton
         se grise. Cf. DinoBankCard. -->
    <div class="machinerie">
      <DinoBankCard />
    </div>
  </section>
</template>

<style scoped>
.home {
  padding: var(--space-5) var(--space-6);
  max-width: 1080px;
}
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}
h2 {
  margin: 0 0 var(--space-2);
  font-size: var(--text-xl);
}
.lead {
  margin: 0;
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.role {
  font-size: var(--text-xs);
  background: var(--surface-2);
  color: var(--text-secondary);
  padding: 2px 8px;
  border-radius: 999px;
  text-transform: capitalize;
}
.refresh {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.updated {
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.error {
  background: color-mix(in srgb, var(--danger) 10%, white);
  border: 1px solid var(--danger);
  color: var(--danger);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
}
.kpis {
  margin-top: var(--space-5);
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: var(--space-4);
}
.kpi {
  background: white;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-4) var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.kpi-label {
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-secondary);
}
.kpi-value {
  font-size: 32px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--brand);
}
.kpi-sub {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.empty {
  grid-column: 1 / -1;
  color: var(--text-secondary);
}

/* La carte machinerie n'entre pas dans la grille des KPI : elle porte un geste,
   pas un chiffre, et sa hauteur varie avec ce qu'elle a à dire. */
.machinerie {
  margin-top: 1.25rem;
}
</style>
