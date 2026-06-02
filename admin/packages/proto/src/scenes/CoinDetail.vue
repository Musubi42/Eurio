<script setup lang="ts">
/* Scène coin-detail — fiche pièce paramétrée par ?ctx=scan|owned|reference.
 * Port de coin-detail.html + coin-detail.js, recâblé sur api + store. */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  coinSvg,
  getCoin,
  getCoin3DAssets,
  getDesignGroupMembers,
  getMarket,
  getRecit,
  simulateScan,
} from '@/api'
import { useCollectionStore } from '@/stores/collection'
import CoinImage from '@/components/CoinImage.vue'

const route = useRoute()
const router = useRouter()
const store = useCollectionStore()

const EUROZONE_21 = ['AT', 'BE', 'BG', 'CY', 'DE', 'EE', 'ES', 'FI', 'FR', 'GR', 'HR', 'IE', 'IT', 'LT', 'LU', 'LV', 'MT', 'NL', 'PT', 'SI', 'SK']

// ── Résolution pièce (fallback robuste) ──
const eurioId = computed(() => String(route.params.eurioId ?? ''))
const coin = computed(() => getCoin(eurioId.value) ?? getCoin(simulateScan(0)))

const ctx = computed<'scan' | 'owned' | 'reference'>(() => {
  const c = String(route.query.ctx ?? 'owned').toLowerCase()
  return c === 'scan' || c === 'reference' ? c : 'owned'
})

const market = computed(() => (coin.value ? getMarket(coin.value.eurioId) : null))
const recit = computed(() => (coin.value ? getRecit(coin.value.eurioId) : null))
const groupMembers = computed(() => (coin.value ? getDesignGroupMembers(coin.value.eurioId) : []))
const nationalVariants = computed(() => {
  const isos = [...new Set(groupMembers.value.map((m) => m.country.toUpperCase()))]
  return isos.length > 1 ? isos : []
})

const entry = computed(() => (coin.value ? store.entry(coin.value.eurioId) : null))
const owned = computed(() => (coin.value ? store.hasCoin(coin.value.eurioId) : false))

// ── Face avers / revers (revers = côté commun packagé, cf. getCoin3DAssets) ──
const assets = computed(() => (coin.value ? getCoin3DAssets(coin.value.eurioId) : null))
const reverseUrl = computed(() => (assets.value ? `${import.meta.env.BASE_URL}${assets.value.reverse}` : ''))
const hasReverse = computed(() => !!reverseUrl.value)
const face = ref<'avers' | 'revers'>('avers')
watch(eurioId, () => (face.value = 'avers')) // reset au changement de pièce

// ── UI state ──
const recitCollapsed = ref(false) // lentille Valeur = replié (Chunk E) — défaut déroulé
const confirmOpen = ref(false)
const toastText = ref('')
const toastOpen = ref(false)
let toastTimer: ReturnType<typeof setTimeout> | null = null
function toast(t: string) {
  toastText.value = t
  toastOpen.value = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toastOpen.value = false), 2200)
}

// ── Formatters ──
function euro(v: number | null): string {
  if (v == null) return '—'
  if (v < 10) return v.toFixed(2).replace('.', ',') + ' €'
  return v.toFixed(1).replace('.', ',') + ' €'
}
function pct(v: number): string {
  return `${v >= 0 ? '+' : ''}${v.toFixed(1).replace('.', ',')} %`
}
function fmtInt(n: number | null): string {
  return n == null ? '—' : n.toLocaleString('fr-FR')
}
function fmtDate(ts: number): string {
  return new Date(ts).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' })
}
function faceLabel(cents: number): string {
  if (cents >= 100) return cents % 100 === 0 ? `${cents / 100} €` : `${(cents / 100).toFixed(2).replace('.', ',')} €`
  return `${cents} c`
}

const topbarTitle = computed(() =>
  ctx.value === 'scan' ? 'Résultat du scan' : ctx.value === 'owned' ? 'Dans ton coffre' : 'Référence',
)

const ownershipDelta = computed(() => {
  if (!market.value) return { label: '—', cls: '' }
  const valueAtAdd = entry.value?.valueAtAddCents ?? null
  if (valueAtAdd != null) {
    const delta = market.value.p50 - valueAtAdd / 100
    return {
      label: (delta >= 0 ? '+' : '') + euro(Math.abs(delta)),
      cls: delta >= 0 ? 'stat-value--delta-up' : 'stat-value--delta-down',
    }
  }
  return { label: euro(market.value.p50), cls: '' }
})

