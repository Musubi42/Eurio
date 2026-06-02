<script setup lang="ts">
/* Scène vault-sets-list — liste des sets (cartes + mini-planche). Port de
 * vault-sets-list.html/.js, recâblé sur api.getSets() (fixture démo). */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getSets } from '@/api'
import type { PreviewSlot, SetCategory, SetPreview } from '@/api'
import CoffreHeader from './CoffreHeader.vue'

const router = useRouter()
const sets = getSets()

const CATEGORY_LABEL: Record<SetCategory, string> = {
  country: 'Pays',
  theme: 'Thème',
  tier: 'Tier',
  personal: 'Perso',
  hunt: 'Chasse',
}

// ── Filtres ──
const catFilter = ref<'all' | SetCategory>('all')
const stateFilter = ref<'all' | 'progress' | 'done' | 'idle'>('all')

function setState(s: SetPreview): 'done' | 'idle' | 'progress' {
  if (s.completedAt != null) return 'done'
  return s.owned === 0 ? 'idle' : 'progress'
}

const visible = computed(() =>
  sets.filter((s) => {
    const catOk = catFilter.value === 'all' || s.category === catFilter.value
    const stOk = stateFilter.value === 'all' || setState(s) === stateFilter.value
    return catOk && stOk
  }),
)

// Ordonnancement : en cours (desc %) + non commencés, puis complétés (sous divider).
const inProgress = computed(() =>
  visible.value
    .filter((s) => s.completedAt == null && s.owned > 0)
    .sort((a, b) => b.owned / b.total - a.owned / a.total),
)
const idle = computed(() => visible.value.filter((s) => s.owned === 0))
const done = computed(() => visible.value.filter((s) => s.completedAt != null))
const mainList = computed(() => [...inProgress.value, ...idle.value])

// ── Stats ──
const stats = computed(() => {
  const total = sets.length
  const completed = sets.filter((s) => s.completedAt != null).length
  const owned = sets.reduce((n, s) => n + s.owned, 0)
  const all = sets.reduce((n, s) => n + s.total, 0)
  return { total, completed, coins: `${owned}/${all}` }
})

const CAT_CHIPS: { id: 'all' | SetCategory; label: string }[] = [
  { id: 'all', label: 'Tous' },
  { id: 'country', label: 'Pays' },
  { id: 'theme', label: 'Thème' },
  { id: 'tier', label: 'Tier' },
  { id: 'personal', label: 'Perso' },
  { id: 'hunt', label: 'Chasse' },
]
const STATE_CHIPS: { id: 'all' | 'progress' | 'done' | 'idle'; label: string }[] = [
  { id: 'all', label: 'Tous' },
  { id: 'progress', label: 'En cours' },
  { id: 'done', label: 'Complétés' },
  { id: 'idle', label: 'Non commencés' },
]

function pct(s: SetPreview): number {
  return Math.round((s.owned / s.total) * 100)
}
function open(s: SetPreview) {
  router.push(`/vault/sets/${encodeURIComponent(s.id)}`)
}
function cellClass(slot: PreviewSlot): string {
  if (slot.metal == null) return 'planche__cell planche__cell--missing'
  if (slot.metal === 'missing') return 'planche__cell planche__cell--missing'
  return 'planche__cell'
}
</script>

