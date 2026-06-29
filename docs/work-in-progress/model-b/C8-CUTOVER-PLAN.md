# C8 — Plan de cutover Model B (préparé 2026-06-29, NON exécuté)

> Prépare la bascule **Model A → Model B** : le canonique passe du eurio.db MinIO
> (Mac writer via lease) au eurio.db du VPS (writer unique derrière `/ingest/run`).
> Ce document est un **plan** — l'exécution se fera dans une session dédiée.

## TL;DR — la réconciliation est un NON-PROBLÈME (mesuré)

La grosse peur (« réconcilier les deltas Mac↔VPS ») **n'existe pas**. Mesuré le 2026-06-29 :

| Donnée Mac | Présente sur le VPS ? |
|---|---|
| 9054 source_images | **9054 / 9054** (0 absent) |
| 6074 image_assets | **6074 / 6074** (0 absent) |
| 3088 reviews décidées | **3088 / 3088** (0 absent) |

→ **Le VPS est un sur-ensemble COMPLET du Mac.** Tout ce qui est sur le Mac est
déjà sur le VPS, qui a en plus le run `a2ff9ffa` (CY/2012) poussé cette session.

**Pourquoi** : la DB Mac est **figée depuis le 16 juin** (dernier source_run /
review / fetch = 2026-06-16 — aucun travail Model A depuis 13 jours). Le seed VPS
du 19 juin a capturé tout l'état Mac, puis les pushes Model B de la session ont
ajouté par-dessus. Il n'y a donc **rien à réconcilier** : aucune écriture Model A
n'est restée bloquée sur le Mac.

Comparaison complète (VPS = Mac + run a2ff9ffa de session) :

| Table | Mac | VPS | Δ (= a2ff9ffa) |
|---|---|---|---|
| coins | 689 | 689 | 0 |
| source_runs | 73 | 74 | +1 |
| source_images | 9054 | 9302 | +248 |
| image_assets | 6074 | 6205 | +131 |
| review_queue | 5773 | 5903 | +130 |
| consensus_verdicts | 4402 | 4480 | +78 |
| image_asset_dino_predictions | 9798 | 10060 | +262 |
| training_runs / iterations / cohorts / recipes | 34 / 1 / 3 / 4 | idem | 0 |

> Conséquence : **on n'a même pas besoin de "perdre" de données.** Le run eBay de
> session est conservé gratuitement (déjà sur le canonique). Le Mac DB peut être
> abandonné tel quel au cutover.

## Les 499 orphelins FK — trivial et optionnel

`image_assets.run_id` dangling (pointe vers un `source_runs.id` qui n'existe plus,
suite à un prune non-cascade historique). **499 sur le Mac, 499 sur le VPS —
identiques** (venus du seed partagé, PAS un effet de la session).

- **Impact réel : nul.** La row `image_assets` est intacte et pleinement utilisable
  (review/training) ; seul `run_id` (provenance) pend dans le vide. SQLite FK ON
  n'enforce pas rétroactivement les violations existantes (que les écritures
  futures) → elles dorment sans rien casser. `ingest_run` les tolère déjà
  (`defer_foreign_keys`).
- **"Nettoyage" = one-liner optionnel**, zéro perte (le run_id pointe déjà vers rien) :
  ```sql
  UPDATE image_assets SET run_id = NULL
   WHERE run_id IS NOT NULL AND run_id NOT IN (SELECT id FROM source_runs);
  ```
  À faire avant ou après le cutover, indépendamment. Le seul gain : la DB passe un
  `PRAGMA foreign_key_check` strict. Pas un bloqueur.

## Le VRAI (et seul) travail de C8 : rafraîchir la source de la réplique