// ── Sparkline ──
const sparkline = computed(() => {
  const pts = market.value?.history ?? []
  if (pts.length < 2) return null
  const w = 320, h = 90, pad = 4
  const min = Math.min(...pts), max = Math.max(...pts)
  const span = max - min || 1
  const step = (w - pad * 2) / (pts.length - 1)
  const coords = pts.map((v, i) => [pad + i * step, pad + (h - pad * 2) * (1 - (v - min) / span)] as const)
  const line = coords.map(([x, y], i) => (i === 0 ? `M${x},${y}` : `L${x},${y}`)).join(' ')
  const fill = `${line} L${coords[coords.length - 1][0]},${h - pad} L${coords[0][0]},${h - pad} Z`
  const [lx, ly] = coords[coords.length - 1]
  return { w, h, line, fill, lx, ly }
})

// ── Sets liés ──
const sets = computed(() => {
  const c = coin.value
  if (!c) return []
  const out: { name: string; done: number; total: number }[] = []
  if (!c.isCommemorative) {
    out.push({ name: `Série circulation ${c.countryName}`, done: 6, total: 8 })
  } else {
    out.push({ name: `Commémoratives ${c.countryName}`, done: 2, total: 15 })
    if (nationalVariants.value.length > 0) {
      out.push({ name: `Émission commune ${c.year}`, done: 1, total: nationalVariants.value.length })
    }
  }
  return out.map((s) => ({ ...s, pct: Math.round((s.done / s.total) * 100), missing: s.total - s.done }))
})

const metalLabel = computed(() => {
  const cents = coin.value?.faceValueCents ?? 0
  return cents >= 100 ? 'Bimétal' : cents >= 10 ? 'Or nordique' : 'Acier cuivré'
})

const showProjection = computed(() => !!market.value?.projection && (market.value?.history.length ?? 0) >= 6)

// ── Actions ──
function back() {
  if (ctx.value === 'scan') router.push('/scan')
  else if (ctx.value === 'owned') router.push('/vault')
  else if (window.history.length > 1) router.back()
  else router.push('/vault')
}
function addToVault(then: 'scan' | null) {
  if (!coin.value) return
  store.addCoin(coin.value.eurioId, {
    valueAtAddCents: Math.round((market.value?.p50 ?? coin.value.faceValue) * 100),
  })
  toast('Ajoutée au coffre')
  if (then === 'scan') setTimeout(() => router.push('/scan'), 700)
}
function confirmRemove() {
  if (!coin.value) return
  store.removeCoin(coin.value.eurioId)
  toast('Retirée du coffre')
  setTimeout(() => router.push('/vault'), 700)
}
</script>

