# Chantier — remise au propre du dépôt

> **Mémoire de travail.** Ce chantier survit à plusieurs sessions. Avant de lancer la
> moindre recherche, **lis la section « Déjà établi »** : elle contient des faits vérifiés
> qui ont coûté cher à découvrir. Ne les re-cherche pas, complète-les.
>
> Démarré le 2026-08-14 · Branche `repo-cleanup` (partie de `scan-corpus-funnel`)
>
> ⚠️ **Le dépôt a déménagé** : `bizz/Eurio` → **`bizz/EurioProject/Eurio`**, avec
> `bizz/EurioProject/loan` à côté. Après un `cd`, relancer `direnv allow` — le devShell
> et le `flipHook` de `flake.nix` résolvent des chemins depuis `$PWD`.

## Objectif

Repartir sur une base propre : un dépôt sans déchets, une architecture documentée, un
historique git lisible — et `loan/` sorti dans son propre dépôt.

## Décisions déjà prises (ne pas rouvrir sans raison)

| Sujet | Décision | ADR |
|---|---|---|
| Archive de l'ancien historique | **Tarball hors ligne uniquement**, jamais poussé en ligne | [005](../../adr/005-remaster-historique-git.md) |
| Forme du nouveau `main` | **~10 commits thématiques**, pas un commit racine unique | [005](../../adr/005-remaster-historique-git.md) |
| Modèles `.tflite` de l'APK | **Sortis de git, fetchés au build** | [004](../../adr/004-artefacts-binaires-hors-git.md) |
| `loan/` | **Extrait**, alimenté par MinIO au lieu de Supabase | [006](../../adr/006-extraction-loan.md) |
| Découpage d'Eurio | **Reporté** : artefacts publiés d'abord | [007](../../adr/007-pas-de-split-eurio-avant-artefacts.md) |
| Ordre général | **Nettoyer d'abord, remaster ensuite** — sinon on grave les déchets | [005](../../adr/005-remaster-historique-git.md) |
| Secrets fuités | Clés **révoquées** par le PO. Pas de `filter-repo` requis puisque l'archive reste hors ligne | [005](../../adr/005-remaster-historique-git.md) |

## Déjà établi — faits vérifiés, ne pas re-chercher

**Le dataset de détection vient de Roboflow.** `coin-gva2j`, CC BY 4.0,
`universe.roboflow.com/yolocoin/coin-gva2j/dataset/1`. 1878 des 1908 images de
`coin_detect/` en viennent (signature `.rf.<hash>`, noms `KakaoTalk_2022…`). Les 30
autres sont des `negative_*.jpg` **à nous**. Donc `best.pt` **est régénérable**.
⚠️ Le script de re-fetch Roboflow a été retiré du repo — seule l'URL du `data.yaml` reste.

**`best.pt` est un YOLOv8-nano mono-classe.** Il ne reconnaît pas la pièce, il dit **où**
elle est : il fournit le prior à la passe Hough qui raffine le rim. Sans lui, Hough vote
sur les lettres et motifs circulaires des fonds eBay.

**Le backend VPS est du SQLite, pas du Postgres.** Le Postgres du projet, c'est Supabase.
Détail : [`../../architecture/README.md`](../../architecture/README.md).

**Les 3 packages admin « à supprimer » sont déjà supprimés de git.**
`admin-vps`, `review-admin`, `web` : **0 fichier tracké** chacun. Il ne reste que
`dist/` + `node_modules/` gitignorés sur le disque. Rien à committer, juste un `rm -rf` local.

**`admin/packages/review/` est vivant** — 10 fichiers trackés, buildé par
`infra/review/Dockerfile`, servi sur `eurio-review.musubi.dev`. C'est le chantier
**K2 non tranché** (`auth-redesign/ROADMAP.md` : « Décision et exécution sur
`admin/packages/review/` »). Ne pas confondre avec `CLAUDE.md`, qui parle de
**`infra/review/`** (le déploiement Docker) et le dit supprimable « à C9 » — or C9
n'existe plus. Deux objets distincts, deux statuts distincts.

