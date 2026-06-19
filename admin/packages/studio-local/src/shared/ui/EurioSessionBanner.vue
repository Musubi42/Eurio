<script setup lang="ts">
/**
 * Bandeau d'avertissement si le PAT eurio-api est manquant ou invalide.
 * Affiché en haut de l'AppLayout, dismissable temporairement. Voir
 * docs/work-in-progress/auth-redesign/PAT-WORKFLOW.md
 */
import { computed, ref } from 'vue'

import { useEurioSession } from '@/stores/eurio-session'

const session = useEurioSession()
const dismissed = ref(false)

const visible = computed(
  () =>
    !dismissed.value &&
    (session.status === 'missing' ||
      session.status === 'invalid' ||
      session.status === 'error'),
)

const message = computed(() => {
  switch (session.status) {
    case 'missing':
      return 'eurio-api : aucun PAT configuré. Crée un .env.local depuis .env.example pour activer les features qui en dépendent.'
    case 'invalid':
      return (
        session.error ||
        'eurio-api : PAT invalide ou expiré. Génère un nouveau token via admin-vps puis MAJ .env.local.'
      )
    case 'error':
      return `eurio-api injoignable : ${session.error ?? 'erreur inconnue'}`
    default:
      return ''
  }
})

const docsUrl =
  'docs/work-in-progress/auth-redesign/PAT-WORKFLOW.md'
</script>

<template>
  <div v-if="visible" class="eurio-banner" role="alert">
    <span class="msg">{{ message }}</span>
    <a class="link" :href="docsUrl" target="_blank" rel="noopener">
      Doc PAT
    </a>
    <button class="close" aria-label="Masquer" @click="dismissed = true">×</button>
  </div>
</template>

<style scoped>
.eurio-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 14px;
  background: #fff4d6;
  border-bottom: 1px solid #f0d77a;
  color: #5d4a0c;
  font-size: 13px;
}
.msg {
  flex: 1;
}
.link {
  color: #5d4a0c;
  text-decoration: underline;
  font-weight: 500;
}
.close {
  background: transparent;
  border: none;
  font-size: 18px;
  cursor: pointer;
  color: inherit;
  padding: 0 4px;
}
.close:hover {
  opacity: 0.7;
}
</style>
