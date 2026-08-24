# ADR — Refacto `ml/` : jobs détachés, Store scindé, structure plate, DB cross-machine

> Statut : **acté** (2026-06-07). Décision issue de la session de cadrage (cf. [`kickoff.md`](./kickoff.md),
> [`README.md`](./README.md)). Suivi d'exécution : [`suivi.md`](./suivi.md).

## Contexte

`ml/` est un fourre-tout : un seul process FastAPI + ~106 scripts, un god-module `state/store.py`
(2705 lignes, 176 edges au graphe), et un `state/` qui mélange `eurio.db`, son schéma, le code d'accès
et des centaines d'artefacts de run. Cartographie graphify + lecture du code (2026-06-07) :

- **Pas de dette d'imports** : 1 seul cycle trivial (`sources/pricing/aggregate.py`). La dette est dans
  la **taille des modules** et le **god-node**, pas dans des dépendances circulaires → refacto incrémental sûr.
- **Trois mécanismes de jobs incohérents** face au hot-reload `uvicorn --reload` :
  | Runner | Détaché | PID persisté | Survit reload |
  |---|---|---|---|
  | Cohort recrop (`lab_routes.py:1923`) | `start_new_session=True` ✅ | `cohort_jobs.pid` ✅ | **Oui** ✅ |
  | `training_runner` (`:587`) | ❌ | ❌ | **Non** ❌ |
  | `iteration_runner` (`:1175`) | ❌ | ❌ | **Non** ❌ |
  Le pattern cohorte est **déjà la bonne réponse, éprouvée**. La douleur n°1 (jobs tués au save) vient
  des deux runners qui ne s'y sont pas encore ralliés.
- **`eurio.db` est écrit par les DEUX machines** mais sur des **tables disjointes** : Mac écrit
  cohort/captures/crops/référentiel, PC écrit `runs/epochs/steps` (`training_runner.py:218-275`). Workflow
  **séquentiel dans le temps** (prép cohorte Mac → entraîne PC → review Mac). `training.db` est un vestige.
- Les communautés graphify recoupent nettement les domaines : `sources` (C3/C12), `vision`/crop (C4),
  `training`/augment/eval (C9/C10), `review`/référentiel (C11), `serving` (api/).

## Décisions

### D1 — Job runner unifié `jobs/` (généraliser le pattern cohorte)
Extraire le mécanisme prouvé du recrop cohorte en un module **générique, domaine-agnostique** `ml/jobs/` :
- table **`jobs`** générique (id, kind libre, status, pid, n_total/n_done, started_at/finished_at, error,
  note, log_path, `params` JSON pour le payload domaine) — **additive**, coexiste avec `cohort_jobs`.
- **lanceur détaché** : `subprocess.Popen(start_new_session=True, stdout=<log fichier>)` → survit au reload,
  hors du groupe de signaux du worker, sort torch/MPS du process API.
- **reaper boot** générique : `os.kill(pid, 0)` + garde anti-runtime, marque les orphelins `failed`.
- l'API redevient **mince** : `enqueue` + `lire le statut`, jamais de logique de job dans le thread serving.
- les logs jobs sortent **sur disque/table** (déjà le cas cohorte via `state/job_logs/`), l'API ne fait que lire
  — on supprime le couplage `for raw in proc.stdout` du thread API.

Migration **un runner à la fois** (auditable) : `training` → `iteration/scrape` → **+ nouveau runner `augmentation`**.

**Worker maison confirmé** (pas de Dramatiq/RQ/broker) : le mécanisme existe déjà sans infra, cohérent zero-infra.

### D2 — `Store` scindé, `eurio.db` unique conservé
Un seul `eurio.db` (doctrine SQLite-only). Un seul **fichier de connexion** (`store/connection.py` — pool WAL,
`isolation_level=None`/autocommit, PRAGMA — déjà correct). Les 2705 lignes éclatées en **modules de requêtes
par domaine** partageant la connexion : `store/cohort.py`, `store/sources.py`, `store/review.py`,
`store/training.py`, `store/jobs.py`, … Chaque module testable en isolation ; refacto d'une requête sans tout casser.

### D3 — Structure `ml/` plate par domaine (façon packages pnpm)
Dossiers **directement sous `ml/`** (pas de `src/eurio_ml/` — superflu pour un projet mono-app) :
```
ml/store/  sources/  vision/  training/  review/  jobs/  serving/  shared/  scripts/  tests/
```
- `vision/` absorbe `scan/` (+ crop/detect/normalize/census) ; `training/` absorbe `augmentations/`+`eval/`+`foundation/` ;
  `serving/` = ex-`api/` (FastAPI mince) ; `shared/` = config/paths/device-resolve/utils.
