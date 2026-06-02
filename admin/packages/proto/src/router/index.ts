/* router/index.ts — vue-router, miroir de la route-table de _shared/router.js.
 *
 * meta.nav    : onglet bottom-nav actif ('scan'|'vault'|'profile'|'marketplace'|null)
 * meta.chrome : 'none' | 'light' | 'dark'  (pilote .screen[data-chrome])
 *
 * Les scènes pas encore migrées pointent sur Placeholder (Chunks C→E).
 */

import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import Placeholder from '@/scenes/Placeholder.vue'
import { useCollectionStore } from '@/stores/collection'

declare module 'vue-router' {
  interface RouteMeta {
    nav: 'scan' | 'vault' | 'profile' | 'marketplace' | null
    chrome: 'none' | 'light' | 'dark'
  }
}

const routes: RouteRecordRaw[] = [
  // Onboarding (Chunk D3)
  { path: '/onboarding/splash', component: () => import('@/scenes/onboarding/OnboardingSplash.vue'), meta: { nav: null, chrome: 'none' } },
  { path: '/onboarding/1', component: () => import('@/scenes/onboarding/OnboardingStep1.vue'), meta: { nav: null, chrome: 'none' } },
  { path: '/onboarding/2', component: () => import('@/scenes/onboarding/OnboardingStep2.vue'), meta: { nav: null, chrome: 'none' } },
  { path: '/onboarding/3', component: () => import('@/scenes/onboarding/OnboardingStep3.vue'), meta: { nav: null, chrome: 'none' } },
  { path: '/onboarding/lentille', component: () => import('@/scenes/onboarding/OnboardingLentille.vue'), meta: { nav: null, chrome: 'none' } },
  { path: '/onboarding/permission', component: () => import('@/scenes/onboarding/OnboardingPermission.vue'), meta: { nav: null, chrome: 'none' } },
  { path: '/onboarding/demo', component: () => import('@/scenes/onboarding/OnboardingDemo.vue'), meta: { nav: null, chrome: 'none' } },

  // Scan (idle → transition 3D → reveal 3D)
  { path: '/scan', name: 'scan', component: () => import('@/scenes/ScanIdle.vue'), meta: { nav: 'scan', chrome: 'dark' } },
  { path: '/scan/transition', component: () => import('@/scenes/scan/ScanTransition3D.vue'), meta: { nav: 'scan', chrome: 'dark' } },
  { path: '/scan/reveal', component: () => import('@/scenes/scan/RevealStratifie.vue'), meta: { nav: 'scan', chrome: 'dark' } },

  // Coin detail (Chunk B)
  { path: '/coin/:eurioId', name: 'coin', component: () => import('@/scenes/CoinDetail.vue'), meta: { nav: null, chrome: 'light' } },

  // Vault (Chunk C)
  { path: '/vault', name: 'vault', component: () => import('@/scenes/vault/VaultHome.vue'), meta: { nav: 'vault', chrome: 'light' } },
  { path: '/vault/sets', component: () => import('@/scenes/vault/VaultSetsList.vue'), meta: { nav: 'vault', chrome: 'light' } },
  { path: '/vault/sets/:setId', component: () => import('@/scenes/vault/VaultSetsDetail.vue'), meta: { nav: 'vault', chrome: 'light' } },
  { path: '/vault/catalog', component: () => import('@/scenes/vault/CarteAGratter.vue'), meta: { nav: 'vault', chrome: 'light' } },
  { path: '/vault/catalog/:iso', component: () => import('@/scenes/vault/VaultCatalogCountry.vue'), meta: { nav: 'vault', chrome: 'light' } },
  { path: '/vault/search', component: () => import('@/scenes/vault/VaultSearch.vue'), meta: { nav: 'vault', chrome: 'light' } },
  { path: '/vault/filters', component: () => import('@/scenes/vault/VaultFilters.vue'), meta: { nav: 'vault', chrome: 'light' } },

  // Profile (Chunk E) — unlock = célébration (Chunk D4)
  { path: '/profile', name: 'profile', component: () => import('@/scenes/profile/ProfileHome.vue'), meta: { nav: 'profile', chrome: 'light' } },
  { path: '/profile/achievements', component: () => import('@/scenes/profile/ProfileAchievements.vue'), meta: { nav: 'profile', chrome: 'light' } },
  { path: '/profile/set/:setId', component: () => import('@/scenes/profile/ProfileSet.vue'), meta: { nav: 'profile', chrome: 'light' } },
  { path: '/profile/settings', component: () => import('@/scenes/profile/ProfileSettings.vue'), meta: { nav: 'profile', chrome: 'light' } },
  { path: '/profile/unlock', component: () => import('@/scenes/profile/ProfileUnlock.vue'), meta: { nav: null, chrome: 'none' } },

  // Marketplace (Chunk E)
  { path: '/marketplace', name: 'marketplace', component: () => import('@/scenes/MarketplaceSoon.vue'), meta: { nav: 'marketplace', chrome: 'light' } },

  // Défaut → onboarding au premier lancement, sinon scan
  { path: '/', redirect: () => (useCollectionStore().firstRun ? '/onboarding/splash' : '/scan') },
  { path: '/:pathMatch(.*)*', component: Placeholder, meta: { nav: null, chrome: 'light' } },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})
