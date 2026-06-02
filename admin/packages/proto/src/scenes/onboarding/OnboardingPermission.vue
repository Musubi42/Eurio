<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useCollectionStore } from '@/stores/collection'
const router = useRouter(); const store = useCollectionStore()
function onClick(e: MouseEvent) {
  const root = e.currentTarget as HTMLElement
  const a = (e.target as HTMLElement).closest('[data-action]')?.getAttribute('data-action')
  if (a === 'allow') { root.dataset.state = 'accepting'; setTimeout(() => router.push('/onboarding/demo'), 400) }
  else if (a === 'later') { store.completeOnboarding(); router.push('/scan') }
  else if (a === 'back') router.push('/onboarding/lentille')
}
</script>

<template>
<section @click="onClick" class="onboarding-permission-root" data-scene="onboarding-permission">
  <div class="onboarding-permission-backdrop" aria-hidden="true">
    <div class="onboarding-permission-backdrop__hint">Pointer une pièce</div>
  </div>

  <header class="onboarding-permission-topbar">
    <div class="onboarding-permission-brand">Eur<em>io</em></div>
    <button type="button" class="onboarding-permission-cancel" data-action="back">Annuler</button>
  </header>

  <div class="onboarding-permission-sheet" role="dialog" aria-labelledby="perm-title">
    <div class="onboarding-permission-handle" aria-hidden="true"></div>

    <div class="onboarding-permission-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 7h3l2-3h8l2 3h3a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1Z"/>
        <circle cx="12" cy="13" r="4"/>
      </svg>
    </div>

    <h1 id="perm-title" class="onboarding-permission-title">Autoriser l'appareil photo.</h1>
    <p class="onboarding-permission-sub">Eurio a besoin de la caméra pour reconnaître tes pièces. Tout se passe sur ton téléphone.</p>

    <ul class="onboarding-permission-promises">
      <li>
        <span class="onboarding-permission-tick" aria-hidden="true">✓</span>
        <span>Scan 100&nbsp;% on-device, aucune connexion requise.</span>
      </li>
      <li>
        <span class="onboarding-permission-tick" aria-hidden="true">✓</span>
        <span>Aucune photo n'est envoyée ni stockée.</span>
      </li>
      <li>
        <span class="onboarding-permission-tick" aria-hidden="true">✓</span>
        <span>Aucun compte, aucun email, jamais.</span>
      </li>
    </ul>

    <div class="onboarding-permission-cta">
      <button type="button" class="onboarding-permission-primary" data-action="allow">
        <span>Autoriser la caméra</span>
        <span aria-hidden="true">→</span>
      </button>
      <button type="button" class="onboarding-permission-secondary" data-action="later">
        Plus tard
      </button>
    </div>

    <div class="onboarding-permission-footer">
      <span aria-hidden="true">🛡</span>
      <span>Confidentialité by design &middot; Android permission native</span>
    </div>
  </div>
</section>
</template>

<style src="../../styles/onboarding-permission.css"></style>
