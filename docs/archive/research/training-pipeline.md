# Pipeline d'entraînement — MobileNetV3 + Triplet Loss

> Ce document décrit comment entraîner le modèle d'extraction d'embeddings pour Eurio.

---

## 1. Objectif

Entraîner MobileNetV3-Small à produire des embeddings discriminants pour les pièces euro. Le modèle ne classifie pas directement — il produit un vecteur de 1024 dimensions qui représente la "signature visuelle" d'une pièce. Des pièces identiques auront des embeddings proches, des pièces différentes auront des embeddings éloignés.

---

## 2. Datasets disponibles

### Datasets existants

| Source | Contenu | Taille | Format | Lien |
|---|---|---|---|---|
| Kaggle — janstaffa | Euro coins, photos réelles | Variable | Images classées par dossier | kaggle.com/datasets/janstaffa/euro-coins-dataset |
| Roboflow — Euro coins | 523 images annotées | ~500 images | YOLO/COCO format | universe.roboflow.com/lucas-capuano/euro-coins-classification |
| GitHub — kaa/coins-dataset | Euro par dénomination | Variable | Keras-ready | github.com/kaa/coins-dataset |
| GitHub — iambarge/CV-coins-project | Pipeline complet Euro | Variable | Custom | github.com/iambarge/CV-coins-project |

### Dataset propre (à constituer)

Pour le POC (10 classes), objectif minimum : **30-50 images réelles par classe**.

Méthode de collecte :
1. Prendre les pièces physiques disponibles
2. Photographier chaque pièce sous 5 éclairages × 5 angles × 3 fonds = ~75 photos
3. Temps estimé : ~5 min par pièce, ~1h pour 10 pièces

### Structure du dataset pour triplet loss

```
dataset/
├── train/
│   ├── 2e_comm_allemagne_2006/
│   │   ├── img_001.jpg    # Photo réelle
│   │   ├── img_002.jpg    # Autre angle
│   │   ├── img_003.jpg    # Autre éclairage
│   │   └── ...
│   ├── 2e_comm_france_2012/
│   │   └── ...
│   └── ...
├── val/
│   └── ... (même structure, 20% des images)
└── test/
    └── ... (même structure, 10% des images)
```

Le triplet loss pioche des triplets (anchor, positive, negative) automatiquement depuis cette structure : anchor et positive viennent du même dossier, negative d'un dossier différent.

---

## 3. Augmentation de données

### Augmentations standard (appliquées à l'entraînement)

```python
transforms.Compose([
    transforms.Resize((256, 256)),
    transforms.RandomCrop(224),
    transforms.RandomRotation(360),       # Pièces = rotation invariant
    transforms.RandomHorizontalFlip(),
    transforms.ColorJitter(
        brightness=0.3,
        contrast=0.3,
        saturation=0.2,
        hue=0.05
    ),
    transforms.GaussianBlur(kernel_size=3, sigma=(0.1, 1.0)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225]),
])
```

### Augmentation synthétique pour les pièces avec peu d'images

Pour les nouvelles pièces (1-3 images officielles seulement) :

**Copy-paste augmentation :**
1. Détourer la pièce (cercle → facile à masquer automatiquement)
2. Coller sur des fonds variés : main, table, tiroir, tissu, etc.
3. Ajouter ombres et reflets réalistes
4. Générer ~50-100 images synthétiques

**Rendu 3D (optionnel, plus avancé) :**
1. Mapper la texture officielle sur un disque 3D dans Blender
2. Rendre avec éclairages variés et textures métalliques
3. Très réaliste pour des pièces (objets plats et ronds)

**Résultat** : 1-3 images officielles → 100+ images d'entraînement utilisables.

---

## 4. Training — Option A : Local (recommandé)

### Prérequis

```bash
# Environnement Python
python -m venv eurio-ml
source eurio-ml/bin/activate

# Dépendances
pip install torch torchvision
pip install pytorch-metric-learning  # Pour le triplet loss
pip install ai-edge-torch            # Pour l'export TFLite
```

### Hardware

| Machine | GPU | Temps estimé (10 classes, 1000 images) |
|---|---|---|
| PC avec 1080 Ti | 11 GB VRAM | ~15-30 min |
| Mac M4 | GPU intégré (MPS) | ~30-60 min |
| Google Colab Free | T4 16 GB | ~20-40 min |
| Google Colab Pro | A100 40 GB | ~5-10 min |

### Script d'entraînement (simplifié)

