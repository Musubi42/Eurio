# Phase 1B — Détection de pièce (YOLOv8-nano)

> Objectif : avant d'identifier une pièce, détecter qu'il y en a une dans le frame. Élimine les faux positifs (table, main, câbles) et crop automatiquement pour une meilleure identification.

---

## Contexte

En Phase 1, le classifieur analyse le frame entier et produit toujours une prédiction, même sans pièce visible. Résultat : 97% de confiance sur un bureau vide → inutilisable.

L'approche "scanner de nourriture" (Yuka, Open Food Facts) résout ça :
1. Détecter l'objet d'intérêt (ici, une pièce)
2. Cropper et ne classifier que la zone détectée
3. N'afficher un résultat que quand la détection est fiable

---

## 1B.1 — Dataset de détection ✅

### Source

Dataset Roboflow "coin-detection" (~1900 images annotées avec bounding boxes), téléchargé via le SDK Roboflow (clé API gratuite dans `.env`).

### Traitement

- Toutes les classes d'origine collapsées en classe unique `coin` (classe 0)
- 30 images négatives synthétiques ajoutées (fonds bois, tissu, bureau, sombre)
- Split automatique train/val (85/15) si le dataset source n'a pas de split val
- Script : `ml/setup_detection_dataset.py`

### Structure

```
ml/datasets/detection/
├── roboflow_raw/          # Dataset brut téléchargé
├── coin_detect/
│   ├── train/
│   │   ├── images/        # ~1620 images + 30 négatives
│   │   └── labels/        # Format YOLO : 0 x_center y_center width height
│   ├── val/
│   │   ├── images/        # ~280 images
│   │   └── labels/
│   └── data.yaml          # Config YOLOv8
```

### data.yaml

```yaml
train: .../coin_detect/train/images
val: .../coin_detect/val/images
nc: 1
names: ['coin']
```

---

## 1B.2 — Entraînement YOLOv8-nano ⏳

### Commande

```bash
go-task detect-train
# ou directement :
.venv/bin/python train_detector.py --export
```

### Configuration

```
model: yolov8n.pt (pré-entraîné COCO)
imgsz: 320            # 320×320 — suffisant pour détecter un cercle
epochs: 150
patience: 30          # Early stopping
batch: 16
freeze: 10            # Freeze backbone 10 premiers epochs
device: mps           # Apple Silicon
# Augmentation
degrees: 15.0
translate: 0.1
scale: 0.5
flipud: 0.5
fliplr: 0.5
```

### Métriques cibles

| Métrique | Cible |
|---|---|
| mAP@50 | > 90% |
| Precision | > 95% (pas de faux positifs) |
| Recall | > 85% (peut manquer quelques frames, le scan est continu) |
| Inference | < 10ms sur Pixel 9a (INT8, 320px) |

---

## 1B.3 — Export TFLite

```bash
go-task detect-export
```

Export automatique à la fin du training avec `--export` :
- Format : TFLite INT8
- NMS intégré dans le modèle (`nms=True`)
- Calibration automatique avec le dataset
- Taille cible : ~2 MB

---

## 1B.4 — Intégration Android ✅

### Pipeline à 2 modèles

```
CameraX frame (toutes les 300ms)
  ↓
[YOLOv8-nano CoinDetector] → détecte bounding box
  ↓
Si détection avec confiance > 50% :
  → Crop le bitmap (+ 10% padding)
  ↓
[MobileNetV3 ArcFace CoinRecognizer] → embedding 256-dim
  ↓
[EmbeddingMatcher] → cosine similarity vs centroids
  ↓
Résultat → UI (nom, pays, année, image)
```

### Fichiers Kotlin

| Fichier | Rôle |
|---|---|
| `CoinDetector.kt` | Wrapper TFLite pour YOLO. Supporte output NMS ([1,N,6]) et raw ([1,5,N]). |
| `CoinAnalyzer.kt` | Orchestre le pipeline 2 modèles. Toggles `useDetector` et `useEmbeddings` pour A/B testing. |
| `CoinRecognizer.kt` (CoinEmbedder) | MobileNetV3 TFLite. Supporte mode classify (softmax) et embed (raw embeddings). |
| `EmbeddingMatcher.kt` | Cosine similarity vs centroids chargés depuis `coin_embeddings.json`. |

### Toggle A/B testing

L'app a des toggles dans le debug panel pour comparer en temps réel :

| Toggle | ON | OFF |
|---|---|---|
| **YOLO** | Frame → YOLO crop → identifieur | Frame entier → identifieur (ancien comportement) |
| **ArcFace** | Embedding → cosine similarity | Logits → softmax classification |

Le toggle YOLO est grisé si `coin_detector.tflite` n'est pas dans les assets.

### Déploiement

```bash
# Copier le détecteur dans les assets Android
cp ml/output/coin_detector.tflite app/src/main/assets/models/
```

L'app détecte automatiquement la présence du modèle au démarrage.

---

## 1B.5 — Livrables

- [x] Dataset de détection (~1900+ images annotées)
- [ ] YOLOv8-nano entraîné (mAP@50 > 90%)
- [ ] Export TFLite INT8 (~2 MB)
- [x] `CoinDetector.kt` : wrapper TFLite pour YOLO
- [x] `CoinAnalyzer.kt` : pipeline 2 modèles avec toggles runtime
- [ ] Test conditions réelles : pas de résultat quand pas de pièce
- [ ] Stabilisation : debounce sur N frames consécutives
