# Direction A C4–C8 — gaps connus (à fermer avant de clore la migration)

> Livré par le workflow `wf_6cfbad4f-9c3` (C4→C8), committé, tests verts
> (1322 pass / 18 reds préexistants), lean-safe, front typecheck OK. La
> CodeReview a surfacé 2 MAJOR non-bloquants + 1 chunk partiel.
>
> **✅ FERMÉS le 2026-07-04 (session de durcissement)** — les 3 sections
> ci-dessous sont gardées pour l'historique, chacune annotée de son fix.
> Suite de tests après fix : 1331 pass / mêmes 18 reds préexistants (0 régression).

## MAJOR 1 — Les suppressions ressuscitent (split résiduel sur delete) — ✅ FERMÉ

**Fix appliqué (2026-07-04)** : route `DELETE /ingest/assets/{id}` (scope
`ingest:write`, idempotent, cascade FK — `store/crops.py::apply_delete_assets`,
SQL-pur lean-safe) + client `client/ingest.py::push_delete_asset` + forward
depuis `delete_crop`. Contrairement au forward recrop (best-effort : la
géométrie est recomputable), le forward delete est **bloquant** : si le
canonique ne confirme pas, `delete_crop` lève 502 et NE supprime PAS localement
(un delete non propagé ressusciterait — c'est précisément ce bug). Sur le VPS
(sync désactivée), le delete local est le canonique. Tests :
`test_ingest_crops.py` (route ×4) + `test_sync_crop_events.py` (forward ×2).

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

## MAJOR 2 — C5 read-only pas réellement appliqué — ✅ FERMÉ (câblé, opt-in)

**Fix appliqué (2026-07-04)** : `StoreBase.__init__` résout désormais
`EURIO_DB_READONLY` par défaut — TOUT Store construit sans `read_only`
explicite l'honore (un seul point de câblage, pas ~40 call-sites). Le writer
canonique `serving/server_serve.py` passe `read_only=False` explicite (immunisé
contre le flag). `backfill_dino_predictions --push` ouvre sa réplique scratch
en `read_only=False` explicite (elle est un espace de travail, pas le cache
machine). Tests : `test_store_readonly.py` ×3 nouveaux.

**Limite assumée (décision ops, pas code)** : poser `EURIO_DB_READONLY=1` sur
Mac/PC casserait aujourd'hui les écritures locales LÉGITIMES qui partagent
`eurio.db` (overlay dismiss intrus C3, `cohort_jobs`, progression
training/scan, runs d'entraînement). Le flag reste donc **off par machine**
tant que cet état local n'est pas séparé du cache réplique — à trancher PO
(split fichier local-state vs tables overlay tolérées). L'invariant « aucun
write canonique local » est lui déjà tenu par le routage C2–C4 (+ delete
ci-dessus).

Le mode read-only (`store/connection.py`) + `resolve_db_readonly()`
(`store/__init__.py`) sont ajoutés ET testés (`test_store_readonly.py`), mais
**aucun Store applicatif n'est construit en read-only** → l'invariant §7
« Mac/PC lisent, n'écrivent jamais » est plombé mais pas branché. C5 est en
réalité « infra posée, pas enforced ».

**Fix** : brancher `resolve_db_readonly()` sur les Store côté compute/funnel
Mac/PC (mode client), en laissant le VPS en écriture. Vérifier qu'aucun chemin
de lecture ne tente un write (sinon `sqlite3.OperationalError: readonly db`).

## PARTIAL — C4d (ingest/dino) — ✅ FERMÉ (inventaire complet)

**Audit + fix (2026-07-04).** Inventaire des écrivains de
`image_asset_dino_predictions` :
- `predict_and_persist_kinds` (recrop manuel, add-crop, sync-crops, review
  score-guided) → forwarde `/ingest/dino` ✅ (déjà fait C4d).
- `_run_inner`/`_flush` (pipeline scrape) → voyage dans `/ingest/run`
  (`image_asset_dino_predictions` est dans `_TABLE_ORDER` de
  `client/runbatch.py`) ✅.
- `scripts/backfill_dino_predictions.py` → **fixé** : `--push` devient le
  DÉFAUT quand `EURIO_API_URL` est configurée (même bascule que
  l'orchestrateur C4c), `--no-push` = échappatoire dev Model A explicite.
- `backfill_face.py`/`backfill_denom.py` (UPDATE colonnes dino brutes) →
  refusent de tourner en mode client (garde C7 `_vps_only_guard`) ✅.
- `store/dino.py::apply_ingest_dino` → write-half serveur, hors-scope ✅.

Reste le point 12 du friction-log (gates qualité `gate_standard_vision`/
`bench_routes` → décision produit `apply_reject`), hors périmètre C4d dino.

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
