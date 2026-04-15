# Eurio ML Pipeline

Train a coin embedding model (MobileNetV3-Small), export to TFLite, and deploy to the Android app.

## Prerequisites

- Nix devShell active (provides Python 3.12, PyTorch, go-task)
- `.venv` with extra deps: `uv pip install --python .venv/bin/python pytorch-metric-learning torchvision matplotlib scikit-learn`
- `../.env` with `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `NUMISTA_API_KEY`

## Quick start

```bash
cd ml/
go-task          # runs the full pipeline
```

## Pipeline steps

All steps can be run individually with `go-task <step>`. Dependencies are handled automatically.

### 1. `prepare` — Split dataset

Resizes raw images (3000x4000) to 256x256 and splits 70/20/10 into train/val/test.

```bash
go-task prepare
```

**Input:** `datasets/<class>/` directories with JPEGs
**Output:** `datasets/eurio-poc/{train,val,test}/<class>/`

### 2. `train` — Train embedding model

MobileNetV3-Small backbone + 256-dim projection head, trained with triplet loss and hard mining.

```bash
go-task train
```

**Output:** `checkpoints/best_model.pth`, `checkpoints/training_log.json`
**Expected:** Recall@1 should improve over epochs. With 5 distinct classes, >60% is achievable.

### 3. `evaluate` — Test set metrics

```bash
go-task evaluate
```

**Output:** Recall@1, Recall@3, per-class accuracy, per-image predictions.

### 4. `visualize` — t-SNE and training curves

```bash
go-task visualize
```

**Output:** `output/tsne_plot.png`, `output/training_curves.png`
**Expected:** Clusters should be visually separated in t-SNE plot.

### 5. `export` — Convert to TFLite

```bash
go-task export
```

**Output:** `output/eurio_embedder_v1.tflite`
**Expected:** < 5 MB (typically ~4.2 MB).

### 6. `validate` — TFLite parity check

```bash
go-task validate
```

**Expected:** Cosine similarity > 0.99 for all test images.

### 7. `embeddings` — Reference embeddings

Computes a centroid embedding per coin class (average of all images, L2-normalized).

```bash
go-task embeddings
```

**Output:** `output/embeddings_v1.json` (full metadata), `output/coin_embeddings.json` (flat, for Android)

### 8. `deploy` — Copy to Android assets

```bash
go-task deploy
```

**Copies to:** `app-android/src/main/assets/models/` and `app-android/src/main/assets/data/`

### 9. `seed` — Populate Supabase

Fetches coin metadata from Numista API, inserts into `coins` table, then inserts embeddings into `coin_embeddings`.

```bash
go-task seed
```

**Requires:** `SUPABASE_SERVICE_ROLE_KEY` in `.env`
**Idempotent:** Uses upsert, safe to re-run.

## Adding a new coin

```bash
go-task add-coin    # prints the guide
```

1. Create a directory: `datasets/<face>_<country>_<year>_<name>/`
   - Example: `datasets/2eur_france_2022_jeux_olympiques/`
2. Add photos (minimum 10, ideally 15+, varied lighting/angles/backgrounds)
3. Find the Numista type ID on [numista.com](https://numista.com) (number in the URL)
4. Add an entry in `datasets/coin_catalog.json`
5. Run `go-task` to re-run the full pipeline

## Utilities

```bash
go-task clean       # remove checkpoints, output, split dataset
```

## File structure

```
ml/
  datasets/
    coin_catalog.json       # Source of truth: dir name → Numista ID + metadata
    1eur_italy_2006_vitruve/    # Raw photos
    ...
    eurio-poc/              # Generated train/val/test split
  checkpoints/
    best_model.pth          # Best PyTorch checkpoint
    training_log.json       # Per-epoch metrics
  output/
    eurio_embedder_v1.tflite
    embeddings_v1.json
    coin_embeddings.json
    tsne_plot.png
    training_curves.png
  prepare_dataset.py
  train_embedder.py
  evaluate.py
  visualize.py
  export_tflite.py
  validate_export.py
  compute_embeddings.py
  seed_supabase.py
  Taskfile.yml
```