**`ml/review/` n'est PAS un chemin mort** — 12 fichiers trackés (`coins_review_routes.py`,
`peer_arbitration_routes.py`, `review_lanes.py`, `publish_cli.py`, `validation/`…).
Seul **`ml/api/`** est mort (renommé `ml/serving/`). Les 13 docs qui citent `ml/review/`
sont **correctes** : ne pas les toucher.

**Supabase n'est pas décoratif** : `build_app_core.py` **lit Supabase** pour produire
`app_core.db`, le catalogue offline de l'APK. Le retrait de Supabase et la publication
d'`app_core` sont donc **le même chantier**.

**git est le transport Mac→PC des poids.** Le casser est **silencieux** : au prochain
`reset --hard`, les fichiers disparaissent, l'échec n'arrive qu'au premier appel de
`normalize_snap.py`.

**Il n'y a aucune CI**, aucun hook, et aucune tâche « lancer toute la suite de tests ».
17 tests étaient rouges au 2026-06-30 (documenté, non revérifié depuis).

**Chiffres corrigés** (des docs anciennes en citent de faux) :
`scan-corpus-funnel` est **+374** sur `main` (pas 21) · `ml/datasets/` tracké = **33 Mo**
(pas 2,5 Go) · `.git` = **146 Mo**.
→ **Source unique des volumes : [`../../architecture/artifacts.md`](../../architecture/artifacts.md) §Volumes.**
Ne recopie pas ces chiffres ailleurs, renvoie-y.

## Lots

### ✅ Lot 0 — Filet de sécurité *(2026-08-14)*
- [x] Tarball des 30 négatifs + provenance Roboflow →
      `~/Documents/Musubi42/eurio-backups/eurio-detection-negatives-20260814.tar.gz`
      (2,5 Mo, sha256 `85ba18d5…`)
- [x] **Tarball complet** → `bizz/EurioProject/eurio-full-20260814.tar` (**5,3 Go**,
      52 853 entrées). Exclut `node_modules`, `.venv`, `__pycache__`, `.next`,
      `.gradle`, `build`, `.cxx` (régénérables, 3,5 Go). Contient `.git`, `loan`,
      `best.pt`, les `.tflite`, les golds annotés, les 30 négatifs
- [x] **Restauration testée** : `.git` seul extrait dans un dossier temporaire →
      `git checkout` restaure **6094 fichiers**, `git fsck` **0 erreur**, HEAD correct
- [ ] **Pousser les deux tarballs sur pCloud** ← PO (ils sont sur disque local)

### ✅ Lot 2 — Extraction de `loan/` *(2026-08-14)*
- [x] `loan/` détracké (116 fichiers) et déplacé → `bizz/EurioProject/loan`
- [x] Dépôt git autonome initialisé, premier commit `ef98288`, 118 fichiers versionnés,
      **aucun secret dans l'index** (`.env.local` / `.vercel/` couverts par `.gitignore`)
- [x] Couplage CSS coupé : `shared/tokens.css` **vendoré** dans `loan/src/styles/tokens.css`
- [x] 4 tâches `loan:*` retirées du `Taskfile.yml`, `CLAUDE.md` mis à jour
- [x] **`loan/docs/migration-vers-minio.md`** écrit : contexte produit, 4 mondes de
      données, 12 champs consommés, divergence v1/v2, plan en 7 étapes, 4 décisions
- [ ] Créer le dépôt distant et pousser ← PO (URL à fournir)
- [ ] La migration Supabase → MinIO elle-même (non prioritaire, documentée)

### ✅ Lot 1 — Déchets francs *(terminé 2026-08-14)*
- [x] `05be2dd` — 6 variantes de quantization + 3 résidus onnx2tf + 2 `labels.cache`
      retirés de l'index (`--cached`, rien ne quitte le disque). −30 395 lignes, ~33 Mo
