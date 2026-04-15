# Handoff — YOLO11-nano déployé, debug du scan à venir

> Session du 2026-04-15 matin. À lire au début de la prochaine session pour reprendre où on s'est arrêté.
>
> **⚠️ Ce handoff est maintenant historique.** La session du 2026-04-15 soir a remplacé YOLO seul par un pipeline unifié. Voir `detection-pipeline-unified.md` pour l'architecture actuelle du scan côté Android.

## État actuel

On a remplacé **YOLOv8-nano** par **YOLO11-nano** dans l'app Eurio pour réduire les faux positifs du scan (murs, bureaux, écrans qui déclenchaient le détecteur). Le nouveau modèle est copié dans `app/src/main/assets/models/coin_detector.tflite` et l'app a été rebuild/installée.

**Ce qu'il reste à faire : tester le scan en conditions réelles sur le téléphone et débugger les comportements inattendus.**

## Ce qui a été fait

### 1. Environnement de training (NixOS + 1080 Ti)

- `yolo_shell.nix` à la racine : FHS env avec Python 3.10, CUDA toolkit, cuDNN, stdlib C++, etc. Nécessaire car les wheels pip de PyTorch ne trouvent pas le loader dynamique sur NixOS.
- `yolo_env/` : venv pip (ignoré par git) avec `torch+cu121`, `ultralytics`, `onnx2tf`.
- Pour entrer : `nix-shell yolo_shell.nix` puis `source yolo_env/bin/activate`.

### 2. Dataset combiné (non commité — lourd)

Script `ml/merge_coin_datasets.py` qui merge deux datasets Roboflow :
- **OwnSoft Euro Coin Detection v7** (1017 train + 80 val + 42 test, déjà nc=1)
- **YoloCOIN v15** (1985 train + 164 test, nc=14 mixte euro/US/Canada/Croatia)

Toutes les classes sont remappées à `0` (une seule classe "coin"). Split 90/10 sur le train de YoloCOIN pour créer un vrai val split. Résultat : **2804 train / 278 val / 206 test**.

Script `ml/add_backgrounds.py` ajoute **200 images COCO val2017** aléatoires dans `train/` comme négatifs (labels vides). But : apprendre au modèle à ne pas firer sur murs, bureaux, objets ronds non-pièces (assiettes, horloges…).

Final : **3004 train / 278 val / 206 test**.

`data.yaml` absolu dans `ml/datasets/coin_detect_v2/data.yaml` (non commité).

### 3. Training

Commande lancée (voir `docs/research/yolo11-train-commands.md`) :

```bash
yolo detect train model=yolo11n.pt data=ml/datasets/coin_detect_v2/data.yaml epochs=300 imgsz=320 batch=32 device=0 cos_lr=True close_mosaic=10 patience=50 project=ml/runs/coin_detect name=yolo11n_v2
```

- Early stop à l'epoch 253 (best à 203), 1h28 sur la 1080 Ti
- Métriques val : **P=0.999 / R=1.000 / mAP50=0.995 / mAP50-95=0.911**
- Poids : `runs/detect/ml/runs/coin_detect/yolo11n_v2/weights/best.pt` (non commité)

**Ces métriques sont suspectes** — le val vient de la même distribution Roboflow que le train, donc ne teste pas vraiment la généralisation. Le vrai test c'est le comportement sur téléphone.

### 4. Export TFLite

