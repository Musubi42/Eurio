import { createRouter, createWebHistory } from 'vue-router'

// Auth-adapter (Model B / R1) : Bearer PAT en local, cookie OIDC en hébergé (cf.
// `shared/config/deploy-target` + `shared/api/eurio-api`). Pas de guard route-level :
// si la session n'est pas OK, `useEurioSession` reflète l'état et `EurioSessionBanner`
// (dans `AppLayout`) affiche le feedback ; les composables échouent proprement.
//
// `meta.heavy` marque les routes qui tapent l'API ML locale `:8042` (ou un endpoint
// dev-only). En hébergé (`hasLocalMlApi` faux), `AppLayout` rend `LocalOnlyNotice` à
// leur place — les composables lourds ne montent pas (zéro fetch mixed-content).
//
// Supabase est encore consulté pour quelques tables data (retrait = chantier D7).

const heavy = { heavy: true } as const

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: () => import('@/shared/ui/AppLayout.vue'),
      children: [
        {
          path: '',
          component: () => import('@/features/dashboard/pages/DashboardPage.vue'),
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
          meta: heavy,
        },
        {
          path: 'coins/numista-review',
          component: () => import('@/features/coins/pages/NumistaReviewPage.vue'),
          meta: heavy,
        },
        {
          path: 'coins/needs-review',
          component: () => import('@/features/coins/pages/CoinsNeedsReviewPage.vue'),
          meta: heavy,
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
          meta: heavy,
        },
        {
          path: 'review/manual',
          component: () => import('@/features/review/pages/ReviewPage.vue'),
          meta: heavy,
        },
        {
          path: 'review/auto-accept',
          component: () => import('@/features/review/pages/AutoAcceptReviewPage.vue'),
          meta: heavy,
        },
        {
          path: 'review/lot/:listing_key',
          component: () => import('@/features/review/pages/LotReviewDetailPage.vue'),
          meta: heavy,
        },
        {
          path: 'review/recover',
          component: () => import('@/features/review/pages/RecoverRejectedPage.vue'),
          meta: heavy,
        },
        {
          // Mixte (GET arbitrage léger + URLs images ML) : accessible en hébergé,
          // les images cassées dégradent proprement.
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
          meta: heavy,
        },
        {
          path: 'training',
          component: () => import('@/features/training/pages/TrainingPage.vue'),
          meta: heavy,
        },
        {
          path: 'confusion',
          component: () => import('@/features/confusion/pages/ConfusionMapPage.vue'),
          meta: heavy,
        },
        {
          path: 'augmentation',
          component: () => import('@/features/augmentation/pages/AugmentationStudioPage.vue'),
          meta: heavy,
        },
        {
          path: 'lab',
          component: () => import('@/features/lab/pages/LabHomePage.vue'),
          meta: heavy,
        },
        {
          path: 'bench',
          component: () => import('@/features/bench/pages/BenchStudioPage.vue'),
          meta: heavy,
        },
        {
          path: 'crop-bench',
          component: () => import('@/features/crop-bench/pages/CropBenchPage.vue'),
          meta: heavy,
        },
        {
          path: 'denom-gold',
          component: () => import('@/features/denom-gold/pages/DenomGoldValidatePage.vue'),
          meta: heavy,
        },
        {
          // Page one-shot d'audit du gate anti-fragment (volontairement hors nav).
          path: 'fragment-audit',
          component: () => import('@/features/fragment-audit/pages/FragmentAuditPage.vue'),
          meta: heavy,
        },
        {
          // Front d'analyse du banc crop-recovery (hors nav).
          path: 'crop-recovery',
          component: () => import('@/features/crop-recovery/pages/CropRecoveryPage.vue'),
          meta: heavy,
        },
        {
          // Vue « par image brute » du banc crop-recovery (hors nav).
          path: 'crop-recovery/by-raw',
          component: () => import('@/features/crop-recovery/pages/RawGalleryPage.vue'),
          meta: heavy,
        },
        {
          path: 'bench/runs/:runId',
          component: () => import('@/features/bench/pages/BenchRunAuditPage.vue'),
          meta: heavy,
        },
        {
          path: 'lab/cohorts/new',
          component: () => import('@/features/lab/pages/CohortNewPage.vue'),
          meta: heavy,
        },
        {
          path: 'lab/cohorts/:id',
          component: () => import('@/features/lab/pages/CohortDetailPage.vue'),
          meta: heavy,
        },
        {
          path: 'lab/cohorts/:id/iterations/new',
          component: () => import('@/features/lab/pages/IterationNewPage.vue'),
          meta: heavy,
        },
        {
          path: 'lab/cohorts/:cohortId/iterations/:iterationId',
          component: () => import('@/features/lab/pages/IterationDetailPage.vue'),
          meta: heavy,
        },
        {
          // Administration (léger, eurio-api only) — rapatrié d'admin-vps (R1).
          path: 'users',
          component: () => import('@/features/users/pages/UsersPage.vue'),
        },
        {
          path: 'me/tokens',
          component: () => import('@/features/tokens/pages/MyTokensPage.vue'),
        },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/',
    },
  ],
})

export default router
