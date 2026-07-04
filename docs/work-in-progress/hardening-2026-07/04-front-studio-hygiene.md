# 04 — Front studio-local : hygiène capabilities / health-check ML

> Fiche de remédiation — hardening 2026-07. Périmètre : `admin/packages/studio-local/`
> (Vue + Pinia + TanStack Query). Findings vérifiés sur le code réel (file:line ci-dessous).

## Résumé

Le store `useCapabilities` (`src/stores/capabilities.ts`) est **LE** mécanisme documenté
(CLAUDE.md §R0bis) pour gater les features lourdes qui tapent l'API ML locale `:8042` :
il ping `${ML_API}/health`, expose `mlStatus` / `hasLocalMlApi`, et `AppLayout` grise la
nav + rend `LocalOnlyNotice` sur les routes `meta.heavy`.

Problème : **aucune feature ne le consomme** (`grep -rl useCapabilities src/features` →
0 résultat). À la place, **5-6 réimplémentations indépendantes** du même health-check
`:8042/health` coexistent, avec des timeouts (2s vs 3s) et des polls (30s ou rien)
divergents — deux pages ouvertes peuvent afficher simultanément « API OK » et
« API down ». Le store global, lui, ne probe **qu'une fois au boot**
(`app/main.ts:24`) : si l'opérateur lance `go-task ml:api` après avoir ouvert le panel,
le seul remède documenté est **recharger la page** (`LocalOnlyNotice.vue:29-31`, pas de
bouton retry).

