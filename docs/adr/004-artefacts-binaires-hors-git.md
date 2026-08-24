# ADR-004 — Artefacts binaires hors de git, fetchés au build

**Date :** 2026-08-14
**Statut :** ✅ **Acceptée et appliquée intégralement** (2026-08-16).

> **Correction du 2026-08-25.** Ce statut affirmait que `best.pt` et le dataset de
> détection « restent dans git ». **C'est faux depuis le 2026-08-16.** L'étape 3 a été
> jouée le même jour : `git ls-files | grep '\.pt$'` → **0**,
> `git ls-files ml/datasets/detection | wc -l` → **0**. Ils vivent dans
> `model-artifacts` sous le préfixe `training/`, épinglés par
> `shared/training-assets.json`, rapatriés par `go-task ml:training-assets:fetch`
> (`ml/tasks.yml`). Le transport Mac→PC **a** changé, et la rassurance « rien ne peut
> casser le PC » ne tient plus : un PC hors ligne sans cache d'artefacts n'a plus de
> poids.

## Contexte

`ml/output/` et `ml/datasets/*` sont **gitignorés** (`.gitignore` l.44 et l.57), et
pourtant ~50 Mo d'artefacts binaires y sont **trackés** : ils ont été force-ajoutés
(`git add -f`). Le commit `d1f5812 "Add .pt and .tflite for PC"` dit pourquoi sans détour :

> **git sert aujourd'hui de transport Mac→PC pour les poids.**

`docs/archive/handoffs-2026/HANDOFF-pc-full-training.md` confirme : la synchro du PC se fait
par `git fetch && git reset --hard origin/<branche>`.

Conséquences observées :
- `.git` pèse **146 Mo** après avoir été ramené de 1,3 Go à 109 Mo en juin — il a donc
  regrossi d'un tiers en six semaines, principalement par force-add
  (chiffres : [`../architecture/artifacts.md`](../architecture/artifacts.md) §Volumes) ;
- le problème n'est pas la taille absolue mais le **taux** : chaque ré-export du
  détecteur ajoute ~37 Mo **définitifs** à l'historique de **deux** remotes
  (codeberg + github), et rien ne borne le nombre de ré-exports ;
- le dernier commit a embarqué au passage 30 395 lignes d'artefacts de toolchain onnx2tf
  (`schema_generated.py`, `schema.fbs`, rapport de correspondance) — du bruit pur.

Contraintes à respecter :
- **MinIO existe déjà** (`eurio-s3.musubi.dev`) avec un cache read-through éprouvé
  (`ml/shared/storage/local_cache.py`), pensé Mac/PC dès l'origine.
- Le **versioning S3 est banni** (`infra/minio/README.md` §Anti-patterns) : le versionnage
  doit passer par la clé d'objet ou un manifeste.
- Un **précédent existe dans le repo** : `compileFilamentMaterials` (`build.gradle.kts`)
  génère des assets au build, gitignorés — et le `cohort_bundle` a déjà un
  **manifeste sha256 par fichier**, le seul mécanisme vérifié du projet.

## Décision

Sortir de git les artefacts binaires régénérables ou transportables, et les servir
depuis MinIO avec un **manifeste sha256** versionné par la clé d'objet.

Application par étapes, du plus sûr au plus risqué :

1. **Déchets purs** — aucun consommateur, aucun mécanisme requis.
   *Fait le 2026-08-14, commit `05be2dd`* : 6 variantes de quantization du détecteur,
   3 résidus onnx2tf, 2 `labels.cache`. −30 395 lignes, ~33 Mo.
2. **Modèles de l'APK** (`coin_detector.tflite`, `eurio_embedder_v1.tflite`,
   `coin_embeddings.json`, `model_meta.json`) → fetch au build Gradle, sur le modèle de
   `compileFilamentMaterials`. ⚠️ **Qualifier d'abord `test_model.tflite`** (19 Mo, non
   tracké, aucun consommateur identifié) : ne pas le porter dans le nouveau mécanisme
   sans savoir à quoi il sert.
3. **Poids et dataset de détection** (`best.pt`, les 3786 labels) → MinIO, **avec un
   remplacement du transport Mac→PC vérifié sur le PC avant tout `git rm`**.

`app_core.db` **n'est pas dans le périmètre** : `.gitignore` l.37-39 documente un choix
délibéré de le committer (« reproducible builds without Supabase access »). Le sortir
revient sur cette décision — sujet distinct.

## Exécution (2026-08-14) — mécanisme livré, bascule en attente

