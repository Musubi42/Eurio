/**
 * Router — guard global qui :
 *  1. Charge `/me` au boot (une fois)
 *  2. Redirige vers `/login` si pas de Principal
 *  3. Redirige vers `/not-authorized` si la route requiert un scope absent
 */
import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true },
  },
  {
    path: '/not-authorized',
    name: 'not-authorized',
    component: () => import('@/views/NotAuthorized.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    component: () => import('@/components/AppShell.vue'),
    children: [
      { path: '', name: 'home', component: () => import('@/views/Home.vue') },
      {
        path: 'sources',
        name: 'sources',
        component: () => import('@/views/Placeholder.vue'),
        meta: { scope: 'sources:read', title: 'Sources' },
      },
      {
        path: 'coins',
        name: 'coins',
        component: () => import('@/views/Placeholder.vue'),
        meta: { scope: 'coins:read', title: 'Coins' },
      },
      {
        path: 'audit',
        name: 'audit',
        component: () => import('@/views/Placeholder.vue'),
        meta: { scope: 'audit:read', title: 'Audit' },
      },
      {
        path: 'review',
        name: 'review',
        component: () => import('@/views/Placeholder.vue'),
        meta: { scope: 'review:read', title: 'Review' },
      },
      {
        path: 'training',
        name: 'training',
        component: () => import('@/views/Placeholder.vue'),
        meta: { scope: 'training:run', title: 'Training' },
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('@/views/Placeholder.vue'),
        meta: { scope: 'users:read', title: 'Users' },
      },
      {
        path: 'me/tokens',
        name: 'tokens',
        component: () => import('@/views/Placeholder.vue'),
        meta: { scope: 'tokens:manage_own', title: 'Mes tokens' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.loaded) {
    await auth.load()
  }
  if (to.meta.public) return true
  if (!auth.isAuthed) {
    return { name: 'login', query: { return_to: to.fullPath } }
  }
  const scope = to.meta.scope as string | undefined
  if (scope && !auth.hasScope(scope)) {
    return { name: 'not-authorized', query: { scope } }
  }
  return true
})
