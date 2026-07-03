# Handoff — Double-write local ↔ canonique VPS (SQLite)

> **But de ce document.** Reprendre, dans une **session dédiée**, le gros morceau
> d'architecture : faire en sorte que les écritures faites sur la base SQLite
> **locale** (Mac / PC) — classification du Jeu d'entraînement, review, crops —
> atterrissent aussi sur la base SQLite **canonique du VPS**, **sans sacrifier
> les perfs locales**, et en supportant du **travail concurrent Mac ‖ PC**.
> Ce doc contient : le problème, les findings (état réel du code), l'espace de
> conception avec trade-offs, une reco, et — en annexe — **tout le reste du
> chantier funnel** pour que la session le termine d'un bloc.
>
> À lire d'abord : [`README.md`](./README.md) (doctrine Model B). Ce handoff en
> est l'extension « écritures interactives multi-machine ».
>
> _Rédigé 2026-07-03 (session maquette funnel). Findings = workflow d'analyse
> `wf_32c69698-7cb`._

---

## 1. Le problème en une page

On a **deux besoins qui tirent en sens opposé** :

1. **Perf locale non négociable.** Le travail lourd (recrop, scan Dino, embeddings,
   tri rapide de centaines de crops, bulk-apply) lit/écrit la base **en local**.
   Mettre de la latence réseau **par opération** rend ça inutilisable (« un enfer »).
   → La base de travail **doit** rester un SQLite local.

2. **Durabilité + reprise multi-machine.** La classification (au train / exclu /
   rejeté / réassigné / à reviewer) est un **actif produit**. Je commence sur le
   Mac, je m'arrête, je reprends sur le PC — **sans rien perdre**. Et parfois je
   travaille sur **les deux machines en même temps** (souvent des crops distincts,
   parfois les mêmes). → La vérité doit converger sur le **canonique VPS**, et les
   **conflits** doivent se résoudre proprement.

**La tension** : write-through synchrone vers le VPS (le patron actuel de la Review)
donne (2) mais tue (1). Le SQLite local seul donne (1) mais casse (2) — c'est
l'état actuel, et **le travail de classification est perdu au changement de machine**
(cf. §3). Il faut une **couche de synchronisation local-first** : écriture locale
instantanée + convergence asynchrone vers le canonique + résolution de conflits.

**C'est un problème de réplication multi-maître offline-first pour SQLite.** Ni
plus ni moins. La bonne nouvelle : Eurio a déjà une brique event-log
(`image_state_events`) qui en est le substrat naturel (§7-A).

---

## 2. Contraintes dures (les garde-fous de la session)

- **Pas de latence réseau sur le chemin chaud.** Toute écriture locale doit être
  instantanée (SQLite local). La sync réseau est **asynchrone, en fond, par lots**.
- **Offline-friendly.** Débrancher le réseau ne doit pas bloquer le tri. La sync
  rattrape à la reconnexion.
- **Multi-maître.** Mac et PC peuvent écrire en même temps. Pas de « single writer »
  bloquant sur le chemin interactif.
- **R0 — zéro dette.** On construit la vraie solution, pas un patch. (Cf. règle repo.)
- **Ne pas casser la doctrine Model B existante** : MinIO = images, jamais la DB ;
  `source_images.run_id` first-seen immuable ; le canonique VPS reste la source de
  vérité pour tout le downstream (bake, bench, export).
- **Idempotence.** Toute op de sync doit pouvoir être rejouée sans effet double
  (retry réseau, reprise après crash).

---

## 3. État actuel — findings (le pourquoi du trou)

_Source : workflow `wf_32c69698-7cb`, lecteur R4 (multi-machine). Chemins absolus
sous `ml/`._

### 3.1 Ce qui existe comme sync aujourd'hui

