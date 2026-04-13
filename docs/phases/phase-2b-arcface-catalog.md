# Phase 2B — ArcFace + Catalogue complet

> Objectif : passer de 5 classes en classification à 500+ types de pièces euro avec metric learning. Ajouter une nouvelle pièce = ajouter 2-3 photos de référence, sans ré-entraîner le modèle.
> **Note double usage** : le modèle d'embedding entraîné dans cette phase sert à **deux usages distincts** — (1) identifier les pièces scannées par l'utilisateur (feature scan), (2) le Stage 4 de matching visuel dans le référentiel de données Eurio (voir [`phase-2c-referential.md`](./phase-2c-referential.md) §2C.6). L'activation du Stage 4 attend la complétion de cette phase.

---

## Contexte

La classification (cross-entropy) fonctionne bien pour 5 classes connues (val accuracy 100% avec augmentation), mais ne scale pas :
- Ajout d'une pièce = ré-entraîner tout le modèle
- 500 classes avec 2-5 images chacune = insuffisant pour un classifieur

Le metric learning avec **ArcFace** résout ces deux problèmes :
- Le modèle apprend un espace d'embeddings où les pièces similaires sont proches
- Ajouter une pièce = calculer son embedding moyen → pas de ré-entraînement
- ArcFace est beaucoup plus stable que triplet loss (testé et échoué en Phase 1)

---

## 2B.1 — ArcFace entraîné et validé ✅

### Résultats (5 classes, 2026-04-10)

| Métrique | Triplet Loss (Phase 1) | Classification | **ArcFace** |
|---|---|---|---|
| Val R@1 / Accuracy | 14% (collapse) | 80% → 100%* | **100%** |
| Val Top-3 | 28% | 100% | **100%** |
| Convergence | Instable | 20 epochs | **8 epochs** |
| Train loss | Instable | 0.01 | **0.04** |

*Classification à 100% grâce à l'augmentation synthétique ajoutée (50 images/classe).

### Implémentation

```python
# train_embedder.py --mode arcface
from pytorch_metric_learning.losses import ArcFaceLoss

loss_fn = ArcFaceLoss(
    num_classes=5,
    embedding_size=256,
    margin=28.6,    # degrés (= 0.5 rad)
    scale=30,
)
# ⚠️ Optimizer séparé pour la matrice de poids ArcFace
loss_optimizer = torch.optim.SGD(loss_fn.parameters(), lr=0.01)
```

### Architecture (inchangée)

```
MobileNetV3-Small (576-dim) → Linear(576, 256) → L2 Normalize → embedding 256-dim
```

À l'inférence : la tête ArcFace est jetée. Le modèle exporté est identique en structure au classifieur. Seul le training change.

### Export TFLite

- Taille : 4.2 MB (identique au classifieur)
- Output : [1, 256] (embeddings L2-normalisés)
- Parity : cosine similarity 1.000000 sur 7 images de test
- `F.normalize` s'exporte correctement via litert_torch

---

## 2B.2 — Augmentation synthétique ✅

Script : `ml/augment_synthetic.py`

### Techniques appliquées

- Rotation 360° (les pièces sont rotation-invariant)
- Masque circulaire (les pièces sont rondes)
- Fonds variés : couleur unie (bois, gris, blanc, sombre), gradient, texture bruitée
- Color jitter : brightness ±40%, contrast ±40%, saturation ±30%
- Blur gaussien (30% des images, sigma 0.3-1.5)
- Position aléatoire sur le fond (centré ± offset)
- Scale variable (50-85% de la taille output)

### Résultat

- 2-17 images source → 50 images augmentées par classe
- Les augmentées sont injectées dans le train set uniquement (pas val/test)
- `prepare_dataset.py` gère le split automatiquement

---

## 2B.3 — Catalogue Numista — en cours ⏳

### Script : `ml/import_numista.py`

Import automatisé des ~500-600 types de pièces 2€ depuis l'API Numista v3.

