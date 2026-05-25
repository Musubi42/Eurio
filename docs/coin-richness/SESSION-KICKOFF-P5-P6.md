# Kickoff — Session prep destructive (P.5 + P.6)

> Document destiné à la **prochaine session Claude Code** sur le chantier
> coin-richness. Lis ce kickoff **avant tout `Edit`/`Bash`**, en complément
> du ROADMAP-DB.md §0 (progress log).
>
> Date de rédaction : **2026-05-25** (fin session 2). Auteur : session
> implémentation P.1–P.4.

---

## 1. Objectif de la session

Livrer les deux derniers chunks **non destructifs** de la phase P, qui posent
le filet de sécurité avant l'acte destructif (wipe) :

- **P.5** — Test de restauration du backup.
- **P.6** — Écriture du script de wipe (NE PAS L'EXÉCUTER), avec drop+recreate
  des 6 tables source-aware sous garde-fou interactif.

**Important** : P.6 produit un script qui sait wiper la DB, mais ne wipe
**rien** durant cette session. Le wipe effectif est un acte ultérieur, sous
confirmation explicite utilisateur, à un moment dédié.

**Effort estimé** : ~2.5 h cumulé (P.5 ≈ 30 min, P.6 ≈ 2 h).

---

## 2. État à l'ouverture (vérifier avant de coder)

À faire **dès le début** pour confirmer que la session précédente est bien
intégrée :

```bash
# 1. Branche + status git
git branch --show-current   # → 'coin-richness/p3-schema' ou ce que l'utilisateur a mergé
git status -s               # devrait être clean (commit fait fin session 2)
git log --oneline -10       # voir les commits P.1→P.4

# 2. DB et backup
ls -lh ml/state/eurio.db ml/state/eurio.db.bak-pre-p3-2026-05-25
# Les deux doivent exister, ~29M chacun.

# 3. Schéma actuel
sqlite3 ml/state/eurio.db "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('source_registry','mints','coin_variants','coin_mint_releases','coin_source_refs','mint_release_prices','mint_release_observations','coin_credits','coin_edge_variants') ORDER BY name;"
# → doit lister les 9 nouvelles tables.

# 4. source_registry seedé
sqlite3 ml/state/eurio.db "SELECT id, kind FROM source_registry ORDER BY id;"
# → 10 rows (numista_api, bce_official, bundesbank, mdp, lmdlp, wikipedia,
#   ebay_browse, 2euros_org, eurio_derived, manual).

# 5. method column présente sur les 2 tables i18n/aliases
sqlite3 ml/state/eurio.db "SELECT name FROM pragma_table_info('coin_names_i18n') WHERE name='method' UNION SELECT name FROM pragma_table_info('coin_aliases') WHERE name='method';"
# → 'method' x 2.

# 6. Tests référentiel verts
cd ml && .venv/bin/python -m pytest tests/test_numista_eurio_id.py tests/test_country_iso2.py tests/test_storage_migration.py -q
# → 100+ passed, 0 failed.
```

Si un check échoue : **arrêter et investiguer** avant P.5/P.6.

---

## 3. Ordre de lecture

1. Ce kickoff (5 min).
2. `ROADMAP-DB.md` §0 (progress log) + §3 (schéma cible) + §7 P.5/P.6/P.6.recreate (15 min).
3. `chantier-C-mintage.md` §"Pattern : identity + observations par source" (5 min — la version révisée des DDL, l'autre est marquée OBSOLÈTE).
4. **Skim** : `SESSION-KICKOFF-IMPLEMENTATION.md` §4 (wipe scope) + §6 (pipeline 3 niveaux) + §13 (mantras). Si tu connais, skip.
5. Mémoires : `feedback_sqlite_only_doctrine.md`, `project_coin_richness.md`.

---

## 4. P.5 — Test de restauration backup (~30 min)

### 4.1 — Pourquoi non négociable

Le wipe (action ultérieure, hors scope cette session) drop ~13k lignes
référentielles. Si le backup n'est pas restaurable, on perd tout sans recours.
P.5 valide **avant le wipe** que le backup est sain.

### 4.2 — Mécanique

```bash
# 1. Backup actuel = ml/state/eurio.db.bak-pre-p3-2026-05-25 (posé fin session 2).
# 2. Restaurer dans un fichier temporaire (NE PAS écraser eurio.db).
TMP=/tmp/eurio_restore_test.db
cp ml/state/eurio.db.bak-pre-p3-2026-05-25 "$TMP"

# 3. Sanity checks SQLite
sqlite3 "$TMP" "PRAGMA integrity_check;"      # doit retourner 'ok'
sqlite3 "$TMP" "PRAGMA foreign_key_check;"    # vide = OK
```

### 4.3 — Vérification métier (`scripts/verify_backup_restore.py` à créer)

Script Python qui :
1. Ouvre le backup restauré + la DB courante.
2. Compare les counts sur toutes les tables wipées (cf. §8 ROADMAP) → doivent
   être **strictement égaux** ou supérieurs côté DB courante (les 9 nouvelles
   tables sont en plus).
3. Re-joue une query métier : page coin détail pour `de-2010-2eur-city-hall-and-roland-bremen` (NID 10069 actuel) → doit retourner ≥1 observation, ≥1 canonical_image, ≥1 cross_ref.
4. Retourne exit code 0 si OK, ≥1 sinon.

Le script vit dans `ml/scripts/verify_backup_restore.py`. Idempotent
(read-only). À ajouter dans Taskfile (`ml:verify-backup`).

### 4.4 — Critère de succès

- `integrity_check` = ok
- `foreign_key_check` vide
- Counts égaux ou supérieurs
- Sample query Bremen renvoie des rows

Si tout est vert → P.5 ✅, on peut écrire P.6.

---

## 5. P.6 — Script wipe + recreate (~2 h)

### 5.1 — Périmètre

Crée `ml/scripts/wipe_referential.py` qui combine deux actions, atomique sous
transaction :

1. **Wipe** : DELETE FROM des tables listées en `ROADMAP-DB.md` §8 :
   `coins`, `referential_catalog`, `design_groups`, `coin_cross_refs`,
   `coin_observations`, `coin_canonical_images`, `coin_aliases`,
   `coin_names_i18n`, `coin_market_quotes`, `coin_national_variants`.
2. **Drop+recreate** des 6 tables source-aware avec FK source → source_registry :
   `coin_observations`, `coin_market_quotes`, `referential_catalog`,
   `coin_canonical_images`, `coin_aliases`, `coin_names_i18n`.

Préserve intégralement : `source_runs`, `source_images`, `image_assets`,
`discovery_*`, `experiment_*`, `cohort_members`, `training_*`,
`augmentation_*`, `benchmark_runs`, `image_asset_dino_predictions`,
`pending_quotes`, `listing_text_signals`, `review_queue`,
`review_claude_verdicts`, `eurio_id_migrations` (patrimoine — 3 rows),
**source_registry** (seedé en P.4), `mints`, `coin_variants`,
`coin_mint_releases`, `coin_source_refs`, `mint_release_prices`,
`mint_release_observations`, `coin_credits`, `coin_edge_variants`.

### 5.2 — DDL post-recreate

Les 6 tables recréées doivent avoir :

- **`source TEXT NOT NULL REFERENCES source_registry(id) ON DELETE RESTRICT`**
- **`source_ref TEXT`** (URL/ID dans la source — déjà ajouté pour observations & market_quotes)
- **`method TEXT`** pour `coin_aliases` + `coin_names_i18n` (split source/method, cf. P.3b)
- Toutes les autres colonnes + indexes + CHECK + PK + UNIQUE intacts

Le script porte les DDL en clair (copier-coller depuis schema.sql en **adaptant**
pour ajouter la FK source sur les 6 tables qui ne l'ont pas encore).

### 5.3 — Garde-fou interactif

```bash
go-task ml:wipe-referential -- --dry-run    # liste les counts, n'écrit rien
go-task ml:wipe-referential -- --apply      # demande confirmation interactive
```

Le mode `--apply` :
1. Crée automatiquement un backup `eurio.db.bak-pre-wipe-{ISO-date}.db`.
2. Affiche les counts à wiper + le diff de schéma à appliquer.
3. Demande `Type "WIPE" to confirm: ` → uppercase exact match obligatoire.
4. Exécute en transaction (BEGIN IMMEDIATE / COMMIT, ROLLBACK on error).
5. Re-vérifie post-wipe : `integrity_check`, `foreign_key_check`, counts à 0
   sur les tables wipées, présence des FK sur les 6 tables recréées.

### 5.4 — Ce que P.6 produit, et ne fait PAS

- ✅ Le script `wipe_referential.py`
- ✅ L'entrée `go-task ml:wipe-referential`
- ✅ Un test du script en `--dry-run` sur la DB courante (vérifie qu'il sait
  bien lister, sans écrire)
- ❌ **NE PAS l'exécuter en `--apply`** durant cette session. Le wipe effectif
  est ultérieur, après V.4 ou avant V.1 selon décision produit.

### 5.5 — Considérations FK sur les 6 tables recréées

Les insertions post-wipe utiliseront le vocabulaire registry grâce à
`registry_map.py` (P.3b). Pour valider, le script peut faire un **smoke insert
synthétique** post-recreate :
- INSERT 1 row dans `coin_observations` avec `source='numista_api'` → doit OK.
- INSERT 1 row avec `source='atlantis'` → doit FK violation.
- ROLLBACK le smoke (pas de pollution).

Si le smoke échoue : recreate cassé. Investiguer avant de tagger P.6 done.

### 5.6 — Critère de succès

- Script écrit, importable
- `--dry-run` produit un rapport listant exactement les tables et counts à wiper
- Smoke insert/FK violation passe en mode test interne
- Script **non exécuté en mode --apply** (à laisser pour plus tard)
- Documentation taskfile à jour

---

## 6. Doctrines à respecter (rappels)

- **SQLite-only** : eurio.db = source de vérité. Pas de touch à `supabase/migrations/`.
- **Provenance first-class** : toute écriture data-aware passe par
  `to_registry_source()` ou un literal du registry. Multi-source = multi-row.
- **Pas de rollback auto** si quelque chose pète : on discute avant de
  remonter du backup.
- **Cohorte clé NID** : ne JAMAIS référencer un eurio_id "promis" en amont du
  refetch. Les eurio_ids sont une *sortie* de la pure function sur le titre
  Numista courant.
- **Chunk-by-chunk + audit visuel** : terminer P.5, livrer, attendre rétro
  utilisateur avant d'attaquer P.6.

---

## 7. Pièges connus à éviter

### 7.1 — Drop d'une table FK-référencée

`source_registry` est référencée par les nouvelles tables (`coin_credits`,
`mint_release_observations`, etc.). Les 6 tables source-aware qu'on drop+recreate
**ne** sont **pas** référencées par les nouvelles tables (les nouvelles tables
référencent `source_registry`, pas `coin_observations`). Donc drop+recreate
des 6 tables est safe — pas de cascade indirecte.

### 7.2 — `PRAGMA foreign_keys=ON` en transaction

Pour que les FK soient enforced pendant le drop+recreate dans la même
transaction, vérifier `PRAGMA foreign_keys=ON` actif (Store le fait au
`_connection`). Sinon les `REFERENCES` deviennent silencieuses.

### 7.3 — `IF EXISTS` sur le DROP

Le script doit utiliser `DROP TABLE IF EXISTS` pour être idempotent (cas où
une row partielle a déjà été créée). Au moment du recreate, `CREATE TABLE`
sans `IF NOT EXISTS` pour failler bruyamment si la table n'a pas été droppée.

### 7.4 — Backup auto avant `--apply`

Le script crée le backup **avant** d'ouvrir la transaction. Si on crashe avant
le COMMIT, on a toujours le backup. Si la transaction commit puis quelque chose
plante derrière, idem.

### 7.5 — `WITHOUT ROWID` sur certaines tables

`coin_national_variants`, `coin_canonical_images`, `cohort_members` ont
`WITHOUT ROWID`. À conserver au recreate (sinon perte d'optim).

---

## 8. Après cette session — quoi vient ensuite ?

| Phase | Chunk | Prérequis |
|---|---|---|
| Décision produit | Décision : **wiper maintenant** ou continuer prep ? | P.5 + P.6 verts |
| (Optionnel) Wipe effectif | `go-task ml:wipe-referential -- --apply` | Backup testé + script validé |
| P.7 | Refacto `refetch_numista_2eur.py` (Supabase → SQLite, `--nids-file`) | P.6 |
| V.1 | Refetch cohorte 19 NIDs | P.7 |
| V.2 | Branchement BCE sur la cohorte | V.1 |
| V.3 | Branchement eBay | V.2 |
| V.4 | Tour admin par Raphaël | V.3 |
| GO/NO-GO | Décision scale 524 | V.4 |

`P.8` (découplage admin Vue ← Supabase → API ml/) et `P.9` (archive legacy)
restent en backlog — peuvent être attaqués en parallèle de V.* ou après.

---

## 9. Glossaire / Cheat sheet

| Terme | Définition |
|---|---|
| **Pipeline source_id** | Identité de l'adapter Python (ex: `'ebay'`). Écrit dans les tables infra (`source_runs.source`, `source_images.source`). Pas FK-bound. |
| **Registry id** | Identité dans `source_registry(id)` (ex: `'ebay_browse'`). Écrit dans les tables data-aware (`coin_observations`, `coin_market_quotes`, etc.). FK-bound post-P.6. |
| **`to_registry_source(pipeline_id)`** | Helper `ml/sources/_base/registry_map.py` qui traduit pipeline → registry. Lève `ValueError` sur unknown. |
| **`source` vs `method`** | `source` = registry id (vraie source). `method` = comment l'info a été dérivée (`'llm_v1'`, `'acronym'`, `NULL` si direct). Applicable à `coin_aliases` et `coin_names_i18n`. |
| **Wipe** | Suppression de toutes les rows référentielles + recreate des 6 tables source-aware avec FK. Acte irréversible (sans backup). |
| **NID-keyed cohort** | Convention : la cohorte 19 est stockée comme liste de NIDs Numista (`ml/state/cohort_validation_19.txt`), pas comme liste d'eurio_ids. Les eurio_ids sont recomputés à chaque refetch. |

---

## 10. État final attendu à la fin de cette session

- ✅ `ml/scripts/verify_backup_restore.py` créé + `go-task ml:verify-backup`
- ✅ Backup `eurio.db.bak-pre-p3-2026-05-25` (existant) restauré dans `/tmp` et vérifié
- ✅ `ml/scripts/wipe_referential.py` écrit + `go-task ml:wipe-referential`
- ✅ `--dry-run` testé sur DB courante (output cohérent, rien écrit)
- ✅ Smoke insert + FK violation testé en mode interne
- ❌ Wipe **NON exécuté** en `--apply`
- ✅ `ROADMAP-DB.md` §0 mis à jour (Session 3 livrée)
- ✅ Branche commit avec message clair `coin-richness P.5+P.6: backup verify + wipe script (non exécuté)`

Si tout est vert, on est prêt pour la **décision produit** "wiper maintenant ?"
et la suite V.* (refetch cohorte).