- Le crop↔review entremêlé (C4) se tranche : **crop = `vision/`, édition/review = `review/`**.
- **Règles de couplage (R0)** : `serving/` n'appelle que les domaines + `jobs/`, zéro métier ; les domaines ne
  s'importent pas horizontalement → ils passent par `store/` ou `jobs/`. C'est ce qui garde chaque package testable seul.
- Les modules neufs (`jobs/`, `store/`) sont créés **directement à leur emplacement final plat** → la restructure
  finale ne déplace que les dossiers legacy.

### D4 — Cross-machine : ~~libSQL / Turso `sqld`~~ → **lease MinIO** (révisé 2026-06-08)

> **RÉVISION (chunk 6)** : libSQL est **abandonné** à l'implémentation. Vérification
> du client Python `libsql-experimental` (0.0.55, juin 2025, toujours *experimental*) :
> `row_factory`/`sqlite3.Row` (118+79 usages), `create_function` (nos UDFs phash,
> [issue #7 ouverte](https://github.com/tursodatabase/libsql-experimental-python/issues/7))
> et `executescript` (bootstrap `schema.sql`) sont **tous non implémentés**. Le swap
> driver « 1 fichier » devient un shim permanent fragile = dette (viole R0).
> **Décision retenue : modèle lease sur MinIO** (l'option « lease » ci-dessous,
> initialement rejetée pour MinIO, est en fait le bon compromis vu l'immaturité du
> client). `eurio.db` canonique dans le bucket `eurio-db` ; verrou atomique
> `PutObject(IfNoneMatch='*')` ; pull→travail `sqlite3` **stock** (zéro perte de
> compat, `store/connection.py` inchangé)→push. Manuel (acquire/release explicites,
> steal manuel au crash ; le startup API ne fait qu'avertir). Implémenté dans
> `ml/store/lease.py` (+ `go-task ml:db:{status,acquire,release,steal}`) ; provisioning
> serveur dans [`chunk6-vps-minio.md`](./chunk6-vps-minio.md). Le split chunk 5 reste
> la bonne fondation (la couture cross-machine vit près de la connexion).
>
> _Texte d'origine conservé ci-dessous pour mémoire._

#### (Décision initiale, supersédée) libSQL / Turso `sqld` (pôle robuste, d'emblée)
On **ne** passe **pas** par un lease MinIO. `sqld` (libSQL) tourne sur le **VPS** = copie autoritaire unique.
Chaque machine = **embedded replica** : lecture locale rapide (sync auto), écritures envoyées au primaire et
**sérialisées côté serveur** → écritures disjointes Mac/PC sans collision, même simultanées. Pas de drift,
pas de merge binaire, pas de SQLite sur FS réseau (anti-pattern corruption).
- Swap driver `sqlite3 → libsql` **localisé dans `store/connection.py`** (un seul endroit) — D2 le prépare.
- Rejetés : commit DB dans Git (binaire 66 Mo, zéro merge), DB montée NFS/SMB (locking cassé → corruption),
  lease MinIO (correct mais checkout unique, moins propre que le vrai client-serveur).

## Conséquences
- L'exigence n°1 (jobs survivent au reload) est réglée dès D1, **à code-iso**, sans toucher aux frontières.
- D2 prépare D4 (driver swap = 1 fichier). D3 range sans rien casser (pas de cycles à défaire).
- Le `state/` dépotoir est nettoyé en passant (artefacts de run hors du module code).

## Questions ouvertes
- `cohort_jobs` : à terme, le fondre dans la table `jobs` générique (vue/spécialisation), ou le garder séparé ?
  → reporté ; les deux coexistent tant que la migration des runners n'est pas finie.
- `sqld` sur VPS : docker natif (comme MinIO) ou systemd ? schéma de migration eurio.db → primaire libSQL.
- Granularité lease/replica plus fine par domaine (tables disjointes) : **ne pas sur-concevoir** pour 2 machines.

## Doctrine
R0 (le refacto *réduit* la dette, pas la déplace), chunks 30 min–3 h livrés + audités
([`feedback_chunk_audit_flow`]), vérifier sur le code pas les docs.
