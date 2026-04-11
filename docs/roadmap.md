# Eurio — Roadmap & Retrospective

> Journal de bord du projet. Chaque phase est documentée au fur et à mesure avec ce qui a été fait, les décisions prises, et les écarts par rapport au plan initial.

---

## Phase 0 — Setup & Prérequis ✅

**Statut :** Terminée — 2026-04-09

### Ce qui a été fait

- [x] Projet Android Studio créé (Kotlin + Compose, package `com.musubi.eurio`)
- [x] Dépendances ajoutées : LiteRT, CameraX, Room, Supabase, Koin, Navigation
- [x] DevShell Nix (`flake.nix` + `.envrc`) : JDK 17, Android SDK 35/36, Gradle, Python 3.12, PyTorch, uv, go-task
- [x] API Numista testée et fonctionnelle (endpoint `v3/types`)
- [x] Supabase : projet créé, 4 tables migrées (`coins`, `coin_embeddings`, `price_history`, `user_collections`)
- [x] LiteRT validé sur Pixel 9a : 1000 classes, 16ms d'inférence
- [x] CameraX : flux caméra fonctionnel sur device
- [x] ML Python : PyTorch + MPS (Apple GPU), MobileNetV3-Small chargé (2.5M params)
- [x] ai-edge-torch installé via uv (venv dans `ml/.venv/`)
- [x] Photos de pièces prises (74 images dans `ml/datasets/`)
- [x] Structure `ml/` créée (placeholder scripts)

### Ce qui n'est pas encore fait

- [ ] eBay Browse API — compte dev en attente de validation
- [ ] Datasets Kaggle — pas encore téléchargés
- [ ] Vérification licences images Numista + datasets

### Écarts par rapport au plan

| Prévu | Réalité | Raison |
|---|---|---|
| TFLite 2.16.1 | LiteRT 1.4.2 | Les `.so` TFLite n'étaient pas 16KB-aligned → incompatible Pixel 9a / Android 15+ ([ADR-001](adr/001-litert-over-tflite.md)) |
| `brew install` / `pip install` | Nix devShell + uv | Reproducibilité, pas d'install globale ([ADR-002](adr/002-nix-devshell.md)) |
| Python 3.11 | Python 3.12 | Conflit sphinx/torch dans nixpkgs pour 3.11 |
| `ai-edge-torch` | `litert-torch` (renommé upstream) | Package renommé, l'import `ai_edge_torch` est deprecated |

---

## Phase 1 — Data & ML Pipeline ✅

**Statut :** Terminée — 2026-04-09

### Ce qui a été fait

- [x] Pipeline ML complète : 8 scripts Python (prepare, train, evaluate, visualize, export, validate, embeddings, seed)
- [x] Taskfile.yml (go-task) pour automatiser la pipeline
- [x] README.md dans `ml/` avec documentation de chaque étape
- [x] `coin_catalog.json` : source de vérité pour les IDs Numista
- [x] Dataset : 5 classes, 74 images, split train/val/test (52/15/7)
- [x] Modèle classifieur MobileNetV3-Small : **val accuracy 80%, top-3 100%**
- [x] Export TFLite validé (4.2 MB, parity cosine 1.000 avec PyTorch)
- [x] Supabase seedé : 5 pièces + embeddings via Numista API (upsert idempotent)
- [x] RLS policies propres : lecture publique, écriture service_role, user_collections scoped
- [x] Scan continu sur Pixel 9a : CameraX ImageAnalysis → TFLite → résultat en overlay
- [x] Fetch détails depuis Supabase (postgrest-kt)
- [x] BuildConfig pour SUPABASE_URL/ANON_KEY depuis `.env`

### Décisions techniques majeures

| Décision | Contexte | Choix |
|---|---|---|
| Classification vs Metric Learning | 5 classes, 13-17 images/classe. Triplet loss → embedding collapse (R@1=14%). | **Classification (cross-entropy)** pour le POC. ArcFace pour le futur (500+ classes). |
| Numista IDs | La recherche Numista API est trop vague. Des IDs devinés retournaient des pièces complètement fausses. | **`coin_catalog.json`** avec IDs vérifiés manuellement. Source de vérité unique. |
| RLS Supabase | Besoin d'insérer des données en seed. Anon key bloquée par RLS. | **Service role key** pour les scripts admin. Policies propres dès le POC. |
| Scan UX | L'utilisateur ne doit pas appuyer sur un bouton ni centrer la pièce. | **Scan continu** (comme un scanner QR). ImageAnalysis toutes les 300ms. |

### Ce qui n'a PAS marché

