/**
 * Wrapper typé sur /users (cf. ml/serving/users_routes.py, C2).
 *
 * - `list()` : `users:read` (admin + owner)
 * - `setRoles()` : `users:manage` (owner uniquement)
 *
 * La création d'un user passe par Authentik (premier login OIDC peuple
 * le miroir local automatiquement). Pas d'endpoint create/delete ici.
 */
import { api } from './client'

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
  list: () => api.get<UserRow[]>('/users'),
  setRoles: (userId: string, roles: Role[]) =>
    api.put<{ id: string; roles: Role[] }>(
      `/users/${encodeURIComponent(userId)}/roles`,
      { roles },
    ),
}
