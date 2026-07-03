# Migration Direction A — writer canonique UNIQUE (VPS)

> **Statut : PLAN, rien codé (2026-07-03).** Fait suite au verdict d'échec de
> l'event-log (`README.md` §« ne converge pas ») et à la décision PO du
> 2026-07-03. À faire valider chunk par chunk AVANT implémentation (doctrine
> chunk-by-chunk + zéro-dette). Remplace l'archi event-log de ce dossier.

## 1. Le verdict qui motive la migration (preuve, pas opinion)

Diagnostic triangulé Mac / VPS / PC sur
`at-2005-2eur-50th-anniversary-of-the-austrian-state-treaty` :

| | crops | train-elig | needs_review | rejetés | outbox |
|---|---|---|---|---|---|
| **Mac** | 273 | 91 | 65 | 106 | vide |
| **VPS canonique** | 252 | 100 | 42 | 106 | (hub) |
| **PC** | 252 | 100 | 42 | 106 | vide |

Les **trois machines ont le MÊME log d'events** (11 698 legacy `machine=NULL`
+ 3 PC + 207 Mac), **outbox vide**, **dernier sync vert** — et pourtant le Mac
matérialise un état différent. **Rejouer le même log donne un résultat
différent selon la machine.** Deux causes structurelles :

1. **Le bulk ne voyage pas.** Diff des IDs de crops : 21 crops Mac-only
   (17 `needs_review` + 4 `auto_phash`), 0 VPS-only, 252 partagés. L'event-sync
   transporte des décisions-sur-lignes, jamais l'existence d'une ligne.
2. **Log partiel.** Sur les 252 crops partagés, le Mac matérialise 90 train /
   48 review, le VPS 100 / 42 — parce que des écrivains **hors-event** ont muté
   `image_assets` sans laisser de trace rejouable.

## 2. Pourquoi « compléter les events » ne peut PAS marcher

Un event-log ne peut posséder proprement une colonne que si cette colonne a
**un seul écrivain**. Or **chaque colonne autoritative a des écrivains eventés
ET non-eventés**, par design (inventaire §4). Compléter les events serait :

- **Du whack-a-mole permanent** : chaque nouveau chemin d'écriture rouvre la fuite.
- **Contre-productif** : les colonnes dérivées (`face`, `denom`,
  `resolution_status` auto, `training_eligible` de gate) sont **recalculées**
  localement par la pipeline ML. Les eventer ferait s'entre-écraser les
  machines (l'auto-validation du Mac écraserait celle du PC via LWW), alors que
  la doctrine actuelle dit déjà « les dérivés se recomputent ».

**Conclusion** : le zéro-décalage ne vient pas d'une couverture d'events
exhaustive. Il vient de **supprimer la seconde copie inscriptible**. Sous writer
unique, `face`/`denom`/`resolution`/`training_eligible`/`bbox` sont calculés et
stockés à **un seul endroit** ; tout le monde lit les mêmes valeurs ; le
problème d'appartenance de colonne **disparaît**.

## 3. Cible architecturale

```
   MAC / PC (compute + UI, AUCUN canonique inscriptible)      VPS (writer UNIQUE)
┌──────────────────────────────────────────────────┐     ┌────────────────────────┐
│ Lecture  : réplique READ-ONLY (pull-replica /       │ GET │ eurio.db canonique     │
│            endpoints read VPS)                      │◀────│  = SEULE copie          │
│ Décision : POST /… vers l'API VPS                   │ PUT │    inscriptible         │
│  (UI optimiste : patch d'affichage local, PAS un    │────▶│  applique en ordre      │
│   canonique ; réconcilié au prochain pull)          │     │  (pas de merge LWW)     │
│ Bulk/ML  : compute local → POST résultats /ingest   │────▶│                         │
│  (GPU Mac/PC ; le VPS n'a pas de GPU)               │     │                         │
└──────────────────────────────────────────────────┘     └────────────────────────┘
```

Principes :

- **Aucune machine n'ouvre `eurio.db` en écriture** sauf le VPS. Mac/PC : replica
  read-only + forward HTTP.
- **Le VPS applique les writes dans l'ordre de réception** (writer unique
  sérialisé) — pas de LWW-par-champ, pas de matérialisation concurrente, donc
  **pas de divergence possible**.
