# Inventaire des artefacts — provenance, consommateur, régénérabilité

> **But de ce fichier : ne plus jamais re-découvrir d'où vient un fichier binaire.**
> Chaque entrée dit qui le produit, qui le consomme, et ce qui se passe si on le perd.
> Vérifié le 2026-08-14. Vue d'ensemble : [`README.md`](./README.md).

**Colonne « Perte »** : 🟢 régénérable par une commande · 🟡 régénérable sous condition
· 🔴 irremplaçable.

## Modèles embarqués dans l'APK

Tailles = `ls -lh` sur disque. **Tracké** ou non indiqué explicitement.

| Artefact | Taille | Tracké | Produit par | Consommé par | Perte |
|---|---|---|---|---|---|
| `assets/models/coin_detector.tflite` | 10 Mo | **non** *(MinIO, ADR-004)* | `ml/training/train_detector.py --export` → `ml/output/`, puis **copie manuelle** | `CoinDetector.kt` | 🟢 `fetchModelAssets` — la version est épinglée par `shared/model-assets.json` |
| `assets/models/eurio_embedder_v1.tflite` | 4,4 Mo | **non** *(MinIO, ADR-004)* | `ml/training/export_tflite.py` → `ml/prod/current/` → `ml/scripts/promote_prod_assets.py` | `CoinEmbedder.kt`, `CoinAnalyzerFactory.kt` | 🟢 idem |
| ⚠️ `assets/models/test_model.tflite` | **19 Mo** | **non** | **inconnu** | **inconnu** (aucun consommateur identifié) | ❓ **À qualifier** — c'est le plus gros fichier des assets, daté du 2026-04-09, jamais documenté. Résidu de spike ? |
| `assets/data/coin_embeddings.json` | 61 ko | **non** *(MinIO, ADR-004)* | `ml/training/compute_embeddings.py` | `EmbeddingMatcher.kt` | 🟢 idem — c'est la table de centroïdes du run promu |
| `assets/data/model_meta.json` | 958 o | **non** *(MinIO, ADR-004)* | `ml/training/export_tflite.py` | `CoinEmbedder.kt` | 🟢 couplé au `.tflite`, publié avec lui |
| `assets/app_core.db` | 3,2 Mo | oui | `ml/export/build_app_core.py` (**lit Supabase**) | `AppCoreBootstrapper.kt` | 🟢 `go-task ml:build-app-core` |
| `src/qa/assets/app_core.db` | 147 ko | non | `ml/export/build_app_core_qa.py` | variante QA | 🟢 |
| `assets/shared_reverse/reverse_2eur_v{1,2}.webp` | 186 ko | oui | `ml/export/build_shared_reverse_assets.py` (re-télécharge + ré-encode) | `CoinRepository.kt` | 🟢 |
| `assets/capture_coins.csv` | 1,5 ko | oui | édité à la main | app | 🔴 donnée primaire |

⚠️ Aucun de ces fichiers n'a de **sha ni de version vérifiée** dans l'APK. ~~Le seul
mécanisme sha256 du projet est le manifeste du `cohort_bundle`~~ → depuis le 2026-08-16,
les 4 artefacts de modèle en ont un : `shared/model-assets.json`, committé, vérifié à
chaque `fetch`. `app_core.db`, `capture_coins.csv` et les WebP restent sans sha.

## Poids d'entraînement

| Artefact | Taille | Produit par | Consommé par | Perte |
|---|---|---|---|---|
| `ml/output/detection/coin_detector/weights/best.pt` | 5,9 Mo | `ml/training/train_detector.py` (YOLOv8-nano) | **prod** : `ml/vision/normalize_snap.py`, + évals | 🟢 depuis le 2026-08-16 : publié dans MinIO, épinglé par `shared/training-assets.json`, rapatrié par `go-task ml:training-assets:fetch`. Un ré-entraînement, lui, ne le refait **pas bit-à-bit** |
| `ml/output/…/tflite_out/best_*.tflite` (6 variantes) | 32 Mo | `train_detector.py --export` | **aucun consommateur** | 🟢 — **retirés de git le 2026-08-14** (`05be2dd`) |

**Ce que fait `best.pt`** : YOLOv8-nano **mono-classe** (`names: ['coin']`). Il ne
reconnaît pas la pièce, il dit **où** elle est. Il fournit le *prior* (les ROI) à la
passe Hough qui raffine le rim en sub-pixel. Sans lui, sur les fonds chargés d'eBay
(coincards avec texte, blisters, mosaïques), Hough vote sur les lettres et les motifs
circulaires et produit des dizaines de faux candidats. Raison écrite dans
`ml/vision/normalize_snap.py` §Listing pipeline.