Périmètre arbitré ce jour-là : **modèles de l'APK uniquement**. `app_core.db` reste
committé (§Décision).

> **Élargi le 2026-08-16** : les artefacts d'entraînement (`best.pt`, dataset de
> détection) ont leur propre chaîne — préfixe `training/` dans `model-artifacts`,
> manifeste `shared/training-assets.json`, tâches `ml:training-assets:{publish,fetch,status}`.
> Le paragraphe ci-dessus les disait « restés dans git » ; ils n'y sont plus.

| Livré | Détail |
|---|---|
| **Deux casiers sous une racine** | `EURIO_CACHE_ROOT` (défaut `~/.cache/eurio`) reste la seule variable à déplacer. Images sous `<root>/<bucket>/`, artefacts sous `<root>/artifacts/`, **plafonds séparés** |
| **Plafond images posé** | `EURIO_CACHE_MAX_GB=20` dans `flake.nix`. Il n'était réglé **nulle part** : défaut `"0"` = aucune éviction, et le cache avait atteint **5,8 Go** en croissance libre |
| **Plafond artefacts** | `EURIO_ARTIFACTS_MAX_GB=5`. Un jeu de modèles fait ~14 Mo — de quoi garder l'historique des versions |
| **Cloisonnement prouvé** | `_evict_if_needed()` balayait toute la racine. Il exclut désormais `artifacts/`. **3 tests** : un artefact volontairement le plus ancien du cache survit à une éviction qui supprime bien l'image la plus ancienne |
| **Vérification sha256** | `artifact_path()` refuse un contenu non conforme (`ValueError`), re-télécharge un cache corrompu, et ne laisse jamais de `.tmp` derrière |
| **Adressage par contenu** | clé `models/<nom>/<sha256[:12]>/<fichier>` — le versioning S3 étant banni, la version est portée par la clé. Republier à l'identique est un no-op ; un contenu différent ne peut jamais écraser l'ancien |
| **Manifeste committé** | `shared/model-assets.json`. Le commit détermine entièrement les poids qui partent dans l'APK : un `git checkout` ancien récupère les modèles de ce commit. **La reproductibilité que donnait le fait de committer les binaires est conservée, sans les binaires** |
| **Outil** | `ml/scripts/model_assets.py` — `status` / `publish` / `fetch`, exposé en `go-task ml:assets:*` |
| **Tâche Gradle** | `fetchModelAssets`, enregistrée et appelable, **délibérément pas branchée sur `preBuild`** |
| **Bucket + policy** | `model-artifacts` ajouté à `infra/minio/bootstrap.sh` et à `eurio-app-policy.json` |

### Ce qui bloque la bascule, et pourquoi c'est sain

La clé applicative `eurio-app` **n'a pas le droit `CreateBucket`** — c'est voulu, elle est
scopée aux buckets existants. Le bucket se crée avec les creds admin, sur le VPS :

```
cd /opt/eurio/infra/minio && ./bootstrap.sh      # idempotent
```

Tant que ce n'est pas fait, `go-task ml:assets:publish` sort avec un message qui donne
cette commande. **Aucun fichier n'a été retiré de git**, et `fetchModelAssets` n'est pas
branchée sur `preBuild` : brancher une dépendance réseau au build avant d'avoir prouvé le
chemin casserait le build de tout le monde. La séquence restante, dans l'ordre :

1. `./bootstrap.sh` sur le VPS
2. `go-task ml:assets:publish` (écrit `shared/model-assets.json`)
3. supprimer les 4 assets du disque, `go-task ml:assets:fetch`, vérifier qu'ils reviennent
   identiques
4. **au même commit** : `git rm --cached` des 4 assets + gitignore + décommenter le
   `dependsOn(fetchModelAssets)`

## Bascule (2026-08-16) — faite, et vérifiée dans les deux sens

La séquence prévue ci-dessus a été jouée intégralement.

| Étape | Résultat |
|---|---|
| 1. Bucket `model-artifacts` créé sur le VPS | ✅ — **sans lancer `bootstrap.sh` en entier** : son étape 3 fait un `docker compose up -d` sur MinIO, dont dépendent `eurio-api`, `eurio-review` et le miroir de backup. Un `mc mb` + `mc version suspend` + réapplication de la policy suffisaient et ne touchent pas au conteneur |
| 2. `go-task ml:assets:publish` | ✅ 4 objets, 14,9 Mo, clés `models/<nom>/<sha12>/<fichier>` |
| 3. Suppression des 4 fichiers puis `fetch` | ✅ **4/4 identiques au sha256 près** |
| 4. `git rm --cached` + gitignore + `dependsOn(fetchModelAssets)` | ✅ même commit |