```python
import torch
from torchvision import models, transforms
from torchvision.datasets import ImageFolder
from pytorch_metric_learning import losses, miners
from torch.utils.data import DataLoader

# 1. Charger MobileNetV3-Small pré-entraîné
model = models.mobilenet_v3_small(weights='IMAGENET1K_V1')

# 2. Retirer le classifieur, garder le feature extractor
# La sortie est un embedding de 576 dimensions
model.classifier = torch.nn.Identity()

# 3. Optionnel : ajouter une projection vers 128 ou 256 dim
# (réduit la taille des embeddings stockés)
embedding_head = torch.nn.Linear(576, 256)
model = torch.nn.Sequential(model, embedding_head)

# 4. Dataset
dataset = ImageFolder("dataset/train/", transform=train_transforms)
dataloader = DataLoader(dataset, batch_size=32, shuffle=True)

# 5. Triplet Loss + Hard Mining
loss_fn = losses.TripletMarginLoss(margin=0.2)
miner = miners.TripletMarginMiner(margin=0.2, type_of_triplets="hard")
optimizer = torch.optim.Adam(model.parameters(), lr=1e-4)

# 6. Training loop
for epoch in range(20):
    for images, labels in dataloader:
        embeddings = model(images)
        hard_triplets = miner(embeddings, labels)
        loss = loss_fn(embeddings, labels, hard_triplets)
        loss.backward()
        optimizer.step()
        optimizer.zero_grad()

# 7. Export TFLite
# Via ai-edge-torch ou torch → ONNX → TFLite
```

### Export TFLite

```python
import ai_edge_torch

# Convertir le modèle PyTorch → TFLite
sample_input = torch.randn(1, 3, 224, 224)
edge_model = ai_edge_torch.convert(model, (sample_input,))
edge_model.export("eurio_embedder_v1.tflite")

# Résultat : fichier ~2-4 MB, prêt à intégrer dans l'APK
```

---

## 5. Training — Option B : Roboflow

Roboflow est un backup si le training local pose problème. L'approche est différente car Roboflow fait de la classification, pas du triplet loss. On peut tout de même l'utiliser pour :

1. **Augmentation de données** : uploader les images, appliquer les augmentations, télécharger le dataset augmenté
2. **Training rapide** : entraîner un classifieur pour valider la qualité du dataset
3. **Export TFLite** : récupérer un modèle de classification (pas d'embeddings)

**Limitations** :
- Pas de triplet loss / contrastive learning
- Pas de contrôle sur l'architecture du modèle
- Ajout d'une nouvelle classe = re-training complet

**Coût** : Free tier = 3 projets, 10K images, training inclus. Suffisant pour le POC.

---

## 6. Calcul des embeddings de référence

Une fois le modèle entraîné, il faut calculer les embeddings de référence pour chaque pièce du catalogue.

```python
# Pour chaque pièce du catalogue
def compute_reference_embedding(model, image_paths):
    embeddings = []
    for path in image_paths:
        img = load_and_preprocess(path)  # resize, normalize
        emb = model(img.unsqueeze(0))     # forward pass
        embeddings.append(emb)
    # Moyenne des embeddings si plusieurs images
    return torch.stack(embeddings).mean(dim=0)

# Résultat : un dictionnaire {numista_id: embedding_vector}
# Sérialisé en JSON et uploadé sur Supabase
```

### Format de la base d'embeddings

```json
{
  "version": "1.0",
  "model": "eurio_embedder_v1",
  "embedding_dim": 256,
  "coins": {
    "numista_12345": {
      "name": "2€ commémorative Allemagne 2006",
      "embedding": [0.023, -0.145, 0.892, ...],
      "updated_at": "2026-04-09"
    },
    "numista_12346": { ... }
  }
}
```

Taille estimée : ~500 KB pour 800 pièces (256 dims × 4 bytes × 800 + métadonnées).

---

## 7. Pipeline automatisée — Nouvelles pièces Day Zero

```
Cron job (quotidien ou hebdomadaire)
  │
  ├── 1. Poll Numista API pour nouvelles entrées
  │
  ├── 2. Télécharger l'image officielle (1-3 images)
  │
  ├── 3. Preprocessing : crop cercle, resize 224×224, normaliser
  │
  ├── 4. Générer augmentations synthétiques (optionnel)
  │      → Copy-paste sur fonds variés
  │      → 1 image → 10-20 variantes
  │
  ├── 5. Calculer l'embedding moyen via le modèle entraîné
  │      → Forward pass sur toutes les variantes
  │      → Moyenne des embeddings
  │
  ├── 6. Ajouter à la base d'embeddings (Supabase)
  │
  └── 7. L'app sync la base au prochain lancement
         → Pièce reconnaissable automatiquement
```

**Aucun re-training nécessaire** pour ajouter une pièce.
**Re-training recommandé** tous les 2-3 mois pour améliorer la qualité globale avec les nouvelles données accumulées.

---

## 8. Métriques de qualité

| Métrique | Cible POC | Cible MVP |
|---|---|---|
| Recall@1 (la bonne pièce est le 1er résultat) | > 80% | > 90% |
| Recall@3 (la bonne pièce est dans le top 3) | > 95% | > 98% |
| Faux positifs (identification erronée avec haute confiance) | < 5% | < 2% |
| Temps d'inférence (Pixel 9a) | < 50ms | < 20ms |