- **Pull (VPS → machine), read-only, manuel.** `ml/client/replica.py::pull_replica`
  (l.55) télécharge `GET /db/replica` (snapshot `VACUUM INTO` cohérent + sha256,
  servi par `ml/serving/db_routes.py`). Docstring explicite : *« Réplique read-only…
  aucune écriture ne passe par là »*. Déclenché par `go-task ml:db:pull-replica`.
- **Push (machine → VPS), scopé run, manuel.** `ml/client/runbatch.py::push_run(conn,
  run_id)` (l.271) = `export_run()` + `POST /ingest/run` (`ml/serving/ingest_routes.py:31`,
  upsert idempotent par clé naturelle + `batch_sha`). Déclenché par un flag `--push`
  sur les scripts d'ingestion (scrape / recrop / dino backfill / export training).
- **Aucune sync automatique** (pas de cron, pas de watch).
- **Aucun mécanisme ne pousse une édition faite APRÈS l'ingestion d'un run** (ex.
  un flip `training_eligible` 3 jours après le scrape). `push_run` re-scanne
  `image_assets WHERE run_id=?` — en théorie un ré-appel *pourrait* propager, mais
  **aucun call-site ne le fait** depuis `lab_routes`.

### 3.2 Où écrivent réellement les endpoints de classification

- `ml/serving/server.py:63` : `CANONICAL_DB = EURIO_DB_PATH or state/eurio.db`.
  **Nom trompeur** : c'est le fichier **local** ouvert par `Store`
  (`ml/store/connection.py:69-84`, sqlite3 local WAL). `server.py:102` :
  `_store = Store(CANONICAL_DB)`.
- Les 4 endpoints classification (`ml/serving/lab_routes.py` : `training-eligible`
  l.2364, `reopen-review` l.2411, `accept-training` l.2486, `reassign` l.2538 —
  **construits dans la session précédente**) font tous
  `store._connection()` → `UPDATE image_assets …` → `conn.commit()`. **Zéro HTTP,
  zéro push.**
- `lab_routes` n'est monté **que** sur `server.py` (poste lourd `:8042`), **jamais**
  sur `server_serve.py` (image lean du VPS derrière `eurio-api`). Ces routes
  **n'existent pas** côté VPS → elles ne peuvent physiquement écrire que le local.
- Selon la tâche : `ml:api` (défaut) → `state/eurio.db` (**jamais** synchronisé) ;
  `ml:api-replica` → `state/eurio.replica.db` (tiré du VPS par `pull_replica`).

### 3.3 Le contraste qui montre la voie : la Review (TC2)

`ml/serving/review_queue/writes.py` (`reject_review` l.152, `restore_rejected`
l.266, `decide_review`) est monté sur **`server_serve.py:53,129`** ET le front
**pointe l'API VPS** pour ces écritures → elles vont **directement au canonique**.
C'est le patron qui **tient l'exigence multi-machine aujourd'hui**. Mais il est
**write-through synchrone** : acceptable pour la review (décisions humaines
espacées), **pas** pour le tri/crop rapide (contrainte §2).

### 3.4 Scénario de perte, concret

1. Trier sur Mac avec `ml:api-replica` (réplique fraîche) → `accept-training`,
   flips `training_eligible`, etc. → écrit `state/eurio.replica.db` **local Mac**.
2. Basculer sur PC → `go-task ml:db:pull-replica` → **re-télécharge le snapshot VPS**,
   qui n'a **jamais** reçu les décisions du Mac → le fichier réplique local est
   **écrasé** → travail Mac **perdu**. 💥

**Verdict : la classification n'est pas durable ni partagée. C'est CE trou que la
session doit fermer.**

---

## 4. Ce qu'il faut synchroniser (cartographie des écritures)

Toutes ne se valent pas — distinguer **décisions humaines autoritatives** (à ne
jamais perdre) des **dérivés recomputables** (moins critiques, régénérables).

