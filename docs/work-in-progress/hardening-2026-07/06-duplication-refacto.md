# 06 — Duplication & briques à factoriser (DRY)

> **Fiche de remédiation** — audit hardening 2026-07. Objectif : **robustesse par refacto**, pas de
> nouvelles features. Chaque finding est vérifié par lecture directe du code (preuves `file:line`).

## Résumé

Le repo contient plusieurs **briques implémentées N fois** au lieu d'une : le même bug devra être
corrigé N fois, et rien (aucun test) ne détecte quand les copies divergent. Quatre briques
identifiées, par ordre de risque décroissant :

1. **Contrat `app_core`** (le plus critique) : la liste de colonnes + l'algorithme de nesting du
   Snapshot v2 sont maintenus **à la main dans 3 langages** (Python producteur, TS proto live, SQL
   Kotlin Android) sans source unique ni test de contrat. Un rename de colonne casse
   **silencieusement l'APK** (exception au bootstrap catalogue) et le proto live.
2. **fetch-with-daily-cache-and-ratelimit** : copié 3× dans les adapters sources (BCE, LMDLP, JO),
   avec gestion 404 déjà divergente entre les copies.
3. **Reap PID-liveness** : le helper canonique `jobs._pid_alive` existe et est utilisé ailleurs,
   mais 2 fonctions de `lab_routes.py` le réimplémentent inline byte-for-byte (3 copies au total),
   avec 3 constantes de seuil distinctes pour le même concept.
4. **Pattern transactionnel manuel** BEGIN/COMMIT/ROLLBACK : 6 occurrences dans `ml/review/` qui
   contournent `store._writing()` — donc **sans `_write_lock`**, s'exposant au `database is locked`
   sporadique sous concurrence ; le service voisin `review_service` a déjà un bug réel de
   double-ROLLBACK causé par ce même pattern manuel.

S'y ajoutent : les variantes quasi-dupliquées `crop_exp/` (dette de lab), et l'**absence totale de
tests** sur JO/wiki (matching fuzzy + overrides manuels + parsing HTML fragile).

---

## Table des findings

