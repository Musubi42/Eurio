# Phase 3 — Bake = seule source d'augmentation

> Pré-requis : phases 1 et 2 livrées (les tiroirs existent ; I2 affiche
> "obverse uniquement" en summary). Avoir lu les commentaires de
> `ml/training/iteration_augmentations.py` lignes 14-20 et le flag
> `--prebaked-augmentations` dans `train_embedder.py`.
>
> Sortie : `train_embedder.py` n'applique **plus aucun transform random**
> sur les samples bakés ; le subprocess log explicitement son contrat
> au boot ; le bake log la source par sample.

## Le problème précis

Aujourd'hui :

1. `iteration_augmentations.py` bake N samples augmentés depuis l'obverse
   sur disque. **OK, obverse-only enforced.**
2. `train_embedder.py:_launch_training` appelle le subprocess avec
   `--prebaked-augmentations`.
3. Côté subprocess (`train_embedder.py:193`) : `build_train_dataset`
   reçoit `recipe_override={"layers": []}` — donc aucune nouvelle
   couche d'augmentation custom n'est appliquée.
4. **MAIS** : `get_train_transforms()` (ligne 168) renvoie une
   `transforms.Compose` qui contient :
   ```py
   Resize((224, 224)),
   RandomRotation(360),
   RandomAffine(degrees=0, translate=(0.02, 0.02), scale=(0.97, 1.03)),
   RandomPerspective(distortion_scale=0.05, p=0.7),
   ColorJitter(brightness=0.3, contrast=0.3, saturation=0.2, hue=0.05),
   GaussianBlur(kernel_size=3, sigma=(0.1, 1.0)),
   ToTensor(),
   Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
   RandomErasing(p=0.2, scale=(0.02, 0.05), value=0.0),
   ```
   Ce Compose est appliqué via le DataLoader **à chaque sample
   chargé**, **même quand `--prebaked-augmentations`** est set.

Donc en pratique, le modèle voit du jitter/rotation/erasing/blur que
la recipe utilisateur ne contrôle pas. C'est **exactement ce que le
user veut purger** : "plus de génération à la volée pour
l'augmentation".

## Ce que cette phase fait

### Décision de design — qu'est-ce qu'on garde ?

Au runtime, on **doit** garder uniquement :

- `Resize((224, 224))` : ce n'est pas une augmentation, c'est une
  contrainte d'input du modèle. Le bake écrit en HxW variable
  (typiquement 1024+) — il faut downscaler.
- `ToTensor()`
- `Normalize(mean=ImageNet, std=ImageNet)` : prétraitement requis
  pour ResNet18 préentraîné.

On **purge** :

- `RandomRotation(360)`
- `RandomAffine`
- `RandomPerspective`
- `ColorJitter`
- `GaussianBlur`
- `RandomErasing`

Ces 6 transforms doivent **toutes** être présentes dans la recipe si
l'utilisateur les veut. Pas de "buy one get six free" silencieux.

### Cas non-prebaked (legacy)

Le path `train_embedder.py` sans `--prebaked-augmentations` (mode
legacy `/training/run` direct) garde l'ancien comportement. C'est
explicitement noté en sprint 1 handoff : "le legacy on-the-fly
augmentation reste en place pour les chemins non-iteration via
`/training/run` direct". On ne casse pas ce path.

## Backend

### B1 — `train_embedder.py:get_train_transforms`

**Fichier** : `ml/training/train_embedder.py` ligne 135-179.

**Renommer** la fonction actuelle en `get_legacy_train_transforms()`
(elle reste utilisée pour le mode non-prebaked). Et créer :

```py
def get_prebaked_transforms() -> transforms.Compose:
    """Transforms applied when augmentations are baked on disk.

    Strict contract: NO random augmentation here. The bake step
    (iteration_augmentations.py) is the *only* source of variability.
    Everything below is plain preprocessing.
    """
    return transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
```

**Modifier** `build_train_dataset` (ligne 182) :

```py
def build_train_dataset(args):
    if getattr(args, "prebaked_augmentations", False):
        legacy = get_prebaked_transforms()  # ← changement
        # recipe_override={"layers": []} reste pour neutraliser la recipe layer
        ...
    else:
        legacy = get_legacy_train_transforms()
        ...
```

### B2 — Logging explicite au boot

**Fichier** : `ml/training/train_embedder.py` après le device select
(ligne 647 pour le mode arcface — adapter aussi pour classify et
embed si on veut être propre).

Ajouter :

```py
import json as _json

def _log_runtime_contract(args, device, n_train, n_classes):
    payload = {
        "event": "runtime",
        "mode": args.mode,
        "device": str(device),
        "torch_version": torch.__version__,
        "augmentations_runtime": "disabled" if getattr(args, "prebaked_augmentations", False) else "legacy_compose",
        "dataset_size": n_train,
        "num_classes": n_classes,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
    }
    print("RUNTIME " + _json.dumps(payload), flush=True)
```

Appelé juste après `print(f"Mode: arcface | Device: {device}")` (et
équivalents pour classify/embed). Le préfixe `RUNTIME ` aide les regex
côté training_runner.

### B3 — Tensor placement check

**Fichier** : `ml/training/train_embedder.py` après `model.to(device)`
(lignes 412, 547, 699).

```py
print(f"TENSOR_CHECK model.device={next(model.parameters()).device}", flush=True)
```

Pour que phase 5 puisse confirmer dans le log tail que le modèle est
bien sur le bon device.

