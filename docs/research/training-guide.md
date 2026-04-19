# Guide d'entraînement ML — Ce qu'il faut savoir

> Référence interne pour comprendre comment fonctionne le training, ce qui est stocké où, et comment scaler.

## Le modèle n'est pas incrémental

Quand tu ajoutes une nouvelle pièce, le modèle est **ré-entraîné sur toutes les classes**. Ce n'est pas un ajout — c'est une reconstruction complète.

Pourquoi : ArcFace apprend un espace d'embeddings global où toutes les classes sont positionnées les unes par rapport aux autres. Ajouter une classe change les positions relatives de toutes les autres. C'est comme réorganiser une étagère entière quand tu ajoutes un livre, pas juste le glisser au bout.

### Ce que ça implique

- Pour entraîner 1 nouvelle pièce, tu ré-entraînes les 500 classes existantes + la nouvelle
- Le dataset complet (toutes les images augmentées de toutes les classes) doit être disponible
- Le résultat est un nouveau `best_model.pth` qui remplace l'ancien

## Ce que produit le training

Un entraînement produit ces fichiers :

| Fichier | Taille | Rôle | Garde ou jette ? |
|---|---|---|---|
| `best_model.pth` | ~4.3 MB | Poids du réseau neuronal (le cerveau) | **Garde — c'est LA valeur** |
| `coin_embeddings.json` | ~18 KB (7 classes) | Centroïdes par design (vecteurs de référence) | Recalculable depuis le modèle |
| `model_meta.json` | 168 B | Métadonnées (mode, classes, dimension) | Recalculable |
| `training_log.json` | ~5 KB | Historique epochs (loss, R@1, R@3) | Utile mais pas critique |
| `eurio_embedder_v1.tflite` | ~4.2 MB | Export mobile du modèle | Recompilable depuis le .pth |
| `datasets/*/augmented/*.jpg` | ~550 KB/design | Images augmentées d'entraînement | **Jetable — régénérable en secondes** |

### Résumé : ce qu'il faut stocker

**Dans Supabase Storage** (bucket `ml-models`, ~9 MB total) :
- `best_model.pth` — pour pouvoir ré-entraîner depuis un autre poste
- `model_meta.json` — pour savoir ce qui est dans le modèle
- `embeddings_v1.json` — pour recalculer les centroïdes
- `coin_embeddings.json` — les centroïdes flat pour Android

**Dans Supabase DB** (table `coin_embeddings`, ~2 KB/design) :
- Les embeddings de référence par `eurio_id` — utilisés par l'admin pour afficher le badge "entraîné"

**Jetable** (local uniquement) :
- Les images augmentées — régénérées par `augment_synthetic.py`
- Le dataset splitté `eurio-poc/train/val/test` — régénéré par `prepare_dataset.py`
- Le TFLite — recompilé par `export_tflite.py`

## Les 3 fichiers qui vont dans l'APK Android

Pour que le scan fonctionne sur le téléphone, 3 fichiers doivent être dans `app-android/src/main/assets/` :

```
assets/
├── models/
│   └── eurio_embedder_v1.tflite    ← le réseau neuronal compilé
└── data/
    ├── coin_embeddings.json         ← les centroïdes (1 vecteur 256-dim par design)
    └── model_meta.json              ← mode, classes, dimension
```

Le TFLite contient **uniquement le réseau** — il ne sait pas combien de classes existent. C'est `coin_embeddings.json` qui contient la "mémoire" des designs connus. Quand l'app scanne une pièce :

1. Le TFLite transforme la photo en un vecteur 256-dim
2. L'app compare ce vecteur à tous les centroïdes dans `coin_embeddings.json`
3. Le centroïde le plus proche (cosine similarity) = le match

Si tu oublies de déployer `coin_embeddings.json` mais que tu déploies le TFLite, le modèle tourne mais ne reconnaît que les anciens designs.

## Commandes de déploiement

```bash
# 1. Recompiler le TFLite (si le modèle a changé)
cd ml && go-task export

# 2. Recalculer les centroïdes (si de nouvelles classes ont été entraînées)
cd ml && go-task embeddings

# 3. Copier les 3 fichiers dans les assets Android
cd ml && go-task deploy

# 4. Rebuild l'app
go-task android:run
```

Ou via l'admin web (`/training` → section Export TFLite) :
- Bouton "Compiler TFLite" → `POST /export/tflite`
- Bouton "Valider TFLite" → vérifie que PyTorch et TFLite produisent les mêmes embeddings
- Bouton "Déployer vers Android" → copie les fichiers
- Bouton "Upload Supabase" → push le modèle vers Supabase Storage

