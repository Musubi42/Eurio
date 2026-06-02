<script setup lang="ts">
/* Scène marketplace-soon — teaser bottom-sheet. Port de marketplace-soon.html/.js. */
import { onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const toastText = ref('—')
const toastOn = ref(false)
let toastTimer: ReturnType<typeof setTimeout> | null = null
function toast(text: string) {
  toastText.value = text
  toastOn.value = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toastOn.value = false), 1800)
}
onBeforeUnmount(() => {
  if (toastTimer) clearTimeout(toastTimer)
})

function close() {
  if (window.history.length > 1) router.back()
  else router.push('/scan')
}
</script>

<template>
  <section class="marketplace-root" data-scene="marketplace-soon">
    <div class="marketplace-backdrop" aria-hidden="true" @click="close"></div>

    <div class="marketplace-hint">Marketplace · aperçu</div>

    <button type="button" class="btn-icon marketplace-close" data-testid="marketplace-close" aria-label="Fermer" @click="close">×</button>

    <aside class="marketplace-sheet" role="dialog" aria-label="Marketplace — bientôt">
      <div class="sheet-handle" aria-hidden="true"></div>

      <span class="marketplace-badge">Bientôt · 2026</span>

      <h1 class="marketplace-title">La marketplace <em style="font-weight:300;">Eurio</em></h1>

      <p class="marketplace-copy">
        Achète et vends des pièces euro au sein d'une communauté qui partage
        le même référentiel. Prix suggérés automatiquement, identification
        garantie, commission 6 % seulement.
      </p>

      <div class="marketplace-features">
        <div class="marketplace-feature">
          <div class="marketplace-feature__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6">
              <path d="M3 6h2l2.5 11a2 2 0 002 1.5h7a2 2 0 002-1.5L21 9H7" />
              <circle cx="10" cy="21" r="1.2" />
              <circle cx="17" cy="21" r="1.2" />
            </svg>
          </div>
          <div class="marketplace-feature__label">Vends en 30 secondes</div>
        </div>
        <div class="marketplace-feature">
          <div class="marketplace-feature__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M20 6L9 17l-5-5" />
            </svg>
          </div>
          <div class="marketplace-feature__label">Identification garantie</div>
        </div>
        <div class="marketplace-feature">
          <div class="marketplace-feature__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6">
              <circle cx="9" cy="9" r="3.2" />
              <circle cx="16.5" cy="10.5" r="2.4" />
              <path d="M3 19c0-3 3-5 6-5s6 2 6 5M14 19c0-2 2-3.5 4-3.5s3 1.2 3 3" />
            </svg>
          </div>
          <div class="marketplace-feature__label">Communauté de collectionneurs</div>
        </div>
      </div>

      <button type="button" class="btn marketplace-cta" data-testid="marketplace-notify" @click="toast('Merci — on te notifiera au lancement')">
        Me prévenir au lancement
      </button>
      <div class="marketplace-fineprint">
        Lancement <b>T3 2026</b> · Zéro spam
      </div>
    </aside>

    <div class="marketplace-toast" :class="{ 'is-on': toastOn }">{{ toastText }}</div>
  </section>
</template>

<style src="../styles/marketplace-soon.css"></style>