- [x] `rm -rf` local des 3 packages admin morts (`dist/` + `node_modules/` gitignorés,
      régénérables par `pnpm install && build`)
- [x] `ml/swagger.yaml` retiré — c'était la spec **de Numista**, zéro référence
- [x] Chemins morts **`ml/api/` → `ml/serving/`** : 77 occurrences dans 34 docs vivantes
- [x] **K1 ✅** coché dans `auth-redesign/ROADMAP.md`
- [x] Bannière sur `docs/research/sources-admin-page.md` (visait `admin/packages/web/`)
- [x] `local-sync/HANDOFF-next-session.md` → `docs/archive/local-sync/` + bannière ⛔️
- [x] Bannière sur `docs/DECISIONS.md` renvoyant vers `docs/adr/README.md`
- [x] `datasets-minio-migration.md` → `docs/archive/` + bannière (chiffres faux)
- [x] Chantier référencé dans `docs/work-in-progress/README.md` (focus remis à jour)
- [x] `CLAUDE.md` : 3 corrections (`app_core.db`, schéma de vérité, `infra/review/`)

> **⚠️ Piège rencontré, à retenir.** Le remplacement `ml/api/` → `ml/serving/` **n'est
> pas un `sed` global**. Deux fichiers ont migré vers `ml/review/`, pas `ml/serving/` :
> `coins_review_routes.py` et `review_queue_routes.py`. Un `sed` aveugle aurait créé
> deux chemins faux. Vérifier l'existence de chaque cible avant tout renommage de masse :
> ```
> grep -rho "ml/serving/[a-zA-Z0-9_/]*\.py" docs/ | grep -v docs/archive | sort -u \
>   | while read p; do [ -f "$p" ] || echo "INTROUVABLE: $p"; done
> ```
> Six chemins restent introuvables **et c'est normal** : ils désignent du code
> délibérément supprimé (`bootstrap_canonical.py` en C2, les `sync_*` de l'event-log
> abandonné) dans des docs qui le disent explicitement, ou jamais écrit
> (`dashboard_logic.py`, proposition de sprint).

### ✅ Lot 3 — package partagé + générateur multi-cible *(2026-08-14)*
- [x] `shared/` devient **`@eurio/shared`** (et non `@eurio/tokens` : il porte aussi
      `fixtures/`, un nom « tokens » aurait menti). Package workspace privé, `exports`
      sur `./tokens.css` et `./fixtures/*.json`, entrée `../shared` dans
      `admin/pnpm-workspace.yaml`
- [x] Les 5 imports relatifs remontant la racine sont supprimés (proto, studio-local,
      review) — **les 3 builds passent**, `--indigo-700` présent dans le CSS produit
- [x] `generate_android_tokens.mjs` → **`generate_tokens.mjs`**, multi-cible : registre
      `TARGETS`, `--target`, `--check`, `--help`. Sortie Kotlin **identique au bit près**
      hors la ligne d'en-tête nommant le script
- [x] `tokens:check` **ne dépend plus de git** (avant : `git diff --exit-code`) : compare
      le généré au disque, sortie 2 sur dérive. Marche sur arbre sale et hors dépôt
- [x] **Symlink `app-android/src/qa/assets/fixtures` supprimé** → tâche Gradle
      `syncQaFixtures` (`Sync` sur `preBuild`, sortie gitignorée), **exécutée et vérifiée**
- [x] 🔴 `infra/review/Dockerfile` réparé : il ne copiait que `tokens.css`, le
      `pnpm install --frozen-lockfile` aurait échoué **au déploiement**
- [ ] Supprimer le middleware `/shared/` de `studio-local/vite.config.ts` — plus aucun
      demandeur (vérifié), annoté VESTIGE. Attend une vérif de `go-task parity:*`