## Dataset de détection — origine élucidée

`ml/datasets/detection/` contient **deux vues du même corpus** :

| Dossier | Contenu | Provenance |
|---|---|---|
| `roboflow_raw/` | 1878 images, **14 classes** (1 Euro, 2 Euro, US 1cent, US 25cent, Canada 10cent, Croatia 2 Kune…) | **Dataset public Roboflow `coin-gva2j`, CC BY 4.0** — `https://universe.roboflow.com/yolocoin/coin-gva2j/dataset/1`. Photos d'un utilisateur tiers (noms de fichiers `KakaoTalk_2022…`) |
| `coin_detect/` | 1908 images = les 1878 de Roboflow **écrasées en 1 seule classe `coin`** + **30 négatifs à nous** | dérivé + apport propre |

**L'écrasement 14 classes → 1 est délibéré et correct** : on veut « objet rond
métallique », pas l'identification. S'entraîner sur des pièces non-euro *aide* la
généralisation.

> ✅ **Depuis le 2026-08-16, l'ensemble du dossier `ml/datasets/detection/` est un
> artefact rapatriable** — 7 580 fichiers, 47,5 Mo de contenu, publié dans
> `model-artifacts` sous `training/detection_dataset/<content_digest[:12]>/` et épinglé
> par `shared/training-assets.json`. `go-task ml:training-assets:fetch` le reconstruit
> intégralement. Vérifié : dataset supprimé + cache vidé → reconstruction de 7 580
> fichiers identiques octet à octet.

| Élément | Perte | Détail |
|---|---|---|
| Les 1878 images Roboflow | 🟢 | Dans l'artefact. Re-téléchargeables par ailleurs, mais ⚠️ **le script de re-fetch a été retiré du repo** — seule l'URL du `data.yaml` reste |
| Les **30 `negative_*.jpg`** (2,5 Mo) | 🟢 | ~~🔴~~ Nos images sans pièce, pour réduire les faux positifs. Elles étaient sur **un seul disque** (leurs labels dans git, pas elles) ; elles sont maintenant dans l'artefact MinIO, donc dans la chaîne de sauvegarde |
| Les **3788** `.txt` de labels | 🟢 | Dans l'artefact, avec les images qu'ils annotent. Encore trackés dans git en double — le `git rm` attend une vérification depuis le PC |

🔴 **Sauvegarde des 30 négatifs** : `eurio-detection-negatives-20260814.tar.gz`
(2,5 Mo, sha256 `85ba18d584c929c361b822d8852647170b52ab2cc54562bf00861aa0b4cd98a6`),
avec les `data.yaml` et README Roboflow pour la provenance. → pCloud.
*Ce fichier vit **hors du repo** (`~/Documents/Musubi42/eurio-backups/`) : un agent ne
peut pas le vérifier depuis le dépôt.*

~~⚠️ `coin_detect/data.yaml` contient des **chemins absolus périmés**~~ → **corrigé le
2026-08-16**, en même temps que le passage en artefact : un dataset rapatriable ne peut
pas supposer un emplacement absolu. Les chemins sont maintenant relatifs (`path: .`).
Le fichier déclarait aussi un split `test:` qui **n'a jamais existé sur disque** — retiré.

## Données primaires — à garder en git, jamais régénérables

| Artefact | Pourquoi |
|---|---|
| `ml/datasets/eurio_referential.json` (4,2 Mo), `coin_catalog.json`, `matching_log.jsonl` | Référentiel canonique |
| `ml/state/*/{*gold*,ground_truth}.jsonl` (`denom_gold`, `face_gold`, `crop_gold`, `verdict_gold`, `theme_match_gold`…) | 🔴 **Annotation humaine.** Irremplaçable |
| `ml/state/*_nids.txt` (25, un par pays) | Listes de Numista IDs |
| `shared/fixtures/qa_curation.json` | Édité à la main par le PO |
| `ml/datasets/sources/*.{html,json}` (98, ~14 Mo) | 🔴 Snapshots web datés, non re-téléchargeables. Force-ajoutés contre `.gitignore` |

## À qualifier

