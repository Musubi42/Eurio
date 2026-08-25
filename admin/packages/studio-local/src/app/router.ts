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
// Data : 100 % via eurio-api (canonique SQLite). Le client Supabase front a été
// retiré (D7) — il ne reste que des features de *push* vers le mirror Android.

const heavy = { heavy: true } as const

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: () => import('@/shared/ui/AppLayout.vue'),
      children: [
        {
          // `/` sert DEUX écrans : les KPI pour l'arbitre, l'accueil d'un ami
          // pour qui n'a pas `review:arbitrate` (ACCUEIL-AMI §7). L'arbitrage
          // est fait dans `HomePage`, pas ici : une garde de route ne saurait
          // pas attendre que `/me` ait répondu.
          path: '',
          component: () => import('@/features/accueil/pages/HomePage.vue'),
        },
        {
          // La MAQUETTE de l'accueil, sur fixtures — hors nav, sans réseau.
          // Elle monte le composant définitif : ce qu'on y regarde est ce qu'on
          // livre. Elle sert à trancher le visuel, puis à revoir les cas
          // limites qu'on ne sait pas provoquer en base (file vide, ami à zéro,
          // `/class-need` qui tombe).
          path: 'accueil/maquette',
          component: () => import('@/features/accueil/pages/AccueilMaquettePage.vue'),
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
          // La MAQUETTE de la section « images d'évaluation » de la fiche
          // pièce, sur fixtures — hors nav, sans réseau. Elle monte le
          // composant définitif : ce qu'on y regarde est ce qu'on livre.
          // ⚠️ PAS `meta.heavy` : la maquette ne tape rien.
          path: 'coins/eval-images/maquette',
          component: () =>
            import('@/features/coins/pages/EvalImagesMaquettePage.vue'),
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
          // `/besoin` — le poste de pilotage de l'enrichissement DINO (O2).
          // PAS `meta.heavy`, et c'est délibéré : `GET /class-need` est du SQL
          // pur sur le canonique (pas de `:8042`, pas de cv2). Savoir ce qui
          // manque, et ce que ça coûterait, ne doit pas dépendre d'un Mac
          // allumé. Seuls les GESTES qu'elle propose sont lourds, et la page
          // les grise elle-même via `hasLocalMlApi`.
          path: 'besoin',
          component: () => import('@/features/besoin/pages/BesoinPage.vue'),
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
          meta: heavy,
        },
        {
          path: 'review/lot/:listing_key',
          component: () => import('@/features/review/pages/LotReviewDetailPage.vue'),
        },
        {
          // La pêche — file scopée par la PRÉDICTION (`?class=<class_id>`).
          // PLUS `heavy` depuis le lot 1 de review-collaborative-v2 : les crops
          // sont servis en URLs MinIO présignées (absolues) par eurio-api, et les
          // suggestions DINO sont une LECTURE (0 crop sans prédiction persistée
          // sur 21 223 — le fallback qui encodait à la demande ne s'allume jamais).
          // Seul l'éditeur de crop reste local, et il se grise tout seul.
          path: 'review/peche',
          component: () => import('@/features/review/pages/PechePage.vue'),
        },
        {
          path: 'review/recover',
          component: () => import('@/features/review/pages/RecoverRejectedPage.vue'),
          meta: heavy,
        },
        {
          // La vue BULK d'arbitrage (lot 8) — la seconde moitié de la boucle de
          // review collaborative. Pas `heavy` : elle ne lit que le canonique et
          // des URLs MinIO présignées. La garde est serveur (`review:arbitrate`
          // sur les POST, lot 4b) ; la nav ne fait que du confort.
          path: 'review/arbitrage',
          component: () => import('@/features/review/pages/ArbitrageBulkPage.vue'),
        },
        {
          // La vue UNITAIRE, antérieure au lot 8. Conservée tant que la vue bulk
          // n'est pas éprouvée — sa suppression est inscrite au lot 9 (D10).
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
          // Page sœur « ce qui manque pour entraîner », maille classe. Tape le
          // preflight + le funnel du ML API local → heavy (grisée en hébergé).
          path: 'lab/cohorts-test/:id',
          component: () => import('@/features/lab/pages/CohortTestPage.vue'),
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
