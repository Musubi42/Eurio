# Decisions log — data-layer unification

> Décisions structurelles avec date, contexte, conséquences. Append-only.
> Chaque décision a un ID `D-NN-YYYY-MM-DD`.

## D-01-2026-06-19 — Dual frontend studio-local + admin-vps

**Contexte** : audit du codebase a révélé que `packages/web/` est le front
réel (heavy local) et `packages/panel/` (créé en C5) était une fausse
piste. Les contraintes mixed-content du browser interdisent à un site
HTTPS hosté de taper `localhost:8042` (ML API local).

**Décision** : deux frontends séparés.
- `admin/packages/studio-local/` (ex `packages/web/`) : heavy local sur
  Mac/PC, `pnpm dev :5173`, Bearer PAT
- `admin/packages/admin-vps/` (ex `packages/panel/`) : light hosted sur
  `eurio-admin.musubi.dev`, cookie OIDC, mobile-friendly, read-mostly +
  users/tokens

**Conséquences** : packages renommés (`git mv`), CLAUDE.md mis à jour avec
règle R0bis, `infra/eurio-admin/` créé.

## D-02-2026-06-19 — eurio-api = seule porte d'entrée data

**Contexte** : la donnée éditoriale a vécu en parallèle dans Supabase
(app-facing v2), `eurio.db` local Mac (leasé via MinIO) et VPS. Schémas
divergents.

**Décision** : SQLite VPS = source de vérité unique. Tout frontend (et
plus tard tout ML compute) tape `eurio-api.musubi.dev`. Supabase devient
mirror downstream uniquement pour l'app Android.

**Conséquences** : Phase 1 → Phase 6 du roadmap. Lease MinIO à tuer en
Phase 5.

## D-03-2026-06-19 — Heavy compute reste local, écrit via HTTP

**Contexte** : crops, scrape, training utilisent GPU/CPU local + I/O
disque rapide. Ne peuvent pas migrer sur VPS (1080 Ti, etc.).

**Décision** : le compute reste sur Mac/PC. Mais au lieu d'écrire dans
une DB locale, le code Python devient un client HTTP de `eurio-api`
(Phase 6). Aucune DB locale après cutover.

