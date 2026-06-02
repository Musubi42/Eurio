<script setup lang="ts">
/* Scène vault-sets-detail — planche d'un set. Port de vault-sets-detail.html/.js.
 * Fallback sur 'it-circulation' si setId inconnu (comme l'original). */
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getSet } from '@/api'
import type { CoinMetal, SetCoin } from '@/api'
import { useCollectionStore } from '@/stores/collection'

const route = useRoute()
const router = useRouter()
const store = useCollectionStore()

const detail = computed(() => getSet(String(route.params.setId)) ?? getSet('it-circulation')!)

function isOwned(c: SetCoin): boolean {
  return store.hasCoin(c.eurioId) || c.owned
}
const ownedCount = computed(() => detail.value.coins.filter(isOwned).length)
const total = computed(() => detail.value.coins.length)
const pct = computed(() => Math.round((ownedCount.value / total.value) * 100))
const isComplete = computed(() => ownedCount.value === total.value)
const missing = computed(() => total.value - ownedCount.value)

// Fan : 4 disques représentatifs (1 par métal si possible).
const fan = computed(() => {
  const coins = detail.value.coins
  const picks: SetCoin[] = []
  for (const m of ['copper', 'nordic', 'silver', 'bimetal'] as CoinMetal[]) {
    const c = coins.find((x) => x.metal === m)
    if (c) picks.push(c)
  }
  let i = 0
  while (picks.length < 4 && coins.length) picks.push(coins[i++ % coins.length])
  return picks.slice(0, 4)
})

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })
}
function formatDateShort(iso: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  return `${String(d.getDate()).padStart(2, '0')}·${String(d.getMonth() + 1).padStart(2, '0')}·${String(d.getFullYear()).slice(2)}`
}

// Long-press case manquante (mock)
const toastText = ref('')
const toastOpen = ref(false)
let toastTimer: ReturnType<typeof setTimeout> | null = null
let pressTimer: ReturnType<typeof setTimeout> | null = null
function toast(t: string) {
  toastText.value = t
  toastOpen.value = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toastOpen.value = false), 1800)
}
function pressStart(c: SetCoin) {
  if (isOwned(c)) return
  pressTimer = setTimeout(() => toast(`Marquer ${c.val} comme possédée ?`), 550)
}
function pressCancel() {
  if (pressTimer) clearTimeout(pressTimer)
}
function openCoin(c: SetCoin) {
  router.push(`/coin/${encodeURIComponent(c.eurioId)}`)
}
</script>

<template>
  <section class="scene-vsd-root" data-scene="vault-sets-detail" :data-completed="isComplete ? 'true' : 'false'">
    <div class="scene-vsd-topbar">
      <a class="scene-vsd-back" data-testid="sets-back" @click.prevent="router.push('/vault/sets')">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7" /></svg>
        <span>Retour</span>
      </a>
      <button type="button" class="scene-vsd-topbar__more" aria-label="Plus d'options">
        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="19" cy="12" r="1.5" /></svg>
      </button>
    </div>

    <header class="scene-vsd-hero">
      <div class="scene-vsd-banner" aria-hidden="true">Série complète</div>
      <div class="scene-vsd-fan" aria-hidden="true">
        <div v-for="(c, i) in fan" :key="i" class="scene-vsd-fan__disc" :class="[`disc--${c.metal}`, `scene-vsd-fan__disc--${i + 1}`]">
          <span class="scene-vsd-fan__val">{{ c.val }}</span>
        </div>
      </div>

      <div class="scene-vsd-hero__eyebrow"><span class="eyebrow eyebrow--gold">{{ detail.kindLabel }}</span></div>
      <h1 class="scene-vsd-hero__title" v-html="detail.title" />
      <p class="scene-vsd-hero__desc">{{ detail.description }}</p>
      <div class="scene-vsd-hero__chips">
        <span v-for="chip in detail.chips" :key="chip" class="chip">{{ chip }}</span>
      </div>
    </header>

    <div v-if="isComplete" class="scene-vsd-completed-note">Complété le <span>{{ formatDate(detail.completedAt) }}</span></div>

    <section class="scene-vsd-progress">
      <div class="scene-vsd-progress__numeric">
        <span class="scene-vsd-progress__label">Progression</span>
        <div class="scene-vsd-progress__pct"><span>{{ pct }}</span><small>%</small></div>
        <span class="scene-vsd-progress__ratio"><span>{{ ownedCount }} / {{ total }}</span> pièces collectées</span>
      </div>
      <div class="scene-vsd-progress__bar progress-bar"><div class="progress-track"><div class="progress-fill" :style="{ width: pct + '%' }"></div></div></div>
    </section>

    <section class="scene-vsd-section">
      <div class="scene-vsd-section-head">
        <h2>Planche</h2>
        <div class="scene-vsd-legend"><span>possédées</span><span class="missing">à scanner</span></div>
      </div>
      <div class="scene-vsd-planche planche">
        <div class="planche__grid">
          <div
            v-for="c in detail.coins"
            :key="c.eurioId"
            :class="isOwned(c) ? 'planche__cell' : 'planche__cell planche__cell--missing'"
            :data-owned="isOwned(c) ? 'true' : 'false'"
            @click="openCoin(c)"
            @pointerdown="pressStart(c)"
            @pointerup="pressCancel"
            @pointerleave="pressCancel"
            @pointercancel="pressCancel"
          >
            <div class="disc" :class="isOwned(c) ? `disc--${c.metal}` : 'disc--missing'"><span class="disc__val">{{ c.val }}</span></div>
            <span v-if="isOwned(c) && formatDateShort(c.scannedAt)" class="planche__cell__date">{{ formatDateShort(c.scannedAt) }}</span>
          </div>
        </div>
      </div>
      <a v-if="missing > 0" class="scene-vsd-affiliate" @click="toast('Lien partenaire · bientôt')">Où trouver les <span>{{ missing }}</span> manquantes <span aria-hidden="true">→</span></a>
    </section>

    <aside class="scene-vsd-reward">
      <div class="scene-vsd-reward__medal">
        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2l2.5 5 5.5.8-4 3.9.9 5.5L12 14.8 7.1 17.2 8 11.7 4 7.8 9.5 7z" /></svg>
      </div>
      <div class="scene-vsd-reward__body">
        <div class="scene-vsd-reward__label">Récompense</div>
        <div class="scene-vsd-reward__title">{{ detail.reward.title }}</div>
        <div class="scene-vsd-reward__hint">Débloqué à la dernière pièce scannée.</div>
      </div>
    </aside>

    <div style="height: var(--space-10)"></div>

    <div class="toast" :data-visible="toastOpen ? 'true' : 'false'" role="status">{{ toastText }}</div>
  </section>
</template>

<style src="../../styles/vault-sets-detail.css"></style>