- **UI optimiste = couche d'affichage**, jamais un canonique. Un clic patche le
  cache local pour le rendu immédiat + enfile un forward ; l'état vrai revient au
  prochain pull. Le chemin de tri reste rapide sans seconde source de vérité.
- **Le compute lourd reste local** (contrainte : VPS no-GPU, cf.
  [[deployment-topology]]) mais **écrit au VPS via l'API**, pas en local.

## 4. Inventaire des écrivains de `image_assets` (le cœur du zéro-dette)

Tout écrivain doit avoir une disposition explicite sous Direction A. Aucun ne
reste un `UPDATE image_assets` local hors-VPS.

| Fichier | Colonnes | Catégorie | Émet auj. | Disposition sous A |
|---|---|---|---|---|
| `review/review_queue_routes.py` | eurio_id, face, phash, quality_reason, resolution_status, training_eligible | décision humaine | Y | **→ write API VPS** (la route tourne déjà côté serveur en mode lean ; garantir qu'en local elle POST au VPS) |
| `review/peer_arbitration_routes.py` | idem + | décision humaine | Y | → write API VPS |
| `serving/review_queue/writes.py` | idem | décision humaine | Y | → write API VPS |
| `serving/lab_routes.py` | eurio_id, quality_reason, resolution_status, training_eligible | décision humaine (funnel) | Y | → write API VPS (chemin chaud : write-behind) |
| `serving/coin_assets_routes.py` | eurio_id, resolution_status | décision humaine | Y | → write API VPS |
| `serving/crop_edit.py` | bbox_json, detection_method, dims, phash, storage_status | recrop manuel | Y | → write API VPS (bulk : le PNG part sur la même clé MinIO ; seules les colonnes voyagent) |
| `sources/_base/steps/enqueue.py` | quality_reason, resolution_status, training_eligible | pipeline (routage) | Y | → write API VPS (résultat d'ingest) |
| `sources/_base/steps/detect_crop.py` | storage_status | pipeline | Y | → write API VPS (ingest) |
| `scripts/gate_standard_vision.py` | quality_reason, resolution_status, training_eligible | gate qualité | Y | → write API VPS |
| `sources/_base/steps/resolve.py` | resolution_status | pipeline (auto needs_review) | **N** | → write API VPS (ingest) |
| `sources/_base/steps/auto_validate.py` | face, denom | dérivé vision | **N** | → write API VPS (ingest) |
| `sources/_base/dedup.py` | bbox_json, detection_method, eurio_id | pipeline dedup | **N** | → write API VPS (ingest) |
| `serving/bench_routes.py` | training_eligible, quality_reason (gate too_tilted) | gate qualité | **N** | → write API VPS |
| `training/training_set_scan.py` | face | dérivé vision | **N** | → write API VPS (ou recompute-only côté VPS lecture) |
| `vision/recrop_zero.py` | storage_status, n_crops_detected | recovery bulk | **N** | → write API VPS (ingest recrop) |
| `scripts/recrop_ebay_refine.py` | bbox_json, detection_method, dims, phash | recrop batch | **N** | → write API VPS (ingest recrop) |
| `scripts/recrop_lots_per_coin.py` | idem | recrop batch | **N** | → write API VPS (ingest recrop) |
| `scripts/recrop_review_score_guided.py` | idem | recrop batch | **N** | → write API VPS (ingest recrop) |
| `scripts/backfill_face.py` · `backfill_denom.py` · `backfill_quality_score.py` | face / denom / quality_score | **migration one-shot** | N | **tourne sur le VPS** (ou via API) une fois, pas de sync |
| `scripts/migrate_canonical_schema.py` · `migrate_to_minio.py` | origin / storage_path_legacy | **migration one-shot** | N | idem — s'exécute contre le canonique VPS |
| `archive/scripts/*` · `tests/*` | — | archive / test | N | **hors-scope** (ne tournent pas en prod multi-machine) |

**Surface d'écriture VPS à concevoir** (regroupe les colonnes ci-dessus) :
`PUT /assets/{id}/decision` (eurio_id, resolution_status, training_eligible,
quality_reason, face), `POST /ingest/crops` (recrops : bbox/phash/dims/method +
PNG MinIO), `POST /ingest/derived` (face/denom/verdicts pipeline). À affiner en
C2.

## 5. Plan en chunks (chacun laisse le système vert)

- **C0 — Geler & sauvegarder. ✅ FAIT (2026-07-03).** 3 backups online-backup
  `eurio.db.pre-migA-20260703` (Mac 97 MB / VPS 103 MB / PC 97 MB).
- **C1 — Réconcilier le delta Mac. ✅ FAIT (2026-07-03).** Analyse : les 6205
  crops existent des deux côtés (0 manquant) ; **189 lignes divergeaient, TOUTES
  artefact `bootstrap_backfill`** ; les 14 décisions humaines récentes du Mac
  étaient **déjà sur le VPS** (rien à pousser). Décision §6.1 tranchée : **le VPS
  fait foi**, 20 vieilles décisions legacy `machine=None` (déjà superseded)
  écartées et archivées (`c1-archive-discarded-legacy.md`). **Action : re-seed du
  Mac ← VPS** (`pull-replica`, zéro write VPS). *Vérif ✅ : diff Mac↔VPS = 0
  ligne sur 6205 ; pièce-témoin 252/100/42 sur les 3 machines.*
- **C2a — Décisions humaines sur le VPS. ✅ FAIT (2026-07-03).** Logique SQL
  extraite dans `store/decisions.py` (source unique cv2-free, commit-free :
  apply_accept_training/reopen_review/set_training_eligible/reassign/lot_decide),
  modèles wire dans `serving/decision_models.py`, routeur lean
  `serving/funnel_writes.py` (funnel + lot, scope `review:write`, monté sur
  server_serve). `lab_routes`/`review_queue_routes` délèguent aux helpers (comportement
  préservé). Durcissement : peer_arbitration passe à `review:write`. +18 tests
  (parity/funnel/lot), 0 régression (diff suite HEAD↔C2a identique). *Vérif ✅ :
  POST accept-training/reassign/lot → colonnes mutées, 403 sans scope, idempotent.*
- **C2b — `POST /ingest/crops`. ✅ FAIT (2026-07-03).** Write-half SQL-pure de la
  géométrie de recrop (bbox/detection_method/dims/phash/storage_status) dans
  `store/crops.py` (`apply_ingest_crops`, commit-free, miroir DB de
  `crop_edit.apply_manual_crop` sans cv2 + hint `cache_invalidate`) + route
  `POST /ingest/crops` (`ingest:write`, UPSERT idempotent, `missing` tolérant)
  dans `serving/ingest_routes.py` (déjà montée lean+full). +5 tests. *Vérif ✅ :
  colonnes écrites, missing pour id inconnu, idempotent, COALESCE storage_status,
  403 sans scope ; route présente sur server_serve.* La surface d'écriture VPS
  (§4) est désormais complète.
- **C3 — Router les décisions humaines** (routes `serving/*`, `review/*`) vers
  l'API VPS quand on tourne en local (aujourd'hui elles écrivent le eurio.db
  local). Chemin chaud = write-behind optimiste (§3). Livrable : funnel + review
  écrivent le VPS. *Vérif : une décision sur le Mac apparaît au VPS et, après
  pull, sur le PC.*
- **C4 — Router bulk & dérivés** (`resolve`, `auto_validate`, `dedup`, recrops,
  gate, recovery) vers `/ingest/*`. Livrable : la pipeline ML locale ne fait
  plus AUCUN `UPDATE image_assets` local. *Vérif : grep « UPDATE image_assets »
  hors VPS = 0 (sauf migrations/tests).*
- **C5 — Replica read-only strict.** Le eurio.db local devient un cache
  read-only (rafraîchi par pull-replica / transport §6.2). Retirer toute
  capacité d'écriture locale. Livrable : Mac/PC lisent, n'écrivent jamais.
  *Vérif : ouverture en `mode=ro` ne casse rien.*
- **C6 — Retirer l'infra event-log** (§6.4) : `image_state_events` colonnes
  sync (op_id/machine/hlc), `sync_outbox`, `sync_tombstones`,
  `sync_orphan_events`, worker debounce, badge, `ml:db:sync*`,
  `sync_routes`/`sync_replay`/`client/sync*`. Livrable : code mort supprimé.
  *Vérif : suite de tests verte sans les modules sync.*
- **C7 — Migrations one-shot. ✅ FAIT (2026-07-04).** Garde-fou automatique
  (`scripts/_vps_only_guard.py::guard_vps_only`, bypass
  `--i-know-this-is-canonical`) câblé sur `backfill_face.py`/`backfill_denom.py`/
  `backfill_quality_score.py` : refuse de tourner si `EURIO_DB_READONLY` (C5)
  ou `EURIO_API_URL` (client Direction A) sont configurés — ces scripts
  mutent `image_assets.face`/`denom`/`quality_score` par `UPDATE` brut, hors
  transport `/ingest/*`. `migrate_canonical_schema.py`/`migrate_to_minio.py`
  restent couverts par leur bandeau `DEPRECATED` existant (déjà hors chemin
  actif, pas de garde auto ajouté). Doc dédiée :
  `docs/work-in-progress/local-sync/vps-only-migrations.md` (liste des 5
  scripts + point non tranché : `backfill_face`/`backfill_denom` dépendent de
  torch/DINO donc doivent tourner GPU, ce qui contredit « VPS-only » strict —
  remonté PO, pas résolu). *Vérif ✅ : guard refuse avec `EURIO_DB_READONLY=1`
  et avec `EURIO_API_URL` set (exit 1 + message stderr), no-op sans ces env
  vars, bypass `--i-know-this-is-canonical` fonctionne — 4 tests
  `test_vps_only_guard.py`.*
- **C8 — Walkthrough PO revu. ✅ FAIT (2026-07-04).** `walkthrough-tests.md`
  réécrit : plus de Phase 0 bootstrap, plus de Phase de rattrapage —
  setup machine = `go-task ml:db:pull-replica` seul, décision = POST direct
  VPS (visible immédiatement, pas de cycle à attendre), reprise PC = simple
  pull sans merge. `README.md`/`backend.md`/`frontend.md`/`data-schema.md`
  déjà bannés ARCHIVÉ (README l'était depuis C1 ; backend/frontend/data-schema
  bannés dans ce chunk) et pointent vers ce document. Commandes vérifiées :
  seul `ml:db:pull-replica` cité (existe dans `ml/tasks.yml`), `ml:db:sync` /
  `ml:db:sync-bootstrap` absents (retirés C6b). *Vérif ✅ : grep sur le nouveau
  walkthrough — zéro occurrence de `sync_outbox`/`hlc`/`bootstrap`/
  `image_state_events`/badge.*

## 6. Décisions ouvertes (à trancher avec le PO avant les chunks concernés)

1. **Delta Mac orphelin (C1)** — remonter (`/ingest` bulk + rejeu décisions) ou
   acter perdu ? C'est la **seule perte de données possible** de toute la
   migration. Recommandation : remonter, c'est du vrai travail de tri.
2. **Transport replica (C5)** — garder `pull-replica` maison (snapshot VACUUM,
   déjà là, simple, « tire à la demande ») **vs** Litestream/LiteFS (réplique
   live streaming, plus de fraîcheur mais une dépendance à opérer). Reco : rester
   sur `pull-replica` d'abord (zéro dépendance), évaluer LiteFS si la latence de
   fraîcheur gêne.
3. **Forme exacte du write-behind (C3)** — file locale persistée (survit au
   crash) qui POST au VPS avec retry/backoff, UI optimiste par-dessus. Détailler
   le contrat (ordre, idempotence, réconciliation au pull).
4. **Retrait vs dormance de l'event infra (C6)** — supprimer franchement (reco,
   zéro-dette) vs garder en dormance le temps de stabiliser A. Reco : supprimer,
   on a les backups + git.

## 7. Invariants (ce qui doit rester vrai après A)

- **Un seul `eurio.db` inscriptible** dans tout le système : celui du VPS.
- `grep "UPDATE image_assets"` hors VPS = 0 en prod (migrations/tests exceptés).
- Une décision faite sur n'importe quelle machine est visible partout **après un
  pull**, sans étape de merge.
- Aucune matérialisation locale concurrente → **aucune divergence possible par
  construction** (plus de « même log, états différents »).
- Le compute lourd reste local (GPU) ; seules les **écritures** partent au VPS.

## Liens

- Verdict & diagnostic détaillé : `README.md` (ce dossier), mémoire
  [[project-local-sync-event-log]].
- Décision : mémoire [[project-sync-direction-a-single-writer]].
- Topologie (VPS no-GPU) : [[deployment-topology]],
  `docs/operations/deployment-topology.md`.
- Modèle B (writer canonique VPS, socle déjà posé) :
  `docs/work-in-progress/model-b/README.md`.