> **À retenir : le piège n'était pas dans le code applicatif mais dans les images
> Docker.** Rendre `shared/` membre du workspace change ce que `pnpm install` exige au
> build. Toucher au workspace ⇒ relire `infra/*/Dockerfile`.

### 🟡 Lot 4 — Registre d'artefacts MinIO *(mécanisme livré 2026-08-14, bascule en attente)*

Périmètre arbitré : **modèles de l'APK uniquement**. `best.pt` reste dans git → le
transport Mac→PC n'est pas touché → **rien ne peut casser le PC**. `app_core.db` reste
committé (décision délibérée du `.gitignore`, liée au retrait de Supabase).

- [x] Deux casiers sous `EURIO_CACHE_ROOT` : images `<root>/<bucket>/`, artefacts
      `<root>/artifacts/`, **plafonds séparés**
- [x] **Plafond images `20` Go** posé dans `flake.nix` — il n'était réglé nulle part
      (défaut `"0"` = aucune éviction) et le cache était à **5,8 Go** en croissance libre
- [x] Plafond artefacts `5` Go (`EURIO_ARTIFACTS_MAX_GB`)
- [x] `_evict_if_needed()` exclut `artifacts/` — **3 tests** le prouvent
- [x] `artifact_path()` : vérification sha256, re-téléchargement d'un cache corrompu,
      refus net d'un contenu non conforme
- [x] `ml/scripts/model_assets.py` (`status`/`publish`/`fetch`) + `go-task ml:assets:*`
- [x] Manifeste `shared/model-assets.json`, adressage par contenu
      (`models/<nom>/<sha[:12]>/<fichier>`)
- [x] Bucket `model-artifacts` + policy dans `infra/minio/{bootstrap.sh,policies/}`
- [x] Tâche Gradle `fetchModelAssets` enregistrée, **pas branchée sur `preBuild`**
- [ ] **← PO : `cd /opt/eurio/infra/minio && ./bootstrap.sh` sur le VPS** (la clé
      applicative n'a pas `CreateBucket`, et c'est voulu)
- [ ] `go-task ml:assets:publish`
- [ ] Vérifier le round-trip : supprimer les 4 assets, `fetch`, comparer les sha
- [ ] **Au même commit** : `git rm --cached` des 4 assets + gitignore + décommenter
      `dependsOn(fetchModelAssets)`

> **Rien n'a été retiré de git.** Le fetch n'est pas prouvé de bout en bout tant que le
> bucket n'existe pas — brancher une dépendance réseau au build avant ça casserait le
> build de tout le monde.

### ⬜ Lot 5 — Remaster git
Sur un arbre déjà propre. Statuer sur `source-lmdlp-rebuild` (+4, travail fini non mergé)
**avant**, sinon il est perdu.

### ⬜ Lot 6 — Split d'Eurio
Quand iOS arrive. Après le lot 4, c'est du déplacement de dossiers.

## Questions ouvertes — bloquantes

| # | Question | Bloque |
|---|---|---|
| 1 | **Faut-il exempter les artefacts de build de l'éviction LRU du cache MinIO ?** (le cache est déjà persistant : le hors-ligne marche sur cache chaud. Le risque est qu'un `_evict_if_needed()` supprime un artefact et casse un build qui marchait) | Lot 4 |
| 2 | Nom du **dossier parent** (`Documents/Musubi42/bizz/…`) accueillant `eurio/` et `loan/` | Lot 2 |
| 3 | `loan` lit-il le **même artefact `app_core`** que l'app (schéma v2), ou garde-t-il son `catalog.json` ? | Lot 2 |
| 4 | **K2** : le service `eurio-review.musubi.dev` tourne-t-il encore, feature abandonnée ou différée ? | Lot 1 |
| 5 | Plan de retrait de **Supabase** : par quoi est-il remplacé pour l'app ? | Lot 4 |
| 6 | `source-lmdlp-rebuild` : merger ou abandonner ? | Lot 5 |
| 7 | **`app-android/…/assets/models/test_model.tflite`** (19 Mo, non tracké, aucun consommateur identifié, daté 2026-04-09) : résidu de spike ou artefact utile ? | Lot 4 |