| Tentative | Résultat | Leçon |
|---|---|---|
| Triplet loss + BatchHardMiner | R@1 = 14% sur test. Embedding collapse total (toutes les sims à 97%). | Triplet loss est instable avec très peu de données. Nécessite des centaines de classes. |
| 1 batch/epoch | 52 images, batch=40, drop_last=True → 1 seul batch par epoch. Le modèle ne voyait qu'un gradient step par epoch. | Toujours vérifier le nombre effectif de batches. Oversampling x10 a résolu. |
| `ai_edge_torch.convert()` | `AttributeError: module has no attribute 'convert'`. Le package est renommé. | Utiliser `litert_torch.convert()`. |

### Métriques finales

| Métrique | Triplet Loss (v1) | Classification (v2) |
|---|---|---|
| Val Recall@1 / Accuracy | 14% | **80%** |
| Val Top-3 | 28% | **100%** |
| TFLite size | 4.2 MB | 4.2 MB |
| Inference time (Pixel 9a) | 16ms | 30ms |
| Model load time | 48ms | 82ms |

### Test en conditions réelles (Pixel 9a)

- La 2€ allemande (Kniefall) est **bien reconnue** quand bien cadrée
- La 1€ Portugal est **bien reconnue**
- La 1€ Espagne (Juan Carlos) est sur-représentée — le modèle la prédit par défaut
- La 1€ Italie (Vitruve) et 1€ Allemagne (Aigle) sont **mal reconnues** (confondues avec Juan Carlos)
- **Problème principal** : le modèle classifie tout ce qui est dans le frame (table, câbles, main), pas seulement la pièce → faux positifs constants

### Conclusion Phase 1

Le pipeline end-to-end fonctionne : photo → modèle → TFLite → Android → scan continu → Supabase. La qualité de reconnaissance est insuffisante pour un usage réel, mais les causes sont identifiées (peu de données + pas de détection de pièce). La Phase 1B va adresser ça.

---

## Phase 1B — Détection de pièce (YOLOv8-nano) ⏳

**Statut :** En cours — 2026-04-10

### Objectif

Ajouter une étape de détection avant l'identification. Le modèle doit d'abord détecter qu'il y a une pièce dans le frame, cropper autour, puis identifier.

### Ce qui a été fait

- [x] 1B.1 — Dataset de détection préparé
  - Dataset Roboflow "coin-detection" téléchargé (~1900 images avec bounding boxes)
  - Toutes les classes collapsées en classe unique `coin`
  - 30 images négatives synthétiques ajoutées (fonds sans pièce)
  - Split train/val automatique (85/15)
  - Script : `setup_detection_dataset.py`
- [x] 1B.2 — Entraînement YOLOv8-nano lancé
  - YOLOv8n pré-entraîné COCO, fine-tuné à 320×320
  - Freeze backbone 10 epochs, patience 30 (early stopping)
  - Augmentation : rotation 15°, scale 0.5, flipud/fliplr 0.5
  - Script : `train_detector.py`
- [x] 1B.4 — Intégration Android préparée
  - `CoinDetector.kt` : wrapper TFLite pour YOLO (supporte NMS intégré et raw output)
  - `CoinAnalyzer.kt` : pipeline 2 modèles en série (YOLO crop → identifieur)
  - Toggle YOLO ON/OFF dans le debug panel pour A/B testing
  - Graceful fallback : si `coin_detector.tflite` absent → full-frame (ancien comportement)

### Training terminé ✅ — mais résultats réels décevants ❌

**Métriques training** : mAP@50=99.5%, P=99.7%, R=100% — excellent sur le val set.

**Test Pixel 9a (2026-04-10)** : faux positifs massifs. YOLO détecte des "pièces" sur les murs, écrans, bureaux à 80-89% de confiance. Quand il crop ces zones random, ArcFace retourne systématiquement 226447 (Kniefall) comme "moins mauvais" match.

Voir analyse complète : `docs/research/yolo-detection-findings.md`

### Problèmes identifiés

1. **Dataset manque de négatifs réalistes** — les 30 images synthétiques ne suffisent pas face au monde réel
2. **Bbox trop grandes** — les crops font 40-50% du frame au lieu de cibler un petit objet
3. **Export TFLite** — INT8 cassé, NMS cassé, float32 seul fonctionne (12 MB au lieu de 2 MB)

### En attente (prochaine session)

- [ ] Enrichir le dataset avec 50-100 négatifs réalistes (photos Pixel)
- [ ] Explorer un meilleur dataset ou un modèle pré-entraîné
- [ ] Ré-entraîner et re-tester
- [ ] Résoudre l'export INT8/float16 pour réduire la taille

### Décisions

