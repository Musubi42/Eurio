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

### ⬜ Lot 3 — `@eurio/tokens` + générateur multi-cible
Package = `tokens.css` + `shared/fixtures/`. Tue au passage le symlink
`app-android/src/qa/assets/fixtures`.

### ⬜ Lot 4 — Registre d'artefacts MinIO
Le gros morceau. Sort les binaires de git **et** rend le split possible.
**Le fetch doit être vérifié sur le PC avant tout `git rm`.**

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