## État du VPS — relevé du 2026-08-14, **mis à jour après bascule**

Accès : `ssh serverOimNixDontpanic`, projet dans `/opt/eurio`.

> ✅ **Mac et VPS sont alignés depuis le 2026-08-14.** `repo-cleanup` poussée sur
> **codeberg et github** (`f5660724`), VPS basculé dessus. Les deux machines ont
> désormais les **mêmes deux remotes** (`codeberg`, `github`) — sur le VPS, `origin`
> a été renommé `codeberg` pour coller au Mac.
>
> **Vérifié après bascule** : les 4 conteneurs n'ont pas redémarré (up depuis le
> 2026-07-12), `eurio-admin`/`eurio-review`/MinIO en HTTP 200, `eurio-api` sain
> (`/healthz` 200, `/whoami` 200, `/db/replica` 401 = protégé ✅ — attention,
> **`/health` n'existe pas sur eurio-api**, c'est `/healthz`). `eurio.db` 149 Mo et
> les 6,8 Go MinIO intacts.
>
> **Filet posé avant l'opération** : le `main` local du VPS portait une lignée
> pré-réécriture unique. Sauvegardé en `git bundle` (910 Mo, historique complet,
> vérifié) → `bizz/EurioProject/vps-main-preswitch-20260814.bundle` sur le Mac, plus
> un tag local `vps-main-preswitch-20260814` sur le VPS. **Ce bundle n'a
> délibérément PAS été poussé** : c'est de la lignée antérieure au `filter-repo` de
> juin, la pousser réintroduirait les objets que cette purge avait retirés.
> Une copie reste dans `/tmp` du VPS (868 Mo) — supprimable, elle fait doublon.
>
> ⚠️ Piège écarté au passage : `infra/minio/data` **est tracké** — mais un seul
> fichier, la sentinelle `.do-not-delete`. Les 6,8 Go sont hors git et la bascule
> n'a touché aucun fichier sous ce chemin (vérifié avant d'agir).

| Élément | État |
|---|---|
| Branche | **`repo-cleanup` à `f5660724`**, alignée sur le Mac (depuis la bascule du 2026-08-14). `scan-corpus-funnel`, `main` et `sources-jo-wikipedia` conservées localement |
| Conteneurs | `eurio-api`, `eurio-admin`, `eurio-minio`, `eurio-review` **up 4 semaines** · `eurio-scrape-tor` **unhealthy** |
| `eurio-review` | **HTTP 200** → la feature K2 est **vivante**, pas dormante |
| Canonique | `eurio.db` = **149 Mo**, dernière écriture **12 juillet** |
| MinIO | **6,8 Go** de données |
| Disque | 287 Go / 393 Go utilisés, **86 Go libres** (77 %) |

### 🔴 Les sauvegardes ne tournent pas

Vérifié par quatre chemins indépendants : **aucun timer systemd**, **aucune entrée cron**
(utilisateur ni système), **`rclone` n'est pas installé**, **aucune trace dans le
journal**, et **aucune archive** nulle part sur le disque.

Ce qui existe : `infra/backup/eurio-backup.sh` + sa doc, et une clé age dans
`~/.config/eurio-backup/age-key.txt` datée du **17 juin**. Le dispositif a donc été
préparé puis **jamais branché**.

Sont concernés : **6,8 Go d'images MinIO** (raws, crops, canoniques) et le canonique
`eurio.db` de 149 Mo. Le tarball du 2026-08-14 sauve le dépôt local, **pas** ces données.

### Conséquence sur une règle existante

`infra/minio/README.md` §Anti-patterns interdit le versioning S3 avec ce motif :

> « The protection model is **"weekly tarball + audit"**, not S3 native versioning. »

