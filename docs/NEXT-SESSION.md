# Eurio — Prochaine session

> Document de handoff pour reprendre le travail. Écrit le 2026-04-10.

---

## État actuel du projet

### Ce qui fonctionne ✅

- **ArcFace embedder** : R@1=100% sur 5 pièces, export TFLite validé (4.2 MB, cosine sim 1.000)
- **Classification** : val accuracy 100% avec augmentation synthétique (50 images/classe)
- **Pipeline Android** : CameraX → scan continu 300ms → résultat overlay avec nom, pays, année, image Numista
- **Toggles A/B** : YOLO ON/OFF et ArcFace ON/OFF dans le debug panel
- **Debug capture** : bouton CAPTURE sauvegarde frame caméra + crop YOLO + logs texte
- **Catalogue Numista** : 445 pièces de 2€ importées (métadonnées complètes, ~300 images)
- **Augmentation synthétique** : rotation, fonds variés, masque circulaire, 50 images/classe

### Ce qui ne fonctionne PAS ❌

- **YOLO détection** : faux positifs massifs. Détecte des "pièces" sur murs, écrans, bureaux. Le dataset Roboflow manque de négatifs réalistes. Voir `docs/research/yolo-detection-findings.md`.
- **Biais ArcFace** : quand YOLO crop du bruit, ArcFace retourne toujours 226447 (Kniefall) comme "moins mauvais" match.
- **Export TFLite YOLO** : INT8 cassé, NMS cassé. On utilise float32 sans NMS (12 MB). Voir `docs/adr/003-yolo-tflite-export.md`.
- **Images Numista manquantes** : ~145 images non téléchargées (rate limit). ~55 pièces restant à importer.

---

## Priorité #1 : Améliorer la détection YOLO

### Le problème

Le modèle YOLOv8-nano a 99.5% mAP en validation mais détecte des "pièces" partout en conditions réelles. Il manque de négatifs réalistes dans le dataset d'entraînement.

### Actions à explorer

1. **Enrichir le dataset avec des négatifs réalistes**
   - Prendre 50-100 photos avec le Pixel : bureau, mur, écran, main vide, objets ronds non-pièces
   - Les ajouter dans `ml/datasets/detection/coin_detect/train/images/` avec des labels vides
   - Re-entraîner : `go-task detect-train`

2. **Chercher un meilleur dataset**
   - Roboflow "YoloCOIN" (`yolocoin/coin-gva2j`) — 826 images, 20 classes
   - Roboflow-100 coins (`roboflow-100/coins-1apki`)
   - Combiner avec le dataset actuel

3. **Entraîner sur Roboflow cloud**
   - Upload images + annotations sur Roboflow
   - Entraîner dans le cloud (meilleur GPU, auto-tuning)
   - Télécharger le modèle

4. **Chercher un modèle pré-entraîné**
   - Un modèle coin detection déjà publié sur Roboflow Universe ou Hugging Face
   - Fine-tuner sur nos conditions spécifiques

5. **Hough Transform comme pré-filtre**
   - Détection de cercles classique (OpenCV) avant YOLO
   - Filtre les faux positifs non-ronds (murs, écrans)

### Debug workflow

```bash
# 1. Tester sur le Pixel, appuyer CAPTURE quand YOLO détecte un faux positif
# 2. Récupérer les captures
adb pull /storage/emulated/0/Android/data/com.musubi.eurio/files/Documents/eurio_debug/ ./debug_captures/

# 3. Analyser les frames + crops pour comprendre ce que YOLO voit
# frame_*.jpg = ce que la caméra voit
# crop_*.jpg = ce que YOLO a croppé et envoyé à ArcFace
# capture_*.txt = logs détaillés
```

---

## Priorité #2 : Compléter le catalogue Numista

Attendre le reset du quota API (mai 2026), puis :

```bash
# 1. Cacher les URLs pour les anciennes entrées
.venv/bin/python import_numista.py --backfill-urls

# 2. Télécharger les images manquantes (0 API calls)
.venv/bin/python import_numista.py --retry-images --retry-delay 2

# 3. Importer les pièces restantes
.venv/bin/python import_numista.py
```

---

## Priorité #3 : Réduire la taille du modèle YOLO

Le TFLite float32 fait 12 MB. Options :
- Float16 : 5.8 MB (devrait fonctionner, à tester)
- Résoudre le crash INT8 (GATHER_ND) — peut nécessiter une version différente de onnx2tf
- Explorer l'export sans onnx2tf (ex: `ai-edge-torch` direct, ou ultralytics avec TF 2.16)

---

## Fichiers clés

| Fichier | Description |
|---|---|
| `ml/train_detector.py` | Entraînement YOLOv8-nano |
| `ml/setup_detection_dataset.py` | Préparation dataset détection |
| `ml/train_embedder.py` | Entraînement ArcFace/classification |
| `ml/import_numista.py` | Import catalogue Numista |
| `ml/augment_synthetic.py` | Augmentation d'images |
| `ml/Taskfile.yml` | Toutes les commandes go-task |
| `app/.../ml/CoinDetector.kt` | Wrapper TFLite YOLO (output [1,5,2100]) |
| `app/.../ml/CoinAnalyzer.kt` | Pipeline 2 modèles + capture debug |
| `app/.../ml/CoinEmbedder.kt` | Wrapper TFLite ArcFace/classification |
| `app/.../ml/EmbeddingMatcher.kt` | Cosine similarity matching |
| `app/.../MainActivity.kt` | UI avec toggles + capture + bbox overlay |
| `docs/adr/003-yolo-tflite-export.md` | Comment exporter YOLO en TFLite |
| `docs/research/yolo-detection-findings.md` | Analyse des problèmes YOLO |

---

## Commandes utiles

```bash
cd ml

# Pipeline complète ArcFace (5 pièces)
go-task augment && go-task prepare && go-task train-arcface && go-task export && go-task validate && go-task embeddings && go-task deploy

# YOLO
go-task detect-setup          # Préparer dataset
go-task detect-train          # Entraîner + exporter

# Export YOLO TFLite manuellement (si ultralytics export fail)
.venv/bin/python -c "from ultralytics import YOLO; YOLO('output/detection/coin_detector/weights/best.pt').export(format='onnx', imgsz=320, simplify=True, nms=False)"
.venv/bin/python -m onnx2tf -i output/detection/coin_detector/weights/best.onnx -o output/detection/coin_detector/weights/tflite_no_nms
cp output/detection/coin_detector/weights/tflite_no_nms/best_float32.tflite output/coin_detector.tflite
cp output/coin_detector.tflite ../app/src/main/assets/models/

# Numista
.venv/bin/python import_numista.py --retry-images --retry-delay 2

# Debug captures
adb pull /storage/emulated/0/Android/data/com.musubi.eurio/files/Documents/eurio_debug/ ./debug_captures/
```
