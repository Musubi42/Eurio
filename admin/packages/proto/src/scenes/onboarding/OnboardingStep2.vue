<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useCollectionStore } from '@/stores/collection'
const router = useRouter(); const store = useCollectionStore()
function onClick(e: MouseEvent) {
  const a = (e.target as HTMLElement).closest('[data-action]')?.getAttribute('data-action')
  if (a === 'next') router.push('/onboarding/3')
  else if (a === 'back') router.push('/onboarding/1')
  else if (a === 'skip') { store.completeOnboarding(); router.push('/scan') }
}
</script>

<template>
<section @click="onClick" class="onboarding-2-root" data-scene="onboarding-2">
  <header class="onboarding-2-topbar">
    <div class="onboarding-2-brand">Eur<em>io</em></div>
    <button type="button" class="onboarding-2-skip" data-action="skip">Passer</button>
  </header>

  <div class="onboarding-2-preview" aria-label="Aperçu non réel du futur coffre">
    <span class="onboarding-2-example-tag">Exemple · aperçu</span>
    <div class="onboarding-2-preview__label">Ton coffre · aperçu</div>
    <div>
      <span class="onboarding-2-preview__total">86,40&nbsp;€</span>
      <span class="onboarding-2-preview__delta">▲ 12&nbsp;%</span>
    </div>

    <div class="onboarding-2-stats">
      <div class="onboarding-2-stat">
        <div class="onboarding-2-stat__value">24</div>
        <div class="onboarding-2-stat__label">Pièces</div>
      </div>
      <div class="onboarding-2-stat">
        <div class="onboarding-2-stat__value">7</div>
        <div class="onboarding-2-stat__label">Pays</div>
      </div>
      <div class="onboarding-2-stat">
        <div class="onboarding-2-stat__value">3</div>
        <div class="onboarding-2-stat__label">Séries</div>
      </div>
    </div>
  </div>

  <div class="onboarding-2-recent">
    <div class="onboarding-2-recent__label">Ajoutées récemment · exemple</div>
    <div class="onboarding-2-grid" aria-hidden="true">
      <div class="onboarding-2-cell"><span class="onboarding-2-cell__flag">🇫🇷</span><span class="onboarding-2-cell__value">2€</span></div>
      <div class="onboarding-2-cell"><span class="onboarding-2-cell__flag">🇩🇪</span><span class="onboarding-2-cell__value">1€</span></div>
      <div class="onboarding-2-cell"><span class="onboarding-2-cell__flag">🇪🇸</span><span class="onboarding-2-cell__value onboarding-2-cell__value--sm">50c</span></div>
      <div class="onboarding-2-cell"><span class="onboarding-2-cell__flag">🇮🇹</span><span class="onboarding-2-cell__value onboarding-2-cell__value--sm">20c</span></div>
      <div class="onboarding-2-cell"><span class="onboarding-2-cell__flag">🇵🇹</span><span class="onboarding-2-cell__value onboarding-2-cell__value--sm">10c</span></div>
      <div class="onboarding-2-cell"><span class="onboarding-2-cell__flag">🇧🇬</span><span class="onboarding-2-cell__value">2€</span></div>
    </div>
  </div>

  <div class="onboarding-2-pager" aria-hidden="true">
    <span></span>
    <span data-active="true"></span>
    <span></span>
  </div>

  <div class="onboarding-2-copy">
    <span class="eyebrow">Étape 2 sur 3</span>
    <h1>À quoi ressemblera ton coffre.</h1>
    <p>Chaque pièce prend place dans ton coffre local. Voilà à quoi ça ressemblera quand tu l'auras rempli.</p>
  </div>

  <div class="onboarding-2-cta">
    <button type="button" class="onboarding-2-back" data-action="back" aria-label="Retour">←</button>
    <button type="button" class="btn btn-gold" data-action="next">
      <span>Suivant</span>
      <span aria-hidden="true">→</span>
    </button>
  </div>
</section>
</template>

<style src="../../styles/onboarding-2.css"></style>
