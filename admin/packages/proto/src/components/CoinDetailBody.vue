<script setup lang="ts">
/* CoinDetailBody — corps de la fiche pièce (récit → caractéristiques), extrait de
 * CoinDetail.vue pour être monté à deux endroits (R0, 1 source de vérité) :
 *   • route /coin/:id (coquille CoinDetail.vue) — ctx owned|reference|scan
 *   • scène ScanReveal (sheet expanded) — ctx scan
 * Paramétré par `coin` + `ctx`. Émet `toast` (l'hôte possède sa surface toast). */
import { computed, ref } from 'vue'
import {
  getDesignGroupMembers,
  getMarket,
  getRecit,
} from '@/api'
import type { Coin } from '@/api'
import { useCollectionStore } from '@/stores/collection'
import Spotlight3D from '@/components/Spotlight3D.vue'

const props = withDefaults(
  defineProps<{
    coin: Coin
    ctx: 'scan' | 'owned' | 'reference'
    /* Conservé pour compat (le scan le passe) — le corps ne rend plus de hero
       image : les deux hôtes (scan + coquille /coin/:id) fournissent un hero 3D. */
    showHero?: boolean
  }>(),
  { showHero: true },
)
const emit = defineEmits<{ toast: [msg: string] }>()

const store = useCollectionStore()

const EUROZONE_21 = ['AT', 'BE', 'BG', 'CY', 'DE', 'EE', 'ES', 'FI', 'FR', 'GR', 'HR', 'IE', 'IT', 'LT', 'LU', 'LV', 'MT', 'NL', 'PT', 'SI', 'SK']

const market = computed(() => getMarket(props.coin.eurioId))
const recit = computed(() => getRecit(props.coin.eurioId))
// Chapitres du récit, dédupliqués : on masque le titre d'un chapitre quand il
// répète mot pour mot le titre du récit (sinon « composant perdu » qui se répète).
const recitChapters = computed(() => {
  const r = recit.value
  if (!r) return []
  const h = r.headline.trim().toLowerCase()
  return [r.event, r.context, r.designers, r.place].map((ch) => ({
    ...ch,
    title: ch.title && ch.title.trim().toLowerCase() === h ? null : ch.title,
  }))
})
const groupMembers = computed(() => getDesignGroupMembers(props.coin.eurioId))
const nationalVariants = computed(() => {
  const isos = [...new Set(groupMembers.value.map((m) => m.country.toUpperCase()))]
  return isos.length > 1 ? isos : []
})

const entry = computed(() => store.entry(props.coin.eurioId))

// ── En-tête value-forward (identité + prix + grade) ──
const displayName = computed(() => props.coin.theme?.trim() || props.coin.designDescription?.trim() || '')
// Titre centré de l'en-tête : le nom de la pièce (commémo) ; sinon le pays
// (la dénomination + l'année vivent déjà dans l'eyebrow au-dessus).
const headTitle = computed(() => displayName.value || props.coin.countryName)
const priceRange = computed(() => {
  const m = market.value
  if (!m) return euro(props.coin.faceValue)
  // Fourchette plate (P25≈P75) → valeur unique plutôt que « X – X ».
  return Math.abs(m.p75 - m.p25) < 0.01 ? euro(m.p50) : `${euro(m.p25)} – ${euro(m.p75)}`
})
// Grade = condition saisie (pièce possédée) ; sinon non affiché.
const grade = computed(() => entry.value?.condition || null)
// Cote « plate » (P25≈P75) → on n'affiche pas 3 cartes identiques.
const flatMarket = computed(() => {
  const m = market.value
  return !!m && Math.abs(m.p75 - m.p25) < 0.01
})