<template>
  <section class="scene-vsl-root" data-scene="vault-sets-list">
    <div class="scene-vsl-scroll">
      <CoffreHeader active="sets" />

      <div class="scene-vsl-stats">
        <span><strong>{{ stats.total }}</strong>sets</span>
        <span><strong>{{ stats.completed }}</strong>complétés</span>
        <span><strong>{{ stats.coins }}</strong>pièces</span>
      </div>

      <div class="scene-vsl-filters">
        <div class="scene-vsl-filters__row" role="radiogroup" aria-label="Filtrer par catégorie">
          <span class="scene-vsl-filters__label">Type</span>
          <button v-for="c in CAT_CHIPS" :key="c.id" type="button" class="scene-vsl-filters__chip" :aria-pressed="catFilter === c.id" @click="catFilter = c.id">{{ c.label }}</button>
        </div>
        <div class="scene-vsl-filters__row" role="radiogroup" aria-label="Filtrer par état">
          <span class="scene-vsl-filters__label">État</span>
          <button v-for="c in STATE_CHIPS" :key="c.id" type="button" class="scene-vsl-filters__chip" :aria-pressed="stateFilter === c.id" @click="stateFilter = c.id">{{ c.label }}</button>
        </div>
      </div>

      <div class="scene-vsl-list">
        <article v-for="s in mainList" :key="s.id" class="scene-vsl-card" :data-set-id="s.id" @click="open(s)">
          <div class="scene-vsl-card__head">
            <div class="scene-vsl-card__titles">
              <h3 class="scene-vsl-card__title">{{ s.title }}</h3>
              <p class="scene-vsl-card__sub">{{ s.description }}</p>
            </div>
          </div>
          <div class="scene-vsl-card__chips">
            <span class="scene-vsl-card__kind" :class="`scene-vsl-card__kind--${s.category}`">{{ CATEGORY_LABEL[s.category] }}</span>
            <span class="chip">{{ s.kind }}</span>
          </div>
          <div class="scene-vsl-card__preview">
            <div class="planche planche--compact">
              <div class="planche__grid">
                <div v-for="(slot, i) in s.preview" :key="i" :class="cellClass(slot)">
                  <div v-if="slot.metal === 'missing'" class="disc disc--missing disc--xs"><span class="disc__val">{{ slot.val }}</span></div>
                  <div v-else-if="slot.metal != null" class="disc disc--xs" :class="`disc--${slot.metal}`"><span class="disc__val">{{ slot.val }}</span></div>
                </div>
              </div>
            </div>
          </div>
          <div class="scene-vsl-card__progress">
            <div class="scene-vsl-card__progress__bar progress-bar"><div class="progress-track"><div class="progress-fill" :style="{ width: pct(s) + '%' }"></div></div></div>
            <div class="scene-vsl-card__progress__label">{{ s.owned }} / {{ s.total }}</div>
            <div class="scene-vsl-card__progress__pct tabular">{{ pct(s) }}%</div>
          </div>
        </article>

        <template v-if="done.length">
          <div class="scene-vsl-divider"><span class="scene-vsl-divider__label">Complétés</span><span class="scene-vsl-divider__line"></span></div>
          <article v-for="s in done" :key="s.id" class="scene-vsl-card scene-vsl-card--done" :data-set-id="s.id" @click="open(s)">
            <div class="scene-vsl-card__head">
              <div class="scene-vsl-card__titles">
                <h3 class="scene-vsl-card__title">{{ s.title }}</h3>
                <p class="scene-vsl-card__sub">{{ s.description }}</p>
              </div>
              <div class="scene-vsl-card__crown" aria-label="Complété"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M3 8l4.5 3L12 4l4.5 7L21 8l-1.5 10h-15z" /></svg></div>
            </div>
            <div class="scene-vsl-card__chips">
              <span class="scene-vsl-card__kind" :class="`scene-vsl-card__kind--${s.category}`">{{ CATEGORY_LABEL[s.category] }}</span>
              <span class="chip">{{ s.kind }}</span>
            </div>
            <div class="scene-vsl-card__preview">
              <div class="planche planche--compact">
                <div class="planche__grid">
                  <div v-for="(slot, i) in s.preview" :key="i" :class="cellClass(slot)">
                    <div v-if="slot.metal === 'missing'" class="disc disc--missing disc--xs"><span class="disc__val">{{ slot.val }}</span></div>
                    <div v-else-if="slot.metal != null" class="disc disc--xs" :class="`disc--${slot.metal}`"><span class="disc__val">{{ slot.val }}</span></div>
                  </div>
                </div>
              </div>
            </div>
            <div class="scene-vsl-card__progress">
              <div class="scene-vsl-card__progress__bar progress-bar"><div class="progress-track"><div class="progress-fill" :style="{ width: pct(s) + '%' }"></div></div></div>
              <div class="scene-vsl-card__progress__label">{{ s.owned }} / {{ s.total }}</div>
              <div class="scene-vsl-card__progress__pct tabular">{{ pct(s) }}%</div>
            </div>
          </article>
        </template>
      </div>

      <div style="height: var(--space-10)"></div>
    </div>
  </section>
</template>

<style src="../../styles/vault-sets-list.css"></style>