S'ajoutent : des routes `sources/*` et `referential/*` qui appellent `:8042` **sans**
`meta.heavy` (violation R0bis) et retombent en hébergé sur des **données MOCK
silencieuses** (coverage, quotes, images fictifs sans aucun indicateur visuel) ; un
couplage cross-feature (`sources/` importe `usePoller`/`checkMlApi` depuis
`training/`) ; et une race condition dans `CoinDetailPage.vue` (réponses obsolètes qui
écrasent l'état après navigation A→B).

## Findings

| Sévérité | Preuve (file:line) | Constat |
|---|---|---|
| medium | `src/stores/capabilities.ts:30-45` ; `src/features/training/composables/useTrainingApi.ts:114-123` ; `src/features/coins/pages/CoinsPage.vue:360-366` + `:254` | Trois implémentations du ping `/health` : store Pinia (timeout 2s, pas de poll), `checkMlApi()` exporté (3s, état local), `checkMlApi()` local à CoinsPage (3s + `setInterval` 30s). Seuils/états divergents, aucune réconciliation. TrainingPage est déjà gatée `meta.heavy` par le store mais exécute EN PLUS sa propre détection (`TrainingPage.vue:3` import, `:52` appel). |
| medium | `src/app/main.ts:24` (unique appel `.probe()` de tout `src/`) ; `src/shared/ui/LocalOnlyNotice.vue:29-31` | Pas de retry sur le gate global : `probe()` n'est appelé qu'au boot. `LocalOnlyNotice` instruit « 1. Lance l'API ML… 2. Recharge cette page » — pas de bouton réessayer. SourcesPage/TrainingPage/AugmentationStudioPage ont dû réinventer chacune un `refreshApiStatus({showProbe:true})` local. |
| medium | `src/app/router.ts:56-70` et `:110-125` (pas de `meta.heavy`) ; `src/app/nav.ts:69-98` (pas de `heavy:true`) ; `src/features/sources/composables/useSourceDetail.ts:112,232,246,404,443,497-608` ; `src/features/referential/composables/useReferentialApi.ts:65-81,145-191,282-284,386-395` | Routes `/sources/*` et `/referential/*` non-heavy alors qu'elles fetch directement `${ML_API}` (violation R0bis). En hébergé (mixed-content HTTPS→127.0.0.1), l'échec est absorbé et remplacé par des mocks (`generateMockImages/Quotes/Breakdown`, `useSourceDetail.ts:497-608`) **sans badge** dans `SourceDetailPage.vue` — seule `SourcesPage.vue:121,128` (liste) a un bandeau « ML API hors-ligne ». |
| medium | `grep -rl useCapabilities src/features` → 0 ; `useTrainingApi.ts:114` ; `confusion/composables/useConfusionMap.ts:66` ; `lab/pages/LabHomePage.vue:38` (+`setInterval` L31) ; `coins/pages/CoinsPage.vue:360` (+L254) ; `sources/pages/SourcesPage.vue:29` (+healthPoller L66/L75) | Le store capabilities n'est consommé par AUCUNE feature ; 5 sites de poll 30s indépendants → jusqu'à 5-6 requêtes `/health` parallèles, état up/down divergent entre pages. |
| medium | `src/features/sources/pages/SourcesPage.vue:8-10` | Couplage cross-feature : `import { checkMlApi, usePoller } from '@/features/training/composables/useTrainingApi'`. `sources/` dépend d'un utilitaire générique enfoui dans la feature `training/` ; un refacto de `useTrainingApi.ts` casse `sources/` silencieusement. |
| medium | `src/features/coins/pages/CoinDetailPage.vue:179-280` (fetchCoin), `:271-279` (loaders chaînés), `:557` (watch route), `:407` (goToVariant) | Race : `fetchCoin` + `loadConfusion/loadMarketPrice/loadI18nAndAliases/loadCharacteristics/loadSourceStatus` écrivent inconditionnellement dans les refs partagés à la résolution, sans requestId ni AbortController. Navigation A→B (variant ou voisin de confusion, même route) : les callbacks tardifs de A peuvent écraser les données de B (mélange caractéristiques(A)/coin(B)). |
| low | `src/stores/capabilities.ts:24-27` ; `src/shared/ui/AppLayout.vue:25` | Boot : `mlStatus` démarre à `'unknown'` (le commentaire ligne 24 prétend « baseline true » — faux) → `hasLocalMlApi` faux jusqu'à résolution du ping ; deep-link/F5 sur une route heavy flashe `LocalOnlyNotice` + nav grisée jusqu'à 2s même API up. |
| low | `src/shared/utils/coin-images.ts:27-44,46-58` (+ import ML_API via `useTrainingApi` ligne 2) | `loadCanonicalIndex()`/`firstImageUrl()` gatent sur `import.meta.env.DEV` au lieu de `HAS_LOCAL_ML_API`/`caps.hasLocalMlApi` — troisième critère de gating ML, dans `shared/` en plus. |
| low | `src/features/denom-gold/pages/DenomGoldValidatePage.vue:32,218` | Checkbox « masquer validés » (`hideValidated`) bindée mais jamais consommée — contrôle UI mort. |
| low | `src/features/confusion/composables/useConfusionMap.ts:102,118,121,136,171,207` | Doc-drift : fonctions `fetch*FromSupabase` + commentaires « Supabase fallback » alors qu'elles appellent `eurioApi.get(...)` — Supabase retiré du front depuis D7 (2026-07-01). |
| low | `src/shared/query/client.ts` ; `grep -rl useQuery src/features` → 9 fichiers (lab/, coins/ seulement) | TanStack Query (persistance IndexedDB, staleTime 5min, retry) sous-utilisé : ~20 pages font `onMounted + loading/try/catch` à la main (re-fetch systématique, pas de dédup, gestion d'erreur ad hoc). |

## Cause racine

Le gating capability (`useCapabilities` + `meta.heavy` + `AppLayout`/`LocalOnlyNotice`)
a été construit au moment de la fusion R1 (Model B, 2026-06-30) mais **n'a jamais été
adopté par les features** : chaque page qui avait besoin de savoir si `:8042` répondait
a bricolé son propre ping (souvent en copiant `checkMlApi` de `training/`), son propre
poll, son propre bandeau. Le store global, resté sans consommateur et sans repoll,
n'a jamais été confronté à ses lacunes (pas de retry, baseline mensongère au boot).
Les pages `sources`/`referential`, arrivées après, ont contourné le gate entièrement
(pas de `meta.heavy`) en absorbant les échecs par des mocks.

**Consolidation = un seul store.** Toute connaissance de l'état de `:8042` doit passer
par `useCapabilities` (état + probe + repoll), et tout gating de route par `meta.heavy`.
Aucun `fetch(/health)` ni `setInterval` de santé en dehors du store.

## Plan par chunks

### Chunk A — repoll sur `useCapabilities` + bouton « réessayer » dans `LocalOnlyNotice` (~1h)

- **Fichiers** : `src/stores/capabilities.ts`, `src/shared/ui/LocalOnlyNotice.vue`,
  (option) `src/shared/ui/AppLayout.vue`.
- Exposer sur le store : `probe()` réentrant (déjà là) + un `startPolling(intervalMs)` /
  `stopPolling()` idempotent (un seul `setInterval` global, no-op en hébergé), ou a
  minima laisser `probe()` appelable et l'appeler depuis `LocalOnlyNotice`.
- `LocalOnlyNotice.vue` : remplacer « Recharge cette page » (l.31) par un bouton
  « Réessayer » qui appelle `caps.probe()` (état `checking` affiché pendant le ping).
- Bonus rattaché : corriger le commentaire mensonger `capabilities.ts:24` et traiter
  `'unknown'/'checking'` comme état transitoire côté `AppLayout.vue:25` (spinner ou
  passage optimiste, au choix — trancher avec le PO) pour tuer le flash au boot (finding low).
- **Vérification** : ouvrir `/training` sans `go-task ml:api` → notice avec bouton ;
  lancer l'API ; cliquer « Réessayer » → la page lourde apparaît **sans reload**.
  Deep-link F5 sur `/lab` avec API up → plus de flash LocalOnlyNotice.

### Chunk B — faire consommer `useCapabilities` par toutes les pages, supprimer les pings locaux (~2-3h)

- **Fichiers** : `src/features/training/composables/useTrainingApi.ts` (supprimer
  `checkMlApi` export, l.114-123), `src/features/training/pages/TrainingPage.vue`
  (l.3, l.52), `src/features/coins/pages/CoinsPage.vue` (l.254, l.353, l.360-366),
  `src/features/sources/pages/SourcesPage.vue` (l.8-10, l.29, healthPoller l.66/75),
  `src/features/confusion/composables/useConfusionMap.ts` (l.66) +
  `ConfusionMapPage.vue` (checkApi l.83, setInterval l.69),
  `src/features/lab/pages/LabHomePage.vue` (l.31, l.38),
  `AugmentationStudioPage.vue` + son composable (refreshApiStatus).
- Chaque page lit `useCapabilities().hasLocalMlApi` / `.mlStatus` (réactif) ; le poll
  30s devient l'unique `startPolling()` du store (démarré par `AppLayout` ou par les
  pages qui en ont besoin via un compteur d'abonnés).
- Inclure `src/shared/utils/coin-images.ts` : remplacer `import.meta.env.DEV` par
  `HAS_LOCAL_ML_API` et importer `ML_API` depuis `@/shared/api/ml-api` (pas via
  `useTrainingApi`).
- **Vérification** : `grep -rn "fetch(\`\${ML_API}/health" src/` → 1 seule occurrence
  (le store) ; `grep -rn "setInterval.*[Cc]heck\(Ml\)\?Api\|healthPoller" src/features` → 0 ;
  onglet Réseau : une seule requête `/health` par intervalle quelle que soit la page ;
  arrêter/relancer `go-task ml:api` → toutes les pages ouvertes basculent ensemble.

### Chunk C — routes `sources/*` / `referential/*` : `meta.heavy` OU badge « données simulées » (~1-2h + décision PO)

- **Décision à trancher d'abord** (R0 : on discute avant) : ces pages sont-elles
  voulues consultables en hébergé (données eurio-api légères + widgets ML dégradés) ?
  - **Si non** → marquer `meta: { heavy: true }` sur `router.ts:56-70` et `:110-125`,
    `heavy: true` sur les items nav `nav.ts:69-98`. Le gate standard fait le reste.
  - **Si oui (pages mixtes)** → supprimer le fallback mock silencieux : les widgets
    alimentés par `generateMockImages/Quotes/Breakdown` (`useSourceDetail.ts:497-608`)
    affichent un badge explicite « données simulées — API ML indisponible » (composant
    partagé, ex. `shared/ui/MockDataBadge.vue`), piloté par `caps.hasLocalMlApi` ;
    les actions d'écriture (`triggerSourceRun`, `runHeal`, `applyFixProposal`…
    `useReferentialApi.ts:65-81,145-191,386-395`) sont désactivées quand faux.
- **Fichiers** : `src/app/router.ts`, `src/app/nav.ts`,
  `src/features/sources/composables/useSourceDetail.ts`,
  `src/features/sources/pages/SourceDetailPage.vue`,
  `src/features/referential/composables/useReferentialApi.ts`.
- **Vérification** : build `VITE_DEPLOY_TARGET=hosted` + `pnpm preview` : soit
  `/sources` grisé dans la nav + `LocalOnlyNotice`, soit la page détail source montre
  le badge sur coverage/quotes/images et aucune donnée fictive sans marquage. En
  local API down, même comportement.

### Chunk D — sortir `usePoller` (et ce qui reste de générique) de `features/training` vers `shared/` (~30min)

- **Fichiers** : créer `src/shared/composables/usePoller.ts` (déplacement, pas copie),
  mettre à jour les imports : `useTrainingApi.ts`, `TrainingPage.vue`,
  `SourcesPage.vue:8-10`. (`checkMlApi` disparaît au Chunk B — si B et D sont livrés
  ensemble, seul `usePoller` déménage.)
- **Vérification** : `grep -rn "from '@/features/training" src/features --include="*.vue" --include="*.ts" | grep -v features/training` → 0 ; `pnpm build` OK.

### Chunk E — garde anti-stale dans `CoinDetailPage.vue` (~1h)

- **Fichier** : `src/features/coins/pages/CoinDetailPage.vue`.
- Introduire un jeton de génération : `let fetchGen = 0` ; `fetchCoin` fait
  `const gen = ++fetchGen` et le passe aux loaders (l.271-279) ; chaque écriture de ref
  est gardée par `if (gen !== fetchGen) return`. Alternative équivalente :
  un `AbortController` par navigation, aborté en tête de `fetchCoin` et dans
  `onUnmounted`, signal propagé aux fetch.
- **Vérification** : simuler (Network throttling « Slow 3G ») : ouvrir pièce A, cliquer
  immédiatement un variant B (l.407) → une fois B chargé, aucune section
  (caractéristiques, i18n, confusion, prix) ne re-flashe avec les données de A ;
  vérifier aussi B→retour arrière→A.

### Hors périmètre immédiat (tracké, non bloquant)

- `DenomGoldValidatePage.vue:32,218` : implémenter le filtre `hideValidated` (modèle :
  `fragment-audit/FragmentAuditPage.vue` et son `filtered`) ou retirer la checkbox — quick-win 15min, à glisser dans B ou C.
- `useConfusionMap.ts` : renommer `fetch*FromSupabase` → `fetch*` + purger les
  commentaires Supabase (doc-drift D7) — quick-win, à glisser dans B.
- Généralisation TanStack Query (`shared/query/client.ts` sous-utilisé) : dette
  d'architecture réelle mais migration de masse = chantier séparé, à trancher avec le
  PO (R0). Ne pas mélanger avec cette fiche.

## Tooling de test : socle absent

`studio-local` n'a **aucun test** (`find src -name "*.test.*" -o -name "*.spec.*"` → 0
fichier ; pas de `vitest` ni de script `test` dans
`admin/packages/studio-local/package.json`). La consolidation ci-dessus touche le socle
(store capabilities, gating de routes, poller partagé) sans filet.

