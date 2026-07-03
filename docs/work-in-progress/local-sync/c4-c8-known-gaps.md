# Direction A C4–C8 — gaps connus (à fermer avant de clore la migration)

> Livré par le workflow `wf_6cfbad4f-9c3` (C4→C8), committé, tests verts
> (1322 pass / 18 reds préexistants), lean-safe, front typecheck OK. La
> CodeReview a surfacé 2 MAJOR non-bloquants + 1 chunk partiel. **Tracés ici,
> pas cachés** — à traiter dans une session de durcissement.

## MAJOR 1 — Les suppressions ressuscitent (split résiduel sur delete)

`serving/crop_edit.py::delete_crop` ne propage plus la suppression au VPS.
C6 a retiré le tombstone/outbox (seul mécanisme de propagation de delete), et
C4d a câblé le forward `/ingest/crops` pour le RECROP mais **pas** pour le
delete. Sous Direction A, un delete sur le Mac ne mute que la réplique locale →
le prochain `pull-replica` écrase le local avec la copie VPS et le crop
**réapparaît**. `delete_crop` est atteignable via `review_queue_routes.py`
(pruning de crops surnuméraires) en studio local.

**Fix** : ajouter un transport de suppression canonique (ex.
`DELETE /ingest/assets/{id}`) et forwarder depuis `delete_crop` quand
`sync_enabled()` (miroir du forward recrop) ; OU documenter delete hors-scope et
le bloquer en mode client Direction-A. (L'inventaire §4 du plan n'a jamais listé
`delete_crop` — write-path révélé par le retrait de l'event-log.)

## MAJOR 2 — C5 read-only pas réellement appliqué

Le mode read-only (`store/connection.py`) + `resolve_db_readonly()`
(`store/__init__.py`) sont ajoutés ET testés (`test_store_readonly.py`), mais
**aucun Store applicatif n'est construit en read-only** → l'invariant §7
« Mac/PC lisent, n'écrivent jamais » est plombé mais pas branché. C5 est en
réalité « infra posée, pas enforced ».

**Fix** : brancher `resolve_db_readonly()` sur les Store côté compute/funnel
Mac/PC (mode client), en laissant le VPS en écriture. Vérifier qu'aucun chemin
de lecture ne tente un write (sinon `sqlite3.OperationalError: readonly db`).

## PARTIAL — C4d (ingest/dino)

`POST /ingest/dino` + `store/dino.py` ajoutés et testés (rescore Dino
client-side → VPS), mais le chunk est revenu `partial`. À reprendre : confirmer
que TOUS les écrivains de prédictions Dino (recrop manuel, review score-guided,
backfill) forwardent bien via `/ingest/dino` et qu'aucun `UPDATE
image_asset_dino_predictions` local ne subsiste hors fallback dev.

## Non déployé sur le VPS

C4–C8 est committé mais **PAS déployé** sur le VPS (le canonique tourne encore
en C3 = `12a04e9`, sain). Le deploy de C4–C8 touche le schéma (retrait colonnes
sync de `image_state_events`) et retire les endpoints `/db/events` + le worker —
à faire dans une session dédiée, après les 2 fix MAJOR, avec health-check.
Runbook deploy : `cd infra/eurio-api && direnv exec /opt/eurio docker compose up
-d --build` (sops via direnv).

Voir aussi `friction-log.md` (21 items de friction transverses).
