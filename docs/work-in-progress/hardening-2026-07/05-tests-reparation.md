# 05 — Réparation de la suite de tests ML (les « 18 rouges connus »)

> Fiche de remédiation auto-portée — hardening 2026-07. Périmètre : `ml/tests/` (pytest),
> plus le constat de couverture manquante côté front et sync. Findings vérifiés le
> 2026-07-04 (lecture code + reproduction pytest réelle, branche `sources-jo-wikipedia`).

## Résumé

Les rouges de la suite pytest ne sont **pas** du bruit homogène. Ils se répartissent en
**trois classes** qui appellent des remèdes opposés :

- **Classe A — tests obsolètes après refacto** : les imports pointent des modules déplacés
  (`test_benchmark.py` → `training/…`) ou des fixtures synthétiques qu'un changement de
  pipeline (YOLO-first) a rendues invisibles (`test_normalize_listing.py`). Le code de prod
  est correct ; c'est **le test qu'on répare**. Conséquence grave quand même : le hold-out
  gate anti-triche et la détection multi-pièces n'ont plus *aucun* test qui passe.
- **Classe B — tests qui révèlent un VRAI bug de prod** : trois cas confirmés, dont un
  **CRITICAL destructeur de données** (`wipe_referential` cascade-delete 5 tables
  « préservées »), un endpoint DELETE dont le guard 409 est mort (décorateur sur la
  mauvaise fonction), et un crash FK garanti sur toute DB fraîche (`source_registry`
  jamais auto-seedé). Ici c'est **le code qu'on corrige** — le test rouge dit la vérité.
- **Classe C — fixtures incomplètes violant un invariant prod** : la fixture omet le lien
  M:N `source_image_runs` que le code de prod maintient partout. Le test échoue pour une
  raison qui n'existe pas en vrai usage → **compléter la fixture** pour qu'elle respecte
  l'invariant, et le documenter.

Traiter les tests rouges comme « connus donc ignorables » a déjà laissé passer : un script
capable d'effacer 20 000+ lignes de données terrain, et un endpoint qui purge les artefacts
d'un entraînement **en cours** sans erreur.

---

> ### ✅ État 2026-07-05 — Classe B (bugs de prod) TRAITÉE
>
> - **#1 CRITICAL `wipe_referential`** — ✅ corrigé (`117ad75`, Option 3 : wipe FK-off).
>   **Le bug était plus large que cette fiche** : pas 5 tables mais **9+** tables FK→coins
>   cascade-détruites (mesuré 20015 lignes) — les 5 P.3a **+** `coin_descriptions_i18n`
>   (~10k i18n), `coin_topics`, `coin_source_status`, `wikipedia_nl_coins`. D'où un
>   post-check par **critère** (orphelin attendu ssi parent ∈ WIPE_TABLES), pas par liste
>   figée. Gate intégrité réel = `foreign_key_check` **post-refetch** (à documenter au runbook).
> - **#2 CRITICAL décorateur DELETE iterations** — ✅ **déjà corrigé** depuis la rédaction de
>   la fiche (décorateur sur `delete_iteration`, guard 409 vivant, `test_delete_iteration` vert).
> - **#3 HIGH `source_registry` non seedé** — ✅ corrigé (`771821c`, seed idempotent au
>   bootstrap via `store/source_registry_seed.py`).
>
> **Reste (Classe A/C, non traité)** : #4 (`test_benchmark` imports plats ×7), #5
> (`test_normalize_listing` cv2 vs YOLO ×4), #6 (fixture `_seed_min_run` M:N), #7 (~~`==10`~~
> ✅ corrigé au passage), #8 (couverture front). + un rouge pré-existant hors fiche :
> `test_eurio_referential::enrich_lmdlp` (import mort `scrape_lmdlp`). Suite : **14 rouges
> pré-existants, 1368 verts** (zéro régression).

## 1. Table des findings

