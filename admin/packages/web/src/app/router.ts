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
          path: 'coins/numista-review',
          component: () => import('@/features/coins/pages/NumistaReviewPage.vue'),
        },
        {
          path: 'coins/needs-review',
          component: () => import('@/features/coins/pages/CoinsNeedsReviewPage.vue'),
        },
        {
          path: 'coins/:eurio_id',
          component: () => import('@/features/coins/pages/CoinDetailPage.vue'),
        },
        {
          path: 'sources',
          component: () => import('@/features/sources/pages/SourcesPage.vue'),
        },
        {
          path: 'sources/:id',
          component: () => import('@/features/sources/pages/SourceDetailPage.vue'),
        },
        {
          path: 'sources/:id/runs/:run_id',
          component: () => import('@/features/sources/pages/SourceRunDetailPage.vue'),
        },
        {
          path: 'sources/:id/runs/:run_id/listings',
          component: () => import('@/features/sources/pages/SourceRunListingsPage.vue'),
        },
        {
          path: 'review',
          component: () => import('@/features/review/pages/ReviewDashboardPage.vue'),
        },
        {
          path: 'review/manual',
          component: () => import('@/features/review/pages/ReviewPage.vue'),
        },
        {
          path: 'review/auto-accept',
          component: () => import('@/features/review/pages/AutoAcceptReviewPage.vue'),
        },
        {
          path: 'review/ccproxy',
          component: () => import('@/features/review/pages/ClaudeReviewPage.vue'),
        },
        {
          path: 'review/lot/:listing_key',
          component: () => import('@/features/review/pages/LotReviewDetailPage.vue'),
        },
        {
          path: 'audit',
          component: () => import('@/features/audit/pages/AuditPage.vue'),
        },
        {
          path: 'operations',
          component: () => import('@/features/operations/pages/OperationsPage.vue'),
        },
        {
          path: 'referential',
          component: () => import('@/features/referential/pages/ReferentialPage.vue'),
        },
        {
          path: 'referential/divergences',
          component: () => import('@/features/referential/pages/DivergencesPage.vue'),
        },
        {
          path: 'referential/fixes',
          component: () => import('@/features/referential/pages/FixesPage.vue'),
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
          path: 'lab',
          component: () => import('@/features/lab/pages/LabHomePage.vue'),
        },
        {
          path: 'bench',
          component: () => import('@/features/bench/pages/BenchStudioPage.vue'),
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