**La prémisse est fausse** : il n'y a pas de tarball hebdomadaire. La règle interdit donc
un filet de sécurité au nom d'un autre filet qui n'existe pas. À rediscuter — soit on
branche la sauvegarde et la règle redevient fondée, soit on réexamine le versioning.

## Objectifs de la prochaine session

Par ordre de priorité assumé :

1. **Brancher la sauvegarde du VPS.** C'est le seul point où une panne fait perdre des
   données non reproductibles. Passe avant tout le reste.
2. **Boucler le lot 4** : `./bootstrap.sh` sur le VPS → `ml:assets:publish` → vérifier le
   round-trip → `git rm --cached` + `dependsOn`. ✅ **Prérequis levé** : le VPS a les
   fichiers `infra/minio/` à jour depuis la bascule — `bootstrap.sh` y créera bien
   `model-artifacts` et réappliquera la policy.
3. **Rediscuter le versioning S3** à la lumière du point 1.
4. **Trancher K2** — le service tourne et répond, la question n'est plus « est-il mort »
   mais « le garde-t-on ».
5. **Lot 5, le remaster git** — en dernier, et pas avant que le lot 4 soit bouclé (sinon
   on grave dans la nouvelle base les binaires qu'on s'apprête à sortir). Décision encore
   ouverte : `source-lmdlp-rebuild` (+4, travail fini) — merger ou abandonner.
6. `eurio-scrape-tor` unhealthy depuis un moment — diagnostiquer.

## Doc encore à écrire

`docs/architecture/` ne couvre **que** le stockage et le transport de la donnée. Zones
importantes sans aucune page, par ordre d'utilité pour un agent qui arrive :

1. **`local-sync`** — HLC, outbox, `EURIO_SYNC_MODE: hub`, `GET /db/events/pull`. C'est le
   mécanisme central du modèle « writer unique » et il n'est décrit nulle part.
2. **`ml/serving/server.py`** — 1400+ lignes, structure `*_routes.py`, endpoints. On sait
   seulement qu'il en a un mort.
3. **Schéma de `eurio.db`** et où vivent ses migrations (`ml/state/schema.sql`,
   `ml/serving/migrations/`).
4. **Pipeline de scan** : scrape → crop → embed → match.
5. **Entraînement** : `ml/lab/iterations/`, `promote_iteration`, cohortes.
6. **Sources eBay / Numista** — et pourquoi `ml/datasets/sources/` est 🔴 irremplaçable.
7. **Front admin `studio-local`** (196 fichiers) et **app Android** (Compose/Room/flavors).
8. **Procédures de base** : entrer dans le devShell, lancer l'API, lancer les tests.

## Pièges à ne pas réintroduire

1. **`APP_CORE_VERSION = 1`**, codé en dur, jamais incrémenté. Un `app_core.db` neuf sans
   incrément ⇒ l'app **skippe le bootstrap en silence**.
2. **`POST /export/deploy` skippe silencieusement** les sources manquantes : renvoie
   `200 {count: 0}`. Un déploiement raté ne lève pas.
3. **`ml/tasks.yml` → `ml:deploy`** copie depuis `ml/output/`, que `ml/serving/server.py`
   déclare supprimé. Trois mécanismes de déploiement concurrents.
4. **`ml/tests/conftest.py`** a une fixture **autouse** qui mocke MinIO : tout nouveau code
   de fetch sera **stubbé, donc non testé**, sauf opt-out explicite.
5. **`coin_detect/data.yaml`** a des chemins absolus périmés (`…/Musubi42/Eurio/…` au lieu
   de `…/bizz/Eurio/…`) — déjà cassé sur le Mac.
6. **Ne jamais juger la fraîcheur d'un chantier au `git log` du dossier** : 14 dossiers de
   `work-in-progress/` datent du 2026-06-07, qui est un **déplacement en masse**, pas de
   l'activité.
7. **`crop-forensics` est gelé, pas vieux** : ses signaux ont été **réfutés au bench**.
   Le coder en l'état serait une erreur.