| Donnée | Table.colonnes | Nature | Criticité sync |
|---|---|---|---|
| Classification humaine | `image_assets`: `resolution_status`, `training_eligible`, `eurio_id` (reassign), `face`, `quality_reason`, `resolved_at` | **Autoritative** — décision humaine | **Haute** — perte = travail refait |
| File de review | `review_queue`: `status`, `decided_*`, `lane` | Autoritative | Haute |
| Journal d'état | `image_state_events` (append-only) + `image_state_current` (dérivé) | **Event-log** | Haute (c'est le substrat, §7-A) |
| Verdicts scan Dino | `cohort_training_scan_results` (+ futures colonnes `suggestion*`) | **Dérivé** (recomputable par re-scan) | Basse — peut se régénérer |
| Embeddings / prédictions | `image_asset_dino_predictions`, banques `.npz` | Dérivé lourd | Basse (déjà hors DB pour les .npz) |
| Crops / images | MinIO (pas la DB) | Binaire | **Hors périmètre** (MinIO gère déjà) |

**Conséquence de design** : on peut d'abord ne synchroniser QUE la couche
autoritative (classification + review + events) et laisser les dérivés se
recalculer localement. Ça réduit fortement le volume et les conflits.

---

## 5. Le sous-problème concurrence (Mac ‖ PC)

Trois cas, par ordre de fréquence :

1. **Crops distincts** (cas courant). Mac touche l'asset A, PC touche l'asset B.
   → **Union triviale**, zéro conflit. N'importe quelle sync par op-log le gère.
2. **Même crop, champs différents.** Mac réassigne `eurio_id`, PC pose `training_eligible=0`.
   → **Merge par champ** : les deux s'appliquent. Pas un vrai conflit.
3. **Même crop, même champ, décisions divergentes.** Mac : accepte au train
   (`training_eligible=1, manual`). PC : rejette (`rejected, eligible=0`).
   → **Vrai conflit.** Politique nécessaire.

**Politique recommandée : Last-Writer-Wins au niveau du CHAMP, ordonné par une
horloge logique hybride (HLC).** Pourquoi :
- Les décisions de classification sont des **verdicts humains** : « la dernière
  décision gagne » est **intuitif et correct** dans ce domaine (on corrige, la
  correction la plus récente fait foi).
- **Field-level** (pas row-level) pour que le cas 2 ne se perde pas.
- **HLC** (`(ts_physique, compteur_logique, node_id)`) et pas l'horloge murale :
  Mac et PC dérivent, il faut un **ordre total causal** stable. Standard, ~50 lignes.
- **On garde l'événement perdant dans le log** (audit) : rien n'est effacé, on
  matérialise juste le gagnant.

> ⚠️ Ne PAS partir sur du merge sémantique fin (« fusionner deux avis ») ni du
> surfacing manuel de conflit en v1 — trop de complexité pour un gain marginal.
> LWW-par-champ+HLC couvre >99 % des cas réels (surtout que le cas 1 domine).

**Option de réduction de conflits (orthogonale, optionnelle)** : un **lease
souple par cohorte** (« je bosse sur mix-zone-17 ») affiché dans l'UI pour
éviter que deux machines tapent la même cohorte — pas un lock dur, juste un
signal social. Réduit le cas 3 sans le résoudre. À considérer si les conflits
deviennent gênants en pratique.

---

## 6. Pourquoi les solutions « toutes faites » ne suffisent pas (survol)

- **Litestream** : streame le WAL vers un object store → **disaster-recovery
  single-writer**, PAS multi-maître. ❌ (ne résout pas deux machines qui écrivent).
- **LiteFS** : FUSE, primary/replica avec lease → **un seul writer à la fois**. ❌
- **rqlite / dqlite** : SQLite distribué via Raft → écritures passent par le
  consensus = **latence réseau par write**. ❌ (viole §2).
- **libSQL / Turso embedded replicas** : réplique embarquée qui sync depuis un
  primary, mais **writes vont au primary** (write-through-ish). ⚠️ proche du
  patron review, même limite perf sur le chemin chaud.
