import { createRouter, createWebHistory } from 'vue-router'
import { DEV_BYPASS, supabase } from '@/shared/supabase/client'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      component: () => import('@/features/auth/pages/LoginPage.vue'),
      meta: { requiresAuth: false },
    },
    {
      // Cible du magic link — gère la race condition session/router
      path: '/auth/callback',
      component: () => import('@/features/auth/pages/AuthCallbackPage.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/',
      component: () => import('@/shared/ui/AppLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        {
          path: '',
          redirect: '/sets',
        },
        {
          path: 'sets',
          component: () => import('@/features/sets/pages/SetsListPage.vue'),
        },
        {
          path: 'coins',
          component: () => import('@/features/coins/pages/CoinsPage.vue'),
        },
        {
          path: 'coins/arbitrage',
          component: () => import('@/features/coins/pages/CoinArbitragePage.vue'),
        },
        {
          path: 'coins/:eurio_id',
          component: () => import('@/features/coins/pages/CoinDetailPage.vue'),
        },
        {
          path: 'audit',
          component: () => import('@/features/audit/pages/AuditPage.vue'),
        },
        {
          path: 'parity',
          component: () => import('@/features/parity/pages/ParityPage.vue'),
        },
        {
          path: 'training',
          component: () => import('@/features/training/pages/TrainingPage.vue'),
        },
        {
          path: 'confusion',
          component: () => import('@/features/confusion/pages/ConfusionMapPage.vue'),
        },
        {
          path: 'augmentation',
          component: () => import('@/features/augmentation/pages/AugmentationStudioPage.vue'),
        },
        {
          path: 'benchmark',
          component: () => import('@/features/benchmark/pages/BenchmarkPage.vue'),
        },
        {
          path: 'benchmark/runs/:id',
          component: () => import('@/features/benchmark/pages/BenchmarkRunDetailPage.vue'),
        },
        {
          path: 'benchmark/compare',
          component: () => import('@/features/benchmark/pages/BenchmarkComparePage.vue'),
        },
        {
          path: 'lab',
          component: () => import('@/features/lab/pages/LabHomePage.vue'),
        },
        {
          path: 'lab/cohorts/new',
          component: () => import('@/features/lab/pages/CohortNewPage.vue'),
        },
        {
          path: 'lab/cohorts/:id',
          component: () => import('@/features/lab/pages/CohortDetailPage.vue'),
        },
        {
          path: 'lab/cohorts/:id/iterations/new',
          component: () => import('@/features/lab/pages/IterationNewPage.vue'),
        },
        {
          path: 'lab/cohorts/:cohortId/iterations/:iterationId',
          component: () => import('@/features/lab/pages/IterationDetailPage.vue'),
        },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/sets',
    },
  ],
})

// Auth guard — désactivé en dev local si VITE_SUPABASE_SERVICE_KEY est défini
router.beforeEach(async (to) => {
  if (DEV_BYPASS) {
    if (to.path === '/login' || to.path === '/auth/callback') return '/sets'
    return true
  }
  if (!to.meta.requiresAuth) return true

  const { data: { session } } = await supabase.auth.getSession()

  if (!session) return '/login'

  const role = session.user.app_metadata?.role
  if (role !== 'admin') {
    await supabase.auth.signOut()
    return '/login'
  }

  return true
})

export default router
