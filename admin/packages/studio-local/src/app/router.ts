import { createRouter, createWebHistory } from 'vue-router'

// Auth via PAT (Bearer header sur les XHR eurio-api), pas via cookie ni
// guard route-level. Si le PAT est absent / invalide, le store
// `useEurioSession` reflète l'état et `EurioSessionBanner` (intégré dans
// `AppLayout`) affiche le feedback. Les routes restent accessibles —
// les composables qui appellent eurio-api échouent proprement avec
// `EurioApiError` / `MissingPatError` si la session n'est pas OK.
//
// Supabase est encore consulté pour 4 tables data (cf. ARCHITECTURE.md).

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: () => import('@/shared/ui/AppLayout.vue'),
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
          path: 'review/lot/:listing_key',
          component: () => import('@/features/review/pages/LotReviewDetailPage.vue'),
        },
        {
          path: 'review/recover',
          component: () => import('@/features/review/pages/RecoverRejectedPage.vue'),
        },
        {
          path: 'review/peer-arbitration',
          component: () => import('@/features/review/pages/PeerArbitrationPage.vue'),
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
          path: 'referential/coverage',
          component: () => import('@/features/referential/pages/CoveragePage.vue'),
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
          path: 'crop-bench',
          component: () => import('@/features/crop-bench/pages/CropBenchPage.vue'),
        },
        {
          path: 'denom-gold',
          component: () => import('@/features/denom-gold/pages/DenomGoldValidatePage.vue'),
        },
        {
          // Page one-shot d'audit du gate anti-fragment (volontairement hors nav).
          path: 'fragment-audit',
          component: () => import('@/features/fragment-audit/pages/FragmentAuditPage.vue'),
        },
        {
          // Front d'analyse du banc crop-recovery (hors nav).
          path: 'crop-recovery',
          component: () => import('@/features/crop-recovery/pages/CropRecoveryPage.vue'),
        },
        {
          // Vue « par image brute » du banc crop-recovery (hors nav).
          path: 'crop-recovery/by-raw',
          component: () => import('@/features/crop-recovery/pages/RawGalleryPage.vue'),
        },
        {
          path: 'bench/runs/:runId',
          component: () => import('@/features/bench/pages/BenchRunAuditPage.vue'),
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

export default router