| Décision | Contexte | Choix |
|---|---|---|
| Dataset | Annoter 74 images à la main vs dataset existant | **Dataset Roboflow** (~1900 images) collapsé en classe unique — beaucoup plus rapide |
| Image size | 640px (standard YOLO) vs 320px | **320px** — suffisant pour détecter un cercle, <10ms inférence |
| Négatives | Pas de négatives vs images sans pièce | **30 images synthétiques** — insuffisant, besoin de négatifs réalistes |
| Export | INT8 + NMS vs float32 sans NMS | **Float32 sans NMS** — seul format fonctionnel (12 MB). NMS fait côté Kotlin. |
| Seuil | 50% vs 70% | **70%** — réduit les faux positifs les plus flagrants |

---

## Phase 2B — ArcFace + Catalogue ✅ (partiellement)

**Statut :** ArcFace validé sur 5 classes — 2026-04-10. Catalogue en cours d'import.

### Objectif

Passer de la classification (cross-entropy, 5 classes) au metric learning (ArcFace, scalable à 500+), et constituer un catalogue complet des pièces 2€ euro.

### Ce qui a été fait

#### ArcFace — validé ✅

- [x] Mode `--mode arcface` ajouté à `train_embedder.py`
  - Utilise `pytorch-metric-learning.losses.ArcFaceLoss` (déjà dans le venv)
  - Optimizer séparé pour la matrice de poids ArcFace (SGD, lr=0.01)
  - Hyperparamètres : margin=28.6°, scale=30, epochs=40, batch=64, m_per_class=4
- [x] Entraîné sur 5 pièces avec augmentation synthétique
  - **R@1 = 100%** dès l'epoch 8, stable jusqu'à epoch 40
  - Train loss : 13.3 → 0.04 (convergence propre, pas de collapse)
- [x] Export TFLite validé (4.2 MB, output shape [1, 256], cosine sim 1.000)
- [x] Embeddings de référence calculés et déployés (13 KB, 5 pièces)
- [x] Intégration Android avec `EmbeddingMatcher` (cosine similarity)
- [x] Toggle ArcFace ON/OFF dans le debug panel pour A/B testing

#### Augmentation synthétique ✅

- [x] Script `augment_synthetic.py` : rotation 360°, fonds variés, éclairage, perspectives, masque circulaire
- [x] 50 images augmentées par classe → intégrées dans le train set uniquement
- [x] `prepare_dataset.py` modifié : les augmentées vont dans train, les photos réelles dans val/test

#### Catalogue Numista — en cours ⏳

- [x] Script `import_numista.py` : recherche globale "2 euros", filtrage par face_value, téléchargement images
- [x] 445 pièces de 2€ importées (métadonnées complètes + ~300 images)
- [x] Répertoires renommés de slugs vers Numista IDs (ex: `1eur_italy_2006_vitruve` → `135`)
- [x] `coin_catalog.json` migré : clé = Numista ID, métadonnées enrichies (description, poids, diamètre, composition)
- [x] Image URLs cachées dans le catalogue pour retry sans API
- [ ] ~145 images manquantes (rate limit Numista atteint : 2060/~2000 calls/mois)
- [ ] ~55 coins restant à importer (pages non scannées)

### Comparaison des 3 approches ML

| Métrique | Triplet Loss | Classification | **ArcFace** |
|---|---|---|---|
| Val R@1 / Accuracy | 14% | 80% | **100%** |
| Val Top-3 | 28% | 100% | **100%** |
| Convergence | Collapse | 20 epochs | **8 epochs** |
| Ajout nouvelle pièce | Ré-entraîner | Ré-entraîner | **Juste calculer centroid** |
| Scale à 500 classes | Non viable | Fragile | **Conçu pour** |

### Décisions

| Décision | Contexte | Choix |
|---|---|---|
| Librairie ArcFace | insightface vs pytorch-metric-learning vs manuel | **pytorch-metric-learning** — déjà installé, bien maintenu |
| Embedding dim | 128 vs 256 vs 512 | **256** — sweet spot pour ~500 classes |
| Test sur 5 vs 500 classes | Entraîner tout d'un coup vs valider petit puis scaler | **5 pièces d'abord** — validation rigoureuse sur pièces physiques possédées |
| Directory naming | Slugs humains vs Numista IDs | **Numista IDs** — automatisable, pas d'ambiguïté |
| Numista search | Par pays vs recherche globale | **Recherche globale** `q=2+euros` — plus simple, attrape tous les pays |
| Catalogue format | Numista IDs comme clés, URLs d'images cachées pour retry offline | **coin_catalog.json** avec `obverse_image_url` et `reverse_image_url` |

### Ce qui reste pour compléter Phase 2B

- [ ] Compléter le catalogue (attendre reset quota Numista en mai, puis `--backfill-urls` + `--retry-images`)
- [ ] Entraîner ArcFace sur les ~445 classes (quand toutes les images sont là)
- [ ] Sync OTA des embeddings via Supabase Storage

---

## Phase 2 — Scan MVP ✅ (largement avancée)

**Statut :** Fonctionnel — scan continu + ArcFace + détails + image Numista

### Ce qui a été fait