| # | Finding | Classe | Sévérité | Preuve (file:line) | Verdict |
|---|---------|--------|----------|--------------------|---------|
| 1 | `wipe_referential` cascade-supprime 5 tables « préservées » (coin_variants, coin_mint_releases, mint_release_prices, mint_release_observations, coin_credits) | **B** | **CRITICAL** | `ml/scripts/wipe_referential.py:53-64` (WIPE_TABLES incl. `coins`), `:174-179` (`PRAGMA foreign_keys=ON`), `:324` (DELETE) ; `ml/state/schema.sql:1543,1560,1599,1618,1635` (ON DELETE CASCADE) | **Corriger le CODE** |
| 2 | DELETE `/cohorts/{cid}/iterations/{iid}` : décorateur attaché à `_purge_iteration_artifacts`, le vrai handler `delete_iteration` (guard 409 + delete DB) est du code mort | **B** | **CRITICAL** | `ml/serving/lab_routes.py:1035-1036` (décorateur mal placé), `:1055-1066` (handler shadowé, jamais enregistré) ; test rouge `ml/tests/test_lab_api.py:291-306` | **Corriger le CODE** |
| 3 | `source_registry` jamais auto-seedé → `sqlite3.IntegrityError: FOREIGN KEY constraint failed` sur toute DB fraîche dès qu'un run touche `price_aggregate` | **B** | HIGH | `ml/sources/_base/steps/price_aggregate.py:147-153` (INSERT coin_source_refs), `ml/state/schema.sql:1580` (FK RESTRICT), `ml/store/connection.py` `_bootstrap` (exécute schema.sql seul, pas de seed) ; repro : `pytest tests/test_orchestrator.py::test_target_eurio_ids_loops_one_subquery_per_eurio_id` | **Corriger le CODE** |
| 4 | 7 tests de `test_benchmark.py` en `ModuleNotFoundError` : imports `train_embedder` / `check_real_photos` / `evaluate_real_photos` plats, modules déplacés en `training/` et `training/eval/` (refacto `8e2ddc1`) | **A** | MEDIUM | `ml/tests/test_benchmark.py:117,137,172,184,218,252,275` (imports locaux dans les tests) ; vrais chemins : `ml/training/train_embedder.py`, `ml/training/eval/check_real_photos.py`, `ml/training/eval/evaluate_real_photos.py` | **Réparer le TEST** |
| 5 | 4 tests de `test_normalize_listing.py` rouges (`assert 0 == N`) : fixtures = cercles cv2 peints, mais `detect_circles_multi` est passé YOLO-first → YOLO ne voit rien, Hough jamais atteint | **A** | MEDIUM | `ml/vision/normalize_snap.py:817-853` (`_yolo_detect_bboxes` d'abord, Hough seulement dans les bboxes) ; `ml/tests/test_normalize_listing.py` (`_make_listing`) | **Réparer le TEST** (fixtures/mock) |
| 6 | Fixture `_seed_min_run` omet `source_image_runs` → export/ingest échoue en FK, alors que la prod maintient toujours ce lien M:N | **C** | MEDIUM | `ml/tests/test_model_b_c2_c3.py:32-49` ; `ml/client/runbatch.py:148-159` (export via `source_image_runs`) ; `ml/sources/_base/dedup.py:120-133` (invariant prod) | **Réparer le TEST** (fixture) |
| 7 | `test_wipe_referential.py` hardcode `source_registry == 10`, la DB courante en a 11 (source JO) ; test non-hermétique (tourne sur copie de `state/eurio.db`) | **A** | LOW | `ml/tests/test_wipe_referential.py:82` | **Réparer le TEST** |
| 8 | Zéro outillage de test dans le front unique `studio-local` (ni script `test`, ni vitest, aucun `*.test.*`) | — | LOW (dette) | `admin/packages/studio-local/package.json` | **Ajouter couverture** (cf. §5) |

---

## 2. Fiches par finding — action + critère « passe pour la bonne raison »

### 2.1 [B / CRITICAL] `wipe_referential` détruit les tables « préservées » — traité en détail au §3

Voir §3 ci-dessous (options + recommandation).

### 2.2 [B / CRITICAL] Décorateur DELETE iterations sur la mauvaise fonction

**Constat** (`ml/serving/lab_routes.py:1035-1066`) : le commit `82e82735` (2026-06-30) a
inséré `_purge_iteration_artifacts` juste au-dessus de `delete_iteration` en lui volant le
décorateur `@router.delete("/cohorts/{cohort_id}/iterations/{iteration_id}")`. Résultat :

- la route live ne fait **que** `rmtree` les artefacts disque — pas de check `cohort_id`,
  pas de guard `status in ("training","benchmarking")` → 409, pas de
  `store.delete_iteration` ;
- on peut donc supprimer le checkpoint/tflite/embeddings d'un entraînement **en cours**
  (HTTP 200) et la ligne DB de l'itération survit → divergence silencieuse DB↔disque ;
- `delete_iteration` (`:1055`) est du code mort (aucun autre appelant, grep confirmé).

**Action** (code) : déplacer le décorateur sur `delete_iteration(cohort_id, iteration_id)`.
`_purge_iteration_artifacts` redevient un helper interne (elle est déjà appelée en
`:1065`). Ne rien changer d'autre — la logique 404/409/delete est déjà écrite et correcte.

**Critère de vérification** : `tests/test_lab_api.py::test_delete_iteration_forbidden_while_running`
passe **parce que** l'API renvoie 409 sur une itération `status='training'` (pas parce
qu'on aurait assoupli l'assertion). Ajouter/valider aussi le cas nominal : DELETE d'une
itération `done` renvoie `{"deleted": true}`, la ligne DB disparaît **et** les répertoires
`lab/iterations/<iid>` sont purgés ; DELETE avec mauvais `cohort_id` → 404.

