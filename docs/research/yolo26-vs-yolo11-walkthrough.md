# YOLO Upgrade Walkthrough — Detection de pieces

> Date : 2026-04-10. Guide pour passer de YOLOv8-nano a un modele plus performant.

---

## TL;DR — Decision

| | YOLOv8-nano (actuel) | YOLO11-nano | YOLO26-nano |
|---|---|---|---|
| Params | 3.2M | 2.6M | 2.4M |
| mAP COCO | 37.3 | 39.5 | 40.9 |
| CPU ONNX | 80ms | 56ms | 39ms |
| TFLite Android | OK (CPU+GPU) | OK (CPU+GPU, fix export) | CASSE (GPU delegate) |
| TFLite float32 | ~12 MB | ~10 MB | ~9 MB |
| Statut | En prod, faux positifs | Pret a tester | Risque TFLite |

### Recommandation : YOLO11-nano

**YOLO26-nano** a de meilleures metriques mais son **export TFLite ne fonctionne pas sur Android** (GPU delegate crash, issue fermee "not planned"). Le workaround ONNX Runtime complexifie le pipeline.

**YOLO11-nano** est le sweet spot :
- +2.2 mAP vs YOLOv8-nano
- 30% plus rapide sur CPU
- 19% moins de params
- **TFLite Android fonctionne** (CPU et GPU avec le bon export)
- Deja teste et valide par la communaute

---

## Ou entrainer ?

### Option A : PC Linux NixOS + 1080 Ti (RECOMMANDE)

| | Specs |
|---|---|
| GPU | NVIDIA 1080 Ti — 11 GB VRAM, CUDA (compute capability 6.1, Pascal) |
| Avantage | 5-10x plus rapide que Mac MPS pour le training |
| Temps estime | ~30 min pour 300 epochs sur ~1500 images |

C'est le choix evident : CUDA est le runtime natif de PyTorch/YOLO, la 1080 Ti a 11GB de VRAM (largement suffisant pour nano), et c'est gratuit.

**Specificite NixOS** : les wheels pip de PyTorch sont linkes contre `/lib64/ld-linux-x86-64.so.2` et des libs systemes (glibc, libstdc++, CUDA, cuDNN) qui n'existent pas aux chemins standards sur NixOS. Deux options :

#### A.1 — Approche recommandee : `shell.nix` FHS env

Creer `yolo_shell.nix` a la racine du projet :

```nix
{ pkgs ? import <nixpkgs> {
    config.allowUnfree = true;
    config.cudaSupport = true;
  }
}:

(pkgs.buildFHSEnv {
  name = "yolo-cuda-env";
  targetPkgs = pkgs: with pkgs; [
    python310
    python310Packages.pip
    python310Packages.virtualenv
    cudaPackages.cudatoolkit
    cudaPackages.cudnn
    linuxPackages.nvidia_x11
    libGL
    glib
    zlib
    stdenv.cc.cc.lib   # libstdc++.so.6 — requis par les wheels PyTorch
    git
    which
  ];
  runScript = "zsh";
}).env
```

Puis :

```bash
# 1. Verifier que la carte est vue par le driver (hors shell nix)
nvidia-smi
# Doit afficher: NVIDIA GeForce GTX 1080 Ti, driver version, CUDA version

# 2. Entrer dans le FHS env
nix-shell yolo_shell.nix

# 3. Creer et activer le venv (maintenant on est dans un /usr/lib /bin classique)
python -m venv yolo_env
source yolo_env/bin/activate

# 4. Installer PyTorch CUDA + Ultralytics
#    cu121 fonctionne avec la 1080 Ti (Pascal reste supporte dans les wheels actuels)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install "ultralytics>=8.4.0" onnx2tf

# 5. Verifier
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# Doit afficher: True NVIDIA GeForce GTX 1080 Ti
```

A chaque nouvelle session : `nix-shell yolo_shell.nix` puis `source yolo_env/bin/activate`.

#### A.2 — Alternative : `nix-ld` (si deja active sur ton systeme)

Si tu as deja `programs.nix-ld.enable = true;` dans ta config NixOS, tu peux rester dans un shell normal et juste faire :

```bash
# Ajouter les libs CUDA a NIX_LD_LIBRARY_PATH via nix-ld, puis
python -m venv yolo_env
source yolo_env/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
pip install "ultralytics>=8.4.0" onnx2tf
```

Plus simple mais exige que `nix-ld` soit configure avec cudatoolkit/cudnn/nvidia_x11 dans `programs.nix-ld.libraries`. Si tu ne sais pas si c'est le cas : utilise l'option A.1.

### Option B : Mac M3 Air (MPS)