// ── Design : lettering par face (données brutes, cf. loader select) ──
const obverseLettering = computed(() => props.coin.raw?.obverse_lettering ?? null)
const reverseLettering = computed(() => props.coin.raw?.reverse_lettering ?? null)
const edgeLettering = computed(() => props.coin.raw?.edge_lettering ?? null)
// designDescription est souvent juste le titre (donnée catalogue) → ne l'afficher
// comme description que si c'est une vraie phrase (≥ 40 car.).
const obverseDesc = computed(() => {
  const d = props.coin.designDescription?.trim()
  return d && d.length >= 40 ? d : null
})
const hasDesign = computed(
  () => !!(obverseDesc.value || obverseLettering.value || reverseLettering.value || edgeLettering.value),
)

// ── UI state ──
const recitCollapsed = ref(false) // lentille Valeur = replié (Chunk E) — défaut déroulé

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
  const c = props.coin
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
  const cents = props.coin.faceValueCents ?? 0
  return cents >= 100 ? 'Bimétal' : cents >= 10 ? 'Or nordique' : 'Acier cuivré'
})

const showProjection = computed(() => !!market.value?.projection && (market.value?.history.length ?? 0) >= 6)

// ── Caractéristiques physiques (E2 + E3 CoinSnap) ──
const physical = computed(() => {
  const c = props.coin
  return { diameter: c.diameterMm, weight: c.weightG, edge: c.edgeDescription, composition: c.composition }
})
const hasPhysical = computed(() => {
  const p = physical.value
  return !!(p.diameter || p.weight || p.edge || p.composition)
})
// Tranche : description d'edge si dispo, sinon le lettering de tranche.
const edgeLabel = computed(() => props.coin.edgeDescription?.trim() || (edgeLettering.value ? `Inscrite · ${edgeLettering.value}` : null))

// ── Courbe de rareté (uniquement pour les pièces rares) ──────────────────────
// Distribution stylisée tirage→rareté (PAS la cote) : plus le tirage est faible,
// plus le marqueur glisse vers la queue rare (à droite). Affichée seulement quand
// la pièce est cotée rare — sinon le badge suffit (condensation CoinSnap).
const rarityCurve = computed(() => {
  const m = market.value
  if (!m?.rarity?.gold) return null
  const mint = props.coin.mintage ?? 1_500_000
  // log10 : 10k → queue rare (~0.9) ; 100M → tête commune (~0.1)
  const frac = Math.min(0.92, Math.max(0.12, 1 - (Math.log10(Math.max(mint, 1)) - 4) / 4))
  const W = 120, H = 40, base = H - 3, n = 48
  const peak = 0.4, sigma = 0.17
  const g = (u: number) => Math.exp(-((u - peak) ** 2) / (2 * sigma * sigma))
  const pt = (i: number): [number, number] => {
    const u = i / n
    return [u * W, base - g(u) * (base - 4)]
  }
  const curve = Array.from({ length: n + 1 }, (_, i) => pt(i))
    .map(([x, y], i) => (i === 0 ? `M${x.toFixed(1)},${y.toFixed(1)}` : `L${x.toFixed(1)},${y.toFixed(1)}`))
    .join(' ')
  // Aire de queue : du marqueur jusqu'à la droite, refermée sur la base.
  const start = Math.round(frac * n)
  const tailPts = Array.from({ length: n - start + 1 }, (_, k) => pt(start + k))
  const mx = frac * W
  const tail = `M${mx.toFixed(1)},${base} ` + tailPts.map(([x, y]) => `L${x.toFixed(1)},${y.toFixed(1)}`).join(' ') + ` L${W},${base} Z`
  const my = base - g(frac) * (base - 4)
  return { W, H, base, curve, tail, mx, my, label: m.rarity.label }
})
</script>

