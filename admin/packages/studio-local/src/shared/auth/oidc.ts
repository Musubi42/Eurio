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
