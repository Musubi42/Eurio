# QA Chrome MCP — front Model B (R1) + chemin de données (R2)

> **But.** Vérifier **de bout en bout dans un vrai navigateur** que le front fusionné
> (R1) marche aux deux endroits, que la donnée charge **du VPS** et que les images
> viennent **du bon stockage** (MinIO), que le gating « lourd » est correct, et qu'il
> n'y a **aucune fuite mixed-content**. Complète les vérifs CLI déjà faites (build,
> endpoints, healthz, sha).

---

## Résultats QA — session 30/06/2026

### Préconditions vérifiées (CLI)

| Cible | Résultat |
|---|---|
| `eurio-api.musubi.dev/healthz` | ✅ 200 |
| `eurio-admin.musubi.dev` (front hébergé) | ✅ 200 |
| `localhost:5173` (front local, dev server) | ✅ 200 |
| `127.0.0.1:8042/health` (ML local) | ✅ 200 |

### Tableau PASS/FAIL par cas

#### Groupe A — Hébergé : chargement + auth + routing réseau

| Cas | Résultat | Preuve |
|---|---|---|
| **A1** — Page charge, 0 erreur JS fatale | ✅ PASS | SPA rendue (sidebar Eurio / Admin, KPIs). 0 erreur console. |
| **A2** — Auth cookie, `GET /me` 200 | ✅ PASS | `GET eurio-api.musubi.dev/me` → 200. Bas sidebar = `raphaelthi59@gmail.com · owner · admin · reviewer`. Pas de header `Authorization`, cookies seuls. |
| **A3** — Zéro requête `:8042` en hébergé | ❌ **FAIL → CORRIGÉ** | Voir § Bug A3 ci-dessous. Fix appliqué 30/06, build rebuilté, **déploiement VPS en attente**. |

#### Groupe B — Hébergé : gating features lourdes

| Cas | Résultat | Preuve |
|---|---|---|
| **B1** — Items lourds grisés + badge « local » | ✅ PASS | 10 items nav rendus sans `<a>`, tous avec tooltip « disponible uniquement en local » (Revue Numista, Review queue, Training, Lab, Studio bench, Crop Bench, Parity Viewer, Arbitrage Numista, Cartographie ML, Gold denom). |
| **B2** — `/training`, `/lab`, `/review` → `LocalOnlyNotice` | ✅ PASS | Heading « Cette vue tourne en local » + instructions pnpm dev. Aucune vraie page rendue. Zéro fetch lourd *propre à la route*. |
| **B3** — Vues légères cliquables | ✅ PASS | `/coins` (658 pièces, `GET /coins` 200), `/audit` (Audit log), `/users` (liste, `GET /users` 200), `/me/tokens` (5 tokens) — tous chargés. |

#### Groupe C — Hébergé : vues admin

| Cas | Résultat | Preuve |
|---|---|---|
| **C1** — Dashboard KPIs | ✅ PASS | `GET /stats/overview` → 200. Coins 689, Review queue 5901, Sources 1 run/24h, Users 1. Bouton « Rafraîchir » met à jour l'horodatage. |
| **C2** — Users | ✅ PASS | `GET /users` → 200. Liste rendue. Bouton « Modifier rôles » visible (owner). Lecture seule testée, édition non déclenchée. |
| **C3** — Cycle token complet | ✅ PASS | `POST /me/tokens` → 200, token `eurio_3-ZKy…` affiché **une seule fois** en clair. Modale custom Vue (pas de `prompt()` natif). `DELETE /me/tokens/6` → 200, `revoked: true` confirmé via API. **Cleanup fait** (token de test révoqué). |

#### Groupe D — Hébergé : données VPS + images

| Cas | Résultat | Preuve |
|---|---|---|
| **D1** — Images depuis MinIO (`eurio-s3.musubi.dev`) | ⚠️ **N/A (bloqué par A3)** | Le endpoint `/coins/{id}/assets` qui chargerait les crops MinIO appelait `:8042` → 503. Images affichées = BCE + Numista externes. **À re-tester après déploiement du fix A3.** |
| **D2** — Données cohérentes | ✅ PASS | `GET /coins?limit=60` → 200, 658 pièces (filtre AD). Dashboard = 689 total global. Cohérent. `GET eurio-api.musubi.dev` pour toutes les données. |

#### Groupe E — Local (`localhost:5173`) : PAT + features lourdes

| Cas | Résultat | Preuve |
|---|---|---|
| **E1** — Aucun item grisé | ✅ PASS | `127.0.0.1:8042/health` → 200 au boot → `hasLocalMlApi=true`. Tous les items nav actifs, sans badge « local ». |
| **E2** — Feature lourde active | ✅ PASS | `/training` : vraie page « ArcFace · 403 classes ». `POST 127.0.0.1:8042/training/estimate` → 200. |
| **E3** — Dégradation si ML off | ⚪ Non testé | Requerrait couper `go-task ml:api` manuellement. |
| **E4** — Auth PAT Bearer | ✅ PASS | `GET eurio-api.musubi.dev/me` → 200 avec Bearer. Sans header → 401. PAT injecté depuis `VITE_EURIO_PAT` (`.env.local`). |

