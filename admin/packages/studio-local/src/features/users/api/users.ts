/**
 * Wrapper typé sur `/users` (cf. `ml/serving/users_routes.py`). Rapatrié d'admin-vps
 * (R1), rebranché sur `eurioApi`.
 *
 * - `list()` : scope `users:read` (admin + owner)
 * - `setRoles()` : scope `users:manage` (owner uniquement), anti-lockout dernier owner
 *
 * La création d'un user passe par Authentik (premier login OIDC peuple le miroir local
 * automatiquement). Pas d'endpoint create/delete ici.
 */
import { eurioApi } from '@/shared/api/eurio-api'

export type Role = 'owner' | 'admin' | 'reviewer'

export const ALL_ROLES: Role[] = ['owner', 'admin', 'reviewer']

export interface UserRow {
  id: string
  email: string
  name: string | null
  created_at: number
  last_login_at: number | null
  active: boolean
  roles: Role[]
}

export const usersApi = {
  list: () => eurioApi.get<UserRow[]>('/users'),
  setRoles: (userId: string, roles: Role[]) =>
    eurioApi.put<{ id: string; roles: Role[] }>(
      `/users/${encodeURIComponent(userId)}/roles`,
      { roles },
    ),
}
