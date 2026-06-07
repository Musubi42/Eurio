# Refacto ML — kickoff de session

> À coller / ouvrir au début d'une session dédiée. But de la session : **discuter les stratégies**
> de refacto de `ml/` (pas coder tout de suite). Lis [`README.md`](./README.md) d'abord (la vision).

## Ce qu'on veut sortir de la 1re session

Une **décision d'architecture** (ADR) sur :
1. Comment isoler les **jobs longs** du cycle de vie de l'API (exigence n°1 : reload sans tuer les jobs).
2. Le **découpage en services/domaines** de `ml/` (frontières, qui parle à qui).
3. Faut-il **dockeriser**, et quoi.
4. L'ordre d'exécution (par chunks, façon doctrine `feedback_chunk_audit_flow`).

## Exigence n°1 en détail — le hot-reload tue les jobs

Aujourd'hui : `uvicorn --reload` surveille `ml/` ; tout `save` relance le process → un scrape / crop /
training en cours **meurt**. Inacceptable quand on code le back-end tout en faisant tourner des jobs.

**Piste forte (déjà éprouvée dans le repo)** : le recrop cohorte a migré d'un *thread daemon en mémoire*
(qui mourait avec le process) vers un **subprocess détaché** possédant son entrée `cohort_jobs`, avec
**reaper par `pid`** (cf. memory `project_cockpit_rebuild`, commit `c69ff22`). Généraliser ce pattern :
- une table `jobs` (type, params, statut, pid, ts, progression) — `cohort_jobs` est déjà un embryon,
- un **worker** (process séparé) qui exécute, l'API ne fait qu'`enqueue` + lire le statut,
- l'API redevient **stateless et rechargeable** sans impact sur les jobs.

À débattre : worker maison (poll de la table) vs. task queue (Dramatiq/RQ). La doctrine zero-infra
(`user_raphael`, `feedback_nix_devshell`) penche vers le **maison** (zéro broker), à confirmer.

## Questions ouvertes à trancher (matière à discussion)

- **Frontières de service** : `sources` / `vision(crop+detect)` / `training(augment+train)` / `review` /
  `serving(API)` — est-ce le bon découpage ? Où vivent `foundation/` (DINO) et `Store` (god node) ?
- **`Store`** (176 edges) : faut-il le casser en accès par-domaine, ou rester un seul gateway DB ?
- **eurio.db** : un seul fichier SQLite partagé entre services — OK en local, mais concurrence d'écriture
  si workers parallèles ? (WAL, isolation — cf. `feedback_store_autocommit_unique`).
- **Docker ou pas** : isole les cycles de vie + reproductible, mais ajoute de la complexité face au Nix
  actuel. Conteneuriser seulement le worker ? l'API ? MinIO est déjà en docker natif côté VPS.
- **Périmètre** : refacto à code-iso (juste réorganiser + job runner) d'abord, ou en profiter pour
  régler la dette (cycles d'import, couplage) ?

## §Indexation — graphify + LLM, ou structure seule ?

**Recommandation : la structure (AST) seule suffit pour DÉMARRER.**
- `ml/` est du **code** → l'AST graphify le couvre déjà entièrement (functions, classes, calls, imports).
  Les **god nodes** (couplage), **communautés** (frontières de service candidates) et **cycles d'import**
  (dette) — tout ce dont un refacto a besoin — sont déjà là dans `graphify-out/graph.json`.
- Commandes utiles en session : `graphify explain "Store"`, `graphify query "qui appelle detect_crop"`,
  `graphify path "sources_routes" "Store"`, et le `GRAPH_REPORT.md` (god nodes + cycles).
- **Une passe sémantique LLM sur `ml/` n'apporterait que le « pourquoi »** (rationale des docstrings/READMEs).
  Utile *plus tard*, ciblée sur un sous-module qu'on n'arrive pas à comprendre — **pas un pré-requis**.
  Coût ≈ celui d'une passe sous-agents ; à ne lancer que si la structure ne suffit pas à décider.

→ Donc : **on part sur graphify structurel** (déjà construit), on cartographie le couplage, on dérive
les frontières des communautés. Semantic LLM = option de secours ciblée.

## Posture
- Doctrine R0 (pas de dette) : le refacto doit *réduire* la dette, pas la déplacer.
- Chunks 30 min–3 h, livrer + audit (`feedback_chunk_audit_flow`).
- Vérifier sur le code, pas sur les docs (leçon 2026-06-07 : les docs ml/ sous-déclarent la réalité).
- Pré-requis avant gros refacto : le **découplage scrape↔crop** (`roadmap.md` #13) est un bon premier chunk.

## Memories liées
`project_cockpit_rebuild` (pattern subprocess/cohort_jobs), `feedback_store_autocommit_unique`,
`feedback_architecture_eurio_db_vs_supabase`, `project_admin_workspace`, `feedback_nix_devshell`,
`project_graphify_doc_hygiene`.