## Performances d'entraînement par machine

### MacBook Pro M4 (MPS)

| Paramètre | Valeur |
|---|---|
| Device | MPS (Apple Silicon GPU) |
| batch_size | 64 |
| num_workers | 0 (MPS ne supporte pas bien le multiprocessing) |
| pin_memory | non |

**7 classes** : ~2-3 minutes
**500 classes** : ~20-30 minutes

### PC Linux — 1080 Ti (CUDA)

| Paramètre | Valeur |
|---|---|
| Device | CUDA |
| batch_size | 256 |
| num_workers | 4 (parallélise le chargement sur les 8 cores Ryzen) |
| pin_memory | oui (transfert CPU→GPU optimisé) |
| persistent_workers | oui |

**7 classes** : ~30 secondes
**500 classes** : ~3-4 minutes

Le GPU n'est pas le bottleneck — c'est le chargement des images. Les `num_workers` font que le CPU pré-charge les batches suivants pendant que le GPU traite le batch courant.

### Pourquoi le PC est ~8× plus rapide

1. **batch_size 256 vs 64** : 4× moins de batches par epoch
2. **num_workers 4 vs 0** : le GPU n'attend plus que le CPU lise les images
3. **CUDA vs MPS** : CUDA est plus mature, meilleures performances sur les petits modèles

## VRAM et RAM

### Ce qui est en VRAM (occupé en permanence)

- Modèle MobileNetV3-Small : ~5 MB
- Matrice ArcFace (num_classes × 256) : ~0.5 MB pour 500 classes
- Gradients + optimiseur : ~15 MB
- **Total fixe : ~20-30 MB**

### Ce qui est en VRAM (par batch, temporaire)

- 1 batch de 256 images (224×224×3) : ~37 MB
- Activations intermédiaires : ~200-400 MB
- **Total par batch : ~300-500 MB**

### Total VRAM estimé

| Scénario | VRAM | 1080 Ti (11 GB) |
|---|---|---|
| 7 classes, batch 64 | ~500 MB | OK |
| 500 classes, batch 256 | ~800 MB | OK |
| 500 classes, batch 512 | ~1.4 GB | OK |
| 500 classes, batch 1024 | ~2.5 GB | OK |

La 1080 Ti est largement surdimensionnée pour ce modèle. Le bottleneck n'est jamais la VRAM.

### RAM CPU (16 GB Ryzen)

Les images ne sont pas toutes en RAM. Le DataLoader les lit depuis le SSD, les décode (JPEG → tenseur), et les passe au GPU batch par batch. Avec `num_workers=4`, il y a ~4 batches pré-chargés en RAM ≈ 150 MB. Aucun problème avec 16 GB.

## Workflow multi-machine

### Entraîner sur le Mac, déployer sur le téléphone

```
Mac : entraîne → exporte TFLite → déploie dans assets → build APK
```

Tout est local, simple.

### Entraîner sur le PC GPU, récupérer sur le Mac

```
PC  : entraîne → upload best_model.pth vers Supabase Storage
Mac : download best_model.pth → exporte TFLite → déploie → build APK
```

Ou via l'admin web :
1. Sur le PC : `/training` → entraîne les pièces → "Upload Supabase"
2. Sur le Mac : récupère le modèle depuis Supabase → "Compiler TFLite" → "Déployer"

### Ce qui doit être synchronisé entre les machines

| Donnée | Synchronisé via |
|---|---|
| Images source (obverse.jpg) | Supabase Storage (bucket `coin-images`) |
| Modèle entraîné (best_model.pth) | Supabase Storage (bucket `ml-models`) |
| Embeddings de référence | Supabase DB (`coin_embeddings`) |
| Images augmentées | **Non synchronisé** — régénérées localement |
| Dataset splitté | **Non synchronisé** — régénéré localement |

## Pipeline complète : de Numista au scan utilisateur

```
1. Image Numista (obverse.jpg)
   ↓
2. Augmentation (50 variantes : rotation, fond, éclairage, blur)
   ↓
3. Entraînement ArcFace (toutes les classes ensemble)
   ↓
4. best_model.pth (4.3 MB — le cerveau)
   ↓
5. Calcul des centroïdes (1 vecteur 256-dim par design)
   ↓
6. Export TFLite (4.2 MB — le cerveau compilé pour mobile)
   ↓
7. Déploiement dans assets Android
   ↓
8. Build APK
   ↓
9. L'utilisateur scanne une pièce
   ↓
10. TFLite produit un embedding → comparé aux centroïdes → match !
```
