<script setup lang="ts">
/* Scène profile-history — historique des scans (E8 CoinSnap). Liste toutes les
 * identifications passées (store.scanHistory), qu'elles soient au coffre ou non.
 * Distinct du coffre : scanner ≠ posséder. */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { getCoin } from '@/api'
import { useCollectionStore } from '@/stores/collection'
import CoinImage from '@/components/CoinImage.vue'

const router = useRouter()
const store = useCollectionStore()

interface Row {
  key: string
  eurioId: string
  scannedAt: number
  name: string
  sub: string
  owned: boolean
}
const rows = computed<Row[]>(() =>
  store.scanHistory
    .map((h, i) => {
      const coin = getCoin(h.eurioId)
      if (!coin) return null
      return {
        key: `${h.eurioId}-${h.scannedAt}-${i}`,
        eurioId: h.eurioId,
        scannedAt: h.scannedAt,
        name: coin.theme || coin.countryName,
        sub: `${coin.countryName} · ${coin.year ?? '—'}`,
        owned: store.hasCoin(h.eurioId),
      }
    })
    .filter((r): r is Row => r !== null),
)

function fmtWhen(ts: number): string {
  const d = new Date(ts)
  return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' }) +
    ' · ' +
    d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}
function open(eurioId: string, owned: boolean) {
  router.push(`/coin/${encodeURIComponent(eurioId)}?ctx=${owned ? 'owned' : 'reference'}`)
}
function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/profile')
}
</script>

<template>
  <section class="profile-history-root" data-scene="profile-history">
    <div class="profile-history-head">
      <button type="button" class="profile-history-head__back" data-testid="history-back" aria-label="Retour" @click="goBack">
        <svg viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6" /></svg>
      </button>
      <h1 class="profile-history-head__title">Historique des scans</h1>
    </div>

    <p class="profile-history-intro">Toutes tes identifications, qu'elles soient au coffre ou non.</p>

    <div v-if="rows.length" class="profile-history-list">
      <button v-for="r in rows" :key="r.key" type="button" class="profile-history-row" @click="open(r.eurioId, r.owned)">
        <div class="profile-history-row__coin"><CoinImage :coin="getCoin(r.eurioId)!" :size="44" :show-label="false" /></div>
        <div class="profile-history-row__meta">
          <span class="profile-history-row__name">{{ r.name }}</span>
          <span class="profile-history-row__sub">{{ r.sub }}</span>
        </div>
        <div class="profile-history-row__right">
          <span class="profile-history-row__badge" :class="r.owned ? 'is-owned' : 'is-scanned'">{{ r.owned ? 'Au coffre' : 'Scannée' }}</span>
          <span class="profile-history-row__when tabular">{{ fmtWhen(r.scannedAt) }}</span>
        </div>
      </button>
    </div>

    <div v-else class="profile-history-empty">
      <div class="profile-history-empty__icon" aria-hidden="true">
        <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M12 8v4l3 2" stroke-linecap="round" /></svg>
      </div>
      <p>Aucun scan pour l'instant.<br />Tes identifications apparaîtront ici.</p>
      <button type="button" class="btn btn-primary" @click="router.push('/scan')">Scanner une pièce</button>
    </div>
  </section>
</template>

<style src="../../styles/profile-history.css"></style>
