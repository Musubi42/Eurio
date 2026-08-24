/**
 * Login OIDC (Authentik) — mode hébergé (cookie). Model B / R1.
 *
 * En hébergé, l'auth est un cookie HttpOnly `eurio_session` posé par eurio-api après
 * le flow Authentik. Le front ne manipule pas le cookie ; il **redirige** vers
 * `GET /auth/oidc/login?return_to=…` qui rebondit sur Authentik (SSO silencieux si une
 * session Authentik est déjà active) puis revient sur le panel avec le cookie posé.
 * `return_to` est restreint au panel origin côté serveur (anti open-redirect).
 *
 * En mode PAT (local), ce module n'a pas de sens (auth par Bearer).
 */
import { eurioApi } from '@/shared/api/eurio-api'

export function oidcLoginUrl(returnTo: string = window.location.href): string {
  return `${eurioApi.base}/auth/oidc/login?return_to=${encodeURIComponent(returnTo)}`
}

export function startOidcLogin(returnTo?: string): void {
  window.location.href = oidcLoginUrl(returnTo)
}

/**
 * Clé de la garde anti-boucle d'auto-login OIDC.
 *
 * Elle vit ICI et non dans le store parce que DEUX endroits l'écrivent : le
 * store l'arme quand un auto-login a déjà été tenté, et `oidcLogout` l'arme
 * pour empêcher le ré-login silencieux juste après une déconnexion. Une chaîne
 * magique recopiée dans les deux serait une divergence programmée — le jour où
 * l'une change, la déconnexion se remet à boucler sans que rien ne le dise.
 */
export const OIDC_TRIED_KEY = 'eurio.oidc.tried'

export function oidcLogoutUrl(): string {
  return `${eurioApi.base}/auth/oidc/logout`
}

/**
 * Se déconnecter — de Eurio **et** d'Authentik.
 *
 * 🔴 CORRIGÉ LE 2026-08-24. La première version faisait un `POST /logout` en
 * `fetch`, puis rechargeait. Elle effaçait bien notre cookie… et la session
 * Authentik survivait : le panel revenait, prenait un 401, déclenchait son
 * auto-login OIDC, et Authentik ré-authentifiait **en silence**. Le bouton
 * paraissait ne rien faire. Constaté par le PO :
 *
 *   « ça rafraîchit, la page Authentik passe sans me demander de login, et je
 *     reviens toujours en tant que reviewer »
 *
 * Une NAVIGATION, pas un `fetch` : le navigateur doit quitter le panel pour
 * aller chez Authentik en emportant ses cookies. `GET /auth/oidc/logout` efface
 * notre cookie et redirige vers l'`end_session_endpoint`.
 *
 * On arme au passage la garde anti-boucle du store (`eurio.oidc.tried`) : sans
 * elle, si l'utilisateur revient sur le panel, l'auto-login repartirait —
 * exactement ce qu'on vient de défaire.
 */
export function oidcLogout(): void {
  try { sessionStorage.setItem(OIDC_TRIED_KEY, '1') } catch { /* privacy mode */ }
  window.location.href = oidcLogoutUrl()
}
