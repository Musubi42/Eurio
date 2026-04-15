# YOLO11-nano — commandes de training

Commandes prêtes à copier pour le training sur 1080 Ti (NixOS).

## 0. Entrer dans l'environnement

```bash
nix-shell yolo_shell.nix
```

```bash
source yolo_env/bin/activate
```

## 1. Lancer le training (version simple)

```bash
yolo detect train model=yolo11n.pt data=ml/datasets/coin_detect_v2/data.yaml epochs=300 imgsz=320 batch=32 device=0 cos_lr=True close_mosaic=10 patience=50 project=ml/runs/coin_detect name=yolo11n_v2
```

## 2. Lancer le training + sauver le log

```bash
yolo detect train model=yolo11n.pt data=ml/datasets/coin_detect_v2/data.yaml epochs=300 imgsz=320 batch=32 device=0 cos_lr=True close_mosaic=10 patience=50 project=ml/runs/coin_detect name=yolo11n_v2 2>&1 | tee ml/runs/train_$(date +%Y%m%d_%H%M).log
```

## 3. Monitorer la VRAM (shell séparé)

### nvtop (recommandé, TUI)

```bash
nix-shell -p nvtop --run nvtop
```

### nvidia-smi en boucle (zéro install)

```bash
watch -n 1 nvidia-smi
```

### nvidia-smi streaming compact

```bash
nvidia-smi dmon -s u
```

## 4. Après le training — validation

```bash
yolo detect val model=ml/runs/coin_detect/yolo11n_v2/weights/best.pt data=ml/datasets/coin_detect_v2/data.yaml imgsz=320
```

## 5. Après le training — prédiction sur images de test

```bash
yolo detect predict model=ml/runs/coin_detect/yolo11n_v2/weights/best.pt source=ml/datasets/coin_detect_v2/test/images imgsz=320 conf=0.5
```

## 6. Export ONNX (étape 1 de 2 pour TFLite)

```bash
yolo export model=runs/detect/ml/runs/coin_detect/yolo11n_v2/weights/best.pt format=onnx imgsz=320 simplify=True nms=False opset=13
```

Le fichier `best.onnx` est créé à côté de `best.pt`.

## 7. Conversion ONNX → TFLite (étape 2 de 2)

**Préparer un dummy input** (workaround bug onnx2tf 2.4.0 + numpy récent) :

```bash
python -c "import numpy as np; np.save('ml/.dataset_cache/dummy_input.npy', np.random.rand(1, 320, 320, 3).astype(np.float32))"
```

**Lancer la conversion** :

```bash
python -m onnx2tf -i runs/detect/ml/runs/coin_detect/yolo11n_v2/weights/best.onnx -o runs/detect/ml/runs/coin_detect/yolo11n_v2/weights/tflite -cind images ml/.dataset_cache/dummy_input.npy "[[[[0.0,0.0,0.0]]]]" "[[[[1.0,1.0,1.0]]]]"
```

Le fichier final : `runs/detect/ml/runs/coin_detect/yolo11n_v2/weights/tflite/best_float32.tflite` (~10 MB).

**IMPORTANT** : ne PAS ajouter `-dgc` / `disable_group_convolution` — ça casse le GPU delegate Android (voir ADR 003).

## 8. Copier le modèle dans l'app Android

```bash
cp runs/detect/ml/runs/coin_detect/yolo11n_v2/weights/tflite/best_float32.tflite app/src/main/assets/models/coin_detector.tflite
```

(adapter le chemin `app/src/main/assets/models/` selon l'arborescence réelle du module Android)

## 9. Rebuild et installer sur le téléphone

```bash
./gradlew installDebug
```
