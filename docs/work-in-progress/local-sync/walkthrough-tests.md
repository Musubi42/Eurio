# local-sync — walkthrough de validation PO (Mac → VPS → PC)

> **Direction A (2026-07-04).** Le VPS est le SEUL `eurio.db` inscriptible.
> Mac/PC sont des clients replica+forward : lecture = réplique read-only tirée
> du VPS, écriture = POST direct vers l'API VPS (funnel/lot/crops/faces déjà
> déployés C2a/C2b/C3/C4). **Il n'y a plus de bootstrap par machine, plus
> d'event-log, plus d'outbox, plus de HLC** — ces concepts appartenaient à
> l'ancienne archi (sync par event-log), abandonnée et retirée (C6a/b/c). Voir
> [`migration-direction-a.md`](./migration-direction-a.md) pour le plan complet
> et [`README.md`](./README.md) pour le verdict d'échec de l'ancienne archi.
>
> Prérequis par machine : `direnv` chargé (`EURIO_API_URL` + `EURIO_API_TOKEN`
> exportés). **Où lancer les commandes** : depuis la racine du repo (ou
> n'importe quel sous-dossier — `go-task ml:*` remonte tout seul jusqu'au
> Taskfile racine). Les tasks `ml:*` tournent déjà dans `ml/` (`dir: ./ml`),
> donc les chemins relatifs comme `state/eurio.db` pointent sur
> `ml/state/eurio.db` sans qu'on ait à `cd`.

## Setup d'une machine (une fois, ~1 min — pas de bootstrap)

```bash
# Tire une réplique read-only fraîche depuis le VPS (snapshot VACUUM INTO,
# vérif sha). Écrase le fichier local — rien à perdre : le local n'est jamais
# un canonique, juste un cache de lecture.
go-task ml:db:pull-replica
```

C'est tout. Pas de dry-run, pas de `--from`, pas de rattrapage de décisions
locales : sous Direction A, une décision n'existe QUE si elle a été postée au
VPS (voir §Décision plus bas) — il n'y a donc jamais de « travail local non
poussé » à réconcilier avant de seeder.

## Phase 1 — Décision sur le Mac

1. `go-task ml:api` + front local (`pnpm dev`).
2. Dans le Jeu d'entraînement : exclure un crop du train (« Exclure »), ou
   accepter/réassigner une décision de review.
3. Le clic déclenche un `POST` direct vers l'API VPS (funnel/lot via
   `serving/funnel_writes.py` + `store/decisions.py`, recrops via
   `POST /ingest/crops`, faces via `POST /ingest/faces`). L'UI patch le cache
   local pour l'affichage immédiat (optimiste), mais **le canonique vrai est
   déjà sur le VPS** dès la réponse HTTP 200 — pas de cycle de sync différé à
   attendre.
4. **Vérif VPS** — la décision y est immédiatement :

```bash
ssh serverOimNixDontpanic 'docker exec eurio-api python -c "
import sqlite3; c = sqlite3.connect(\"/var/lib/eurio/eurio.db\")
r = c.execute(\"SELECT eurio_id, resolution_status, training_eligible FROM image_assets WHERE id=?\", (ASSET_ID,)).fetchone()
print(r)
"'
```

## Phase 2 — Reprise sur le PC

1. Tirer le repo (`git pull`).
2. `go-task ml:db:pull-replica` → simple rebase du cache local depuis le VPS.
   **La décision faite sur le Mac est déjà visible** (elle était déjà sur le
   VPS avant même que le PC ne tire) — pas d'étape de merge, pas de conflit
   possible : le VPS est le seul écrivain, il n'y a rien à réconcilier entre
   deux logs.
3. Modifier quelque chose côté PC (ex. réassigner un crop) → même POST direct
   au VPS. Retour Mac, `pull-replica` → la modif PC y est.

## Phase 3 — Bulk & compute lourd (recrops, pipeline ML)

- Le calcul lourd (GPU) reste local : `recrop_ebay_refine.py`,
  `recrop_lots_per_coin.py`, `recrop_review_score_guided.py`, le pipeline
  `sources/cli.py`, `recrop_cohort_census.py --coin --push` (C4a/b/c).
- Ces scripts lisent la réplique locale (pull-replica en amont), calculent en
  local, puis **poussent le résultat** via `POST /ingest/crops` /
  `POST /ingest/run` / `POST /ingest/dino` selon le cas — jamais un `UPDATE
  image_assets` local quand `EURIO_API_URL` est configuré (fallback Model A
  local seulement en dev, sans `EURIO_API_URL`).
- Vérif : lancer un recrop batch sur le Mac, `pull-replica` sur le PC → les
  nouvelles bbox/phash sont là, le PNG re-téléchargé depuis MinIO est à jour
  (hint `cache_invalidate` transporté par `/ingest/crops`).

## Invariants (ce qui doit rester vrai)

- **Un seul `eurio.db` inscriptible** dans tout le système : celui du VPS.
- Une décision faite sur n'importe quelle machine est visible partout **après
  un `pull-replica`**, sans étape de merge, sans conflit possible.
- Mac/PC n'ouvrent JAMAIS `eurio.db` en écriture (réplique read-only, C5) — le
  seul chemin d'écriture est un POST HTTP vers l'API VPS.
- Aucune matérialisation locale concurrente → aucune divergence possible par
  construction (fini le « même log, états différents » qui a motivé la
  migration — cf. `migration-direction-a.md` §1).
- Les migrations one-shot (`backfill_face.py`, `backfill_denom.py`,
  `backfill_quality_score.py`) sont VPS-only, gardées par
  `scripts/_vps_only_guard.py` (C7) — voir
  [`vps-only-migrations.md`](./vps-only-migrations.md).

## En cas de pépin

- Le POST échoue (réseau/401/422) → l'UI affiche l'erreur ; la décision n'est
  **pas** appliquée (pas de queue offline locale sous Direction A — le VPS est
  la seule source de vérité, pas de mode dégradé « décide en local puis
  rattrape »).
- API locale (:8042) down côté Mac/PC → aucune décision possible (le front
  parle à :8042 qui relaie au VPS) ; relancer `go-task ml:api`.
- Réplique locale qui semble périmée → `go-task ml:db:pull-replica` (jamais de
  garde « refuse si pending » : il n'y a plus d'outbox à perdre).
- Diagnostic canonique : lire directement `eurio.db` sur le VPS (cf. commande
  Phase 1) — c'est la seule vérité, pas de log à triangulaire entre machines.