Aujourd'hui `client/replica.pull_replica()` télécharge la réplique depuis **MinIO**
(bucket `eurio-db`, `store/lease.py`), **pas** depuis le VPS. Or MinIO est **figé au
16 juin** (la réplique tirée en session n'avait pas a2ff9ffa). Donc en l'état, un
`--push` lit une réplique périmée et écrit sur un canonique en avance = split-brain
latent (anodin pour un scrape neuf, problématique pour recrop/dino qui lisent l'état
existant).

**Le cœur de C8 = la réplique doit refléter le canonique VPS, pas le MinIO périmé.**
Deux options (décision à trancher en session d'exécution) :

- **Option A — sync VPS → MinIO** (moins de code) : après chaque `ingest_run` (ou
  cron périodique/debounced), le VPS upload son `eurio.db` + SHA dans le bucket
  `eurio-db`. `pull_replica` reste inchangé et récupère l'état frais. Coût : upload
  ~106 Mo (→ debounce/périodique plutôt que par-push). Le lease devient vestigial.
- **Option B — repointer `pull_replica` sur le VPS** : endpoint authentifié
  `GET /db/replica` (+ `/db/replica/sha`) servant le canonique, ou `scp` depuis le
  VPS. Sort MinIO du chemin réplique. Plus propre conceptuellement, un peu plus de code.

> Recommandation à pré-mâcher : **Option A** (réutilise pull_replica + le SHA-check
> existant ; ajoute juste un uploader côté VPS, déclenché post-ingest ou par cron).
> Le backup périodique `infra/backup/eurio-backup.sh` (→ pCloud) couvre déjà la
> durabilité ; on greffe l'upload MinIO à côté.

## Séquence de cutover (session d'exécution future)

1. **Geler Model A** : `go-task ml:db:acquire` n'est plus utilisé ; documenter que
   le Mac n'écrit plus le canonique. (Aucune écriture Mac en cours — DB figée 16/06.)
2. **(optionnel) nettoyage orphelins** : le one-liner ci-dessus sur le canonique VPS.
3. **Rafraîchir la source réplique** : implémenter Option A ou B → vérifier que
   `pull_replica` ramène un état = VPS (contient a2ff9ffa).
4. **Bascule writer** : le VPS est désormais le writer unique (déjà le cas via
   `/ingest/run`). Le lease MinIO devient **secours d'urgence** (réacquérable si le
   VPS tombe). Documenter la procédure de secours.
5. **Backup** : brancher le backup périodique du canonique VPS (eurio.db → MinIO
   et/ou pCloud) — durabilité du nouveau writer unique.
6. **Doc topology A→B** : MAJ `docs/operations/deployment-topology.md` (Modèle A →
   Modèle B : VPS=canonique/writer, Mac/PC=calcul via réplique+push).
7. **Sanity e2e** : un `--push` recrop court → vérifier réplique fraîche (VPS) →
   push → canonique cohérent.

## Rollback

Trivial tant que Model B n'a pas tourné longtemps : le lease MinIO + le eurio.db
Mac (figé 16/06) restent intacts. Pour revenir en Model A : re-`go-task ml:db:acquire`
sur le Mac, et le canonique MinIO reprend (on perd alors le delta Model B accumulé
côté VPS — d'où l'intérêt de garder le backup VPS). Aucune migration destructive
n'est faite au cutover → rollback = changer la source du writer.

## Décisions ouvertes (à trancher en session d'exécution)

1. **Option A (sync VPS→MinIO) vs B (pull_replica ← VPS direct)** pour la fraîcheur réplique.
2. **Déclencheur du sync** (Option A) : post-ingest immédiat (simple, coûteux à
   ~106 Mo) vs cron périodique (5-15 min) vs debounce. Recommandé : cron/debounce.
3. **Nettoyage orphelins** : maintenant, au cutover, ou jamais (purement cosmétique).
4. **Sort du Mac DB** : abandon pur (le VPS a tout) ou conserver une archive figée.

## Ce que C8 n'est PAS (démythifié)

- ❌ PAS de réconciliation bidirectionnelle de deltas (VPS ⊇ Mac, mesuré).
- ❌ PAS de risque de perte de travail réel (rien n'est stranded sur le Mac).
- ❌ PAS de migration de schéma lourde (le schéma VPS est déjà à jour, migrations 0001-0004).
- ✅ Essentiellement : **rafraîchir la source de la réplique + retirer le lease + doc**.
