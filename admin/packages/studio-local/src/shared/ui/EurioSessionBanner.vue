<script setup lang="ts">
/**
 * Bandeau d'avertissement si le PAT eurio-api est manquant ou invalide.
 * Affiché en haut de l'AppLayout, dismissable temporairement. Voir
 * docs/work-in-progress/auth-redesign/PAT-WORKFLOW.md
 */
import { computed, ref } from 'vue'

import { useEurioSession } from '@/stores/eurio-session'
import { AUTH_MODE } from '@/shared/config/deploy-target'
import { startOidcLogin } from '@/shared/auth/oidc'

const session = useEurioSession()
const dismissed = ref(false)

const cookieMode = computed(() => AUTH_MODE === 'cookie')

const visible = computed(
  () =>
    !dismissed.value &&
    (session.status === 'missing' ||
      session.status === 'invalid' ||
      session.status === 'error'),
)

const message = computed(() => {
  // Mode cookie (hébergé) : tout repose sur la session Authentik.
  if (cookieMode.value) {
    if (session.status === 'error')
      return `eurio-api injoignable : ${session.error ?? 'erreur inconnue'}`
    return session.error || 'Tu n’es pas connecté. Connecte-toi via Authentik pour accéder au panel.'
  }
  // Mode PAT (local).
  switch (session.status) {
    case 'missing':
      return 'eurio-api : aucun PAT. Lance le front via `go-task front:dev` depuis le shell direnv du repo — le PAT vient de secrets/dev.env (EURIO_API_TOKEN).'
    case 'invalid':
      return (
        session.error ||
        'eurio-api : PAT invalide ou expiré. Régénère EURIO_API_TOKEN (`go-task secrets:edit`), puis `direnv reload` et relance `go-task front:dev`.'
      )
    case 'error':
      return `eurio-api injoignable : ${session.error ?? 'erreur inconnue'}`
    default:
      return ''
  }
})

// En mode cookie, propose le login OIDC (sauf si l'API est carrément injoignable).
const showLogin = computed(() => cookieMode.value && session.status !== 'error')

const docsUrl =
  'docs/work-in-progress/auth-redesign/PAT-WORKFLOW.md'
</script>

<template>
  <div v-if="visible" class="eurio-banner" role="alert">
    <span class="msg">{{ message }}</span>
    <button v-if="showLogin" class="login" @click="startOidcLogin()">
      Se connecter avec Authentik
    </button>
    <a v-else class="link" :href="docsUrl" target="_blank" rel="noopener">
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
.login {
  background: #5d4a0c;
  color: #fff4d6;
  border: none;
  border-radius: 6px;
  padding: 4px 12px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.login:hover {
  opacity: 0.9;
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