- ONNX export direct via `yolo export`
- ONNX → TFLite via `ml/run_onnx2tf.py` (wrapper qui monkey-patch `download_test_image_data` — l'URL upstream est cassée et renvoie du HTML au lieu du `.npy` de calibration)
- **Deux fichiers générés** dans `runs/detect/ml/runs/coin_detect/yolo11n_v2/weights/tflite/` :
  - `best_float32.tflite` — 10 MB, déployé dans l'app
  - `best_float16.tflite` — 5.3 MB, backup si float32 pose souci
- Export sans NMS (`nms=False`) — le NMS est fait côté Kotlin (voir ADR 003)
- Pas de `disable_group_convolution` — sinon GPU delegate Android crash (issue connue pour YOLO11)

Modèle copié : `cp runs/detect/ml/runs/coin_detect/yolo11n_v2/weights/tflite/best_float32.tflite app/src/main/assets/models/coin_detector.tflite`

## Ce qu'il faut tester en priorité dans la prochaine session

1. **L'app démarre-t-elle sans crash ?** Si le loader TFLite plante, regarder logcat. Fallback : utiliser `best_float16.tflite` à la place.
2. **Le scan détecte-t-il les pièces ?** (golden path)
3. **Le scan NE détecte PAS** :
   - murs, tissus, bureaux, claviers, écrans
   - objets ronds non-pièces : assiettes, horloges, bouchons, frisbees
4. **Comportement dans des conditions difficiles** : piece dans les doigts, sur du tissu, sous faible lumière, flou, etc.

## Points techniques à vérifier côté Android

Le code pertinent est dans :
- `app/src/main/java/com/musubi/eurio/ml/CoinDetector.kt` — load du modèle, inference, post-process NMS
- `app/src/main/java/com/musubi/eurio/ml/CoinAnalyzer.kt` — pipeline caméra → détecteur
- `app/src/main/java/com/musubi/eurio/MainActivity.kt`

À vérifier :
- **Shape d'entrée** : `[1, 3, 320, 320]` float32 normalisée `[0,1]` — identique à YOLOv8n, pas de changement attendu
- **Shape de sortie** : `[1, 5, 2100]` (4 bbox coords + 1 conf, pour 2100 anchors à imgsz 320) — **à confirmer**, car YOLO11 pourrait avoir un layout transposé `[1, 2100, 5]` selon la version de l'export. Si ça crash avec `IndexOutOfBounds`, c'est probablement ça.
- **Seuil de confiance** : potentiellement à ré-tuner. Le nouveau modèle est beaucoup plus confiant sur les vraies pièces (val P=0.999). Si le seuil actuel est bas (ex: 0.25) on pourrait le monter à 0.4-0.5 sans perdre de recall, ce qui tuerait encore plus de faux positifs.
- **NMS** : seuils IoU inchangés a priori, mais à surveiller.

## Comment reproduire le pipeline complet

```bash
# 1. Entrer dans l'env
nix-shell yolo_shell.nix
source yolo_env/bin/activate

# 2. Re-télécharger les datasets Roboflow si besoin (voir urls dans le walkthrough)
#    puis placer les zips dans ml/datasets/coin_detect_v2/euro/ et coin/ et dézipper

# 3. Reconstruire le dataset
python ml/merge_coin_datasets.py
python ml/add_backgrounds.py  # DL COCO val2017 (~1 GB) la première fois

# 4. Re-entraîner (optionnel)
#    voir docs/research/yolo11-train-commands.md section 1 ou 2

# 5. Re-exporter TFLite
#    voir sections 6 et 7 du même fichier
#    IMPORTANT : utiliser ml/run_onnx2tf.py (pas `python -m onnx2tf` direct)
```

## Fichiers clés (tracked dans git)

| Fichier | Rôle |
|---|---|
| `yolo_shell.nix` | Environnement Nix reproductible pour le training |
| `ml/merge_coin_datasets.py` | Merge euro/ + coin/ Roboflow → format flat YOLO |
| `ml/add_backgrounds.py` | Ajoute 200 backgrounds COCO comme négatifs |
| `ml/run_onnx2tf.py` | Wrapper onnx2tf qui court-circuite le bug de download |
| `docs/research/yolo26-vs-yolo11-walkthrough.md` | Walkthrough complet (décision, setup NixOS, étapes) |
| `docs/research/yolo11-train-commands.md` | Commandes prêtes à copier (train, val, export) |
| `docs/research/yolo11-handoff-scan-debug.md` | Ce fichier |
| `app/src/main/assets/models/coin_detector.tflite` | **Le nouveau modèle déployé** |

## Fichiers ignorés par git (à savoir)

- `yolo_env/` — venv, recréable
- `runs/` — sorties training (poids `.pt`, logs, graphes, tflite intermédiaires)
- `yolo11n.pt`, `yolo26n.pt` — poids pré-entraînés auto-téléchargés
- `ml/datasets/coin_detect_v2/` — dataset combiné (~3000 images)
- `ml/.dataset_cache/` — cache COCO val2017 (815 MB)

Le `best.pt` est uniquement dans `runs/detect/ml/runs/coin_detect/yolo11n_v2/weights/best.pt` sur cette machine. Si on veut pouvoir re-exporter sans retrain, il faudrait soit le commiter (5.5 MB, acceptable), soit mettre en place un stockage externe.

## Commentaire libre

Le training s'est très bien passé. Le vrai risque maintenant c'est que les deux datasets Roboflow soient tellement "propres" (studio, fond blanc, bien cadrés) que le modèle n'aie pas appris à généraliser sur des photos prises main levée avec téléphone. Les 200 backgrounds COCO aident mais ne compensent pas une éventuelle domain shift. **Si le scan rate des pièces évidentes ou garde des faux positifs tenaces, la solution propre sera de collecter 100-200 frames réelles depuis l'app Eurio (debug captures), les annoter à la main, et faire un fine-tuning sur 50 epochs de plus.**
