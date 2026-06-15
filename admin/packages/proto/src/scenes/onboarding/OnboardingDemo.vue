<script setup lang="ts">
import { useRouter } from 'vue-router'
import { simulateScan } from '@/api'
import { useCollectionStore } from '@/stores/collection'
const router = useRouter(); const store = useCollectionStore()
const sampleId = simulateScan(0)
function onClick(e: MouseEvent) {
  const a = (e.target as HTMLElement).closest('[data-action]')?.getAttribute('data-action')
  if (a === 'skip') { store.completeOnboarding(); router.push('/scan'); return }
  store.completeOnboarding(); router.push('/scan?id=' + encodeURIComponent(sampleId))
}
</script>

<template>
<section @click="onClick" class="onb-demo-root" data-scene="onboarding-demo" data-action="scan">
  <svg class="onb-demo-noise" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
    <filter id="onb-demo-turb"><feTurbulence type="fractalNoise" baseFrequency="1.6" numOctaves="2" seed="7"/><feColorMatrix type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.55 0"/></filter>
    <rect width="100%" height="100%" filter="url(#onb-demo-turb)"/>
  </svg>

  <button type="button" class="onb-demo-skip" data-action="skip">Passer</button>

  <div class="onb-demo-header">
    <span class="eyebrow">Démo · sans pièce</span>
    <div class="onb-demo-header__title">Fais ton premier scan</div>
  </div>

  <div class="onb-demo-guide" aria-hidden="true">
    <div class="onb-demo-corner onb-demo-corner--tl"></div>
    <div class="onb-demo-corner onb-demo-corner--tr"></div>
    <div class="onb-demo-corner onb-demo-corner--bl"></div>
    <div class="onb-demo-corner onb-demo-corner--br"></div>
  </div>

  <div class="onb-demo-coinwrap" aria-hidden="true">
    <span class="onb-demo-loaner-tag">Pièce prêtée</span>
    <div class="onb-demo-coin"><span class="onb-demo-coin__glyph" data-slot="glyph">2€</span></div>
  </div>

  <div class="onb-demo-tap" aria-hidden="true">
    <span class="onb-demo-tap__ring"></span>
  </div>

  <div class="onb-demo-hint">
    <span>On t'en prête une — <span class="onb-demo-tapword">tape</span> pour la scanner</span>
  </div>

  <div class="onb-demo-endow">
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>
    Elle comptera dans ta collection
  </div>
</section>
</template>

<style src="../../styles/onboarding-demo.css"></style>