#### Groupe F — Sanity backend

| Cas | Résultat | Preuve |
|---|---|---|
| **F1** — `/healthz` → 200 | ✅ PASS | Vérif CLI pré-session. |

---

## Bug A3 — Détail et fix

### Symptôme
À chaque chargement de page en hébergé, le front émettait des requêtes HTTP vers
`http://127.0.0.1:8042` (le ML API local). En mode HTTPS hébergé, Chrome autorise
les requêtes HTTP→localhost sans lever de warning mixed-content (exemption navigateur),
d'où l'absence de signal console — le bug était silencieux.

Requêtes observées (non exhaustif) :
- `GET http://127.0.0.1:8042/numista-review/stats` → 503 (toutes les 30s, sur **toutes** les pages)
- `GET http://127.0.0.1:8042/lab/cohorts?status=draft` → 503 (CoinsPage au mount)
- `GET http://127.0.0.1:8042/coins/enrichment-counts` → 503 (CoinsPage au mount)
- `GET http://127.0.0.1:8042/referential/coin-canonicals/{id}` → 503 (CoinDetailPage au mount)
- `GET http://127.0.0.1:8042/coins/{id}/assets` → 503 (CoinDetailPage au mount)
- `GET http://127.0.0.1:8042/health` → 503 (CoinsPage, poll 30s)

### Cause racine
Le gate `hasLocalMlApi` fonctionnait **uniquement au niveau nav** (items grisés ✅)
mais pas au niveau **data-fetching** des composants. Les composables et pages
accessibles en hébergé appelaient `ML_API` directement sans vérifier `HAS_LOCAL_ML_API`.

### Fix appliqué (30/06/2026, branche `sources-jo-wikipedia`)

| Fichier | Changement |
|---|---|
| `shared/composables/useNavState.ts` | `if (!HAS_LOCAL_ML_API) return` dans `fetchBadges()` — stoppe le poll 30s en hébergé |
| `features/coins/composables/useCoinAssets.ts` | early return `{}` / `{total:0,assets:[]}` dans `fetchEnrichmentCounts` et `fetchCoinAssets` |
| `features/coins/pages/CoinsPage.vue` | guard `if (HAS_LOCAL_ML_API)` autour de `checkMlApi` + `loadEnrichmentCounts` + interval |
| `features/lab/composables/useLabQueries.ts` | `enabled: HAS_LOCAL_ML_API` sur `useCohortsQuery` (stop query `lab/cohorts` en hébergé) |
| `features/coins/pages/CoinDetailPage.vue` | guard `mergeLocalCanonicals()` + `v-if="… && HAS_LOCAL_ML_API"` sur bouton Entraîner |

Build TypeScript + Vite hosted : ✅ zéro erreur, 4.1s.

---

## Prochaine session — TODO

### 1. Déployer le fix A3 sur le VPS (priorité haute)

```bash
# Sur le VPS (/opt/eurio)
cd /opt/eurio/infra/eurio-admin
direnv exec /opt/eurio docker compose up -d --build
```

