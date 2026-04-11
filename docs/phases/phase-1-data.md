# Phase 1 — Data First

> Objectif : constituer le dataset, entraîner le premier modèle d'embedding, et peupler Supabase avec le catalogue. À la fin de cette phase, on a un modèle TFLite fonctionnel et une base de pièces avec des prix.

---

## 1.1 — Constitution du dataset d'entraînement

### Collecte des images

```
Étape 1 : Trier les datasets téléchargés en Phase 0
  → Identifier les images correspondant aux 10 classes POC
  → Copier dans la structure cible
  → Estimer le nombre d'images par classe

Étape 2 : Photos personnelles
  → Photographier les pièces physiques
  → Par pièce : 5 éclairages × 5 angles × 3 fonds = ~75 photos
  → Temps : ~5 min/pièce

Étape 3 : Images officielles
  → Numista : images de référence
  → ECB : designs standards
  → Sites des monnaies nationales
```

### Structure du dataset

```
ml/datasets/eurio-poc/
├── train/   (70%)
│   ├── 2e_comm_allemagne_2006/
│   │   ├── kaggle_001.jpg
│   │   ├── photo_perso_001.jpg
│   │   └── ...
│   ├── 2e_comm_france_2012/
│   │   └── ...
│   └── ... (10 classes)
├── val/     (20%)
│   └── ... (même structure)
└── test/    (10%)
    └── ... (même structure)
```

Script de préparation :

```python
# ml/prepare_dataset.py
# 1. Rassembler les images de toutes les sources
# 2. Resize à 256×256 (plus grand que 224 pour permettre le random crop)
# 3. Split train/val/test (70/20/10)
# 4. Vérifier : au moins 30 images par classe dans train
```

### Augmentation de données

Appliquée dynamiquement pendant l'entraînement (pas de fichiers à générer) :

```python
train_transforms = transforms.Compose([
    transforms.Resize((256, 256)),
    transforms.RandomCrop(224),
    transforms.RandomRotation(360),
    transforms.RandomHorizontalFlip(),
    transforms.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.2, hue=0.05),
    transforms.GaussianBlur(kernel_size=3, sigma=(0.1, 1.0)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])
```

Pour les classes avec très peu d'images (< 20), augmentation synthétique supplémentaire :
- Copy-paste sur fonds variés (mains, tables, tissu)
- Script dédié `ml/augment_synthetic.py`

---

## 1.2 — Entraînement du modèle d'embedding

### Script principal

```bash
# Depuis la racine du projet (devShell Nix actif via direnv)
cd ml/

python train_embedder.py \
  --dataset ./datasets/eurio-poc/train \
  --val-dataset ./datasets/eurio-poc/val \
  --model mobilenet_v3_small \
  --embedding-dim 256 \
  --epochs 20 \
  --batch-size 32 \
  --margin 0.2 \
  --lr 1e-4 \
  --device auto \
  --output ./checkpoints/
```

### Ce que fait le script

```python
# ml/train_embedder.py (structure)

# 1. Charger MobileNetV3-Small pré-entraîné
model = models.mobilenet_v3_small(weights='IMAGENET1K_V1')

# 2. Retirer le classifieur → feature extractor
model.classifier = nn.Identity()

# 3. Ajouter une tête de projection (576 → 256 dims)
model = nn.Sequential(model, nn.Linear(576, 256))

# 4. Triplet loss avec hard mining
loss_fn = TripletMarginLoss(margin=0.2)
miner = TripletMarginMiner(margin=0.2, type_of_triplets="hard")

# 5. Training loop (20 epochs)
# 6. Validation à chaque epoch (Recall@1, Recall@3)
# 7. Sauvegarde du meilleur modèle
```

### Métriques à surveiller

| Métrique | Cible POC | Comment |
|---|---|---|
| Train loss | Décroissante et stable | Courbe de loss |
| Recall@1 (val) | > 80% | La bonne pièce est le 1er résultat |
| Recall@3 (val) | > 95% | La bonne pièce est dans le top 3 |
| t-SNE visualization | Clusters bien séparés | Script `ml/visualize.py` |

### Itérations

Le cycle d'amélioration :

```
Entraîner → Évaluer (Recall@1) → Identifier les erreurs
  → Ajouter des photos des cas qui échouent
  → Ajuster les hyperparamètres si nécessaire
  → Ré-entraîner

Prévoir 3-5 itérations. ~30 min par cycle sur 1080 Ti.
```