### 2.3 [B / HIGH] `source_registry` jamais auto-seedé

**Constat** : `coin_source_refs.source REFERENCES source_registry(id) ON DELETE RESTRICT`
(`ml/state/schema.sql:1580`) et `StoreBase` active `PRAGMA foreign_keys=ON` — la FK est
enforcée **dès aujourd'hui** (le commentaire de `ml/sources/_base/registry_map.py` disant
« FK enclenchée à partir du recreate P.6 » est obsolète et faux). Or `schema.sql` ne seed
rien et `ml/scripts/seed_source_registry.py` n'est appelé nulle part automatiquement.
Toute DB fraîche (nouvelle machine, restore désastre, CI) qui exécute un run touchant
`price_aggregate.py:147-153` crashe en `IntegrityError` opaque, sans try/except, avortant
le COMMIT du run entier. Reproduit réellement :
`tests/test_orchestrator.py::test_target_eurio_ids_loops_one_subquery_per_eurio_id`.

**Action** (code) : appeler le seed (idempotent, `INSERT OR IGNORE`) depuis le bootstrap
du Store (`ml/store/connection.py`, `_bootstrap`, juste après l'`executescript` de
`schema.sql`) — c'est l'option la plus propre : le seed devient une propriété du schéma,
pas un rite manuel. Alternative minimale si on refuse le seed au bootstrap : precondition
dure au démarrage du serving (`SELECT count(*) FROM source_registry`, erreur explicite
« run scripts/seed_source_registry ») — mais ça ne couvre pas les scripts CLI.
Corriger au passage le commentaire obsolète de `registry_map.py`.

**Critère de vérification** : le test d'orchestrator ci-dessus passe **sans** ajouter
d'INSERT manuel dans sa fixture (c'est justement le point : une DB fraîche doit être
utilisable). Contre-vérification : les tests qui seedent déjà manuellement
(`test_runbatch.py`, `test_lmdlp.py`, `test_ebay_standards.py`) restent verts (le seed
est OR IGNORE, pas de double-insert). Nouveau test dédié : Store fraîchement créé sur
`tmp_path` → `SELECT count(*) FROM source_registry` ≥ 10.

### 2.4 [A / MEDIUM] `test_benchmark.py` — imports plats obsolètes