Le `docker compose` rebuild le front depuis les sources avec `VITE_DEPLOY_TARGET=hosted`
(les build args Supabase publics viennent de l'env SOPS). Le résultat est servi par nginx.

Alternative si build local préféré : copier `admin/packages/studio-local/dist/` vers le VPS
et redémarrer nginx (sans rebuild docker).

### 2. Re-valider A3 + D1 après déploiement

- **A3** : recharger `eurio-admin.musubi.dev`, `read_network_requests` filtré sur `8042` → doit
  retourner 0 résultat sur le Dashboard, `/coins`, `/coins/{id}`, `/training` (LocalOnlyNotice).
- **D1** : ouvrir un coin détail → vérifier que les images de crops (section Enrichment) chargent
  depuis `eurio-s3.musubi.dev` (MinIO presigned). Si la section reste vide, c'est normal pour les
  coins sans crops dans eurio.db — choisir un coin avec `enrichment_count > 0` (filtre « Avec image »
  dans CoinsPage, ou regarder le badge count).

### 3. E3 — test dégradation ML off (optionnel, non bloquant)

Couper `go-task ml:api` manuellement, recharger `localhost:5173`, vérifier que :
- les items lourds passent grisés + `LocalOnlyNotice`
- relancer `ml:api` + recharger → de nouveau actifs

### 4. Committer et pousser

Le fix A3 est sur la branche `sources-jo-wikipedia` (non poussée). À committer proprement
avec les fichiers modifiés :

```
admin/packages/studio-local/src/shared/composables/useNavState.ts
admin/packages/studio-local/src/features/coins/composables/useCoinAssets.ts
admin/packages/studio-local/src/features/coins/pages/CoinsPage.vue
admin/packages/studio-local/src/features/lab/composables/useLabQueries.ts
admin/packages/studio-local/src/features/coins/pages/CoinDetailPage.vue
```

---

## Mode d'exécution (à graver pour la session QA)

- **Modèle : Sonnet 4.6** (pas Opus — overkill ici). Switcher via `/model` avant de lancer.
- **Chrome** : deux instances connectées = `tabs_context_mcp` timeout. Appeler d'abord
  `list_connected_browsers` → `select_browser` avec le bon `deviceId`. Puis `tabs_context_mcp`.
- **Outils** : MCP `claude-in-chrome`. Charger en UN seul ToolSearch :
  `tabs_context_mcp, navigate, computer, read_page, tabs_create_mcp,
  read_console_messages, read_network_requests, javascript_tool`.
- **Pattern** : `tabs_context_mcp` d'abord → un **nouveau** tab par cible → naviguer →
  observer (DOM via `read_page`, réseau via `read_network_requests`, console via
  `read_console_messages`) → conclure.
- **Séquentiel, pas sous-agents** : une seule session Chrome partagée → les agents
  parallèles entrelaceraient les preuves réseau. Driver A→F en séquentiel.
- **Révocation token** : le bouton Révoquer utilise `confirm()` natif (fige l'extension).
  Faire le DELETE via `javascript_tool` + `fetch` avec `credentials: 'include'`. Récupérer
  l'ID du token via `GET /me/tokens`.
- **Le login Authentik interactif n'est PAS automatisable** : précondition = être déjà
  connecté dans Chrome avant de lancer la QA.

## Préconditions

| Cible | URL | À avoir |
|---|---|---|
| Front hébergé | `https://eurio-admin.musubi.dev` | session Authentik active dans Chrome |
| Backend canonique | `https://eurio-api.musubi.dev/healthz` → 200 | (déjà OK) |
| Images | `https://eurio-s3.musubi.dev` (MinIO presigned) | — |
| Front local | `http://localhost:5173` | `pnpm -C admin/packages/studio-local dev` |
| API ML locale | `http://127.0.0.1:8042/health` | `go-task ml:api` (pour les cas E1/E2) |

---

## Cas de QA (référence)

### Groupe A — Hébergé : chargement + auth + routing réseau

- **A1 — La page charge.** Naviguer `eurio-admin.musubi.dev`. *Attendu* : SPA rendue
  (sidebar « Eurio / Admin », pas d'écran blanc). `read_console_messages` → **0 erreur
  JS fatale**.
- **A2 — Auth cookie.** `read_network_requests` → `GET eurio-api.musubi.dev/me` **200**,
  pas de header `Authorization`. Bas de sidebar = email + rôles.
- **A3 — Zéro `:8042`.** Cliquer 3-4 vues légères. `read_network_requests` filtre `8042`
  → **0 résultat**. ⟵ *cœur du test.*

### Groupe B — Hébergé : gating des features lourdes

- **B1 — Nav grisée.** Items lourds : grisés, badge « local », non-cliquables.
- **B2 — Notice sur accès direct.** URL directe `/training` → `LocalOnlyNotice`, pas de
  vraie page. `read_network_requests` filtre `8042` → **0**.
- **B3 — Légers cliquables.** Dashboard, Sets, Pièces, Sources, Audit, Operations,
  Référentiel, Utilisateurs, Mes tokens : chargent.

### Groupe C — Hébergé : les 3 vues rapatriées (admin)

- **C1 — Dashboard KPIs.** `GET /stats/overview` **200**. Rafraîchir met à jour l'horodatage.
- **C2 — Users.** `GET /users` **200**, liste rendue. Bouton « Modifier rôles » visible.
- **C3 — Mes tokens, cycle complet.** Créer token `qa-chrome-mcp` → clair affiché 1× →
  révoquer via `DELETE /me/tokens/{id}` (JS fetch, pas le bouton UI qui déclenche `confirm()`).

### Groupe D — Hébergé : données VPS + images

- **D1 — Images depuis MinIO.** Ouvrir un coin avec enrichment (badge > 0 dans la liste).
  `read_network_requests` → URL images = **`eurio-s3.musubi.dev`**.
- **D2 — Données cohérentes.** Liste Pièces / compteurs Dashboard cohérents.

### Groupe E — Local (`localhost:5173`) : PAT + features lourdes

- **E1 — Nav complète.** Ping `:8042/health` → 200, **aucun** item grisé.
- **E2 — Feature lourde active.** Training charge, `read_network_requests` → requêtes `:8042`.
- **E3 — Dégradation si ML off.** Couper `ml:api` → items grisés + LocalOnlyNotice.
- **E4 — Auth PAT.** `GET /me` 200 avec `Authorization: Bearer eurio_…`.

### Groupe F — Sanity backend

- **F1** — `https://eurio-api.musubi.dev/healthz` → **200**.

---

## Garde-fous d'exécution

- Actions **sensibles** (C2 édition rôles, C3 création/révocation token) : objets de
  test uniquement, cleanup systématique.
- Pas de dialogs JS (`confirm`/`alert`) via l'extension — ils figent Chrome. Révocation =
  `fetch DELETE` en JS.
- `read_network_requests` avec filtre d'hôte pour trancher la cible (`eurio-api` vs
  `:8042` vs `eurio-s3`).
- Bloqué après 2-3 essais sur un cas → **stop**, rapport de ce qui a été tenté.
