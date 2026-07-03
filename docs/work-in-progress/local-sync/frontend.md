# local-sync — frontend (badge sidebar)

## Composants

- **`src/shared/ui/SyncStatusBadge.vue`** — bloc fixé en bas de sidebar, entre
  la nav et la zone identité (`AppLayout.vue`). Gated `caps.hasLocalMlApi`
  (absent en hébergé : le worker n'existe que sur :8042 local). Mode
  `collapsed` = pastille seule.
- **`src/shared/api/sync-api.ts`** — `fetchSyncStatus` / `triggerSync` sur
  `ML_API` (:8042). PAS `eurioApi` : le statut concerne le worker de CETTE
  machine.
- **`src/features/sync/composables/useSyncQueries.ts`** — vue-query :
  `useSyncStatusQuery` (poll 30 s, 5 s pendant une sync),
  `useTriggerSyncMutation` (invalide le statut en settled).

## États visuels

| state | Pastille | Ligne |
|---|---|---|
| `ok` | ● vert | « Sync il y a X min » |
| `pending` | ● vert | « N en attente » (la sync viendra — pas une anomalie) |
| `syncing` | ● orange + halo, bouton en spinner | « Synchronisation… » |
| `error` | ● rouge | « Sync en échec » (détail au hover) |
| `disabled` | ● gris | « Sync désactivée » (EURIO_API_URL absent) |

Bouton `RefreshCw` = `POST /sync/trigger` (désactivé pendant une sync).
Popover au hover (pattern maison `group`/`group-hover` + `absolute`, pas de
lib) : machine, dernier sync, N en attente, compteurs push/pull, erreur
éventuelle, bouton « Synchroniser maintenant ».

## Cas d'usage cible

Fin de session Mac → un œil au badge (vert ? tout est parti) ou clic sur le
bouton → passage au PC → badge vert après le premier pull → même état partout.
