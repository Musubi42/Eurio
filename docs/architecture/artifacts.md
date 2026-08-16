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
| `ml/output/detection/coin_detector/weights/best.pt` | 5,9 Mo | `ml/training/train_detector.py` (YOLOv8-nano) | **prod** : `ml/vision/normalize_snap.py`, + évals | 🟡 régénérable (dataset re-téléchargeable, voir plus bas) mais **pas bit-à-bit** |
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

| Élément | Perte | Détail |
|---|---|---|
| Les 1878 images Roboflow | 🟢 | Re-téléchargeables. ⚠️ **le script de re-fetch a été retiré du repo** (`ml/tasks.yml`) — seule l'URL du `data.yaml` reste |
| Les **30 `negative_*.jpg`** (2,5 Mo) | 🔴 | Nos images sans pièce, pour réduire les faux positifs. **Leurs 30 labels sont trackés dans git, pas leurs images.** |
| Les **3788** `.txt` de labels | 🟡 | Trackés dans git, répartis sur les **deux** vues (`coin_detect/` 1908 + `roboflow_raw/` 1880). Inutiles sans les images |

🔴 **Sauvegarde des 30 négatifs** : `eurio-detection-negatives-20260814.tar.gz`
(2,5 Mo, sha256 `85ba18d584c929c361b822d8852647170b52ab2cc54562bf00861aa0b4cd98a6`),
avec les `data.yaml` et README Roboflow pour la provenance. → pCloud.
*Ce fichier vit **hors du repo** (`~/Documents/Musubi42/eurio-backups/`) : un agent ne
peut pas le vérifier depuis le dépôt.*

⚠️ `coin_detect/data.yaml` contient des **chemins absolus périmés**
(`…/Musubi42/Eurio/…` au lieu de `…/Musubi42/bizz/Eurio/…`) : cassé sur le Mac actuel.

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
| `ml/state/` | ~10 Mo | 2,5 Go |
| `app-android/src/main/assets/` | 17,7 Mo | 36 Mo *(dont `test_model.tflite`, 19 Mo, non tracké)* |
| **`.git`** | — | **146 Mo** *(`size-pack` 143,3 Mio, mesuré après repack)* |

Le tracké total en jeu est de l'ordre de **~50 Mo**, pas de 2,5 Go. Le vrai poids est
dans l'**historique**, que seul un `filter-repo` récupère.

*Mesuré le 2026-08-14. `.git` avait été ramené de 1,3 Go à 109 Mo en juin ; il est
remonté depuis, principalement à cause des artefacts force-ajoutés.*
