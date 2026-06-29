/**
 * Wrapper typé sur `/me/tokens` (cf. `ml/serving/tokens_routes.py`). Rapatrié d'admin-vps
 * (R1), rebranché sur `eurioApi`.
 *
 * Tous les endpoints exigent le scope `tokens:manage_own`. La création retourne le clair
 * **une seule fois** ; le caller doit le mettre en évidence dans la modale, sans persistance.
 */
import { eurioApi } from '@/shared/api/eurio-api'

export interface TokenRow {
  id: number
  name: string
  scopes: string[]
  created_at: number
  last_used_at: number | null
  revoked_at: number | null
  expires_at: number | null
  active: boolean
}

export interface CreateTokenPayload {
  name: string
  scopes: string[]
  /** epoch ms — null/omitted = pas d'expiration */
  expires_at?: number | null
}

export interface CreateTokenResponse {
  id: number
  name: string
  scopes: string[]
  expires_at: number | null
  /** Clair `eurio_…` — affiché UNE FOIS et jamais re-fetchable. */
  token: string
  warning: string
}

export const tokensApi = {
  list: () => eurioApi.get<TokenRow[]>('/me/tokens'),
  create: (body: CreateTokenPayload) =>
    eurioApi.post<CreateTokenResponse>('/me/tokens', body),
  revoke: (id: number) =>
    eurioApi.delete<{ id: number; revoked_at: number; already_revoked?: boolean }>(
      `/me/tokens/${id}`,
    ),
}