- **cr-sqlite (Vlcn)** : extension SQLite qui transforme des tables en **CRR**
  (conflict-free replicated relations), merge multi-maître **automatique** par
  LWW-par-colonne + horloge causale. ✅ **Le seul off-the-shelf qui colle** — voir
  §7-B (mais dépendance + migration de schéma à peser).

---

## 7. Espace de conception — 3 architectures viables

### A. Sync par event-log (RECOMMANDÉ) — capitaliser sur `image_state_events`

**Idée.** Eurio a déjà un **journal d'événements append-only** (`image_state_events`)
+ un état matérialisé (`image_state_current`), alimentés par `emit_state_event`
(`ml/store/events.py`). C'est **exactement** le substrat d'une sync event-sourcée :

- Chaque op de classification = **append d'un événement** `{op_id (uuid), asset_id,
  from_state, to_state, field_changes (payload), actor, machine, hlc}`.
- **Écriture locale = append local instantané** (perf OK, §2).
- **Sync = réplication bidirectionnelle du LOG** (append-only → **union sans
  conflit** : on n'écrase jamais un événement, on ajoute). Batch, asynchrone, en fond.
- Chaque machine **re-matérialise** `image_state_current` + les colonnes dérivées
  de `image_assets` en **rejouant les événements dans l'ordre HLC** → LWW-par-champ
  tombe **naturellement** (le dernier event HLC pour un champ gagne).
- **Idempotence** par `op_id` (rejouer = no-op).

**Pour.** Capitalise sur l'existant ; append-only = merge trivial ; audit complet
gratuit ; local-first natif ; LWW-par-champ émergent ; pas de dépendance externe.

**Contre / à construire.**
- **Aujourd'hui, tous les writes de classification n'émettent pas un event complet**
  (à auditer : `training_eligible`, `quality_reason`, `eurio_id` reassign passent-ils
  bien par `emit_state_event` avec assez de payload pour re-dériver la colonne ?).
  → **Chantier principal** : garantir que **chaque** mutation autoritative appende un
  événement structuré et complet.
- Écrire le **moteur de sync** (endpoint `POST /events/sync` bidirectionnel côté
  VPS : « voici mes events depuis hlc X, donne-moi les tiens », + merge + re-matérialisation).
- Gérer l'HLC (petit module).

**Forme d'endpoint (esquisse).**
```
POST /db/events/push   { events: [...], since_hlc }   → { accepted, server_hlc }
GET  /db/events/pull?since_hlc=...                     → { events: [...] }
```
Un worker local (ou une commande `go-task ml:db:sync`) fait push puis pull puis
re-matérialise. Peut tourner périodiquement et/ou à la demande.

### B. cr-sqlite (CRDT off-the-shelf) — moins de code, plus de dépendance

**Idée.** Charger l'extension cr-sqlite, marquer les tables de classification comme
CRR. Chaque base devient un writer ; `crsql_changes` expose les deltas ; on les
échange entre Mac/PC/VPS et l'extension **merge automatiquement** (LWW-par-colonne
+ horloge causale intégrée).

**Pour.** Merge multi-maître **gratuit** ; sémantique de conflit exactement celle
qu'on veut (LWW-par-colonne) ; beaucoup moins de code de sync à écrire.

**Contre.** **Dépendance native** (extension à builder/charger sur Mac + PC + VPS,
via Nix) ; **migration de schéma** (les tables CRR ont des contraintes : clés
primaires, pas de FK classiques sur les CRR, colonnes gérées) sur un **schéma
mature** (`schema.sql` ~2000 lignes, beaucoup de call-sites) = **risque R0** ;
on hérite de ses choix (LWW strict, pas de field custom merge) ; maturité/écosystème
à évaluer. **À prototyper isolément avant de s'engager.**

### C. Outbox + write-through asynchrone (MVP pragmatique)

**Idée.** Write local instantané **+** une table **outbox** locale
(`{op_id, verb, asset_id, payload, hlc, synced}`). Un worker de fond flushe
l'outbox vers `eurio-api` (qui applique au canonique et **sérialise**), puis un
pull ramène les ops des autres machines.

**Pour.** Plus simple que A (pas de re-matérialisation par replay : le VPS est le
point de merge, ordre d'arrivée) ; local-first ; offline OK (l'outbox tamponne).

**Contre.** Résolution de conflit **plus faible** (ordre d'arrivée serveur, pas HLC
causal) → deux machines offline puis reconnectées peuvent produire un ordre non
intuitif ; deux sources de vérité transitoires (outbox local + canonique) ; on
finit souvent par ré-implémenter un bout de A. **Bon comme étape intermédiaire,
pas comme cible finale.**

### Verdict de reco

**Cible = A (event-log sync)** — c'est le plus aligné R0 et il capitalise sur
`image_state_events`. **Évaluer B en parallèle** par un petit spike (si cr-sqlite
s'intègre proprement via Nix et accepte le schéma, il fait gagner beaucoup de
code). **C** est le fallback MVP si on veut débloquer vite le multi-machine sur la
seule couche review+classification avant d'industrialiser.

> 🔬 **Première tâche concrète de la session** : auditer `emit_state_event`
> (`ml/store/events.py`) et TOUS les writes de `lab_routes.py` / `review_queue/writes.py`
> pour répondre à : *« chaque mutation autoritative émet-elle déjà un événement
> complet et rejouable ? »*. La réponse conditionne l'effort de A.

---

## 8. Découpage proposé pour la session double-write

1. **Audit event-completeness** (½j) — cartographier ce qui émet / n'émet pas
   d'event ; décider A vs B vs C sur données réelles.
2. **HLC + schéma d'event de sync** — stamper les events, ajouter `op_id`, `machine`,
   `hlc` si absents (colonnes additives sur `image_state_events`).
3. **Endpoints de sync** (`push`/`pull` events) sur `server_serve.py` (canonique) +
   client `ml/client/` + `go-task ml:db:sync`.
4. **Re-matérialisation** déterministe (`image_state_current` + colonnes `image_assets`)
   par replay HLC — avec tests de convergence (deux logs divergents → même état).
5. **Router les writes classification par l'event-log** (accept-training,
   training-eligible, reopen-review, reassign, + reject/restore à créer) → tous
   appendent un event ; la sync s'occupe du canonique.
6. **Tests de conflit** : cas 1/2/3 du §5, convergence, idempotence, offline→online.
7. **Migration douce** : `ml:api` / `ml:api-replica` → un seul mode « local + sync ».

---

## 9. Questions ouvertes à trancher dans la session

1. **A, B ou C ?** (dépend de l'audit event-completeness + spike cr-sqlite).
2. **Granularité de conflit** : LWW-par-champ confirmé, ou certains champs méritent
   un traitement spécial (ex. `eurio_id` reassign vs `resolution_status`) ?
3. **Cadence de sync** : à la demande (`go-task ml:db:sync`), au démarrage/arrêt de
   session, périodique (watch), ou combiné ? (Compromis simplicité vs fraîcheur.)
4. **Lease souple par cohorte** : on le fait dès v1 pour réduire les conflits, ou
   on attend de voir s'ils gênent ?
5. **Dérivés** (`cohort_training_scan_results`, embeddings) : on les sync ou on les
   recompute localement après pull ? (Reco : recompute — ne pas les mettre dans le
   log autoritatif.)
6. **Périmètre** : on limite d'abord à la classification (image_assets + review_queue
   + events), ou on vise toute mutation interactive d'entrée de jeu ?

---

## 10. Ce qui est BLOQUÉ vs ce qui peut avancer en parallèle

- ✅ **Peut avancer sans le double-write** : **Phase 1 (UI/naming funnel)** et
  **Phase 2 (scan Dino → suggestions)** — voir Annexe. Ce sont du front (flow déjà
  validé en maquette) + du compute local (le scan écrit des dérivés). Aucune
  dépendance à la sync.
- ⛔ **Bloqué / EST le sujet de la session** : **Phase 3-4** (nouveaux endpoints
  reject/restore/bulk **écrits lean/canonique d'emblée**, et la garantie
  multi-machine). Les faire AVANT de trancher le double-write = dette (on les
  réécrirait). Donc : le double-write se décide **avant ou pendant** Phase 3.

> Recommandation de séquencement global : livrer Phase 1 + Phase 2 (valeur visible,
> zéro archi), **puis** ouvrir la session double-write qui tranche l'archi ET
> livre Phase 3-4-5 dessus.

---

## 11. Références

**Findings / plan** : workflow `wf_32c69698-7cb` (journal dans
`…/subagents/workflows/wf_32c69698-7cb/journal.jsonl`).
**Maquette UX validée** : `scratchpad/plautus-triage.html` (flow funnel final).
**Doctrine** : [`README.md`](./README.md) (Model B), [`R3-iterations-canonical.md`](./R3-iterations-canonical.md).

**Fichiers clés (chemins sous `ml/`)** :
- Sync actuel : `client/replica.py:55` (`pull_replica`), `client/runbatch.py:271`
  (`push_run`), `serving/ingest_routes.py:31` (`/ingest/run`), `serving/db_routes.py`
  (`/db/replica`).
- Écritures classif (locales, à router) : `serving/lab_routes.py:2364,2411,2486,2538`.
- Patron canonique (à imiter) : `serving/review_queue/writes.py:152,266`, monté
  `serving/server_serve.py:53,129`.
- Event-log (substrat de A) : `store/events.py` (`emit_state_event`), `state/schema.sql`
  (`image_state_events`, `image_state_current`, ~l.899-943).
- Connexion / chemins DB : `store/connection.py:69-84`, `serving/server.py:63,102`.

**Commandes** : `go-task ml:db:pull-replica`, `go-task ml:api`, `go-task ml:api-replica`.

---

## Annexe — Plan d'intégration du funnel (le « reste » à finir dans la session)

_Condensé du plan `wf_32c69698-7cb`. Détail complet dans le journal du run._

### A. Mapping catégorie UI → état backend

| Catégorie | Prédicat SQL |
|---|---|
| **Au train** | `resolution_status IN ('auto_name','auto_phash','manual') AND training_eligible=1 AND (face IS NULL OR face!='reverse')` (`lab_routes.py:2277`) |
| **À reviewer** | `resolution_status='needs_review'` + row `review_queue` open (sinon invisible à l'écran Review §C4) |
| **Rejetées** | `resolution_status='rejected'` (englobe reverse via `quality_reason='face_reverse'`) |
| **Exclues** | `training_eligible=0 AND resolution_status!='rejected'` (aucun compteur matérialisé aujourd'hui — à créer) |
| **À vérifier** | `cohort_training_scan_results` : `suggestion IS NOT NULL AND suggestion_applied=0` (à créer, §D) |

### B. Matrice de capabilities

| Transition | Endpoint | État |
|---|---|---|
| Accepter au train | `POST /lab/assets/{id}/accept-training` | ✅ fait (`lab_routes.py:2486`) |
| Exclure/Réinclure | `POST /lab/assets/{id}/training-eligible` | ✅ fait (`:2364`) |
| Repasser en review | `POST /lab/assets/{id}/reopen-review` | ✅ fait (`:2411`) |
| Réassigner | `POST /lab/assets/{id}/reassign` | ✅ fait (`:2538`) |
| Dismiss intrus | `POST /lab/assets/{id}/intruder-dismiss` | ✅ fait (`:2586`) |
| **Rejeter (lab)** | `POST /lab/assets/{id}/reject` | ❌ à créer — patron `review_queue/writes.py:151` |
| **Restaurer (lab)** | `POST /lab/assets/{id}/restore` | ❌ à créer — patron `writes.py:265` + UPSERT façon `reopen-review` |
| **Reverse → Rejetées** | déjà écrit à l'enqueue (`enqueue.py:257`, `quality_reason='face_reverse'`) | ⚠️ gap = **lecture** lab (`n_reverse_flagged` `lab_routes.py:2284` à retirer, `CohortTrainingSet.vue` à corriger) |
| **Bulk apply suggestions** | `POST /lab/cohorts/{id}/training-crops/apply-suggestions {asset_ids[]}` | ❌ à créer — 1 transaction serveur |

> ⚠️ **Tous les nouveaux endpoints (reject/restore/bulk) : les écrire LEAN /
> CANONIQUE d'emblée** (sur `server_serve.py`, patron review), pas sur `server.py` —
> sinon on reproduit le trou multi-machine. C'est le lien direct avec ce handoff.

### C. Changements de schéma (`cohort_training_scan_results`, additif `_ensure_column`)

```sql
denom_score REAL,
denom_verdict TEXT CHECK (denom_verdict IS NULL OR denom_verdict IN ('2eur','not_2eur')),
abs_max_sim REAL,
suggestion TEXT CHECK (suggestion IS NULL OR suggestion IN ('reject','reassign','exclude')),
suggestion_reason TEXT,          -- 'denom'|'off_topic'|'reverse'|'margin'|'outlier+quality'
suggestion_applied INTEGER NOT NULL DEFAULT 0,
suggestion_applied_at TEXT
```
`is_intruder`/`intruder_reason`/`dismissed` inchangés. Miroir dans `ScanResultRow`
(`store/training_scan.py:17`) + INSERT `training_scan_upsert_results`.
**Pas de nouvelle valeur `resolution_status`** (reverse réutilise `rejected` +
`quality_reason`). Reverse → option **A** (rejet dur au moment où `face='reverse'`
est écrit).

### D. Scan Dino → suggestions (`training_set_scan.py::compute_closed_set_verdicts`)

Priorité **reject > reassign > exclude** :
- **reject** si `denom≠2€` (probe `vision/denom_probe.py`, embedding déjà calculé
  passe 1) **OU** `abs_max_sim < ABSOLUTE_SIM_FLOOR≈0.45` (hors sujet, à bencher)
  **OU** `face=reverse`.
- **reassign** si `by_margin` (closed-set, une autre classe de la cohorte réclame).
- **exclude** si `by_outlier AND quality_bad` (réutiliser `_QUALITY_MIN=0.85` /
  `_TILT_MAX_DEG=30` de `review/validation/experts.py`, étendre le SELECT
  `_scope_sql_and_params`).
- **`dino_class_references`** (pin/exclude, `store/dino_references.py`) : levier
  déjà là pour affiner ancres/margin — aucun changement requis, enrichissement futur
  (bouton « pin ce crop » depuis une suggestion rejetée par l'humain).

### E. Chunks funnel (rappel §10)

1. UI/naming (front, non bloqué) · 2. Scan suggestions (compute local, non bloqué) ·
3. Endpoints manquants **lean d'emblée** (dépend de la décision double-write) ·
4. Garantie multi-machine (**= ce handoff**) · 5. `_LEGAL_TRANSITIONS`
(`resolved→rejected`) + invariant « needs_review ⇒ row review_queue ».

### F. Questions PO déjà connues (funnel)

1. Reverse : rejet dur à l'enqueue suffit-il, ou gérer aussi un crop **déjà au
   train** dont la face `reverse` est détectée **après coup** (`n_reverse_flagged`
   suggère que ce cas existe) ?
2. Seuil `ABSOLUTE_SIM_FLOOR` à bencher (mix-zone-17) avant activation.
3. Bulk : « toutes les suggestions pending de la cohorte » vs sélection manuelle.
4. Motif de rejet distinct (`wrong_coin`) vs motifs review classiques
   (`not_a_coin`/`too_low_quality`) pour l'audit.
