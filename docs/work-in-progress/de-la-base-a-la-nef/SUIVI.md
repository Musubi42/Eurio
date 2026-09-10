# SUIVI — de la base à la nef

> Journal daté. Chaque étape y dépose son contrat, le rapport de l'exécutant, le
> contre-rapport, et le verdict de l'architecte. Rien ne se ferme sans les trois.

## 2026-09-10 — Ouverture

Chantier ouvert sur le constat du même jour (`PLAN.md` §Constat). Six décisions
proposées dans `DECISIONS.md`, D5 laissée ouverte. **En attente du PO** : D0 (gel de
l'atelier) et D1 (feu vert sur la suppression des branches distantes et le retrait de
`codeberg`). L'étape 0 peut être jouée jusqu'à 0.3 inclus sans lui ; 0.4 et 0.5
attendent.

Deux faits trouvés à la vérification, absents des docs jusqu'ici :
- `pytest` n'est pas dans le devShell `mac` : `nix develop .#mac --command python -m pytest --version` → `No module named pytest`. La suite de 204 fichiers ne peut pas tourner depuis le shell du dépôt.
- Le build release signe avec la clé debug : `app-android/build.gradle.kts:57`.

## Étape 0 — Le sol

_Contrat : à écrire à l'ouverture de la session d'exécution._

### Contrat · 2026-09-10 · feu vert PO sur D0 et D1

**Faits établis avant de lancer** (requêtes rejouables) :
- Toutes les branches locales et distantes sont des ancêtres de `matrice-dino` (`git merge-base --is-ancestor <b> HEAD` → oui pour les 7). Rien ne se perd en les supprimant ; on tague pour garder les noms.
- `repo-cleanup` est un ancêtre de HEAD : le VPS peut avancer par fast-forward.
- L'arbre de travail porte des modifications **d'un autre chantier** (`Taskfile.yml`, `useLotReview.ts`, `LotDetailView.vue`, specs `lot-*`, trois docs `juge-du-crop/`, `secrets/dev.env`). Elles ne sont ni commitées ni écartées. `git checkout main` classique refuserait ; le geste est `git checkout -B main` depuis `matrice-dino`, qui ne change pas l'arbre.

**Entrées** : `PLAN.md` §Étape 0. **Sorties** : les six critères avec sortie collée, la table branche → tag, les trois docs corrigées.

**Interdits** : `push --force` ; `branch -D` sur une branche non taguée ; `git add -A` ; toucher aux fichiers modifiés de l'autre chantier ; sur le VPS, autre chose que `git fetch`, `git checkout main`, `git config` — aucun `docker compose`.

### Rapport de l'exécutant · 2026-09-10

Trois passes. La première a fermé 0.1, 0.2, 0.3, 0.5, 0.6 et s'est **arrêtée** sur 0.4 : `/opt/eurio` portait une `main` locale divergente (`8cdd7403`, 201 commits depuis le merge-base `24aa4636`, 23 sans équivalent patch). L'arbre a été remis sur `repo-cleanup`, les deux `docker-compose.yml` retrouvés, aucun conteneur touché. → D7.

La deuxième a buté sur `git push` depuis le VPS : « key marked as read only ». → D8, skill `eurio-vps-deploy` corrigée.

La troisième a tenté de pousser le tag depuis le Mac : 22 minutes, deux pushes concurrents, rien d'atterri. L'architecte a mesuré **1 308 Mo / 13 012 objets** dont 309 Mo de `eurio.db.bak-*`, tué les pushes. → D9, bundle `../archives/eurio-vps-main-8cdd7403.bundle` (911 Mo, `git bundle verify` ok).

Chaîne VPS finale (exit 0) : `main` réalignée sur `github/main`, `repo-cleanup` / `scan-corpus-funnel` / `sources-jo-wikipedia` supprimées avec `-d` (donc fusionnées), `codeberg` retiré, `branch.main.remote=github`. Conteneurs inchangés : `eurio-admin` Up 39 h, `eurio-api` Up 2 j, `eurio-review` et `eurio-minio` Up 2 mois.

| Critère | Sortie | Verdict |
|---|---|---|
| 0.1 | `git rev-list --count main..archive/matrice-dino` → `0` | PASS |
| 0.2 | `main` ; local = github = `122445b6` | PASS |
| 0.3 | `git tag -l 'archive/*' \| wc -l` → 8 ; `git branch \| wc -l` → 1 | PASS |
| 0.4 | VPS HEAD `main` @ `122445b6`, `branch.main.remote` = `github` | PASS |
| 0.5 | `git remote` → `github`, Mac et VPS | PASS |
| 0.6 | trois mentions restantes, toutes datées et au passé | PASS |

