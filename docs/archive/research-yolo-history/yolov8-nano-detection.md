# YOLOv8-nano — Recherche détection de pièces

> Recherche effectuée le 2026-04-10. Objectif : détecter "y a-t-il une pièce dans le frame ?" avant identification.

---

## 1. Datasets existants

| Source | Images | Format | Notes |
|---|---|---|---|
| Roboflow "Coin Detection" (Aistudio) | ~2400 | YOLO | Multi-class, collapser en `coin` unique |
| Roboflow "Coins Detection" (Almira) | ~600 | YOLO | Bounding boxes prêtes |
| Photos Eurio existantes | 74 | Brut | À annoter (bounding boxes) |

**Stratégie** : récupérer le dataset Roboflow, collapser toutes les classes en `coin` (classe 0), merger avec nos images annotées.

---

## 2. Training best practices

### Hyperparamètres recommandés

```yaml
model: yolov8n.pt          # Pré-entraîné COCO (transfer learning)
imgsz: 320                  # 320x320 suffit pour détecter un cercle
epochs: 150-300
patience: 50                # Early stopping
batch: 16
lr0: 0.01
freeze: 10                  # Freeze backbone 10 premiers epochs
# Augmentation coin-specific
degrees: 15
translate: 0.1
scale: 0.5
flipud: 0.5
```

### Images négatives

- 5-10% du dataset = images **sans pièce** (bureau, mains vides, objets ronds)
- Format YOLO : image présente, fichier `.txt` label **vide** (0 bytes)
- Réduit significativement les faux positifs en production

---

## 3. Export TFLite

```python
model.export(
    format='tflite',
    imgsz=320,
    int8=True,              # Quantification INT8 pour mobile
    nms=True,               # Intégrer NMS dans le modèle (sinon à coder en Kotlin)
    data='data.yaml',       # Pour calibration INT8 automatique
)
```

### Performances attendues

| Config | Taille | Inference Pixel 9a |
|---|---|---|
| YOLOv8n 320px FP32 | ~6 MB | ~15ms |
| YOLOv8n 320px INT8 | ~2 MB | <10ms |

### Gotchas

- Le tenseur de sortie TFLite a un layout différent de PyTorch → utiliser les exemples Android d'Ultralytics
- `nms=True` à l'export évite d'implémenter NMS en Kotlin
- La calibration INT8 nécessite `data=dataset.yaml` pour être automatique

---

## 4. Annotation

| Outil | Setup | YOLO export | AI-assist | Recommandation |
|---|---|---|---|---|
| Roboflow Annotate | Aucun (browser) | Natif | Oui | Pour nos 74 images |
| CVAT | Docker local | Natif | SAM | Si on veut rester local |
| labelImg | `pip install` | Natif | Non | Léger mais basique |
| Label Studio | Docker | Plugin | Non | Trop lourd pour ce besoin |

---

## 5. Pipeline complète

```
1. Télécharger dataset Roboflow (2400 images) → collapser en classe "coin"
2. Annoter nos 74 images (Roboflow Annotate ou CVAT)
3. Ajouter ~50 images négatives (bureau, mains, objets)
4. Merger les datasets
5. Train YOLOv8n (320px, freeze 10 epochs, patience 50)
6. Export TFLite INT8 + NMS
7. Intégrer CoinDetector.kt dans l'app Android
```
