# local-sync — backend

> **⚠️ ARCHIVÉ (2026-07-04).** Décrit l'infra event-log (émission/replay/hlc),
> retirée en C6a/b/c au profit de Direction A (writer canonique unique VPS,
> pas de merge). Conservé comme archive du raisonnement. Voir
> [`migration-direction-a.md`](./migration-direction-a.md) et le nouveau
> [`walkthrough-tests.md`](./walkthrough-tests.md).

## Émission (chemin chaud, zéro réseau)

`ml/store/events.py::emit_state_event` stampe chaque event (`op_id`, `machine`,
`hlc`) et l'enfile dans `sync_outbox`, dans la transaction du caller. Deux
helpers au-dessus :
- `emit_field_event(...)` — self-transition porteuse de `fields` (mutations de
  colonnes sans changement d'état : flip eligible, reassign, recrop, lane…).
- `record_tombstone(...)` — à appeler AVANT un DELETE d'asset (le CASCADE
  emporte les events, pas le tombstone).

Mode hub (`EURIO_SYNC_MODE=hub`, VPS) : stampe mais n'enfile pas.

## Endpoints canonique (`ml/serving/sync_routes.py`, lean + full, scope `ingest:write`)

```
POST /db/events/push   {machine, events[], tombstones[]}
  → 1 tx BEGIN IMMEDIATE : apply_remote (dédup op_id, tombstones d'abord,
    matérialisation LWW) → {accepted[], orphaned[], server_hlc, stats}
  Le client ne marque `pushed` QUE les accepted ; les orphaned (asset inconnu
  du canonique — run pas encore ingéré) restent pending et reviendront.

GET /db/events/pull?machine=&since_hlc=&limit=500
  → events + tombstones hlc > since, machine != demandeur, ORDER BY hlc.
  Pagination : curseur = hlc du dernier event de page (has_more) ; tombstones
  bornés à la même fenêtre ; doublons inter-pages absorbés par l'idempotence.
```

## Replay (`ml/store/sync_replay.py::apply_remote`)

1. rejoue les orphelins parkés dont l'asset est apparu ;
2. tombstones (terminal — delete gagne, DELETE + CASCADE, purge des orphelins
   du même asset) ;
3. events : skip op_id connu / asset tombstoné ; row_ops appliqués (dont le
   snapshot add-crop qui CRÉE la row) ; asset toujours inconnu → parké ;
   sinon INSERT **verbatim** (op_id/machine/hlc/created_at d'origine, id
   autoinc local, PAS d'entrée outbox → pas d'écho) ;
4. matérialisation par asset touché : relecture de TOUS ses events porteurs de
   `fields`, `ORDER BY (hlc IS NOT NULL), hlc, created_at, id` → dernière
   valeur par `table.colonne` gagne (le résultat ne dépend pas de l'ordre
   d'arrivée des lots) ; SQL direct (ne re-traverse ni `_LEGAL_TRANSITIONS`
   ni le CHECK actor) ;
5. rebuild `image_state_current` hlc-ordered ;
6. `hlc_merge(max hlc reçu)` — causalité.

## Cycle client (`ml/client/sync.py::run_sync_cycle`)

push par lots de 500 (events + tombstones joints via l'outbox ; ops obsolètes
soldées) → pull paginé depuis `sync_state.pull_cursor_hlc`, chaque page
appliquée dans sa transaction → purge `pushed` d'avant le début du cycle
(marge PO d'un cycle complet) → `sync_state.last_*`. Sans `EURIO_API_URL`
explicite, la sync est désactivée (on ne pousse jamais vers le défaut
localhost). CLI de secours : `go-task ml:db:sync`.

## Worker (`ml/serving/sync_worker.py`, thread démon, startup hook `server.py`)

- réveil toutes les 30 s ; cycle si `age(plus ancien pending) ≥
  EURIO_SYNC_DEBOUNCE_S` (600) — latence bornée, zéro réseau si rien n'a changé ;
- pull-only périodique à la même cadence (machine passive = reçoit quand même) ;
- `trigger()` immédiat (`POST /sync/trigger`, bouton badge) ;
- backoff 60→900 s après échec (offline : l'outbox tamponne) ;
- `--reload` tue/relance le thread avec le process — inoffensif, tout l'état
  vit dans `sync_outbox`/`sync_state`. `GET /sync/status` expose
  `idle|pending|syncing|ok|error|disabled` + compteurs.

## Interactions avec l'existant

- **`/ingest/run`** : `export_run` fait `SELECT *` → op_id/machine/hlc voyagent
  aussi par les run-batches ; l'ingest (DELETE-par-run_id + réinsertion) reste
  cohérent (mêmes op_id) et le dédup absorbe la double-livraison.
- **`pull-replica`** : reste le canal BULK (nouveaux scrapes). Gardé : refuse
  d'écraser un fichier avec des ops pending (`--force` pour outrepasser).
- **Bootstrap one-shot** : `go-task ml:db:sync-bootstrap` (dry-run) puis
  `-- --apply` — cf. walkthrough.

## Config

| Var | Défaut | Rôle |
|---|---|---|
| `EURIO_API_URL` | (absent → sync désactivée) | cible du push/pull (VPS) |
| `EURIO_API_TOKEN` | — | PAT bearer (scope ingest:write) |
| `EURIO_SYNC_DEBOUNCE_S` | 600 | latence max avant push + cadence pull-only |
| `EURIO_MACHINE_ID` | généré (`<host≤11>-<4hex>`) | identité HLC ; `vps` sur le VPS |
| `EURIO_SYNC_MODE` | (absent) | `hub` sur le VPS : stampe sans outbox |