Branche → tag : `coin-richness/p3-schema`→`archive/coin-richness-p3-schema` 9051c20b · `data-harmonization` eae5b6da · `debug-data-taxonomy` a82d8cd0 · `repo-cleanup` 21be7b13 · `scan-corpus-funnel` d1f58122 · `source-lmdlp-rebuild` 4cf86e8c · `sources-jo-wikipedia` 36a75a57 · `matrice-dino` e4be1c3f. Les 8 tags sont sur github.

Commits de l'étape sur `main` : `a5e9341f` (ouverture), `d02288b8` (tronc unique dans les instructions), `122445b6` (mention datée dans l'index).

Restes signalés, non traités : le tag local `vps-main-preswitch-20260814` ramené par le fetch (gardé, jamais poussé) ; deux fichiers `ml/bench/gold_crop/sample.py` et `ml/tests/test_gold_crop_sample.py` modifiés par l'autre chantier.

### Contre-rapport · 2026-09-10 · relecteur neuf (sonnet), critères seuls

| Critère | Sortie | Verdict |
|---|---|---|
| 0.1 | `0` | PASS |
| 0.2 | `main` ; local = github = `d3cca1f7` | PASS |
| 0.3 | 9 tags `archive/*` locaux, 8 sur github ; 1 branche ; heads github = `main` seul | PASS |
| 0.4 | première lecture : VPS @ `122445b6` ≠ github @ `d3cca1f7` → **FAIL** ; l'architecte a joué `git fetch github main && git merge --ff-only github/main` sur le VPS ; relecture : `main` / `github` / `d3cca1f7` / une seule branche → PASS | PASS |
| 0.5 | `github` seul, Mac et VPS | PASS |
| 0.6 | trois mentions, toutes datées et au passé, jugées ligne par ligne | PASS |

Falsification : `git branch tmp-x` porte le compte à 2, que le seuil « ≤ 2 » aurait laissé passer. → critère 0.3 resserré à **1** dans `PLAN.md`. Branche supprimée, retour à 1.

Succession : « rien ne manquait ».

### Verdict de l'architecte · 2026-09-10 · **étape 0 fermée**

Le FAIL transitoire de 0.4 est réel et instructif : un commit poussé après la chaîne VPS suffit à désaligner le sol. C'est l'argument de l'étape 1, une machine qui regarde à chaque push. La 9e ref `archive/*` locale est `vps-main` (D9), volontairement absente de github.

**Étape 1 ouverte** : le fil à plomb. Préalable connu : `pytest` absent du devShell.

## Étape 1 — Le fil à plomb

### Contrat · 2026-09-10

**Faits établis avant de lancer** :
- `ml/.venv/bin/python -m pytest -q` → **2 795 passed, 40 warnings, 136 s**, depuis le shell du Mac (direnv chargé, secrets exportés). Ce qui reste à prouver : le même vert **sans** les secrets et sans la réplique, sur un runner neuf.
- `pytest` n'est ni dans le flake ni dans `pyproject.toml` (D11). La venv se bâtit par `go-task ml:setup` (uv, `--system-site-packages`, torch par plateforme).
- Dépôt public ; pas de job Android (D10). `Taskfile.yml` est **modifié par un autre chantier** : ne pas y toucher ; la CI appelle `go-task tokens:check` qui existe déjà, et les commandes de test directement.
- `gh` est authentifié (`Musubi42`).

**Entrées** : `PLAN.md` §Étape 1, D2, D10, D11. **Sorties** : `.github/workflows/ci.yml`, le devShell `ci` dans `flake.nix`, `pytest` dans `pythonEnv`, un run vert sur `main`, la falsification jouée, la liste des tests rouges sans secrets s'il y en a.

**Interdits** : désactiver ou marquer `skip` un test ; secret dans le workflow ; toucher `Taskfile.yml`, `ml/tasks.yml`, ou tout fichier modifié de l'autre chantier ; `git add -A` ; relancer une commande longue sans ordre de l'architecte ; plus d'un push par itération.

### Rapport de l'exécutant · 2026-09-10