<template>
  <section v-if="coin" class="coin-detail-root" data-scene="coin-detail">
    <!-- Top bar -->
    <div class="coin-detail-topbar">
      <button type="button" class="coin-detail-topbar__back" aria-label="Retour" @click="back">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6" /></svg>
      </button>
      <div class="coin-detail-topbar__title">{{ topbarTitle }}</div>
      <button type="button" class="coin-detail-topbar__more" aria-label="Plus d'options">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="12" cy="19" r="1.6" /></svg>
      </button>
    </div>

    <!-- Hero -->
    <div class="coin-detail-hero" :data-ctx="ctx">
      <div v-if="ctx === 'scan'" class="coin-detail-hero__gold-badge"><span>✦</span> Nouvelle pièce</div>

      <div class="coin-detail-hero__photos">
        <div v-if="ctx !== 'reference'" class="coin-detail-photo coin-detail-photo--user">
          <span class="coin-detail-photo__label">{{ ctx === 'scan' ? 'Ta capture' : 'Ta photo' }}</span>
          <div v-html="coinSvg(coin, { size: 200 })" />
        </div>
        <div class="coin-detail-photo coin-detail-photo--reference">
          <span class="coin-detail-photo__label">Référence</span>
          <CoinImage v-if="face === 'avers'" :coin="coin" :size="200" />
          <img v-else class="coin-svg coin-img" :src="reverseUrl" alt="Revers — côté commun" loading="lazy" decoding="async" />
        </div>
      </div>

      <div v-if="ctx === 'owned'" class="coin-detail-ownership">
        <div class="stat">
          <div class="stat-label">Ajoutée</div>
          <div class="stat-value">{{ entry ? fmtDate(entry.addedAt) : '—' }}</div>
        </div>
        <div class="stat">
          <div class="stat-label">Condition</div>
          <div class="stat-value">{{ entry?.condition || 'Non renseignée' }}</div>
        </div>
        <div class="stat">
          <div class="stat-label">Valeur actuelle</div>
          <div class="stat-value" :class="ownershipDelta.cls">{{ ownershipDelta.label }}</div>
        </div>
      </div>

      <div class="coin-detail-face-toggle" role="tablist">
        <button type="button" :aria-selected="face === 'avers'" @click="face = 'avers'">Avers</button>
        <button type="button" :aria-selected="face === 'revers'" :disabled="!hasReverse" :title="hasReverse ? '' : 'Revers indisponible'" @click="hasReverse && (face = 'revers')">Revers</button>
      </div>
    </div>

    <!-- Récit -->
    <div v-if="recit" class="coin-detail-recit" :data-collapsed="recitCollapsed ? 'true' : 'false'">
      <div class="coin-detail-recit__kicker">Le récit</div>
      <h2 class="coin-detail-recit__headline">{{ recit.headline }}</h2>
      <p class="coin-detail-recit__lead">{{ recit.lead }}</p>
      <div class="coin-detail-recit__chapters">
        <div v-for="ch in [recit.event, recit.context, recit.designers, recit.place]" :key="ch.eyebrow" class="coin-detail-recit__chapter">
          <span class="coin-detail-recit__chapter-eyebrow">{{ ch.eyebrow }}</span>
          <div class="coin-detail-recit__chapter-title">{{ ch.title }}</div>
          <p class="coin-detail-recit__chapter-body">{{ ch.body }}</p>
        </div>
      </div>
      <button type="button" class="coin-detail-recit__more" @click="recitCollapsed = false">Lire le récit <span aria-hidden="true">↓</span></button>
    </div>

    <!-- 01 Identité -->
    <section class="coin-detail-section">
      <div class="coin-detail-section__head"><span class="coin-detail-section__num">01</span><span class="coin-detail-section__title">Identité</span></div>
      <div>
        <div class="coin-detail-identity__value">{{ faceLabel(coin.faceValueCents) }}</div>
        <div class="coin-detail-identity__meta">
          <span>{{ coin.countryName }}</span><span>·</span><span class="u-mono tabular">{{ coin.year ?? '—' }}</span>
          <template v-if="coin.isCommemorative"><span>·</span><span>Commémorative</span></template>
        </div>
        <div v-if="coin.theme" class="coin-detail-identity__theme">{{ coin.theme }}</div>
        <div class="coin-detail-identity__rarity">
          <span :class="market?.rarity.gold ? 'badge badge--gold' : 'badge'">{{ market?.rarity.label ?? 'Commune' }}</span>
        </div>
      </div>
    </section>

    <!-- 02 Valorisation -->
    <section class="coin-detail-section">
      <div class="coin-detail-section__head"><span class="coin-detail-section__num">02</span><span class="coin-detail-section__title">Valorisation marché</span></div>
      <div v-if="market">
        <div class="coin-detail-valuation">
          <div class="coin-detail-pct"><div class="coin-detail-pct__label">P25</div><div class="coin-detail-pct__value">{{ euro(market.p25) }}</div></div>
          <div class="coin-detail-pct coin-detail-pct--median"><div class="coin-detail-pct__label">P50 · médiane</div><div class="coin-detail-pct__value">{{ euro(market.p50) }}</div></div>
          <div class="coin-detail-pct"><div class="coin-detail-pct__label">P75</div><div class="coin-detail-pct__value">{{ euro(market.p75) }}</div></div>
        </div>
        <div class="coin-detail-valuation__delta" :class="market.deltaVsFace >= 0 ? 'coin-detail-valuation__delta--up' : 'coin-detail-valuation__delta--down'">
          {{ pct(market.deltaVsFace) }} vs valeur faciale ({{ euro(coin.faceValue) }})
        </div>
      </div>
      <div v-else class="coin-detail-empty">Pas encore de données de marché<br /><span class="eyebrow">Pièce de circulation, valeur faciale</span></div>
    </section>

    <!-- 03 Historique -->
    <section class="coin-detail-section">
      <div class="coin-detail-section__head"><span class="coin-detail-section__num">03</span><span class="coin-detail-section__title">Historique de prix</span></div>
      <div v-if="market && sparkline && market.history.length >= 6">
        <svg class="coin-detail-spark" :viewBox="`0 0 ${sparkline.w} ${sparkline.h}`" preserveAspectRatio="none" aria-hidden="true">
          <path class="fill" :d="sparkline.fill" />
          <path class="line" :d="sparkline.line" />
          <circle class="point" :cx="sparkline.lx" :cy="sparkline.ly" r="4" />
        </svg>
        <div class="coin-detail-history__stats">
          <div class="stat"><div class="stat-label">3 mois</div><div class="stat-value u-mono tabular" :class="(market.delta3m ?? 0) >= 0 ? 'coin-detail-valuation__delta--up' : 'coin-detail-valuation__delta--down'">{{ market.delta3m != null ? pct(market.delta3m) : '—' }}</div></div>
          <div class="stat"><div class="stat-label">12 mois</div><div class="stat-value u-mono tabular">{{ market.history.length }} pts</div></div>
        </div>
        <button type="button" class="coin-detail-history__extend" @click="toast('Vue 5 ans · bientôt')">Étendre sur 5 ans</button>
      </div>
      <div v-else class="coin-detail-empty">Historique insuffisant pour tracer une tendance</div>
    </section>

    <!-- 04 Projection -->
    <section v-if="showProjection && market?.projection" class="coin-detail-section">
      <div class="coin-detail-section__head"><span class="coin-detail-section__num">04</span><span class="coin-detail-section__title">Projection 5 ans</span></div>
      <div class="coin-detail-projection">
        <div class="coin-detail-projection__label">Dans 5 ans</div>
        <div class="coin-detail-projection__range u-display-it">{{ euro(market.projection.low) }} – {{ euro(market.projection.high) }}</div>
        <div class="coin-detail-projection__disclaimer">Estimation indicative basée sur la tendance historique.</div>
      </div>
    </section>

    <!-- 05 Sets liés -->
    <section class="coin-detail-section">
      <div class="coin-detail-section__head"><span class="coin-detail-section__num">05</span><span class="coin-detail-section__title">Sets liés</span></div>
      <div>
        <div v-for="s in sets" :key="s.name" class="coin-detail-set">
          <div class="coin-detail-set__head">
            <div class="coin-detail-set__name">{{ s.name }}</div>
            <div class="coin-detail-set__count tabular">{{ s.done }}/{{ s.total }}</div>
          </div>
          <div class="progress-bar"><div class="progress-track"><div class="progress-fill" :style="{ width: s.pct + '%' }"></div></div></div>
          <a v-if="s.missing > 0" class="coin-detail-set__affiliate" @click="toast('Lien partenaire · bientôt')">Où trouver les {{ s.missing }} manquantes <span aria-hidden="true">→</span></a>
        </div>
      </div>
    </section>

    <!-- 06 Détails -->
    <section class="coin-detail-section">
      <div class="coin-detail-section__head"><span class="coin-detail-section__num">06</span><span class="coin-detail-section__title">Détails</span></div>
      <div>
        <dl class="coin-detail-dl">
          <dt>Tirage total</dt><dd>{{ fmtInt(coin.mintage) }}</dd>
          <dt>Métal</dt><dd>{{ metalLabel }}</dd>
          <dt>Sources</dt><dd>{{ coin.provenance.sourcesUsed.join(', ') || '—' }}</dd>
          <dt>Dernière MAJ</dt><dd>{{ coin.provenance.lastUpdated || '—' }}</dd>
        </dl>
        <p v-if="coin.designDescription" class="coin-detail-description">{{ coin.designDescription }}</p>
        <div v-if="nationalVariants.length > 0" class="coin-detail-common">
          <div class="coin-detail-common__title">Émission commune zone euro</div>
          <div class="eyebrow">{{ nationalVariants.length }} pays participants · frappe nationale</div>
          <div class="coin-detail-common__flags">
            <span v-for="cc in EUROZONE_21" :key="cc" class="coin-detail-common__flag" :style="{ opacity: nationalVariants.includes(cc) ? 1 : 0.35 }">{{ cc }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- CTA sticky -->
    <div class="coin-detail-cta">
      <button v-if="ctx === 'scan'" type="button" class="btn btn-gold" data-testid="add-to-vault" @click="addToVault('scan')">Ajouter au coffre</button>
      <template v-else-if="ctx === 'owned'">
        <div class="coin-detail-cta__confirm" :data-open="confirmOpen ? 'true' : 'false'">
          <span>Retirer cette pièce de ton coffre ?</span>
          <div class="coin-detail-cta__confirm-actions">
            <button type="button" class="btn btn-ghost" @click="confirmOpen = false">Annuler</button>
            <button type="button" class="btn btn-primary" data-testid="confirm-remove" @click="confirmRemove">Confirmer</button>
          </div>
        </div>
        <button type="button" class="btn btn-ghost" data-testid="ask-remove" @click="confirmOpen = true">Retirer du coffre</button>
      </template>
      <button v-else type="button" class="btn btn-gold" data-testid="add-to-vault-manual" :disabled="owned" @click="addToVault(null)">
        {{ owned ? 'Déjà au coffre' : 'Ajouter au coffre manuellement' }}
      </button>
    </div>

    <!-- Toast -->
    <div class="coin-detail-toast" :data-open="toastOpen ? 'true' : 'false'" role="status" aria-live="polite">{{ toastText }}</div>
  </section>
</template>

<style src="../styles/coin-detail.css"></style>
