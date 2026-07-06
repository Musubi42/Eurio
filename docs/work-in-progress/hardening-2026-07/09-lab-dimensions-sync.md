# F09 — Sync des dimensions lab (`experiment_cohorts` / `experiment_iterations`) → canonique VPS

> **Statut : implémenté (2026-07-06).** Clôt le « push séparé, différé cutover »
> de `ml/client/runbatch.py:49-50`. Fait suite au live-repro : cohortes
> `mix-owned-42`/`owned-ready-24` créées via le lab local → section « jeu
> d'entraînement » (C3, lecture VPS) en 404 `Cohort introuvable`, liste
> canonique des itérations vide. Seed manuel one-shot fait le 2026-07-06
> (`ml/state/vps_cohorts_push.sql`) — ce chantier rend le flux automatique.

## 1. Le trou (constaté, pas théorique)

| Table | Transport local→VPS avant F09 | Symptôme |
|---|---|---|
| `experiment_cohorts` | **aucun** | `GET /lab/cohorts/{id}/training-crops` (lean, C3) → 404 ; réplique sans la cohorte → les autres postes ne la voient jamais |
| `experiment_iterations` | `iteration_runner._sync_canonical` (PUT `/iterations/{id}`) — **mais** silencieusement cassé : FK `cohort_id → experiment_cohorts` violée côté VPS tant que la cohorte n'a pas voyagé (push best-effort ⇒ échec avalé) | `GET /iterations?cohort_id=` (liste canonique multi-postes) vide |

Le run-batch (`/ingest/run`) les exclut **par conception** : tables dimension,
pas run-scopées. Le bon pattern est per-row idempotent, déjà incarné par
`recipe_routes` (dimension écrite direct au VPS) et `iteration_sync_routes`.

## 2. Cible (même modèle que les crops/décisions — Direction A)

```
Poste (Mac/PC), écriture lab locale
  └─ lab_routes / iteration_runner : write local (comme avant)
       └─ push best-effort → VPS canonique        [NOUVEAU pour cohorts,
            POST /ingest/cohort  (upsert par id)    réparé pour iterations]
            PUT  /iterations/{id} (existant, poussé APRÈS la cohorte)
VPS canonique
  └─ lectures front eurioApi (training-crops C3, GET /iterations) → à jour
  └─ réplique (sqlite3_rsync, ≤120 s) → les AUTRES postes voient la cohorte
```

- **Ordre parent→enfant** : toute poussée d'itération est précédée de la
  poussée de sa cohorte (FK `schema.sql:184`, `foreign_keys=ON` au VPS).
- **Idempotence** = UPSERT par clé naturelle `id` (pas d'outbox — retirées en
  C6c, cf. `schema.sql:958-976`).
- **Best-effort partout** : un VPS injoignable ne casse jamais une action lab
  locale (parité avec `_sync_canonical` existant). Le backfill rattrape.
- **Gating** : `client.http.remote_sync_enabled()` (nouveau, partagé) — vrai
  si `EURIO_API_URL` pointe un hôte distant. Même sémantique que le gate
  runner historique (`EURIO_ITERATION_PUSH` reste l'override itérations).

## 3. Pièces livrées

| Pièce | Fichier | Détail |
|---|---|---|
| Primitive upsert cohort | `ml/store/cohorts.py::upsert_cohort` | snapshot `ON CONFLICT(id) DO UPDATE`, préserve `created_at` source, miroir de `upsert_iteration` |
| Routes canoniques | `ml/serving/ingest_routes.py` : `POST /ingest/cohort`, `DELETE /ingest/cohort/{id}` | scope `ingest:write`, transaction pattern ingest, montées inconditionnellement (déjà dans l'image lean — `serving/`+`store/` copiés en entier) |
| Garde FK lisible | `ml/serving/iteration_sync_routes.py` | PUT d'une itération dont la cohorte est absente → **409** explicite (« pousse la cohorte d'abord ») au lieu d'un 500 FK opaque |
| DELETE itération canonique | `ml/serving/iteration_sync_routes.py` : `DELETE /iterations/{id}` | scope `ingest:write` (le lab local peut supprimer une itération) |
| Client push | `ml/client/ingest.py::push_cohort / push_cohort_delete / push_iteration_delete` | gated `remote_sync_enabled()`, no-op sinon |
| Ancrages cohort | `ml/serving/lab_routes.py` | helper best-effort appelé après create / update / delete / clone / add-coins / remove-coin / **auto-freeze** (`create_iteration`) |
| Ancrages itération | `ml/serving/iteration_runner.py` | `_sync_canonical` pousse **la cohorte puis** l'itération ; ajouté aux 2 transitions `_recover_orphans` qui ne poussaient pas ; exposé publiquement pour `lab_routes.update_iteration` / `delete_iteration` |
| Backfill | `ml/scripts/push_lab_dimensions.py` + `go-task ml:lab:push-dimensions` | pousse toutes les cohortes puis itérations locales (idempotent, `--dry`), rattrape l'historique et tout trou futur |
| Tests | `ml/tests/test_ingest_cohort.py`, extensions `test_iteration_sync_routes.py` / `test_iteration_canonical_push.py` | roundtrip/idempotence/scopes/ordre parent-enfant/409 FK/backfill |

## 4. Ce que F09 ne couvre PAS (assumé)

- `iteration_live_tests` / `iteration_aug_vs_real` (satellites) : consommées
  par la vue locale §I4d (mlApi), pas par une lecture canonique — restent
  locales. À réévaluer si une vue VPS en a besoin.
- Le **flip 1a** : F09 est une précondition de plus (sous le flip, les writes
  lab locaux devront router au canonique — les routes `/ingest/cohort`
  serviront de jumeaux). Le flip lui-même reste le chantier F02 §2.
- Conflits multi-postes simultanés : last-write-wins par `id` (deux postes
  éditant la même cohorte en même temps = cas non protégé, comme les recipes).

## 5. Déploiement & vérification

1. Déployer `eurio-api` (rebuild — `serving/`+`store/` sont copiés dans
   l'image, pas de changement Dockerfile).
2. `go-task ml:lab:push-dimensions` (backfill one-shot depuis le poste).
3. Vérifier : `GET /lab/cohorts/<nouvelle>/training-crops` (200), création
   d'une cohorte jetable côté lab local → visible au VPS sans action manuelle
   → suppression → disparue au VPS.