---

## 1.3 — Export TFLite

```python
# ml/export_tflite.py

import ai_edge_torch  # Note : deprecated, renommé litert-torch
import torch

# Charger le meilleur modèle
model = load_model("checkpoints/best_model.pth")
model.eval()

# Convertir PyTorch → TFLite
sample_input = (torch.randn(1, 3, 224, 224),)
edge_model = ai_edge_torch.convert(model, sample_input)

# Quantification INT8 (optionnel, réduit la taille et accélère)
# À tester : si la précision baisse trop, garder float32
edge_model.export("eurio_embedder_v1.tflite")

# Vérifier la taille
# Cible : < 5 MB
```

### Validation de l'export

```python
# Vérifier que le modèle TFLite donne les mêmes résultats que PyTorch
# ml/validate_export.py
# 1. Charger le modèle PyTorch et le modèle TFLite
# 2. Passer les mêmes images dans les deux
# 3. Comparer les embeddings (cosine similarity > 0.99)
```

---

## 1.4 — Calcul des embeddings de référence

```python
# ml/compute_embeddings.py

# Pour chaque pièce du catalogue :
# 1. Charger toutes les images de référence
# 2. Passer dans le modèle → embedding par image
# 3. Calculer l'embedding moyen (centroïde)
# 4. Normaliser (L2 norm)
# 5. Sauvegarder dans un JSON

output = {
    "version": "1.0",
    "model": "eurio_embedder_v1",
    "embedding_dim": 256,
    "coins": {
        "numista_12345": {
            "name": "2€ commémorative Allemagne 2006",
            "embedding": [0.023, -0.145, 0.892, ...],  # 256 floats
        },
        # ...
    }
}

# Sauvegarder
# → ml/output/embeddings_v1.json    (pour l'app Android)
# → Upload sur Supabase Storage      (pour la sync)
```

---

## 1.5 — Peupler Supabase

### Import du catalogue Numista

Script Python ou TypeScript (Edge Function) :

```python
# ml/seed_supabase.py (ou scripts/seed-coins.ts)

# 1. Pour chaque pièce POC :
#    → Fetch Numista API : nom, pays, année, tirage, images
#    → Insert dans la table `coins`
#    → Upload images dans Supabase Storage

# 2. Upload les embeddings
#    → Insert dans `coin_embeddings` (embedding array)
#    → OU upload le JSON dans Supabase Storage
```

### Import des premiers prix

```python
# ml/seed_prices.py

# 1. Pour chaque pièce POC :
#    → Fetch eBay Browse API (sold items, 90 derniers jours)
#    → Calculer P25, P50, P75
#    → Insert dans `price_history`
```

---

## 1.6 — Intégration du modèle dans l'app Android

Copier les artefacts ML dans le projet Android :

```bash
# Modèle TFLite
cp ml/output/eurio_embedder_v1.tflite android/app/src/main/assets/models/

# Base d'embeddings
cp ml/output/embeddings_v1.json android/app/src/main/assets/data/
```

Créer les classes Kotlin pour charger et utiliser le modèle :

```kotlin
// CoinEmbedder.kt — charge le modèle et extrait les embeddings
// EmbeddingMatcher.kt — cosine similarity vs base locale
// Testés unitairement avec des images du dataset de test
```

---

## 1.7 — Livrables Phase 1

- [ ] Dataset organisé : 10 classes, 30+ images/classe (train)
- [ ] Script d'entraînement fonctionnel (`train_embedder.py`)
- [ ] Modèle entraîné : Recall@1 > 80% sur val
- [ ] Export TFLite validé (même résultats que PyTorch)
- [ ] Base d'embeddings de référence (JSON, 10 pièces)
- [ ] Supabase peuplé : 10 pièces + prix + embeddings
- [ ] Modèle TFLite intégré dans l'app Android
- [ ] Classes `CoinEmbedder` et `EmbeddingMatcher` fonctionnelles
- [ ] Tests unitaires de matching (images de test → identification correcte)

---

## Durée estimée

**7-10 jours**
- 2-3 jours : collecte + organisation dataset + photos perso
- 2-3 jours : training + itérations + export TFLite
- 1-2 jours : seed Supabase (catalogue + prix)
- 1-2 jours : intégration dans l'app Android + tests
