# local-sync — écritures locales à pleine vitesse, convergence sur le canonique

> **Statut : LIVRÉ (2026-07-03).** Architecture tranchée et implémentée dans la
> session double-write (suite directe de
> [`../model-b/local-canonical-double-write-HANDOFF.md`](../model-b/local-canonical-double-write-HANDOFF.md)).
> Reste : la migration bootstrap par machine (walkthrough) + calibrage du
> debounce à l'usage.

## Le problème (rappel d'une phrase)

Les décisions humaines (classification du Jeu d'entraînement, review, recrops
manuels) écrites dans le SQLite local Mac/PC n'atteignaient jamais le canonique
VPS → changer de machine perdait le travail ; et le write-through synchrone
(patron review lean) est inutilisable sur le chemin chaud du tri.

## L'architecture retenue — sync par event-log (option A du handoff)

```
   MAC (writer local)            VPS (hub de merge + writer review)      PC (writer local)
┌─────────────────────┐      ┌──────────────────────────────────┐   ┌─────────────────────┐
│ mutation = UPDATE   │ push │ POST /db/events/push             │   │ (symétrique du Mac) │
│  + event (op_id,    │─────▶│  dédup op_id → apply_remote      │◀──│                     │
│    machine, hlc)    │      │  (insère + matérialise)          │   │                     │
│  + sync_outbox      │ pull │ GET /db/events/pull?machine=…    │   │                     │
│ worker debounce 10' │◀─────│  events des AUTRES machines      │──▶│                     │
│ replay LWW-par-champ│      │  (y compris machine='vps')       │   │                     │
└─────────────────────┘      └──────────────────────────────────┘   └─────────────────────┘
```

- **Chemin chaud intact** : un clic = UPDATE local + INSERT event, même
  transaction, zéro réseau. La sync est asynchrone, par lots.
- **Append-only** : on n'écrase jamais un event ; la fusion de deux logs est
  une union. Le conflit n'existe qu'à la matérialisation, où il a une règle :
  **LWW-par-champ ordonné HLC** (la décision la plus récente fait foi,
  l'événement perdant reste dans le log — audit).
- **HLC** (`{ts_ms:013d}-{count:04d}-{machine}`) : ordre total causal stable
  malgré la dérive des horloges ; `hlc_merge` au pull garantit que « ma
  correction après avoir vu » bat ce que j'ai vu.
- **Le VPS est hub ET writer** : ses writes review (montés lean) sont stampés
  `machine='vps'` et redescendent aux machines via le filtre
  `machine != demandeur` du pull. Mode hub (`EURIO_SYNC_MODE=hub`) = il stampe
  mais n'alimente pas d'outbox.
- **Idempotence** partout par `op_id` (uuid) : re-push, re-pull, replay ×2 = no-op.
- **Tombstones** : `delete_crop` journalise la suppression AVANT le DELETE
  (le CASCADE emporte les events, pas le tombstone). Terminal : delete gagne.
- **Périmètre v1 (autoritatif humain)** : funnel classification + décisions
  review (y compris lot) + crops manuels + move-lane/requalify + dino-references
  + intruder-dismiss (best-effort). **Différés** : `correct_listing`, overlay
  `detections_json`. Les dérivés (verdicts scan, embeddings) se recomputent.
- **Le bulk reste `pull-replica`** : la sync event ne transporte que la couche
  autoritative ; les nouveaux scrapes remontent par `/ingest/run` et
  redescendent par un rebase réplique occasionnel (gardé : refuse si outbox
  pending).

## Décisions PO actées (2026-07-03)

1. **Sync automatique** — worker debounce dans le backend local :8042
   (`EURIO_SYNC_DEBOUNCE_S=600`), zéro sync si rien n'a changé, pull-only
   périodique pour les machines passives, + **bouton manuel** (badge sidebar).
   Plus de sync CLI comme workflow principal (`go-task ml:db:sync` = secours).
2. **Badge sidebar permanent** — pastille vert/orange/rouge + « il y a X min »
   + bouton ; hover → popover détail. Local-only.
3. **Rétention** — les ops poussées passent `pushed` dans `sync_outbox` et sont
   purgées au cycle réussi SUIVANT (marge d'un sync). **Le log d'audit
   `image_state_events` n'est jamais purgé.**
4. **Crops manuels = autoritatifs** — le binaire recroppé part sur la MÊME clé
   MinIO (partagée) ; seules les colonnes + un hint `cache_invalidate` voyagent.
5. **Bootstrap = sauver d'abord** — le travail local historique non poussé est
   rattrapé par `sync_bootstrap` (diff + events synthétiques) AVANT le seed.

## Les fichiers

| Couche | Fichiers |
|---|---|
| Fondation | `ml/store/hlc.py`, `ml/store/events.py` (stamping + outbox + tombstone), `ml/state/schema.sql` (§local-sync) |
| Replay | `ml/store/sync_replay.py` (`apply_remote`, LWW, orphelins) |
| Serveur | `ml/serving/sync_routes.py` (push/pull, lean+full), `ml/serving/sync_local_routes.py` (status/trigger), `ml/serving/sync_worker.py` |
| Client | `ml/client/sync.py` (cycle + CLI), `ml/client/sync_bootstrap.py`, `ml/client/replica.py` (garde) |
| Front | `shared/ui/SyncStatusBadge.vue`, `shared/api/sync-api.ts`, `features/sync/composables/useSyncQueries.ts` |
| Tests | `ml/tests/test_sync_{hlc,payloads,crop_events,replay,e2e,bootstrap}.py` (51 tests) |

Détail par couche : [`data-schema.md`](./data-schema.md) ·
[`backend.md`](./backend.md) · [`frontend.md`](./frontend.md) ·
[`walkthrough-tests.md`](./walkthrough-tests.md) (tests manuels PO).
