# ADR-003 — Export YOLOv8-nano vers TFLite

> Date : 2026-04-10
> Statut : Accepté
> Contexte : L'export TFLite natif d'Ultralytics échoue à cause de conflits de dépendances TensorFlow/tf_keras/protobuf dans l'environnement Nix.

---

## Problème

L'export TFLite intégré à Ultralytics (`model.export(format='tflite')`) nécessite une chaîne de dépendances fragile :

```
ultralytics → onnx → onnx2tf → tf_keras → tensorflow
```

### Erreurs rencontrées

1. **`pip: command not found`** — Ultralytics essaie d'auto-installer les dépendances via `pip`, qui n'existe pas dans le venv Nix (on utilise `uv`).

2. **`tf_keras` vs `tensorflow` incompatible** — `tf_keras<=2.19.0` requiert `tensorflow.__internal__.register_load_context_function` qui n'existe plus dans TF 2.21-dev.

3. **`protobuf` version conflict** — TensorFlow 2.21-dev exige `protobuf>=5.29`, mais `onnx2tf` installe `protobuf==4.25.5`.

## Solution retenue

Export en deux étapes via ONNX + onnx2tf (sans passer par l'export intégré Ultralytics) :

### Étape 1 : PyTorch → ONNX (via Ultralytics)

```python
from ultralytics import YOLO
model = YOLO('best.pt')
model.export(format='onnx', imgsz=320, simplify=True, nms=True)
```

- Fonctionne sans TensorFlow
- `nms=True` intègre le NMS dans le modèle ONNX
- Output shape : `(1, 300, 6)` — 300 détections max, format `[x1, y1, x2, y2, confidence, class_id]`

### Étape 2 : ONNX → TFLite (via onnx2tf)

```bash
.venv/bin/python -m onnx2tf \
    -i best.onnx \
    -o tflite_out \
    -oiqt  # INT8 quantization
```

- Génère 6 variantes (float32, float16, int8, full-int8, int16-act, full-int16-act)
- On retient `best_integer_quant.tflite` (INT8, 3.3 MB)
- Pas besoin de `tf_keras` — onnx2tf utilise directement TF Lite Flatbuffer

### Commandes complètes

```bash
# Dans ml/
# 1. Export ONNX
.venv/bin/python -c "
from ultralytics import YOLO
model = YOLO('output/detection/coin_detector/weights/best.pt')
model.export(format='onnx', imgsz=320, simplify=True, nms=True)
"

# 2. ONNX → TFLite (toutes les variantes)
.venv/bin/python -m onnx2tf \
    -i output/detection/coin_detector/weights/best.onnx \
    -o output/detection/coin_detector/weights/tflite_out \
    -oiqt

# 3. Copier la variante INT8
cp output/detection/coin_detector/weights/tflite_out/best_integer_quant.tflite \
   output/coin_detector.tflite

# 4. Déployer dans les assets Android
cp output/coin_detector.tflite ../app/src/main/assets/models/
```

## Alternatives considérées

| Approche | Résultat | Pourquoi écartée |
|---|---|---|
| `model.export(format='tflite')` (Ultralytics natif) | Échec — `tf_keras` incompatible avec TF 2.21-dev | Conflit de dépendances irrésoluble sans downgrader TF |
| `litert_torch.convert()` (comme pour le embedder) | Non tenté | YOLO utilise des ops non supportées par litert_torch (NMS, topk) |
| Export ONNX + `tensorflow.lite.TFLiteConverter` | Échec — protobuf incompatible | Même problème tf_keras |
| **ONNX + onnx2tf (CLI)** | **Succès** | Contourne tf_keras en utilisant le Flatbuffer builder natif |

## Variantes TFLite générées

| Variante | Taille | Usage |
|---|---|---|
| float32 | 11.6 MB | Debug / validation |
| float16 | 5.8 MB | Compromis si INT8 pose problème |
| **integer_quant (INT8)** | **3.3 MB** | **Production mobile** |
| full_integer_quant | 3.1 MB | Si on veut le plus petit possible |

## Format de sortie

Avec `nms=True` dans l'export ONNX, le TFLite produit :

```
Input:  [1, 3, 320, 320]  — image RGB normalisée [0, 1]
Output: [1, 300, 6]       — 300 détections, chaque = [x1, y1, x2, y2, confidence, class_id]
```

Les coordonnées sont en pixels (échelle 320×320). `CoinDetector.kt` les rescale vers la taille de l'image originale.

## Impact

- Le script `train_detector.py --export-only` utilise l'export natif Ultralytics et peut échouer. Utiliser la procédure manuelle ci-dessus.
- Les dépendances `onnx`, `onnxslim`, `onnxruntime`, `onnx2tf` doivent être dans le venv.
- La quantification INT8 ne nécessite pas de dataset de calibration avec onnx2tf (il utilise les min/max des poids).