Recommandation : socle minimal **Vitest** (déjà l'écosystème Vite du package, zéro
config lourde) + `@vue/test-utils` + `@pinia/testing`, avec pour commencer 3 suites
ciblées qui verrouillent exactement ce que cette fiche consolide :

1. `stores/capabilities.spec.ts` — probe up/down/timeout, mode hosted = `disabled`
   sans fetch, repoll réentrant, polling idempotent (fetch mocké).
2. `router.spec.ts` — invariant R0bis : toute route dont la feature importe `ML_API`
   hors store porte `meta.heavy` (ou au minimum : snapshot de la liste des routes heavy).
3. `CoinDetailPage` anti-stale — deux fetchCoin entrelacés (promesses contrôlées), la
   réponse tardive du premier ne doit pas écraser l'état du second.

Câbler `pnpm test` dans le package et l'exposer via une task `go-task admin:test`
(à ajouter au Taskfile) pour l'intégrer aux vérifications de chunk.

## Effort & priorité

| Chunk | Effort | Priorité | Dépendances |
|---|---|---|---|
| A — repoll + bouton réessayer | ~1h | **P1** (irritant quotidien opérateur) | — |
| B — consolidation sur useCapabilities | ~2-3h | **P1** (cœur de la fiche) | A |
| C — sources/referential heavy ou badge mock | ~1-2h | **P1** (données de pilotage fictives non signalées = risque décisionnel) | décision PO ; indépendant de A/B |
| D — usePoller → shared/ | ~30min | P2 | avec B idéalement |
| E — anti-stale CoinDetail | ~1h | P2 (bug réel mais fenêtre étroite) | — |
| Socle Vitest (3 suites) | ~2-3h | P2 (à poser pendant/juste après B) | — |

Total : ~1,5 jour. Ordre suggéré : **A → B(+D, quick-wins) → C (après décision PO) → E → tests**.
Chaque chunk livré séparément avec sa vérification (doctrine chunk-by-chunk + audit).
