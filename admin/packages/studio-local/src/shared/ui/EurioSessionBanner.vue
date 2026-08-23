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

// ─── Identifiant PÉRIMÉ : authentifié, mais avec des scopes d'avant ─────────
//
// Les scopes effectifs valent `jeton ∩ rôles` : un PAT ne gagne JAMAIS un scope
// ajouté après son émission — c'est voulu. La conséquence, elle, ne l'était pas :
// on se retrouve owner/admin sans `review:arbitrate`, donc SANS l'entrée de nav
// « Arbitrage », SANS la carte du tableau de bord (toutes deux gatées sur ce
// scope), et avec un 403 nu en console au premier clic. Vécu tel quel le
// 2026-08-23 : « Review Arbitrage n'a pas de lien, il faut taper dans l'URL »,
// puis `POST /peer-arbitration/approve-batch 403`.
//
// Le serveur journalise déjà ce cas côté écriture (writes.py). Ici on le rend
// visible AVANT le clic, à qui peut y remédier. Le discriminant est la méthode
// d'auth : un cookie OIDC recalcule ses scopes à chaque login (il ne peut pas
// être périmé, seulement vieux de plus de 8 h), un PAT non.
const SCOPES_ATTENDUS_DES_ARBITRES = ['review:arbitrate']

const identifiantPerime = computed(() => {
  const p = session.principal
  if (!p || p.auth_method !== 'api_token') return null
  const arbitre = p.roles.includes('owner') || p.roles.includes('admin')
  if (!arbitre) return null
  const manquants = SCOPES_ATTENDUS_DES_ARBITRES.filter((sc) => !p.scopes.includes(sc))
  return manquants.length ? manquants : null
})

const visible = computed(
  () =>
    !dismissed.value &&
    (session.status === 'missing' ||
      session.status === 'invalid' ||
      session.status === 'error' ||
      identifiantPerime.value !== null),
)

const message = computed(() => {
  if (identifiantPerime.value) {
    return (
      `PAT périmé : tu portes le rôle ${session.principal?.roles.join(' · ')} mais `
      + `pas le scope ${identifiantPerime.value.join(', ')} — il a été ajouté après `
      + `l'émission de ton jeton, et un jeton ne gagne jamais un scope tout seul. `
      + `L'arbitrage est donc invisible dans la nav et répond 403. `
      + `Remède : régénérer EURIO_API_TOKEN, puis go-task secrets:edit + direnv reload.`
    )
  }
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
// Un PAT périmé, lui, ne se répare pas par un login : rien à proposer.
const showLogin = computed(
  () => cookieMode.value && session.status !== 'error' && !identifiantPerime.value,
)

const docsUrl =
  'docs/work-in-progress/auth-redesign/PAT-WORKFLOW.md'
</script>

<template>
  <div v-if="visible" class="eurio-banner" role="alert">
    <span class="msg">{{ message }}</span>
    <button v-if="showLogin" class="login" @click="startOidcLogin()">
      Se connecter avec Authentik
    </button>
    <!-- « Doc PAT » ne veut rien dire pour un ami en cookie OIDC — et le chemin
         pointe dans le dépôt, donc chez lui un lien mort (D11). -->
    <a v-else-if="!cookieMode" class="link" :href="docsUrl" target="_blank" rel="noopener">
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