### Modes d'utilisation

```bash
# Import complet (utilise le quota API)
.venv/bin/python import_numista.py

# Preview sans télécharger
.venv/bin/python import_numista.py --dry-run

# Re-télécharger les images manquantes (ZERO appel API — utilise URLs cachées)
.venv/bin/python import_numista.py --retry-images --retry-delay 2

# Cacher les URLs pour les anciennes entrées (utilise le quota)
.venv/bin/python import_numista.py --backfill-urls
```

### Statut (2026-04-10)

| Élément | Statut |
|---|---|
| Pièces dans le catalogue | 445 / ~550 |
| Images obverse téléchargées | ~300 |
| Images manquantes | ~145 (rate limit CDN) |
| Pièces restantes à importer | ~55 (pages non scannées) |
| Quota API utilisé | 2060 / ~2000 (limité jusqu'en mai) |

### Structure du catalogue

```json
{
  "226447": {
    "numista_id": 226447,
    "name": "2 Euros (Kneeling to Warsaw)",
    "country": "Germany, Federal Republic of",
    "year": 2020,
    "face_value": 2.0,
    "type": "commemorative",
    "diameter_mm": 25.75,
    "weight_g": 8.5,
    "composition": "Bimetallic: nickel brass centre in copper-nickel ring",
    "obverse_description": "In center former German Chancellor...",
    "reverse_description": "...",
    "obverse_image_url": "https://en.numista.com/catalogue/photos/...",
    "reverse_image_url": "https://en.numista.com/catalogue/photos/..."
  }
}
```

Clé = Numista ID (plus de slugs ad-hoc). Les URLs d'images sont cachées pour permettre `--retry-images` sans appels API.

### Répertoires

```
ml/datasets/
├── 135/                # Numista ID
│   ├── 001.jpg         # Photos réelles (tes photos)
│   ├── 002.jpg
│   ├── ...
│   ├── obverse.jpg     # Image studio Numista
│   ├── reverse.jpg
│   └── augmented/      # Généré par augment_synthetic.py
│       ├── aug_0001.jpg
│       └── ...
├── 226447/
├── ...
└── coin_catalog.json   # Source de vérité
```

---

## 2B.4 — Ajout de nouvelles pièces (sans ré-entraînement)

### Processus

```
1. Nouvelle pièce sort (ex: 2€ France 2026 JO)
2. Trouver 2-3 images (Numista, site officiel)
3. Lancer : .venv/bin/python import_numista.py  (si dans Numista)
4. Lancer : go-task augment  (augmentation synthétique)
5. Lancer : go-task embeddings  (calcule le centroid)
6. Lancer : go-task deploy  (copie dans les assets Android)
7. Build + deploy l'app → pièce reconnue automatiquement
```

**Pas de ré-entraînement du modèle.** Le backbone produit déjà de bons embeddings grâce à l'entraînement ArcFace. On ajoute juste un nouveau centroid.

### Sync OTA (futur)

- Stocker `coin_embeddings.json` dans Supabase Storage
- L'app vérifie au lancement s'il y a une version plus récente
- Pièce reconnaissable sans mise à jour de l'APK

---

## 2B.5 — Prochaines étapes

- [ ] Compléter le catalogue Numista (mai — après reset quota)
  1. `--backfill-urls` sur les ~145 entrées sans URL cachée (~100 API calls)
  2. `--retry-images --retry-delay 2` (télécharger les images manquantes, 0 API calls)
  3. `import_numista.py` (importer les ~55 pièces restantes, ~80 API calls)
- [ ] Entraîner ArcFace sur les ~445+ classes (quand les images sont complètes)
- [ ] Valider que R@1 reste > 90% à 445 classes
- [ ] Mettre à jour les embeddings de référence
- [ ] Sync OTA des embeddings via Supabase Storage
- [ ] Tests en conditions réelles sur 50+ types de pièces