**Conséquences** : Phase 6 = gros refactor du ML pipeline. Latence
réseau à valider (un crop = 1-N appels HTTP au lieu d'un INSERT local).

## D-04-2026-06-19 — Friends-review feature deferred

**Contexte** : `packages/review/` (mini-app reviewer pour inviter des
potes) reste hors scope. Reviewer = uniquement toi pour l'instant.

**Décision** : on garde le package `review/` mais on n'investit pas
dedans cette refonte. Voir comment l'absorber dans `admin-vps` plus
tard (option α dans ARCHITECTURE-pivot doc 2026-06-19).

**Conséquences** : `packages/review-admin/` (la régie X-Admin-Token)
supprimée car obsolète avec Authentik. `packages/review/` conservé.
Container `eurio-review` (infra/review) continue à tourner sur image
existante.

## D-05-2026-06-19 — Phase 1 Supabase orphan tables : 404 silencieux

**Finding** : pendant Phase 1, audit a révélé que `coin_confusion_map`
et `sets_audit` **n'existent pas dans Supabase production**. Le schéma
"app-facing v2" Supabase (14 tables `coin`, `coin_image`, etc.) a évolué
sans ces tables. Le frontend studio-local faisait du 404 silencieux.

**Conséquence** : le refactor Phase 1 est autant un bug-fix qu'une
migration. Le script `migrate_orphan_supabase.py` reste comme outil
réutilisable mais ne fait rien aujourd'hui (source vide).

## D-06-2026-06-20 — Architecture layered backend (model / repo / service / router)

**Contexte** : les routers existants (`coins_routes.py`, etc.) sont des
"fat controllers" — SQL + business logic + Pydantic models + validation
HTTP dans un seul fichier de 1000+ lignes. Difficile à tester,
duplications, SQL inline.

**Décision** : pour les nouveaux domaines (sources Phase 2b et suite), on
adopte le pattern layered :
```
ml/serving/<domain>/
├── models.py     Pydantic schemas
├── repository.py SQL pur (sqlite3 stdlib)
├── service.py    Logique métier
└── router.py     FastAPI thin (validation, auth, mapping)
```

Spec dans `ARCHITECTURE.md`.

**Conséquences** :
- Phase 2b inaugurale du pattern (sources)
- Anciens fat-controllers refactorés progressivement (pas big-bang)
- Connexion DB centralisée via `serving/deps.py` (dependency FastAPI)
- Câblage explicite dans `server_serve.py` au lieu de `_CANDIDATES`
  (legacy)

## D-07-2026-06-20 — Documentation centralisée dans `data-layer-unification/`

**Contexte** : sujet large (vision + archi + phases + décisions + reprise).
Un seul gros markdown n'aide personne. La doc doit être facile à mettre
à jour en allant.

**Décision** : structure 5 docs par sujet :
- `VISION.md` — pourquoi + topologie cible
- `ARCHITECTURE.md` — comment écrire un endpoint
- `ROADMAP.md` — quoi + statut + sous-tâches
- `DECISIONS.md` — ce doc (chronologique, append-only)
- `HANDOFF-NEXT-SESSION.md` — reprise concrète, réécrit à la fin de chaque session

`README.md` reste comme entry point (hub).
`IMPLEMENTATION.md` original est superseded par cette structure
(à supprimer ou archiver).

## D-08-2026-06-20 — Sources : READ vers eurio-api, WRITE/TRIGGER restent local

**Contexte** : `sources_routes.py` (2552 lignes) a des imports lourds
au top du module (`cv2` via `sources._base.steps.*`). Impossible à
monter tel quel sur VPS lean.

**Décision** : on porte uniquement les endpoints **read-only** des
sources sur eurio-api (Phase 2b). Les endpoints write/trigger
(`POST /sources/{id}/runs`, retry-downloads, crop-pending) restent
côté ML local jusqu'à Phase 6 (refactor ML pipeline en client HTTP).

**Conséquences** :
- Studio-local sera en pattern hybride **assumé** pour les sources :
  lectures → `eurio-api`, triggers → `localhost:8042`
- Nouveau fichier `serving/sources/` créé from scratch (pas de copy
  de `sources_routes.py` legacy) suivant l'architecture layered
- L'ancien `sources_routes.py` continue de servir sur ML local pour
  les triggers, intouché jusqu'à Phase 6

## D-09-2026-06-20 — Sources status & detail : metadata statique côté eurio-api

**Contexte** : `sources_aggregator.build_status()` (630 lignes) agrège pour
`/sources/status` : registry métadata + quota live (Numista KeyManager,
eBay QuotaTracker) + delta prix (`ml/state/price_snapshots/*.json`) +
coverage (Supabase). L'image lean VPS ne livre pas `state/`, ni
`referential.numista_keys.KeyManager` (clés API non gérées côté serveur),
ni `shared.api_quota.QuotaTracker` côté tracker live.

**Décision** : Phase 2b porte une version **simplifiée** de `/sources/status`
et `/sources/{id}` côté `serving/sources/service.py` :
- registry statique reproduit en dur (labels, cli_hints,
  expected_cadence_days) — c'est la **même** liste que
  `sources_aggregator.SOURCES_REGISTRY`, sans la couche dynamique
- `temporal.last_run_at` / `last_run_kind` / `days_since_last_run` /
  `overdue` : computés depuis `source_runs` (data lives dans la DB
  canonique)
- `quota`, `temporal.delta`, `coverage` : laissés `null`/0 — le front a
  un mock fallback dans `MOCK_SOURCES_STATUS` qui prend le relais
  visuellement (sans crasher)
- `quota_groups`: dict vide, pour la même raison

**Conséquences** :
- Le dashboard SourcesPage est **fonctionnel** mais affiche un "—" pour
  les quotas live, deltas prix et coverage tant que ces couches n'ont
  pas migré
- Si jamais l'aspect "quota live Numista" devient critique : porter
  `referential.numista_keys.KeyManager` côté image lean (= ne dépend
  pas de PIL/cv2), exposer `/sources/numista/quota-status`
- L'endpoint `/source-runs/{run_id}/log` retourne `tail = "(log file
  not shipped to VPS …)"` car `ml/state/run_logs/` n'est pas livré dans
  l'image lean. À revisiter si tail-log devient un usage régulier
  (option : copier le répertoire ou exposer un endpoint de download)

**Pattern reproductible** : pour les prochains domaines (training, review),
préférer cette approche (constante en dur + compute DB) à un port littéral
du fat-controller — plus court à écrire, et le shape reste stable côté front.