<template>
  <div class="coin-detail-body">
    <!-- En-tête value-forward : identité + prix + grade + rareté (+ ownership) -->
    <header class="cd-head">
      <div v-if="ctx === 'scan'" class="cd-head__new"><span>✦</span> Nouvelle pièce</div>
      <div class="cd-head__eyebrow">
        <span class="u-mono tabular">{{ faceLabel(coin.faceValueCents) }}</span> · {{ coin.countryName }} ·
        <span class="u-mono tabular">{{ coin.year ?? '—' }}</span>
        <template v-if="coin.isCommemorative"> · Commémorative</template>
      </div>
      <h1 class="cd-head__title">{{ headTitle }}</h1>
      <div class="cd-head__valgrade">
        <span class="cd-head__price tabular">{{ priceRange }}</span>
        <span v-if="grade" class="cd-head__grade">{{ grade }}</span>
        <span :class="market?.rarity.gold ? 'badge badge--gold' : 'badge'">{{ market?.rarity.label ?? 'Commune' }}</span>
      </div>

      <!-- Courbe de rareté (tirage → percentile), pièces rares uniquement -->
      <div v-if="rarityCurve" class="cd-rarity">
        <svg class="cd-rarity__chart" :viewBox="`0 0 ${rarityCurve.W} ${rarityCurve.H}`" preserveAspectRatio="none" aria-hidden="true">
          <line class="cd-rarity__axis" :x1="0" :y1="rarityCurve.base" :x2="rarityCurve.W" :y2="rarityCurve.base" />
          <path class="cd-rarity__tail" :d="rarityCurve.tail" />
          <path class="cd-rarity__curve" :d="rarityCurve.curve" />
          <line class="cd-rarity__marker" :x1="rarityCurve.mx" :y1="rarityCurve.base" :x2="rarityCurve.mx" :y2="rarityCurve.my" />
          <circle class="cd-rarity__dot" :cx="rarityCurve.mx" :cy="rarityCurve.my" r="2.6" />
        </svg>
        <div class="cd-rarity__meta">
          <span class="cd-rarity__label">{{ rarityCurve.label }}</span>
          <span class="cd-rarity__hint">peu de pièces frappées</span>
        </div>
      </div>

      <div v-if="coin.mintage != null" class="cd-head__tirage"><span>Tirage</span> {{ fmtInt(coin.mintage) }}</div>

      <div v-if="ctx === 'owned' && entry" class="cd-head__owned">
        <div class="stat"><div class="stat-label">Ajoutée</div><div class="stat-value">{{ fmtDate(entry.addedAt) }}</div></div>
        <div class="stat"><div class="stat-label">État</div><div class="stat-value">{{ entry.condition || '—' }}</div></div>
        <div class="stat"><div class="stat-label">Valeur</div><div class="stat-value" :class="ownershipDelta.cls">{{ ownershipDelta.label }}</div></div>
      </div>
    </header>

    <!-- Récit -->
    <div v-if="recit" class="coin-detail-recit" :data-collapsed="recitCollapsed ? 'true' : 'false'">
      <div class="coin-detail-recit__kicker">Le récit</div>
      <h2 class="coin-detail-recit__headline">{{ recit.headline }}</h2>
      <p class="coin-detail-recit__lead">{{ recit.lead }}</p>
      <div class="coin-detail-recit__chapters">
        <div v-for="ch in recitChapters" :key="ch.eyebrow" class="coin-detail-recit__chapter">
          <span class="coin-detail-recit__chapter-eyebrow">{{ ch.eyebrow }}</span>
          <div v-if="ch.title" class="coin-detail-recit__chapter-title">{{ ch.title }}</div>
          <p class="coin-detail-recit__chapter-body">{{ ch.body }}</p>
        </div>
      </div>
      <button type="button" class="coin-detail-recit__more" @click="recitCollapsed = false">Lire le récit <span aria-hidden="true">↓</span></button>
    </div>

    <!-- 01 Valorisation -->
    <section class="coin-detail-section">
      <div class="coin-detail-section__head"><span class="coin-detail-section__title">Valorisation marché</span></div>
      <div v-if="market">
        <!-- Fourchette plate (cote = un seul point) → une seule valeur, pas 3 cartes identiques -->
        <div v-if="flatMarket" class="coin-detail-valuation coin-detail-valuation--flat">
          <div class="coin-detail-pct coin-detail-pct--median"><div class="coin-detail-pct__label">Cote estimée</div><div class="coin-detail-pct__value">{{ euro(market.p50) }}</div></div>
        </div>
        <div v-else class="coin-detail-valuation">
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
      <div class="coin-detail-section__head"><span class="coin-detail-section__title">Historique de prix</span></div>
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
        <button type="button" class="coin-detail-history__extend" @click="emit('toast', 'Vue 5 ans · bientôt')">Étendre sur 5 ans</button>
      </div>
      <div v-else class="coin-detail-empty">Historique insuffisant pour tracer une tendance</div>
    </section>

    <!-- 04 Projection -->
    <section v-if="showProjection && market?.projection" class="coin-detail-section">
      <div class="coin-detail-section__head"><span class="coin-detail-section__title">Projection 5 ans</span></div>
      <div class="coin-detail-projection">
        <div class="coin-detail-projection__label">Dans 5 ans</div>
        <div class="coin-detail-projection__range u-display-it">{{ euro(market.projection.low) }} – {{ euro(market.projection.high) }}</div>
        <div class="coin-detail-projection__disclaimer">Estimation indicative basée sur la tendance historique.</div>
      </div>
    </section>

    <!-- 05 Sets liés -->
    <section class="coin-detail-section">
      <div class="coin-detail-section__head"><span class="coin-detail-section__title">Sets liés</span></div>
      <div>
        <div v-for="s in sets" :key="s.name" class="coin-detail-set">
          <div class="coin-detail-set__head">
            <div class="coin-detail-set__name">{{ s.name }}</div>
            <div class="coin-detail-set__count tabular">{{ s.done }}/{{ s.total }}</div>
          </div>
          <div class="progress-bar"><div class="progress-track"><div class="progress-fill" :style="{ width: s.pct + '%' }"></div></div></div>
          <a v-if="s.missing > 0" class="coin-detail-set__affiliate" @click="emit('toast', 'Lien partenaire · bientôt')">Où trouver les {{ s.missing }} manquantes <span aria-hidden="true">→</span></a>
        </div>
      </div>
    </section>

    <!-- 05 Design : avers / revers + lettering -->
    <section v-if="hasDesign" class="coin-detail-section">
      <div class="coin-detail-section__head"><span class="coin-detail-section__title">Design</span></div>
      <div class="cd-design">
        <div class="cd-design__face">
          <span class="cd-design__label">Avers</span>
          <p v-if="obverseDesc" class="cd-design__desc">{{ obverseDesc }}</p>
          <div v-if="obverseLettering" class="cd-design__lettering"><span>Lettering</span> {{ obverseLettering }}</div>
        </div>
        <div class="cd-design__face">
          <span class="cd-design__label">Revers</span>
          <p class="cd-design__desc cd-design__desc--muted">Côté commun européen.</p>
          <div v-if="reverseLettering" class="cd-design__lettering"><span>Lettering</span> {{ reverseLettering }}</div>
        </div>
        <div v-if="edgeLettering" class="cd-design__edge"><span>Tranche</span> {{ edgeLettering }}</div>
      </div>
    </section>

    <!-- 06 Caractéristiques — diagramme coté (pièce figée + flèche Ø) + métriques color-codées -->
    <section class="coin-detail-section">
      <div class="coin-detail-section__head"><span class="coin-detail-section__title">Caractéristiques</span></div>
      <div>
        <div v-if="hasPhysical" class="cd-phys">
          <!-- Diagramme : la vraie pièce en 3/4 FIGÉE (révèle épaisseur + bimétal),
               cotée en travers par une flèche de diamètre (façon planche technique). -->
          <div class="cd-phys__viz">
            <Spotlight3D :eurio-id="coin.eurioId" :fill="0.62" :tilt-x="-0.42" :spin-amp="0" :spin-speed="0" />
            <svg v-if="physical?.diameter" class="cd-phys__caliper" viewBox="0 0 220 220" preserveAspectRatio="none" aria-hidden="true">
              <line x1="42" y1="110" x2="178" y2="110" />
              <polygon points="42,110 51,105 51,115" />
              <polygon points="178,110 169,105 169,115" />
            </svg>
            <div v-if="physical?.diameter" class="cd-phys__dlabel tabular">Ø {{ physical.diameter }} mm</div>
          </div>

          <div class="cd-phys__metrics">
            <div class="cd-phys__group cd-phys__group--cool">
              <div v-if="edgeLabel" class="cd-phys__row"><span>Tranche</span><b>{{ edgeLabel }}</b></div>
              <div class="cd-phys__row"><span>Métal</span><b>{{ metalLabel }}</b></div>
            </div>
            <div class="cd-phys__group cd-phys__group--warm">
              <div v-if="physical?.diameter" class="cd-phys__row"><span>Diamètre</span><b class="tabular">{{ physical.diameter }} mm</b></div>
              <div v-if="physical?.weight" class="cd-phys__row"><span>Poids</span><b class="tabular">{{ physical.weight }} g</b></div>
            </div>
          </div>
        </div>

        <dl class="coin-detail-dl">
          <dt>Tirage total</dt><dd>{{ fmtInt(coin.mintage) }}</dd>
          <dt>Sources</dt><dd>{{ coin.provenance.sourcesUsed.join(', ') || '—' }}</dd>
          <dt>Dernière MAJ</dt><dd>{{ coin.provenance.lastUpdated || '—' }}</dd>
        </dl>
        <div v-if="nationalVariants.length > 0" class="coin-detail-common">
          <div class="coin-detail-common__title">Émission commune zone euro</div>
          <div class="eyebrow">{{ nationalVariants.length }} pays participants · frappe nationale</div>
          <div class="coin-detail-common__flags">
            <span v-for="cc in EUROZONE_21" :key="cc" class="coin-detail-common__flag" :style="{ opacity: nationalVariants.includes(cc) ? 1 : 0.35 }">{{ cc }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- Communauté — « Reste connecté » (CoinSnap → Facebook ; nous → Discord) -->
    <section class="coin-detail-section cd-community-sec">
      <div class="cd-community">
        <div class="cd-community__icon" aria-hidden="true">
          <svg viewBox="0 0 24 18" width="26" height="20" fill="currentColor"><path d="M20.3 1.6A19.8 19.8 0 0 0 15.4.1l-.3.5c1.8.4 2.7 1 3.6 1.6a13.6 13.6 0 0 0-11.4 0c.9-.6 1.9-1.2 3.6-1.6L10.6.1A19.8 19.8 0 0 0 5.7 1.6C2.6 6.2 1.8 10.7 2.2 15.1a19.9 19.9 0 0 0 6 3l.5-1.3c-1-.4-1.8-.8-2.6-1.4l.6-.4a14.2 14.2 0 0 0 12.6 0l.6.4c-.8.6-1.7 1-2.6 1.4l.5 1.3a19.9 19.9 0 0 0 6-3c.5-5.1-.8-9.6-3.6-13.5ZM8.9 12.4c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Zm6.2 0c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Z"/></svg>
        </div>
        <div class="cd-community__title">Reste connecté</div>
        <div class="cd-community__sub">Partage tes trouvailles et échange avec les autres collectionneurs Eurio.</div>
        <button type="button" class="cd-community__btn" @click="emit('toast', 'Discord · bientôt')">
          Rejoindre le Discord <span aria-hidden="true">→</span>
        </button>
      </div>
    </section>
  </div>
</template>

<style src="../styles/coin-detail.css"></style>