- [x] CameraX ImageAnalysis en mode continu (throttle 300ms)
- [x] Pipeline 2 modèles : `CoinDetector` (YOLO) → crop → `CoinRecognizer` (ArcFace) → `EmbeddingMatcher`
- [x] Overlay résultat : nom, pays, année, valeur, type, image obverse Numista (via Coil)
- [x] Debug panel : inference time, detection confidence, top 3 matches
- [x] **Toggles A/B testing** : YOLO ON/OFF, ArcFace ON/OFF — comparaison en temps réel
- [x] Fetch détails depuis Supabase (match par Numista ID)
- [x] Pas de bouton scan — expérience type QR code scanner
- [x] Dépendance Coil ajoutée pour chargement d'images async

### Ce qui reste

- [ ] Stabilisation du résultat (debounce — même match sur N frames consécutives)
- [ ] Seuils de confiance affinés (après validation YOLO sur device)
- [ ] Bouton "Ajouter au Coffre" (pré-requis Phase 3)
- [ ] Retirer les toggles debug pour la release

---

## Phase 3 — Le Coffre & Valorisation ⏳

**Statut :** À démarrer

Inchangé — voir `docs/phases/phase-3-coffre.md`. Pré-requis : Phase 2 finalisée.

---

## Phase 4 — Gamification & Achievements ⏳

**Statut :** À démarrer

Inchangé — voir `docs/phases/phase-4-gamification.md`. Pré-requis : Phase 3 finalisée.

---

## Phase 5 — Polish & Beta ⏳

**Statut :** À démarrer

Inchangé — voir `docs/phases/phase-5-polish-beta.md`. Pré-requis : Phase 4 finalisée.

---

## Architecture ML actuelle (2026-04-10)

```
                        ┌─────────────────────┐
                        │   CameraX Frame     │
                        │   (toutes les 300ms) │
                        └──────────┬──────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │   CoinDetector (YOLOv8n)    │
                    │   320×320 · ~2 MB · <10ms   │
                    │   "Y a-t-il une pièce ?"    │
                    └──────────────┬──────────────┘
                                   │
                          confiance > 50% ?
                         /                \
                       Non                 Oui
                        │                   │
                   "No coin"        crop bounding box
                                          │
                    ┌─────────────────────▼──────────────────────┐
                    │   CoinRecognizer (MobileNetV3 + ArcFace)   │
                    │   224×224 · 4.2 MB · ~5ms                  │
                    │   → embedding 256-dim L2-normalisé         │
                    └─────────────────────┬──────────────────────┘
                                          │
                    ┌─────────────────────▼──────────────────────┐
                    │   EmbeddingMatcher (cosine similarity)      │
                    │   vs base de centroids (coin_embeddings.json)│
                    │   → top-3 matches avec confiance            │
                    └─────────────────────┬──────────────────────┘
                                          │
                    ┌─────────────────────▼──────────────────────┐
                    │   UI: nom · pays · année · image Numista   │
                    └────────────────────────────────────────────┘
```

### Scripts ML (`ml/`)

| Script | Commande go-task | Description |
|---|---|---|
| `import_numista.py` | `import-numista` | Import catalogue 2€ depuis Numista API v3 |
| `augment_synthetic.py` | `augment` | Génère images augmentées (rotation, fonds, éclairage) |
| `prepare_dataset.py` | `prepare` | Split train/val/test + injection augmentées dans train |
| `train_embedder.py` | `train-arcface` | Entraîne MobileNetV3 + ArcFace (ou classify/embed) |
| `export_tflite.py` | `export` | Export PyTorch → TFLite via litert_torch |
| `validate_export.py` | `validate` | Vérifie parity PyTorch ↔ TFLite (cosine sim > 0.99) |
| `compute_embeddings.py` | `embeddings` | Calcule les centroids de référence par classe |
| `setup_detection_dataset.py` | `detect-setup` | Télécharge et prépare dataset YOLO (Roboflow) |
| `train_detector.py` | `detect-train` | Entraîne YOLOv8-nano + export TFLite |
| `seed_supabase.py` | `seed` | Seed Supabase avec catalogue + embeddings |
| `rename_to_numista_ids.py` | `migrate-dirs` | Migration one-shot des slugs vers Numista IDs |

### Assets Android

| Fichier | Taille | Description |
|---|---|---|
| `models/eurio_embedder_v1.tflite` | 4.2 MB | MobileNetV3-Small ArcFace, input [1,3,224,224], output [1,256] |
| `models/coin_detector.tflite` | ~2 MB | YOLOv8-nano, input [1,3,320,320], output bboxes (à venir) |
| `data/coin_embeddings.json` | 13 KB | Centroids 256-dim pour 5 pièces |
| `data/model_meta.json` | <1 KB | Mode (arcface), classes, embedding_dim |