| # | Sévérité | Emplacements (preuves) | Finding |
|---|---|---|---|
| D1 | **medium** (impact haut : casse APK silencieuse) | `ml/export/build_app_core.py:53` (`_COIN_COLS`), `:63` (`_fetch`), `:80` (`_group_by`), `:117-161` (`build_json`, `schema_version: 2`) ↔ `admin/packages/proto/src/api/loader.ts:64-68` (`COIN_COLS`), `:71` (`pgFetchAll`), `:94` (`groupBy`), `:107-168` (`loadLive`, `schema_version: 2`) ↔ `app-android/src/main/java/com/musubi/eurio/data/local/bootstrap/AppCoreBootstrapper.kt:117` (SQL brut + `getColumnIndexOrThrow` par nom) | Contrat app_core ré-implémenté en Python + TS + SQL Kotlin, synchronisé à la main (`loader.ts:56` : « ⚠️ DOIT REFLÉTER ml/export/build_app_core.py… mettre à jour les deux »). Zéro test croisé (grep `COIN_COLS`/`_COIN_COLS` dans `ml/tests` et proto = 0 ; proto n'a aucun `*.test.ts`). |
| D2 | medium | `ml/sources/jo/adapter.py:295-314` (`_fetch_notice`) ↔ `ml/sources/bce/adapter.py:260-285` (`_fetch_year`) ↔ `ml/sources/lmdlp/adapter.py:217-254` | Brique fetch HTTP + cache journalier `_SNAPSHOTS_DIR / f"{source}_…_{date.today()}.ext"` + `time.sleep(self.sleep)` copiée 3× ; `ml/sources/_base/adapter.py` (point de factorisation naturel) ne contient que le Protocol + dataclasses. Gestion 404 déjà divergente (JO → `None` ; BCE → tuple `(None,404,False)` ; LMDLP → aucune). |
| D3 | medium | `ml/jobs/reaper.py:24-33` (`_pid_alive`, canonique) ↔ `ml/serving/lab_routes.py:2588-2599` (`reap_orphan_training_scans`, inline) ↔ `lab_routes.py:2729-2740` (`reap_orphan_cohort_jobs`, inline) — alors que `lab_routes.py:3296` et `sources_routes.py:2646` appellent déjà `jobs._pid_alive` | Boucle `try/os.kill(pid,0)/except PermissionError→True/except (ProcessLookupError,OSError,ValueError)→False` réimplémentée byte-for-byte 2× dans le même fichier qui importe déjà le helper. 3 seuils distincts (`_TRAINING_SCAN_MAX_RUNTIME_MIN=60`, `_RECROP_MAX_RUNTIME_MIN=60`, `DEFAULT_MAX_RUNTIME_MIN=24*60` à `reaper.py:21`) sans justification de la divergence. |
| D4 | low (mais bug réel prouvé dans le pattern jumeau) | `ml/review/review_queue_routes.py:1061, 1841, 1945, 2414, 3547` + `ml/review/peer_arbitration_routes.py:162` (BEGIN/COMMIT/ROLLBACK manuels) vs `ml/store/connection.py:670-680` (`_writing()`, canonique, acquiert `_write_lock`) — usage correct existant : `publish_cli.py:206`, `peer_arbitration_routes.py:264` | 6 blocs transactionnels manuels qui n'acquièrent pas `_write_lock` → contournent la sérialisation applicative des écritures, risque `database is locked` sporadique. Le même pattern manuel a déjà produit un bug réel de double-ROLLBACK (409→500) dans `ml/review_service/routes_reviewer.py:172-177` + `db.py:69-80`. |
| D5 | low | `ml/scripts/crop_exp/` : `sampler.py`, `sampler_v2.py`, `sampler_by_score.py`, `sampler_inner.py`, `sampler_inner_singles.py`, `score_crops.py`, `score_crops_v2.py`, `score_crops_bg.py`, `score_crops_inner.py` | 8 scripts quasi-dupliqués (docstring `sampler_v2.py` : « Identique à sampler_by_score mais lit le sidecar v2 ») ; chacun refait sa boucle fetch + `API="http://localhost:8042"`. |
| D6 | low | `ml/sources/jo/adapter.py:326-327` ↔ `ml/referential/scrape_wikipedia_coins.py:206-207` | Parsing du suffixe slug d'`eurio_id` (`parts = eid.split("-", 3); slug = parts[3] if len(parts) == 4 else ""`) dupliqué, dégradation silencieuse en `slug=""` (→ `slug_score('',…)=0.0`) si le format change, sans log dans aucun des deux. |
| T1 | medium (test) | `ml/sources/jo/adapter.py:74` (`MANUAL_JO_OVERRIDES`), `:192` (fuzzy matcher), `ml/sources/jo/parser.py:64` (`_capture_between`), `ml/referential/scrape_wikipedia_coins.py:78` (`MANUAL_OVERRIDES`), `:217` (`_expand_joint`) | **Aucun test** pour JO ni wiki (`find ml/tests -iname '*jo*' -o -iname '*wiki*'` → seul `test_jobs_rail.py`, sans rapport) malgré matching complexe + parsing HTML fragile. Voir §6. |

---

## Briques et plans de remédiation

### (a) fetch-with-daily-cache-and-ratelimit → extraire dans `ml/sources/_base/`

**Duplication à refactorer** (même langage, même package). Les 3 adapters reproduisent :
`USER_AGENT` littéral par source → `cache = _SNAPSHOTS_DIR / f"{source}_{key}_{date.today().isoformat()}.{ext}"`
→ `if cache.is_file(): return …` → `httpx.get(url, headers={"User-Agent": USER_AGENT}, …)` →
`time.sleep(self.sleep)` → écriture cache. Tout correctif (TTL, sanitisation du nom de fichier —
JO fait déjà un `celex.replace("/", "_")` ad hoc à `jo/adapter.py:297` —, retry, statuts HTTP)
doit aujourd'hui être porté 3 fois.

**Plan**
1. Créer `ml/sources/_base/http_cache.py` : une fonction/classe unique
   `fetch_cached(source: str, key: str, url: str, *, ext: str, sleep: float, user_agent: str, on_404: … ) -> str | bytes | None`
   — cache journalier dans `_SNAPSHOTS_DIR`, sanitisation de `key`, rate-limit, politique 404
   **explicite et unifiée** (retour `None` + log ; les appelants qui ont besoin du statut le
   reçoivent via un petit résultat structuré, pas 3 conventions ad hoc).
2. Migrer JO (`_fetch_notice`), BCE (`_fetch_year`), LMDLP (`fetch_all_2eur`) dessus — le delta
   par source se réduit à (url template, ext, politique 404).
3. Décider si la divergence 404 actuelle était voulue ; sinon l'unifier au passage.

**Critère de vérification**
- Test unitaire de `http_cache.py` (cache hit/miss, 404, sanitisation, sleep mocké).
- Garde d'unicité : test qui grep les adapters `ml/sources/*/adapter.py` et échoue si l'un
  contient à la fois `date.today().isoformat()` et `httpx.get(` hors `_base/` (aucune ré-implé
  locale de la brique).

### (b) reap PID-liveness → `jobs._pid_alive` partout + boucle SELECT/UPDATE factorisée

**Duplication à refactorer.** `lab_routes.py` importe déjà `jobs` et appelle `jobs._pid_alive`
ligne 3296 ; les copies inline de `reap_orphan_training_scans` (2588-2599) et
`reap_orphan_cohort_jobs` (2729-2740) sont donc gratuites à supprimer.

**Plan**
1. Remplacer les deux blocs inline par `jobs._pid_alive(pid)` (import déjà présent). Promouvoir le
   helper en nom public (`pid_alive`) si on veut éviter l'accès `_underscore` cross-module.
2. Factoriser la boucle « SELECT running → liveness+âge → UPDATE failed » de `reaper.reap_orphans`
   (`ml/jobs/reaper.py:36-…`) en une fonction paramétrée `(conn, table, max_runtime_min,
   status_col/…)` réutilisée par les 3 reapers.
3. Trancher les seuils : soit une constante partagée avec override par table (documenté), soit
   documenter pourquoi training_scans/recrop = 60 min et jobs = 24 h.

**Critère de vérification**
- Test qui échoue si `os.kill(` apparaît dans `ml/serving/lab_routes.py` (la primitive liveness
  ne doit exister qu'à un endroit : `ml/jobs/reaper.py`).
- Test du reaper factorisé : PID mort → reaped, PID vivant + âge < seuil → intact, PID vivant +
  âge > seuil → reaped (déjà partiellement couvert par `test_jobs_rail.py`, à étendre aux tables
  `cohort_training_scans`/`cohort_jobs`).

**Lien** : le finding serving « guard anti-double-run cassé par `--reload` » (`server.py:1144-1176`
export tflite, `:1393-1456` confusion-map — état dans dicts globaux `_export_status`/`_confusion_status`,
pas de PID persisté) se corrige avec la **même brique** : Popen détaché + PID en DB + reaper
factorisé. Traiter (b) d'abord rend cette correction triviale.

### (c) transactions manuelles → `store._writing()`

**Duplication à refactorer**, avec un bug déjà matérialisé dans le pattern jumeau : dans
`ml/review_service/`, le ROLLBACK manuel avant `raise HTTPException(409)`
(`routes_reviewer.py:172-177`) suivi du second ROLLBACK du context manager (`db.py:69-80`) lève
`sqlite3.OperationalError: cannot rollback - no transaction is active` → le 409 devient un 500
opaque. Les 6 blocs manuels de `ml/review/` (`review_queue_routes.py:1061, 1841, 1945, 2414, 3547` ;
`peer_arbitration_routes.py:162`) courent le même risque de classe ET n'acquièrent pas
`self._write_lock` (contrairement à `store._writing()`, `ml/store/connection.py:670-680`), donc
peuvent se chevaucher avec les écritures `_writing()`-based du même process.

**Plan**
1. Remplacer les 6 blocs par `with store._writing() as conn:` (envisager de le promouvoir en API
   publique `writing()` au passage). Conserver la distinction `except HTTPException: raise`
   AVANT le catch générique (le bon pattern existe déjà à `review_queue_routes.py:2014`).
2. Corriger le bug review_service dans la foulée : supprimer le `conn.execute("ROLLBACK")` manuel
   de `routes_reviewer.py:173` (laisser `writing()` rollbacker), ou ajouter
   `except HTTPException: raise` dans `db.py.writing()`.
3. Doc-drift associé à corriger dans le même chantier :
   `docs/work-in-progress/collaborative-review/README.md:3` dit « Rien n'est implémenté » alors
   que `ml/review_service/` est complet et testé E2E — mettre le statut à jour pour que le
   prochain lecteur ne ré-implémente pas.

**Critère de vérification**
- Test qui échoue si `execute("BEGIN")` apparaît dans `ml/review/*.py` hors `store/connection.py`
  (unicité du pattern transactionnel).
- Test de régression du 409 : deux `decide` concurrents sur le même item → le perdant reçoit 409,
  pas 500.

### (d) Contrat `app_core` — LA priorité (risque de casse silencieuse APK)

**Trois implémentations du même contrat, dont une seule duplication est légitime.**

| Implémentation | Rôle | Verdict |
|---|---|---|
| `ml/export/build_app_core.py:53-161` — `_COIN_COLS`, `_fetch`, `_group_by`, `build_json` | **Producteur** canonique (JSON proto + `app_core.db` APK, `:206 build_sqlite`) | Source de vérité |
| `admin/packages/proto/src/api/loader.ts:56-168` — `COIN_COLS`, `pgFetchAll`, `groupBy`, `loadLive` | Mode « live » du proto : re-dérive **le même Snapshot v2** en re-fetchant PostgREST | **Duplication à refactorer** — pas une frontière de langage : le mode `fixtures` du même loader consomme déjà le JSON produit par `build_json` ; le mode live ne fait que ré-implémenter le producteur en TS. Le commentaire `loader.ts:56-58` (« mettre à jour les deux ») est l'aveu du problème, pas une solution. |
| `AppCoreBootstrapper.kt:117` — SQL brut, `getColumnIndexOrThrow` par nom de colonne | **Consommateur** Kotlin de `app_core.db` | **Duplication LÉGITIME** (frontière de langage inévitable : Kotlin doit lire le SQLite) — mais elle doit être **verrouillée par un contrat testé**, pas synchronisée à l'œil. |

**Scénario d'échec actuel** (rien en CI ne le détecte) : un dev renomme une colonne dans
`_COIN_COLS` (ex. `edge_lettering`) et regénère fixtures + `app_core.db`. Le proto live demande
l'ancien nom → 400 PostgREST ou champ manquant ; Android `getColumnIndexOrThrow("edge_lettering")`
lève au bootstrap → **catalogue APK cassé au premier lancement**. Vérifié : aucun test ne référence
`COIN_COLS`/`_COIN_COLS` (grep vide dans `ml/tests` et `admin/packages/proto` ; le proto n'a aucun
`*.test.ts`/`*.spec.ts`).

**Plan (deux volets complémentaires)**
1. **Supprimer la duplication TS** : le mode `live` du proto ne re-fetch plus PostgREST. Deux
   options, au choix du PO :
   - (simple, recommandé) `loadLive()` télécharge l'`app_core.json` bâti (servi par eurio-api ou
     un bucket), c.-à-d. le même artefact que le mode fixtures mais frais → `loader.ts` perd
     ~110 lignes dupliquées et ne peut plus diverger ;
   - (si le re-fetch direct est vraiment voulu) le garder mais alimenté par le manifeste du
     volet 2.
2. **Émettre un manifeste de contrat** depuis le producteur : `build_app_core.py` écrit
   `app_core.manifest.json` (colonnes par table, `schema_version`, clés de nesting). Ce manifeste
   devient l'input de :
   - un test Python qui assert `manifest == _COIN_COLS + …` (trivial, même fichier) ;
   - un test/lint proto qui assert `COIN_COLS === manifest.coin_cols` (tant que le volet 1
     option simple n'a pas rendu `COIN_COLS` inutile) ;
   - un **test de contrat Android** : extraire les identifiants de colonnes référencés par le SQL
     de `AppCoreBootstrapper.kt` (test JVM unit simple, ou script Node dans `scripts/` comme
     `tokens:check`) et vérifier qu'ils ⊆ manifeste. Câblé en CI à côté de `go-task tokens:check`
     (précédent existant dans le repo pour « généré + check en CI »).

**Critère de vérification**
- Renommer une colonne dans `_COIN_COLS` sans toucher au reste **doit faire échouer la CI**
  (test manifeste↔proto et manifeste↔SQL Android). C'est le verrou d'unicité.
- Suppression effective du bloc `pgFetchAll`/`groupBy`/`loadLive` dupliqué si option simple retenue.

**Note d'opportunité** : ce chantier croise la doctrine « Supabase retiré du front » — le mode
live proto utilise `VITE_SUPABASE_ANON_KEY` (`loader.ts:108`), marqué pour purge. L'option simple
du volet 1 supprime cette dépendance en même temps que la duplication.

### (e) `crop_exp/` — variantes de lab quasi-dupliquées

8 scripts (`ml/scripts/crop_exp/sampler*.py`, `score_crops*.py`) refont chacun fetch +
`API="http://localhost:8042"`. Dette de lab, pas un bug actif — mais elle grossit à chaque
itération de l'ablation crop.

**Plan** : (1) factoriser fetch/scoring commun dans `crop_exp/_common.py`, ne garder que les
deltas tri/filtre par script ; (2) **ou**, si l'ablation crop est tranchée (cf. mémoire « crop
différé jusqu'au bench »), archiver les variantes obsolètes sous `ml/archive/scripts/` comme fait
pour les chantiers conclus. **Critère** : ≤ 2 scripts vivants dans `crop_exp/`, zéro littéral
`http://localhost:8042` hors `_common.py`.

⚠️ Précédent à ne pas reproduire lors de l'archivage : le cleanup `ef3e740` a archivé
`scripts/migrate_canonical_images_local.py` alors que `serving/referential_routes.py:959` (discover)
et `:1012` (heal) l'invoquent encore en subprocess → 500 sur deux endpoints live. Avant d'archiver
un script `crop_exp`, grep ses invocations (`python -m scripts.…`, Taskfile, serving).

### (f) slug d'`eurio_id` (D6, opportuniste)

Extraire `theme_slug_of(eurio_id)` (un seul endroit, ex. `ml/referential/` ou `_base/slug_match.py`
qui existe déjà) avec **log warning si `len(parts) != 4`** au lieu du fallback muet `""`, et
l'appeler depuis `jo/adapter.py:326-327` et `scrape_wikipedia_coins.py:206-207`. À faire dans le
même commit que (a) — mêmes fichiers touchés.

---

## Tests manquants JO / Wikipedia (T1)

`find ml/tests -iname '*jo*' -o -iname '*wiki*'` ne retourne que `test_jobs_rail.py` (job runner
générique, sans rapport). Or ce code porte une logique fine à régression **silencieuse** :

- `MANUAL_JO_OVERRIDES` (`ml/sources/jo/adapter.py:74`, dict `[(country, year, slug)] → eurio_id`,
  consommé par le matcher fuzzy `:192`) et `MANUAL_OVERRIDES`
  (`ml/referential/scrape_wikipedia_coins.py:78`, utilisé `:270` et `:345`) : une clé légèrement
  fausse après un changement de titre ne lève **aucune erreur** — l'override ne matche plus et
  retombe en fuzzy, indétectable.
- `_expand_joint` (`scrape_wikipedia_coins.py:217`) : dépliage des émissions communes UE.
- `_capture_between` (`ml/sources/jo/parser.py:64`) : parsing regex du HTML Formex EUR-Lex, format
  non garanti — une évolution de format romprait `is_commemorative_2euro`/`subject`/`year` sans
  détection avant le prochain run réel.

**Minimum viable** (aligné doctrine « preuve-first ») :
1. Fixtures HTML : 2-3 notices JO réelles gelées dans `ml/tests/fixtures/jo/` → test golden de
   `parser.py` (subject/year/celex extraits attendus).
2. Test d'intégrité des overrides : chaque clé `(country, year, slug)` de `MANUAL_JO_OVERRIDES` /
   `MANUAL_OVERRIDES` doit résoudre vers un `eurio_id` existant du référentiel (fixture ou snapshot
   de la table `coins`) — transforme la dégradation silencieuse en échec de test.
3. Cas limites du matching : override prioritaire sur fuzzy, fuzzy sous seuil → non-match explicite,
   `_expand_joint` sur une émission commune connue (ex. TOR 2007).

---

## Effort & priorité

| Ordre | Brique | Effort | Pourquoi cet ordre |
|---|---|---|---|
| **1** | (d) Contrat app_core (manifeste + test croisé, puis proto consomme le JSON bâti) | 0,5-1 j | **Risque de casse silencieuse APK** : c'est le seul finding où une modif banale casse le produit shippé sans qu'aucun signal n'existe. Le test de contrat (volet 2) seul est ~2-3 h et verrouille immédiatement. |
| 2 | (c) `_writing()` dans review/ + fix double-ROLLBACK review_service | ~0,5 j | Bug utilisateur réel déjà prouvé (409→500) + risque `database is locked` ; correctif mécanique, périmètre fermé (6+1 sites). |
| 3 | (b) `_pid_alive` + reaper factorisé | ~0,5 j | Quasi-gratuit (helper déjà importé) ; débloque la correction du guard export/confusion-map cassé par `--reload` avec la même brique. |
| 4 | (a) `_base/http_cache.py` + (f) slug helper | 0,5-1 j | 3 sources migrées + unification 404 ; à faire avant d'ajouter une 4e source (le coût de la duplication croît linéairement). |
| 5 | (T1) Tests JO/wiki | 0,5-1 j | Fixtures golden + intégrité overrides ; idéalement dans la même PR que (a) puisque les adapters bougent. |
| 6 | (e) `crop_exp/` | 2-3 h | Dette de lab, aucun chemin prod ; attendre que l'ablation crop soit tranchée peut suffire (archivage > factorisation). |

**Total estimé : ~3-4 jours**, découpables en chunks 30 min-3 h conformément à la convention
chunk-by-chunk du repo (livrer + attendre rétro entre chaque brique).