**Constat** : 7 tests importent localement `train_embedder` / `check_real_photos` /
`evaluate_real_photos` (`ml/tests/test_benchmark.py:117,137,172,184,218,252,275`) alors que
le refacto `8e2ddc1` a déplacé ces modules en `ml/training/train_embedder.py`,
`ml/training/eval/check_real_photos.py`, `ml/training/eval/evaluate_real_photos.py`.
Repro : `pytest tests/test_benchmark.py -q` → 7 failed / 4 passed, tous
`ModuleNotFoundError`. Le hold-out gate anti-triche (modèle entraîné sur des photos du
bench) et l'agrégation real-photos n'ont plus **aucune** couverture effective.

**Action** (test) : réécrire les imports en `import training.train_embedder as te`,
`import training.eval.check_real_photos as crp`, `import training.eval.evaluate_real_photos
as erp`. Ne pas toucher aux modules de prod. Si des signatures ont dérivé depuis le
déplacement, adapter les tests à l'API actuelle (et signaler tout comportement suspect
comme finding séparé, pas le rustiner).

**Critère de vérification** : `pytest tests/test_benchmark.py -q` → 11 passed. Pour la
bonne raison : mettre temporairement en échec le gate (ex. inverser la condition dans un
scratch local, ou muter l'input du test) et vérifier que
`test_hold_out_gate_rejects_real_photos` échoue alors — preuve que le test exerce bien la
logique et pas juste l'import.

### 2.5 [A / MEDIUM] `test_normalize_listing.py` — fixtures pré-YOLO

**Constat** : `detect_circles_multi` (`ml/vision/normalize_snap.py:817-853`) appelle
d'abord `_yolo_detect_bboxes` et ne fait tourner Hough **que** dans les bboxes YOLO
(`method="yolo+hough"`). Les fixtures `_make_listing` (cercles pleins cv2) ne sont pas
reconnues par YOLO → `bboxes` vide → 0 détection. 4 tests rouges reproduits
(`assert 0 == N`). Bonus vicieux : `test_detect_returns_circle_detection_dataclass`
asserte `d.method.startswith("hough_")`, chaîne que le pipeline actuel ne produit plus —
il ne « passe » aujourd'hui que parce qu'il itère sur une liste vide.

**Action** (test) :
1. Mocker `_yolo_detect_bboxes` (monkeypatch retournant les bboxes attendues des cercles
   synthétiques) pour isoler et tester le refine Hough + post-filtres — c'est le
   comportement que ces tests visaient réellement.
2. Corriger l'assertion `startswith("hough_")` → `in ("yolo+hough", "yolo+bbox")` (ou
   l'ensemble actuel des méthodes), et la rendre non-vacueuse (`assert detections` avant
   d'itérer).
3. Optionnel mais recommandé : 1 test d'intégration avec une vraie image de pièces (si un
   jeu existe sous `ml/tests/fixtures/`) marqué `@pytest.mark.slow`, qui exerce YOLO réel.

**Critère de vérification** : les 4 tests passent avec YOLO mocké **et** un test
sentinelle échoue si on casse volontairement le post-filtre Hough (mêmes précautions que
2.4). Le test dataclass échoue désormais si `detections` est vide.

### 2.6 [C / MEDIUM] Fixture `_seed_min_run` viole l'invariant M:N `source_image_runs`

**Constat** : `ml/tests/test_model_b_c2_c3.py:32-49` insère `source_images` +
`image_assets` mais jamais le lien `source_image_runs`. Or `export_run`
(`ml/client/runbatch.py:148-159`) collecte les `source_images` **strictement** via
`source_image_id IN (SELECT … FROM source_image_runs WHERE run_id=?)` → export avec
`image_assets` orphelines → `ingest_run` échoue en FK au COMMIT (`runbatch.py:385`).
En prod cet état n'existe jamais : `ml/sources/_base/dedup.py:120-133` maintient
systématiquement le lien (`INSERT OR IGNORE INTO source_image_runs`), et le commentaire de
`runbatch.py:~136-138` documente ce containment comme invariant intentionnel.

**Action** (test) : ajouter dans `_seed_min_run` un
`INSERT INTO source_image_runs (source_image_id, run_id) VALUES (?, ?)` reflétant ce que
fait `dedup.py`. Ajouter un commentaire pointant l'invariant (dedup.py) pour que la
prochaine fixture ne refasse pas l'erreur.