| | Specs |
|---|---|
| GPU | Apple Silicon M3 — MPS backend |
| Avantage | Deja configure avec nix/direnv |
| Inconvenient | 5-10x plus lent que CUDA, MPS instable pour training |
| Temps estime | ~2-4h pour 300 epochs |

Utilisable en depannage, mais pas ideal pour iterer rapidement.

### Option C : Roboflow Cloud

| | Details |
|---|---|
| Prix | Free tier = $60/mois de credits, mais YOLO26 non dispo en free |
| | Core plan = $79/mois pour tous les modeles |
| Avantage | Zero setup, auto-tuning, bon GPU |
| Inconvenient | Free tier = "Fast Models Only" (pas YOLO11/26) |
| | Free tier = pas de download des poids du modele |
| | Payant pour avoir les poids + modeles avances |

**Verdict** : pas necessaire. La 1080 Ti suffit largement et c'est gratuit.

### Option D : Google Colab (gratuit)

| | Details |
|---|---|
| GPU | T4 gratuit (16 GB VRAM) |
| Avantage | Gratuit, bon GPU, zero setup local |
| Inconvenient | Sessions limitees (~4h), deconnexions |
| Temps estime | ~20 min pour 300 epochs |

Bonne option de backup si le PC Windows pose probleme.

### Verdict : PC NixOS 1080 Ti > Colab > Mac > Roboflow

---

## Walkthrough complet

### Etape 1 : Preparer le dataset combine

```bash
# Structure cible
datasets/
  coin_detect_v2/
    train/
      images/
        coin_001.jpg
        coin_002.jpg
        background_001.jpg      # images sans pieces
      labels/
        coin_001.txt            # bounding boxes
        coin_002.txt
        background_001.txt      # FICHIER VIDE
    val/
      images/
      labels/
    data.yaml
```

**data.yaml :**
```yaml
path: ./datasets/coin_detect_v2
train: train/images
val: val/images

nc: 1
names: ['coin']
```

**Sources de donnees a combiner :**

1. **OwnSoft Euro** (461 images) — telecharger depuis Roboflow en format YOLO11
   ```
   https://universe.roboflow.com/ownsoft-technologies/euro-coin-detection/dataset/7/download
   ```
   - Selectionner format "YOLOv11"
   - Mapper toutes les classes → "coin" (classe 0)

2. **YoloCOIN** (826 images) — telecharger depuis Roboflow en format YOLO11
   ```
   https://universe.roboflow.com/yolocoin/coin-gva2j
   ```
   - Mapper toutes les classes → "coin" (classe 0)

3. **Images background** (~100-200 images) — scenes interieures sans pieces
   - Telecharger depuis COCO (categorie "indoor") ou Google Images
   - OU utiliser les frames de debug captures qui sont des faux positifs
   - Creer un .txt vide pour chaque image

**Total estime : ~1500 images** (1287 positives + ~200 negatives)
**Split recommande : 85% train / 15% val**

### Etape 2 : Remapper les classes

Les datasets Roboflow ont plusieurs classes (denominations). On veut une seule classe "coin".

```python
# remap_classes.py
import os
import glob

def remap_to_single_class(labels_dir):
    """Remplace toutes les classes par 0 (coin)."""
    for txt_file in glob.glob(os.path.join(labels_dir, "*.txt")):
        lines = []
        with open(txt_file, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 5:
                    # Remplacer la classe par 0
                    parts[0] = '0'
                    lines.append(' '.join(parts))
        with open(txt_file, 'w') as f:
            f.write('\n'.join(lines) + '\n' if lines else '')

# Executer sur les dossiers labels telecharges
remap_to_single_class("datasets/coin_detect_v2/train/labels")
remap_to_single_class("datasets/coin_detect_v2/val/labels")
```

### Etape 3 : Entrainer YOLO11-nano

```bash
# Sur le PC NixOS avec 1080 Ti
# (dans nix-shell yolo_shell.nix + venv active)
yolo detect train \
  model=yolo11n.pt \
  data=datasets/coin_detect_v2/data.yaml \
  epochs=300 \
  imgsz=320 \
  batch=32 \
  device=0 \
  cos_lr=True \
  close_mosaic=10 \
  patience=50 \
  project=runs/coin_detect \
  name=yolo11n_v2

# Parametres :
#   model=yolo11n.pt    → telecharge auto les poids pre-entraines COCO
#   imgsz=320           → meme resolution que notre deploiement actuel
#   batch=32            → la 1080 Ti (11GB) gere facilement pour nano
#   cos_lr=True         → cosine learning rate scheduler
#   close_mosaic=10     → desactive mosaic les 10 derniers epochs
#   patience=50         → early stopping si pas d'amelioration
```

