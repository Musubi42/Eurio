# ArcFace — Recherche few-shot coin recognition

> Recherche effectuée le 2026-04-10. Objectif : passer de 5 classes (classification) à 500+ (metric learning) avec 2-6 images/classe.

---

## 1. Librairie retenue : `pytorch-metric-learning`

Déjà installée dans le venv. Fournit `losses.ArcFaceLoss` et `SubCenterArcFaceLoss`.

```python
from pytorch_metric_learning import losses

loss_fn = losses.ArcFaceLoss(
    num_classes=500,
    embedding_size=256,
    margin=28.6,    # En degrés (= 0.5 rad), converti en interne
    scale=30,       # Commence à 30 pour 500 classes ; 64 peut être trop agressif
)

# ⚠️ ArcFace a sa propre matrice de poids W → optimizer séparé
loss_optimizer = torch.optim.SGD(loss_fn.parameters(), lr=0.01)
```

### Alternatives évaluées

| Librairie | ArcFace | MPS | Notes |
|---|---|---|---|
| `pytorch-metric-learning` | Oui | Oui | **Retenu** — déjà installé, bien maintenu |
| `insightface` | Oui | Partiel | Focus face recognition, trop lourd |
| Manuel (`ArcMarginProduct`) | Oui | Oui | Faisable mais réinventer la roue |

---

## 2. Compatibilité MPS (Mac M4)

ArcFace utilise des ops standard toutes supportées par MPS :
- `torch.acos`, `torch.cos` — supportés
- Matrix multiplication — supporté
- Cross-entropy — supporté

**Fallback** : `PYTORCH_ENABLE_MPS_FALLBACK=1` si un op edge case manque.

Bug connu `addcmul_`/`addcdiv_` sur tenseurs non-contigus → corrigé dans macOS 15+ (M4 = macOS 15+, pas affecté).

---

## 3. Performance few-shot

ArcFace est **idéal** pour le few-shot car :
- Il apprend une **matrice de centres de classe** (pas des paires comme triplet loss)
- Chaque classe contribue indépendamment, peu importe le nombre de samples des autres classes
- La marge angulaire force la séparation inter-classe même avec peu de données
- 2-6 images augmentées à 50+ → suffisant pour l'entraînement classification-style d'ArcFace

### Pourquoi ArcFace > Triplet Loss (confirmé)

| | Triplet Loss | ArcFace |
|---|---|---|
| Résultat Phase 1 | R@1 = 14% (collapse) | Non testé |
| Stabilité few-shot | Instable | Stable |
| Mining nécessaire | Oui (BatchHard) | Non |
| Convergence | Lente, risque collapse | Rapide, fiable |
| Ajout nouvelle classe | Ré-entraînement | Juste calculer centroid |

---

## 4. Architecture : MobileNetV3-Small + ArcFace

Le `CoinEmbedder` actuel fonctionne tel quel :

```
MobileNetV3-Small (576-dim) → Linear(576, 256) → L2 Normalize → embedding 256-dim
```

- **256-dim** = sweet spot pour ~500 classes (128 trop petit, 512 surdimensionné)
- À l'inférence : on jette la tête ArcFace, on garde backbone + projection
- Export TFLite identique à l'actuel (`export_tflite.py` inchangé)

Référence : [MobileNetV3 + ArcFace Kaggle notebook](https://www.kaggle.com/code/aryankashyapnaveen/mobilenetv3-arcface)

---

## 5. Hyperparamètres recommandés

| Paramètre | Valeur | Notes |
|---|---|---|
| margin | 28.6 (degrés) | = 0.5 rad, défaut pytorch-metric-learning |
| scale (s) | 30 | Commencer bas pour 500 classes |
| backbone LR | 1e-4 | Après unfreeze (stratégie 0.1x existante) |
| projection head LR | 1e-3 | |
| ArcFace W LR | 0.01 | SGD, optimizer séparé |
| scheduler | CosineAnnealingLR | Déjà dans le code |
| freeze epochs | 5 | Déjà dans le code |
| total epochs | 30-50 | Plus que les 20 actuels |
| batch size | 64-128 | Plus grand aide ArcFace |
| sampler | MPerClassSampler(m=4) | m=4 suffit (vs m=8 triplet) |

---

## 6. Migration depuis le code actuel

### Ce qui change

```python
# train_embedder.py — remplacer :
loss_fn = losses.TripletMarginLoss(margin=0.2)
miner = miners.BatchHardMiner()

# Par :
loss_fn = losses.ArcFaceLoss(num_classes=len(classes), embedding_size=256, margin=28.6, scale=30)
loss_optimizer = torch.optim.SGD(loss_fn.parameters(), lr=0.01)
# Supprimer le miner
```

### Ce qui ne change PAS

- `CoinEmbedder` (backbone + projection + normalize)
- `export_tflite.py`
- `compute_embeddings.py`
- Pipeline Android (CoinRecognizer)
- Format des embeddings dans Supabase

---

## 7. Export TFLite

Aucun problème. À l'inférence, le modèle exporté est :

```
Input (1, 3, 224, 224) → MobileNetV3-Small → Linear(576, 256) → L2 Normalize → Output (1, 256)
```

La matrice ArcFace `W` est utilisée uniquement pendant le training. Si `F.normalize` pose problème à l'export, normaliser côté Android (`embedding / ||embedding||`).