**Critère de vérification** : les tests de `test_model_b_c2_c3.py` passent **parce que**
l'export contient bien la `source_image` parente et que l'ingest committe — pas parce
qu'on aurait affaibli les assertions ou désactivé les FK. Vérifier dans le test que la
table exportée `source_images` est non vide (assertion explicite, qui aurait attrapé le
bug de fixture d'emblée).

### 2.7 [A / LOW] Assertion hardcodée `source_registry == 10`

**Constat** : `ml/tests/test_wipe_referential.py:82` asserte un compte exact de 10, la DB
courante en a 11 (ajout source JO/EUR-Lex, branche `sources-jo-wikipedia`). Le test tourne
sur une **copie de `ml/state/eurio.db`** (état mutable), pas une fixture figée : toute
évolution légitime du registry le casse.

**Action** (test) : remplacer par une assertion d'invariant réel — soit
`>= 10`, soit mieux : vérifier que l'**ensemble** des ids canoniques attendus est un
sous-ensemble du registry (`{"numista","bce",…} <= {row ids}`). À moyen terme, faire
tourner ces tests sur une fixture SQL dédiée plutôt que sur l'état vivant de
`state/eurio.db` (hermeticité) — à faire en même temps que §3, puisque les deux tests
partagent ce socle.

**Critère de vérification** : le test reste vert après ajout d'une 12e source, et rouge
si une source canonique disparaît du registry.

---

## 3. Traitement spécial — `wipe_referential` (CRITICAL, destructeur)

### Le bug

`apply()` (`ml/scripts/wipe_referential.py:298-324`) ouvre sa connexion via `_connect()`
qui active `PRAGMA foreign_keys=ON` (`:174-179`), puis exécute `DELETE FROM` sur les 10
`WIPE_TABLES` (`:53-64`), dont **`coins`**. Or `ml/state/schema.sql` déclare avec
`ON DELETE CASCADE` :

| Table « préservée » | FK cascade | schema.sql |
|---|---|---|
| `coin_variants` | `parent_type_id → coins(eurio_id)` | :1543 |
| `coin_mint_releases` | `parent_type_id → coins(eurio_id)` | :1560 |
| `mint_release_observations` | `mint_release_id → coin_mint_releases(id)` | :1599 |
| `mint_release_prices` | `mint_release_id → coin_mint_releases(id)` | :1618 |
| `coin_credits` | `eurio_id → coins(eurio_id)` | :1635 |

Aucune de ces 5 tables n'est dans `WIPE_TABLES` ni dans `RECREATE_DDL` — rien ne les
protège du cascade. **Mesuré sur copie de la vraie DB (2026-07-04)** après un simple
`apply()` : `coin_mint_releases` 3312→0, `mint_release_prices` 12161→0,
`mint_release_observations` 3246→0, `coin_credits` 1350→0, `coin_variants` 10→0.
Le docstring (`:28-31`) et `test_wipe_referential.py` affirment pourtant que ces tables
sont préservées — les tests `test_apply_wipes_and_recreates` et
`test_apply_preserves_infra` sont rouges et **disent vrai**. Le backup auto (`:294-295`)
limite la casse mais ne protège pas la DB live elle-même.

### Les 3 options

**Option 1 — Sauvegarder puis réinsérer les 5 tables autour du DELETE.**
Avant le `DELETE FROM coins` : copier les 5 tables dans des tables temporaires
(`CREATE TEMP TABLE _keep_x AS SELECT * FROM x`) ; après le wipe+recreate : réinsérer.
*Risque* : les lignes réinsérées référencent des `eurio_id` / `mint_release_id` qui
n'existent plus après le wipe (le but du wipe est justement de refetch les coins) →
soit on désactive les FK à la réinsertion (et on obtient une DB avec FK orphelines, pire
que tout), soit la réinsertion échoue. Complexe, fragile, et sémantiquement bancal : des
`coin_variants` sans parent `coins` n'ont pas de sens. **Déconseillé.**

**Option 2 — Inclure explicitement les 5 tables dans le wipe scope documenté.**
Les ajouter à `WIPE_TABLES`, mettre à jour docstring + tests + ROADMAP-DB.md §8 : le wipe
du référentiel emporte aussi l'infra P.3a dépendante de `coins`.
*Risque* : **perte assumée de données terrain difficilement re-fetchables** —
`mint_release_prices` (12k lignes LMDLP) et `mint_release_observations` (3.2k) se
re-scrapent, mais c'est du travail et de l'historique d'observation ; `coin_credits`
(1.3k) et `coin_variants` idem. On transforme un bug en feature destructrice. Acceptable
seulement si le PO confirme que ces données sont intégralement régénérables par les
pipelines existants. **Second choix, sur décision PO uniquement.**

**Option 3 — Désactiver les FK le temps du DELETE (recommandée).**
Dans `apply()`, exécuter le wipe avec `PRAGMA foreign_keys=OFF` (le pragma est
hors-transaction en SQLite : le poser avant le `BEGIN`), faire les
`DELETE FROM` + `DROP/CREATE`, réactiver `PRAGMA foreign_keys=ON`, puis — c'est le point
clé — s'appuyer sur le **post-check `PRAGMA foreign_key_check` déjà présent** dans le
script (`:19-20` du docstring, étape 4) pour lister les orphelins. Les 5 tables gardent
leurs lignes ; leurs FK vers `coins` redeviennent valides quand le refetch réinsère les
mêmes `eurio_id` (c'est le contrat du wipe : mêmes ids canoniques, contenu rafraîchi —
cf. la recette wipe+refetch+remap déjà pratiquée dans le repo).
*Risque* : fenêtre où la DB contient des FK orphelines si le refetch échoue ou si des
`eurio_id` disparaissent du référentiel amont. Mitigation : (a) le backup auto existe
déjà ; (b) faire du `foreign_key_check` post-refetch un gate bloquant documenté dans le
runbook du wipe ; (c) logger le diff d'`eurio_id` orphelins à la fin d'`apply()` pour
qu'il soit impossible de le rater.

**Recommandation : Option 3.** C'est la seule qui respecte à la fois l'intention
documentée (« tables préservées ») et la nature des données (rattachées par id canonique
stable, pas par lignes parentes). Elle demande le moins de code, réutilise le post-check
existant, et le risque résiduel est contrôlable par le gate `foreign_key_check`.
Dans tous les cas : mettre à jour le docstring (`:28-31`) pour décrire le mécanisme
réellement en place.

**Critère de vérification** : `test_apply_wipes_and_recreates` et
`test_apply_preserves_infra` passent **parce que** les counts des 5 tables sont identiques
avant/après `apply()` sur une copie de DB réelle (c'est déjà ce qu'ils vérifient — ne pas
toucher leurs assertions, sauf le `== 10` du §2.7). Ajouter une assertion :
`PRAGMA foreign_key_check` post-apply ne remonte que des orphelins attendus (vers `coins`
wipée), et zéro après un refetch simulé.

---

## 4. Priorités et effort

| Prio | Item | Classe | Effort estimé | Pourquoi d'abord |
|---|---|---|---|---|
| **P0** | §3 wipe_referential (option 3) | B | ~2-3 h (code + tests + docstring + runbook) | Data-loss réel, script destructeur exécutable aujourd'hui |
| **P0** | §2.2 décorateur DELETE iterations | B | ~30 min (déplacer un décorateur + valider tests) | Purge d'artefacts d'un training en cours + divergence DB↔disque, fix trivial |
| **P1** | §2.3 seed source_registry au bootstrap | B | ~1 h (bootstrap + test dédié + fix commentaire registry_map) | Crash garanti sur DB fraîche (restore/CI/nouvelle machine) |
| **P2** | §2.4 imports test_benchmark | A | ~30-45 min | Restaure la couverture du hold-out gate anti-triche |
| **P2** | §2.5 fixtures test_normalize_listing (mock YOLO) | A | ~1-2 h | Restaure la couverture détection multi-pièces (cœur scrape) |
| **P3** | §2.6 fixture source_image_runs | C | ~20 min | Débloque les tests Model B C2/C3 |
| **P3** | §2.7 assertion == 10 | A | ~10 min | Hygiène, dans la foulée du §3 |
| **P4** | §5 couverture manquante | — | par chunks 30 min-3 h | Dette structurelle, à planifier |

Règle de séquencement : **classe B d'abord** (data-loss et corruption silencieuse), puis
A (restaurer la couverture perdue), puis C, puis la dette §5. Chaque item = un chunk
livrable indépendamment ; objectif final : `pytest ml/tests -q` **0 rouge**, et la notion
de « rouges connus » disparaît (un rouge redevient un signal, pas du bruit).

---

## 5. Manque structurel — zones critiques sans aucun test

Au-delà des rouges, la revue relève des trous de couverture sur des chemins critiques :

### 5.1 Sync / réplique (Direction A, déployée live 2026-07-04) — zéro test
Le mécanisme writer-unique VPS + réplique `sqlite3_rsync` (thread autopull `server.py`,
scripts timers) n'a aucun test alors qu'il vient de subir un piège réel (« rc=0 no-op »,
cf. commit `1594d30`). Couverture minimale à ajouter :
- test du wrapper pull : stderr non vide ⇒ échec (régression directe du fix `1594d30`) ;
- test qu'un pull no-op (réplique déjà fraîche) est distingué d'un pull échoué ;
- test d'intégration légère : DB source modifiée → pull → la réplique reflète le delta.

### 5.2 Enforcement read-only du Store — zéro test
`EURIO_DB_READONLY` est câblé dans `StoreBase` (durcissement Direction A) mais rien ne
vérifie qu'un Store read-only **refuse** une écriture. Un contournement futur (nouvelle
méthode d'écriture qui bypasse le garde) passerait inaperçu. Ajouter : test paramétré qui
instancie le Store en read-only et vérifie qu'un échantillon représentatif de méthodes
d'écriture (une par famille de store sous `ml/store/`) lève l'erreur attendue, et qu'une
lecture passe.

### 5.3 Endpoints serving — couverture partielle et trouée
`test_lab_api.py` existe mais le bug §2.2 montre le trou : **aucun test ne vérifie la
table de routage elle-même**. Ajouter un test de contrat peu coûteux : itérer
`app.routes` et asserter que chaque paire (méthode, path) attendue est bien liée à la
fonction attendue (`route.endpoint.__name__`) — ce test seul aurait attrapé le décorateur
volé. Compléter par des smoke tests TestClient sur les routes de mutation non couvertes.

### 5.4 Front `studio-local` — zéro test (finding #8)
Le front unique (déployé en local **et** hébergé) n'a ni script `test`, ni vitest, ni
aucun fichier `*.test.*` (`admin/packages/studio-local/package.json`). Couverture minimale
recommandée (vitest, cohérent Vite) :
- `stores/capabilities.ts` : gating `hasLocalMlApi` (baseline deploy-target + ping 8042) —
  c'est ce qui grise le lourd en hébergé, une régression casse le contrat R0bis ;
- `shared/config/deploy-target.ts` + `shared/api/eurio-api.ts` : choix Bearer/PAT vs
  cookie `credentials:'include'` selon `VITE_DEPLOY_TARGET` — une régression = fuite de
  mode d'auth ;
- le marquage `meta.heavy` du router : test qui liste les routes tapant `:8042` et vérifie
  qu'elles portent `meta.heavy` (même esprit que 5.3).

### 5.5 Android — tests JVM présents mais aucun test d'intégration scan
`app-android/src/test/` compte ~15 fichiers JVM, mais rien sur le pipeline scan
(consensus buffer 5/3, normalize Kotlin) côté instrumentation. Hors périmètre de cette
fiche (chantier dédié), mais à inscrire au backlog hardening.

---

*Fiche produite par revue vérifiée (exécutions pytest réelles + lecture code aux
file:line cités). Aucun fichier de code modifié.*