**Vérifié au-delà du protocole**, parce que c'est là que se cache la casse silencieuse :

- build complet `assembleDebug` avec les assets présents → vert, **aucun appel réseau**
  (`fetch` compare le sha au manifeste avant de construire le client MinIO) ;
- cas « clone frais » — les 4 fichiers supprimés du disque :
  - **sans credentials** → échec net, et le message actionnable remonte bien dans la
    sortie Gradle (vérifié : il n'est pas avalé par le `Exec`) ;
  - **avec credentials** → les 4 sont retéléchargés et `assembleDebug` passe.

### Un défaut trouvé au passage : la policy MinIO du repo avait divergé de la prod

`infra/minio/policies/eurio-app-policy.json` **ne contenait pas** le bucket `eurio-db`,
alors que la policy en production, elle, l'accorde. L'appliquer telle quelle aurait
**retiré cet accès** à `eurio-app` — un bucket legacy, certes (remplacé en R2 par
`ml/serving/db_routes.py`, retrait prévu en phase 5 de `data-layer-unification`), mais
encore miroité par le backup. Le bucket a donc été **remis dans le fichier**, isolé dans
un statement `LegacyEurioDbBucketToRemoveInDataLayerUnificationPhase5` : son retrait
redevient un acte délibéré au lieu d'un effet de bord.

Corrigé aussi : `bootstrap.sh` créait `model-artifacts` sans `mc version suspend`, seul
des quatre buckets à ne pas expliciter l'interdiction de versioning.

## Alternatives considérées

| Option | Verdict |
|---|---|
| Statu quo (git comme transport) | Historique qui enfle sans borne sur 2 remotes : 109 Mo → 146 Mo en six semaines |
| Git LFS | Ajoute un service et un coût ; MinIO est déjà là et déjà utilisé pour les images |
| `ml/state/archive.py` (tarball 500 Mo–1 Go, `ml:export-state-full`) | Existe, mais manuel et grossier — tout ou rien, pas de granularité par artefact |
| **MinIO + manifeste sha256** | Réutilise le cache read-through et le pattern `cohort_bundle` existants |

## Conséquences

**Bonnes**
- Historique git borné ; les ré-exports de modèle ne coûtent plus rien à git.
- Les artefacts gagnent un **sha vérifiable**, qu'ils n'ont pas aujourd'hui.
- Le transport Mac↔PC devient explicite au lieu d'être un effet de bord de git.

**Mauvaises, à assumer**
- ⚠️ **Le premier build après un clone exigera le réseau.** Nuance importante : le cache
  de `local_path()` **est déjà persistant** (retour immédiat si `target.exists()`), donc
  le hors-ligne marche sur cache chaud. Le risque réel est ailleurs : l'**éviction LRU**
  (`_evict_if_needed()`, plafond `EURIO_CACHE_MAX_GB`) peut supprimer un artefact déjà
  téléchargé et casser un build qui fonctionnait la veille. ~~Décision ouverte~~ →
  **tranchée** : `artifacts/` est un casier à part, exempté de l'éviction des images et
  doté de son propre plafond (`EURIO_ARTIFACTS_MAX_GB`), avec 3 tests dédiés.
  Et depuis la bascule, l'éviction du casier artefacts ne casserait pas un build non
  plus : `fetch` retéléchargerait, puisque le manifeste porte la clé et le sha.
- ⚠️ **Risque de casse silencieuse du PC** : si on retire les poids de git avant que le
  fetch marche, le prochain `reset --hard` les fait disparaître sans erreur ; l'échec
  n'apparaît qu'au premier appel de `ml/vision/normalize_snap.py`.
- ⚠️ **Le nouveau code de fetch ne sera pas testé par défaut** : `ml/tests/conftest.py`
  a une fixture **autouse** qui remplace le client MinIO par un `MagicMock`. Tout test du
  fetch demande un opt-out explicite.
- Sortir les fichiers de l'index ne réduit **pas** `.git` : seul un `filter-repo` ou un
  remaster le fait (cf. [ADR-005](./005-remaster-historique-git.md)).

## Références

- Inventaire complet : [`../architecture/artifacts.md`](../architecture/artifacts.md)
- Plan antérieur, jamais démarré : `docs/work-in-progress/datasets-minio-migration.md`
  (chiffres périmés : parle de 2,5 Go / 8895 fichiers, la réalité est ~50 Mo)
