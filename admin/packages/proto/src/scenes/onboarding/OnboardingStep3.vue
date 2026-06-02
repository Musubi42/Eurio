<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useCollectionStore } from '@/stores/collection'
const router = useRouter(); const store = useCollectionStore()
function onClick(e: MouseEvent) {
  const a = (e.target as HTMLElement).closest('[data-action]')?.getAttribute('data-action')
  if (a === 'next') router.push('/onboarding/lentille')
  else if (a === 'back') router.push('/onboarding/2')
  else if (a === 'skip') { store.completeOnboarding(); router.push('/scan') }
}
</script>

<template>
<section @click="onClick" class="onboarding-3-root" data-scene="onboarding-3">
  <header class="onboarding-3-topbar">
    <div class="onboarding-3-brand">Eur<em>io</em></div>
    <button type="button" class="onboarding-3-skip" data-action="skip">Passer</button>
  </header>

  <div class="onboarding-3-card">
    <span class="onboarding-3-example-tag">Exemple · progression</span>
    <div class="onboarding-3-card__head">
      <div class="onboarding-3-flag" aria-hidden="true"></div>
      <div class="onboarding-3-card__title">
        France · circulation
        <div class="onboarding-3-card__sub">Série des 8 valeurs</div>
      </div>
      <div class="onboarding-3-fraction">6 / 8</div>
    </div>

    <div class="onboarding-3-progress" aria-label="75 pourcent complété">
      <div class="onboarding-3-progress__fill"></div>
    </div>

    <div class="onboarding-3-grid" aria-hidden="true">
      <div class="onboarding-3-coin onboarding-3-coin--owned"><span class="onboarding-3-coin__label">1c</span><span class="onboarding-3-coin__tick">✓</span></div>
      <div class="onboarding-3-coin onboarding-3-coin--owned"><span class="onboarding-3-coin__label">2c</span><span class="onboarding-3-coin__tick">✓</span></div>
      <div class="onboarding-3-coin onboarding-3-coin--missing"><span class="onboarding-3-coin__label">5c</span></div>
      <div class="onboarding-3-coin onboarding-3-coin--owned"><span class="onboarding-3-coin__label">10c</span><span class="onboarding-3-coin__tick">✓</span></div>
      <div class="onboarding-3-coin onboarding-3-coin--owned"><span class="onboarding-3-coin__label">20c</span><span class="onboarding-3-coin__tick">✓</span></div>
      <div class="onboarding-3-coin onboarding-3-coin--missing"><span class="onboarding-3-coin__label">50c</span></div>
      <div class="onboarding-3-coin onboarding-3-coin--owned"><span class="onboarding-3-coin__label">1€</span><span class="onboarding-3-coin__tick">✓</span></div>
      <div class="onboarding-3-coin onboarding-3-coin--owned"><span class="onboarding-3-coin__label">2€</span><span class="onboarding-3-coin__tick">✓</span></div>
    </div>
  </div>

  <div class="onboarding-3-pager" aria-hidden="true">
    <span></span>
    <span></span>
    <span data-active="true"></span>
  </div>

  <div class="onboarding-3-copy">
    <span class="eyebrow">Étape 3 sur 3</span>
    <h1>Complète des séries entières.</h1>
    <p>Eurio traque chaque série par pays et millésime. Sans points kitsch, sans notifications agressives — juste la satisfaction de voir la collection se compléter.</p>
  </div>

  <div class="onboarding-3-cta">
    <button type="button" class="onboarding-3-back" data-action="back" aria-label="Retour">←</button>
    <button type="button" class="btn btn-gold" data-action="next">
      <span>C'est parti</span>
      <span aria-hidden="true">→</span>
    </button>
  </div>
</section>
</template>

<style src="../../styles/onboarding-3.css"></style>