### B4 — Source path par sample dans le bake

**Fichier** : `ml/training/iteration_augmentations.py:generate_for_iteration`.

Aujourd'hui le bake produit `sample_NNN.jpg` sans métadonnée. Pour que
le tiroir I2 puisse afficher "source: obverse.jpg" par pièce, on
ajoute un fichier `_manifest.json` à côté des samples :

```json
{
  "iteration_id": "...",
  "eurio_id": "fr-1999-2eur",
  "numista_id": 12345,
  "recipe_id": "066c75c654c5",
  "seed": 1234567890,
  "samples": [
    {"file": "sample_001.jpg", "source": "obverse.jpg"},
    ...
  ],
  "generated_at": "2026-05-01T..."
}
```

Écrit en append à la fin de la boucle de bake par coin (ligne 198-199),
juste avant le `reports.append`. Lecture côté front : optionnelle pour
v1, mais le manifest est l'audit trail explicite que la source est
bien obverse-only.

### B5 — `_launch_training` : refuse si I2 pas ready

**Fichier** : `ml/api/iteration_runner.py:_launch_training` (ligne 340).

Aujourd'hui le runner appelle `generate_for_iteration` qui est
idempotent — donc si I2 n'est pas ready, il bake. C'est une
"surprise" silencieuse.

Changement : avant le `start_run`, vérifier que tous les coins ont
≥ variant_count samples. Si non, raise `RuntimeError("I2 incomplete:
{N} coins manquants — bake d'abord via le tiroir I2")`. Le front
(I3 locked si I2 pas ready) empêche déjà ce cas, mais on belt-and-
suspenders côté backend.

## Frontend

### F1 — I2 affiche "obverse uniquement"

**Fichier** : `IterationDrawerI2.vue` (créé en phase 2).

Le summary header inclut littéralement le mot "obverse uniquement"
quand `state === 'ready'`. Cf phase 2 F1.

### F2 — Affichage du manifest (optionnel v1)

Si on veut, dans le body de I2 quand expanded, montrer pour le coin
sélectionné : "source: obverse.jpg, recipe: hell-yeah, seed: …"
(via fetch d'un nouvel endpoint `GET .../iterations/<iid>/bake-manifest/<eurio_id>`).

**v1** : skipper. Le contrat est dans le code et dans I2 summary
("obverse uniquement"). Si l'utilisateur veut l'audit complet, il
ouvre le `_manifest.json` à la main.

## Critère de succès

1. Lancer une iteration : dans le log subprocess (visible via la
   future phase 5, ou via `tail -f` du log file en attendant), on
   doit voir une ligne :
   ```
   RUNTIME {"event":"runtime","mode":"arcface","device":"mps:0","torch_version":"2.x","augmentations_runtime":"disabled","dataset_size":800,"num_classes":16,"epochs":40,"batch_size":256}
   ```
2. Comparaison visuelle : extraire un sample bakké
   (`ml/datasets/<nid>/augmentations/<iid>/sample_001.jpg`) et un
   batch sortant du DataLoader (instrumentation manuelle ponctuelle
   dans la training loop). Le batch après dénormalisation doit être
   **identique** au sample bakké au resize 224 près.
3. `iteration_augmentations.py` produit un `_manifest.json` par coin
   listant les samples et leur source `obverse.jpg`. Vérifier sur la
   cohort `green-v1`.
4. Tenter un `launch_training` sur une iteration sans bake → 400 ou
   409 explicite "I2 incomplete".
5. Le path legacy non-prebaked (lancer un run via
   `/training/run` direct sans iteration) continue de fonctionner
   exactement comme avant. Pas de régression.

## Pièges connus

- **Le mode non-prebaked existe encore** : `/training/run` direct
  (legacy) ne passe pas par `iteration_runner` et utilise
  `get_legacy_train_transforms`. Ne pas casser ce path. La fonction
  legacy reste, juste renommée.
- **`pytorch_metric_learning`** : le mode arcface utilise
  `MPerClassSampler` qui dépend de la quantité de samples par classe.
  Si le bake produit 50 samples × 16 coins = 800, `m_per_class=4`
  donne ~12 batches de 256 par epoch. Vérifier qu'on ne crash pas
  pour des cohorts plus petites (ex : 1 coin, 50 samples → batch_size
  trop grand). Statu quo, ce n'est pas un problème nouveau.
- **Determinisme** : sans le RandomRotation(360) etc., le training va
  être plus déterministe. Si la recipe ne contient pas elle-même de
  rotation, le modèle perd l'invariance par rotation. **C'est le
  comportement voulu** — c'est à la recipe de l'inclure si on veut.
  Documenter clairement dans `iteration-detail-page-design.md` ou
  ailleurs.
- **Le manifest JSON peut grossir** pour des cohorts énormes (par
  exemple 200 coins × 100 samples). C'est négligeable (~10KB par
  coin, structure plate). Pas d'optimisation v1.

## Hors-scope

- Pas de changement de la recipe DSL ni du `AugmentationPipeline`.
- Pas de migration des iterations existantes : les augmentations
  bakées au sprint 1 restent valides, le manifest manquera juste
  pour les anciennes — c'est OK, on ne le rétroactive pas.
- Pas de modification de `compute_embeddings.py` ni
  `validate_per_class.py` (eux n'utilisent pas les augmentations,
  ils tournent sur les val sets).
- Pas de tests automatisés (smoke check manuel via inspection log).