Deux commits sur `main` : `422d1534` (workflow, devShell `ci`, `pytest` dans `pythonEnv`) puis `dcc3f08a` (le devShell `ci` expose la `libstdc++` du stdenv sur Linux : les wheels `torch+cu126` la cherchaient sur l'Ubuntu du runner, même rôle que `nvidiaHook` sur le PC). `flake.lock` inchangé. `go-task ml:setup` appelé tel quel dans le job `ml`, pour ne pas créer une seconde source de vérité.

| Critère | Sortie | Verdict |
|---|---|---|
| 1.1 | `13:    branches: [main]` | PASS |
| 1.2 | run 34493861491 → `failure` : job `ml` rouge sur **15 tests**, non désactivés | **FAIL** |
| 1.3 | `admin`, `ml`, `tokens` | PASS |
| 1.4 | `pytest 9.0.2` dans `.#ci` et `.#mac` | PASS |
| 1.5 | 4 min 50 total : `tokens` 52 s, `admin` 1 min 28 (vitest + typecheck), `ml` 4 min 46 | PASS |

Falsification : PR #2 draft, run 34494617526 → `ml` failure (`test_ci_must_scream`), `tokens` failure (`✗ DÉRIVE Color.kt`, exit 2), `admin` success. `cancel-in-progress` vérifié (run 34494578374 annulé par le push suivant). Branche et PR supprimées.

**Les 15 rouges** (`15 failed, 2699 passed, 79 skipped in 185 s`) : aucun n'attend un secret, **tous lisent un fichier gitignoré** :
- `test_lab_api.py` ×5 : `sources_routes.py:1978` et `coin_assets_routes.py:323` ouvrent `_DB_PATH` en `mode=ro` sur le vrai `eurio.db`, pas sur le `tmp_path` du test. **Ce n'est pas un défaut de test, c'est un couplage caché dans la route.**
- `test_numista_transforms.py` ×2 : `ml/state/numista_cache/10069/prices_*.json`.
- `test_orchestrator.py` ×5, `test_orchestrator_push_c4c.py` ×2 : `MockAdapter` lit `ml/datasets/{64,80,88,96,104}/obverse.jpg`.
- `test_refetch_numista_2eur.py::test_parse_real_cohort_file` : `ml/state/cohort_validation_19.txt`.

Choix rapportés : pas de `magic-nix-cache-action` (backend GitHub arrêté en février 2025), `cache.nixos.org` suffit, shell `.#ci` en ~40 s. Cache Actions `ml/.venv` jamais rempli (service en `400` pendant les runs), sans effet sur la durée. `ml/.venv` du Mac devenue périmée par le changement de `pythonEnv` → `go-task ml:venv-rebuild` lancé par l'architecte.

### Verdict de l'architecte · 2026-09-10 · **étape 1 ouverte sur 1.2 seul**

Le fil à plomb est posé et il crie. Il a d'abord crié sur ceci : 2 795 tests « verts » sur le Mac dont 15 ne l'étaient que par la présence de données hors dépôt. Le critère 1.2 se fermera quand l'étape 2 aura rendu ces 15 tests honnêtes ; les autres critères de l'étape 1 sont soumis au contre-relecteur.

### Contre-rapport · 2026-09-10 · relecteur neuf (sonnet), critères seuls

| Critère | Sortie | Verdict |
|---|---|---|
| 1.1 | `13:    branches: [main]` | PASS |
| 1.2 | run 34493861491 `failure`, mêmes 15 tests que l'exécutant | **FAIL** |
| 1.3 | `admin`, `ml`, `tokens` | PASS |
| 1.4 | `pytest 9.0.2` | PASS |
| 1.5 | `admin` 1 min 28, `ml` 4 min 46, `tokens` 52 s | PASS |
| 1.6 (ajouté) | `permissions: contents: read`, aucun `secrets.` | PASS |
| 1.7 (ajouté) | aucun fichier de `ml/tests` touché par les commits `ci:` | PASS |

Falsification : PR #3, run 34495729294 → `ml` failure, `admin` et `tokens` success. PR fermée, branche supprimée, une seule branche locale.

Succession : **il manquait** que le `push` d'une branche hors `main` ne déclenche rien ; le relecteur a dû ouvrir une PR de lui-même. → texte de falsification corrigé dans `PLAN.md`.

### Verdict de l'architecte · 2026-09-10 · **étape 1 fermée sauf 1.2**, qui se ferme avec l'étape 2

Deux relecteurs indépendants donnent la même liste de 15 tests. Ce n'est pas la CI qui est en défaut, c'est la suite. Le critère 1.2 est rattaché à l'étape 2 : il passera quand `main` sera vert sans rien masquer.

## Étape 2 — Le gabarit

### Contrat · 2026-09-10

**Entrée** : les 15 tests rouges du run 34493861491, en quatre familles :

| Famille | Tests | Ce qu'ils lisent hors dépôt | Nature |
|---|---|---|---|
| A | `test_lab_api.py` ×5 | le vrai `eurio.db` via un `_DB_PATH` de module dans `sources_routes.py` et `coin_assets_routes.py`, en `mode=ro` | **couplage caché dans la route** : le test injecte une base, la route en ouvre une autre |
| B | `test_orchestrator.py` ×5, `test_orchestrator_push_c4c.py` ×2 | `ml/datasets/{64,80,88,96,104}/obverse.jpg` via `MockAdapter` | fixture qui pointe des données réelles |
| C | `test_numista_transforms.py` ×2 | `ml/state/numista_cache/10069/prices_*.json` | test sur données réelles sans fixture |
| D | `test_refetch_numista_2eur.py::test_parse_real_cohort_file` | `ml/state/cohort_validation_19.txt` | idem |

**Ce qui est tranché** :
- A se corrige **dans la route**, pas dans le test : la route lit le chemin de base par le même point d'injection que celui que le test surcharge. Un commit par route, nommé par le test qu'il fait passer.
- B : `MockAdapter` génère ses images dans `tmp_path` (PIL, quelques pixels) ; il ne lit plus `ml/datasets`.
- C et D : si le fichier réel pèse moins de 200 Ko, une copie **anonymisée si nécessaire** entre dans `ml/tests/fixtures/` avec une ligne d'origine ; sinon un `skip(reason=…)` daté qui nomme le fichier attendu.
- Aucun seuil élargi, aucun `assert` retiré.
- Les 79 `skipped` existants : chaque `skip`/`skipif`/`xfail` porte un `reason=`. Les sans raison sont complétés, pas supprimés.
- Trois tests de **pannes muettes** (critère 2.4) : lire la skill `eurio-verify`, choisir trois familles du catalogue, écrire un test par famille dont la mutation cible est **documentée dans le docstring** du test.
- `pytest` arrive dans la venv en `9.1.1` par une transitive alors que le flake fournit `9.0.2` : identifier le paquet qui le tire (`uv pip show`), rapporter, ne rien pinner sans ordre.

**Interdits** : supprimer un test ; marquer `skip` un test de la famille A ou B ; toucher aux fichiers modifiés de l'autre chantier (`Taskfile.yml`, `ml/tasks.yml`, `useLotReview.ts`, `LotDetailView.vue`, specs `lot-*`, docs `juge-du-crop/`, `ml/bench/gold_crop/sample.py`, `ml/tests/test_gold_crop_sample.py`, `secrets/dev.env`) ; `git add -A` ; relancer une commande longue sans ordre ; plus d'un push par itération, trois itérations au plus.

### Rapport de l'exécutant · 2026-09-10

Six commits `fc78ca01..747773fe`, un push, run **34498204039 → success** en une itération (`tokens` 48 s, `admin` 1 min 42, `ml` 5 min 37).

**Le contrat se trompait de fichier.** Aucun `mode=ro` dans `sources_routes.py` ni `coin_assets_routes.py` ; le site fautif est `serving/coin_lookup.py:38`, atteint par `lab_routes.py:2371`. Un `_DB_PATH` résolu **à l'import** : sur le Mac, direnv pointe `EURIO_DB_PATH` sur la réplique et les cinq tests étaient verts pour de mauvaises raisons ; sur le runner, rien. Corrigé par un `bind(db_path)` appelé depuis `lab_routes.bind`, repli inchangé. Un seul commit pour la famille A.

**Reproduire le runner** : `conftest.py` n'a aucun mécanisme et une fixture ne peut pas masquer des chemins dérivés de `Path(__file__)`. Ce qui reproduit : un worktree propre + `env -u` sur toutes les `EURIO_*`. Les 15 rouges y réapparaissent à l'identique, **mais seulement `EURIO_DB_PATH` désarmée** : la variable de direnv masquait la famille A même hors dépôt.

| Critère | Sortie | Verdict |
|---|---|---|
| 2.1 | CI : `2732 passed, 64 skipped, 0 failed` ; local : `2798 passed` | PASS (commande du PLAN corrigée) |
| 2.2 | grep vide | PASS |
| 2.3 | 64 skips, 9 raisons, chacune nomme le fichier absent | PASS |
| 2.4 | trois tests, trois mutations rouges, trois reverts | PASS |
| 2.5 | `8 files, 64 tests passed` | PASS |
| 1.2 | `success` | PASS |

Pannes muettes couvertes : (1) le mapping Numista lit la base injectée, mutation = retirer `coin_lookup.bind` ; (2) un lecteur `mode=ro` voit le WAL, mutation = `immutable=1` ; (3) un seuil entier fractionnaire est refusé par la route, mutation = désarmer le garde dans `dino_thresholds.set_threshold`.

`pytest 9.1.1` arrive par `ai-edge-torch → litert-torch → torch-xla2`. Rien pinné.

Non élucidé : **2 tests de moins collectés sur Linux** que sur Mac hermétique (2 732 + 64 = 2 796 contre 2 798).
