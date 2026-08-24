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

export function oidcLogoutUrl(): string {
  return `${eurioApi.base}/auth/oidc/logout`
}

/**
 * Se déconnecter, puis revenir sur une page vierge.
 *
 * ⛔ C'est un **POST**, pas une navigation. `POST /auth/oidc/logout` rend 204 et
 * efface le cookie de session (`max_age=0`) ; y aller par un `<a href>` ferait
 * un GET, que la route ne sert pas — et le cookie resterait, sans un mot.
 *
 * `credentials: 'include'` est obligatoire : le cookie vit sur
 * `eurio-api.musubi.dev` et le panel sur `eurio-admin.musubi.dev`. Sans lui, le
 * navigateur n'envoie rien et le serveur efface le cookie de personne.
 *
 * Le rechargement en dur (`location.replace`) et non un `router.push` : il faut
 * jeter TOUT l'état en mémoire — le principal, les stores, les caches de requête
 * — sinon l'écran continue d'afficher les données de la session précédente
 * au-dessus d'une session morte.
 */
export async function oidcLogout(): Promise<void> {
  try {
    await fetch(oidcLogoutUrl(), { method: 'POST', credentials: 'include' })
  } catch {
    // Le réseau a lâché : on repart quand même sur une page vierge. Rester sur
    // un écran plein de données avec un bouton qui n'a rien fait est pire que
    // de recharger — au pire l'utilisateur est toujours connecté et le voit.
  }
  window.location.replace('/')
}
