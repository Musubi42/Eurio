/**
 * Cible de déploiement — le SEUL réglage qui distingue local de hébergé (Model B / R1).
 *
 * `studio-local` est UN codebase servi à deux endroits ; `VITE_DEPLOY_TARGET` (posé
 * au build) en dérive tout le reste :
 *  - `AUTH_MODE` : `local` → PAT Bearer (`.env.local`), `hosted` → cookie OIDC Authentik.
 *  - `HAS_LOCAL_ML_API` (baseline) : `local` → true (l'API ML `:8042` tourne sur le poste),
 *    `hosted` → false (mixed-content HTTPS interdit → les features lourdes sont grisées).
 *
 * La capacité ML réelle est affinée à chaud par `stores/capabilities` (ping `/health` en
 * local) ; ce module ne fournit que la baseline statique connue au build.
 */
export type DeployTarget = 'local' | 'hosted'
export type AuthMode = 'pat' | 'cookie'

export const DEPLOY_TARGET: DeployTarget =
  import.meta.env.VITE_DEPLOY_TARGET === 'hosted' ? 'hosted' : 'local'

export const IS_HOSTED = DEPLOY_TARGET === 'hosted'

export const AUTH_MODE: AuthMode = IS_HOSTED ? 'cookie' : 'pat'

/** Baseline connue au build ; en local, raffinée par un ping `:8042/health`. */
export const HAS_LOCAL_ML_API = !IS_HOSTED