**Temps estime : 20-40 min sur 1080 Ti**

### Etape 4 : Valider

```bash
# Verifier les metriques
yolo detect val \
  model=runs/coin_detect/yolo11n_v2/weights/best.pt \
  data=datasets/coin_detect_v2/data.yaml \
  imgsz=320

# Tester sur quelques images
yolo detect predict \
  model=runs/coin_detect/yolo11n_v2/weights/best.pt \
  source=test_images/ \
  imgsz=320 \
  conf=0.5
```

Regarder :
- mAP@50 > 90%
- Precision > 90%
- Recall > 85%
- **Pas de detections sur les images background** (le plus important)

### Etape 5 : Exporter en TFLite

```bash
# Export ONNX d'abord
yolo export \
  model=runs/coin_detect/yolo11n_v2/weights/best.pt \
  format=onnx \
  imgsz=320 \
  simplify=True \
  nms=False

# Puis ONNX → TFLite via onnx2tf
# IMPORTANT : ne PAS utiliser disable_group_convolution=True (casse le GPU Android)
pip install onnx2tf
python -m onnx2tf \
  -i runs/coin_detect/yolo11n_v2/weights/best.onnx \
  -o runs/coin_detect/yolo11n_v2/weights/tflite

# Le fichier float32 sera dans :
# runs/coin_detect/yolo11n_v2/weights/tflite/best_float32.tflite (~10 MB)

# Optionnel : float16 pour reduire la taille (~5 MB)
python -m onnx2tf \
  -i runs/coin_detect/yolo11n_v2/weights/best.onnx \
  -o runs/coin_detect/yolo11n_v2/weights/tflite_fp16 \
  -oqt float16
```

### Etape 6 : Deployer sur Android

```bash
# Copier le modele dans l'app
cp runs/coin_detect/yolo11n_v2/weights/tflite/best_float32.tflite \
   app/src/main/assets/models/coin_detector.tflite

# Builder et deployer
./gradlew installDebug
```

Verifier avec le systeme de debug capture :
1. Scanner des pieces → detection OK ?
2. Scanner des murs/ecrans/bureaux → PAS de detection ?
3. Piece dans les doigts → detection OK ?
4. Piece sur du tissu → detection OK ?

---

## Probleme connu : export TFLite

Notre pipeline actuelle utilise deja onnx2tf pour l'export (voir `docs/adr/003-yolo-tflite-export.md`). Les problemes rencontres :
- INT8 casse (GATHER_ND)
- NMS integre crash au runtime
- Float32 sans NMS fonctionne

Pour YOLO11 : **ne pas utiliser `disable_group_convolution=True`** dans onnx2tf, sinon le GPU delegate Android crash (split en 256 convolutions). Sans ce flag, ca fonctionne sur CPU ET GPU.

---

## Checklist avant de commencer

- [ ] PC NixOS : driver NVIDIA charge, `nvidia-smi` affiche la 1080 Ti
- [ ] PC NixOS : `yolo_shell.nix` cree a la racine du projet
- [ ] PC NixOS : `nix-shell yolo_shell.nix` entre sans erreur
- [ ] PC NixOS : venv cree + `source yolo_env/bin/activate`
- [ ] PC NixOS : `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121`
- [ ] PC NixOS : `pip install "ultralytics>=8.4.0" onnx2tf`
- [ ] PC NixOS : `torch.cuda.is_available()` renvoie `True`
- [ ] Telecharger dataset OwnSoft Euro (format YOLO11)
- [ ] Telecharger dataset YoloCOIN (format YOLO11)
- [ ] Preparer ~100-200 images background
- [ ] Combiner et remapper les classes → "coin"
- [ ] Verifier structure dataset + data.yaml

---

## Sources

- [YOLO11 vs YOLOv8 comparison](https://docs.ultralytics.com/compare/yolov8-vs-yolo11/)
- [YOLO26 vs YOLOv8 comparison](https://docs.ultralytics.com/compare/yolov8-vs-yolo26/)
- [YOLO26 TFLite Android issue (broken)](https://github.com/ultralytics/ultralytics/issues/23282)
- [YOLO11 TFLite Android GPU fix](https://github.com/ultralytics/ultralytics/issues/17837)
- [Tips for best YOLO training](https://docs.ultralytics.com/yolov5/tutorials/tips_for_best_training_results/)
- [How to train YOLO26 custom data](https://blog.roboflow.com/how-to-train-yolo26-custom-data/)
- [Roboflow pricing](https://roboflow.com/pricing)
- [Adding negative samples to YOLO](https://github.com/ultralytics/ultralytics/issues/5044)