| Artefact | Question |
|---|---|
| `ml/state/review.db` + `-wal` + `-shm` | Une SQLite **avec ses sidecars WAL** dans git est incohérente par construction. Intentionnel ? |
| `ml/shared/state/eurio.db` | ~~Rôle non établi~~ → **élucidé le 2026-08-16** : c'était la DB de quota d'API (table `api_call_log`, seule table du fichier), écrite par un chemin codé en dur qui ignorait `EURIO_DB_PATH` — la cause du bug B1. Le quota vit désormais dans `ml/state/eurio.local.db` (gitignorée). Ce fichier n'est plus lu ; **reste tracké** en attendant que chaque machine ait joué la reprise des compteurs. Le détracker est une décision PO |
| `ml/state/denom_bench/gold_vitl14.npz` (3,3 Mo) | Cache d'embeddings. Régénérable mais coûteux (recalcul ViT-L/14 sur tout le gold) |

## Volumes — pour calibrer les attentes

> **Source unique des chiffres du projet.** Les autres documents renvoient ici plutôt que
> de recopier ces valeurs — un chiffre recopié dans quatre fichiers se corrige quatre fois.

| Périmètre | Tracké dans git | Sur disque |
|---|---|---|
| `ml/datasets/` | 33 Mo | 1,0 Go |
| `ml/output/` | 6,2 Mo *(après `05be2dd`, ne reste que `best.pt`)* | 599 Mo |
| `ml/state/` | ~10 Mo | **970 Mo** *(2,5 Go avant le 2026-08-16 — voir ci-dessous)* |
| `app-android/src/main/assets/` | 17,7 Mo | 36 Mo *(dont `test_model.tflite`, 19 Mo, non tracké)* |
| **`.git`** | — | **146 Mo** *(`size-pack` 143,3 Mio, mesuré après repack)* |

Le tracké total en jeu est de l'ordre de **~50 Mo**, pas de 2,5 Go. Le vrai poids est
dans l'**historique**, que seul un `filter-repo` récupère.

## Les sauvegardes ad hoc de `ml/state/` — supprimées le 2026-08-16

`ml/state/` portait **1,7 Go de `.bak-*` / `.pre-*` / `.fix-*`** : 44 SQLite et 2 `.npz`
nommés par chantier (`pre-obverse`, `pre-lanes`, `prebcewipe`…), de mai à juillet, sans
manifeste ni politique de rétention. De la donnée périmée qui ressemble à de la donnée
vivante — le premier endroit où se tromper de fichier.

**Ce qu'ils contenaient d'unique**, mesuré contre le canonique : **5 034 éléments**
— 135 décisions de review, 1 840 crops et 3 059 raws référencés nulle part ailleurs.

> **Trouvaille au passage, à reporter dans le chantier backup** : les « ~4 981 orphelins
> bénins » de MinIO (cf. [`DONNEES.md`](../work-in-progress/backup-pipeline/DONNEES.md)
> §4) **ne sont pas des déchets**. 1 836 des 1 841 crops et 3 059 des 3 140 raws
> orphelins ont une fiche, et elle vivait uniquement dans ces `.bak`. 134 décisions
> humaines (dont 82 identifiant une pièce) pointent vers des crops toujours présents dans
> MinIO. La phrase « ils occupent de la place sans que rien ne les réclame » est vraie du
> point de vue du canonique et fausse du point de vue de la donnée.

Tout l'apport propre est extrait dans **`eurio-bak-recovery-20260816.db`** (2,54 Mo,
sha256 `c3df5703ac78b0784f4ba29c3ffb31f5a681e68ab1673d9944223095120fac7e`), avec la
provenance de chaque ligne. Il vit **hors du dépôt** : copie locale dans
`~/Documents/Musubi42/eurio-backups/` et copie hors machine sur pCloud
(`backups/eurio/`). La couverture a été vérifiée par recomparaison à l'union des 44
fichiers — 5 034/5 034 — avec un test de mutation qui la fait échouer sur 4 lignes
retirées.

⚠️ Le tarball des 30 négatifs (`eurio-detection-negatives-20260814.tar.gz`) **n'était
jamais arrivé sur pCloud** malgré ce que ce fichier affirmait ; il y est depuis le
2026-08-16, sha vérifié en relecture. Les négatifs sont par ailleurs dans l'artefact
MinIO du dataset.

**Reste à faire** : réinjecter les 134 décisions dans le canonique par `/ingest/*`. 82
d'entre elles désignent une pièce par un identifiant de l'ancien schéma (le référentiel a
été re-clé et réduit : 2 628 pièces en mai, 689 aujourd'hui) — il faut les remapper, ou
les réinjecter en « à re-décider » avec le crop rattaché.

*Mesuré le 2026-08-14. `.git` avait été ramené de 1,3 Go à 109 Mo en juin ; il est
remonté depuis, principalement à cause des artefacts force-ajoutés.*
