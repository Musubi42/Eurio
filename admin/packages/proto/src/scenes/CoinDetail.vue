<script setup lang="ts">
/* Scène coin-detail — coquille de la fiche pièce paramétrée par ?ctx=scan|owned|reference.
 * Le corps (récit → caractéristiques) vit dans CoinDetailBody.vue, partagé avec
 * la scène ScanReveal (R0, 1 source de vérité). Cette coquille = topbar + body + CTA. */
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getCoin, getMarket, simulateScan } from '@/api'
import { useCollectionStore } from '@/stores/collection'
import CoinDetailBody from '@/components/CoinDetailBody.vue'
import Spotlight3D from '@/components/Spotlight3D.vue'

const route = useRoute()
const router = useRouter()
const store = useCollectionStore()

// ── Résolution pièce (fallback robuste) ──
const eurioId = computed(() => String(route.params.eurioId ?? ''))
const coin = computed(() => getCoin(eurioId.value) ?? getCoin(simulateScan(0)))

const ctx = computed<'scan' | 'owned' | 'reference'>(() => {
  const c = String(route.query.ctx ?? 'owned').toLowerCase()
  return c === 'scan' || c === 'reference' ? c : 'owned'
})

const market = computed(() => (coin.value ? getMarket(coin.value.eurioId) : null))
const owned = computed(() => (coin.value ? store.hasCoin(coin.value.eurioId) : false))

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

const topbarTitle = computed(() =>
  ctx.value === 'scan' ? 'Résultat du scan' : ctx.value === 'owned' ? 'Dans ton coffre' : 'Référence',
)

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

    <!-- Hero 3D (cohérent avec le scan + les best-coins) -->
    <div class="coin-detail-hero3d"><Spotlight3D :eurio-id="coin.eurioId" interactive /></div>

    <!-- Corps de fiche partagé (en-tête value-forward → caractéristiques) -->
    <CoinDetailBody :coin="coin" :ctx="ctx" :show-hero="false" @toast="toast" />

    <!-- CTA sticky -->
    <div class="coin-detail-cta">
      <button v-if="ctx === 'scan'" type="button" class="btn btn-gold" data-testid="add-to-vault" @click="addToVault('scan')">Ajouter au coffre</button>
      <template v-else-if="ctx === 'owned'">
        <div class="coin-detail-cta__confirm" :data-open="confirmOpen ? 'true' : 'false'">
          <span>Retirer cette pièce de ton coffre ?</span>
          <div class="coin-detail-cta__confirm-actions">
            <button type="button" class="btn btn-ghost btn-ghost--on-dark" @click="confirmOpen = false">Annuler</button>
            <button type="button" class="btn btn-primary" data-testid="confirm-remove" @click="confirmRemove">Confirmer</button>
          </div>
        </div>
        <button type="button" class="btn btn-ghost btn-ghost--on-dark" data-testid="ask-remove" @click="confirmOpen = true">Retirer du coffre</button>
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
