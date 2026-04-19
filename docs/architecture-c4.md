# Architecture C4 — Eurio

> Diagrammes d'architecture au format Mermaid. Niveaux : System Context, Container, Component.

## 1. System Context

Vue d'ensemble : qui interagit avec quoi.

```mermaid
graph TB
    user["👤 Collecteur<br/>(utilisateur final)"]
    admin["👤 Administrateur<br/>(Raphaël)"]

    eurio["📱 Eurio App<br/>Android · Kotlin/Compose"]
    adminweb["🖥️ Admin Console<br/>Vue 3 · Vite"]
    mlapi["⚙️ ML API<br/>FastAPI · Python"]

    supabase["☁️ Supabase<br/>PostgreSQL + Storage + Auth"]
    numista["🌐 Numista API<br/>v3 · catalogue pièces"]

    user -->|"scanne des pièces"| eurio
    admin -->|"gère catalogue,<br/>lance entraînements"| adminweb

    adminweb -->|"CRUD coins, sets,<br/>embeddings"| supabase
    adminweb -->|"training, export,<br/>images augmentées"| mlapi

    mlapi -->|"seed embeddings,<br/>query coins"| supabase
    mlapi -->|"fetch images,<br/>metadata"| numista

    eurio -.->|"offline-first<br/>(snapshot packagé)"| supabase

    style eurio fill:#1A1B4B,color:#fff
    style adminweb fill:#C8A864,color:#1A1B4B
    style mlapi fill:#2FA971,color:#fff
    style supabase fill:#3ECF8E,color:#fff
    style numista fill:#6366f1,color:#fff
```

## 2. Container Diagram

Les briques techniques et leurs connexions.

```mermaid
graph TB
    subgraph "Poste développeur (Mac / Linux)"
        adminweb["Admin Web<br/>Vue 3 + Vite<br/>:5173"]
        mlapi["ML API<br/>FastAPI + uvicorn<br/>:8042"]
        mlscripts["ML Scripts<br/>Python · PyTorch<br/>train, augment, export"]
        datasets["Datasets<br/>ml/datasets/{numista_id}/<br/>images sources + augmentées"]
        checkpoints["Checkpoints<br/>ml/checkpoints/<br/>best_model.pth"]
        output["Output<br/>ml/output/<br/>TFLite + embeddings"]
    end

    subgraph "Supabase Cloud"
        db["PostgreSQL<br/>coins, coin_embeddings,<br/>sets, set_members,<br/>coin_series"]
        storage["Storage<br/>coin-images bucket<br/>WebP obverse/reverse"]
        auth["Auth<br/>Magic link + RLS<br/>role: admin"]
    end

    subgraph "Android Device"
        app["Eurio App<br/>Kotlin · Compose · Room"]
        tflite["TFLite Runtime<br/>eurio_embedder_v1.tflite"]
        yolo["YOLO Detector<br/>coin_detector.tflite"]
        room["Room DB<br/>coins, vault, sets"]
        assets["Assets<br/>catalog_snapshot.json<br/>coin_embeddings.json<br/>model_meta.json"]
    end

    numista["Numista API v3"]

    %% Admin Web connections
    adminweb -->|"PostgREST<br/>anon/service key"| db
    adminweb -->|"HTTP<br/>train, images, export"| mlapi

    %% ML API connections
    mlapi -->|"subprocess"| mlscripts
    mlapi -->|"FileResponse"| datasets
    mlapi -->|"PostgREST<br/>service key"| db
    mlscripts -->|"read/write"| datasets
    mlscripts -->|"read/write"| checkpoints
    mlscripts -->|"write"| output
    mlscripts -->|"httpx<br/>fetch types"| numista
    mlscripts -->|"httpx<br/>upload images"| storage

    %% Deploy flow
    output -.->|"go-task deploy<br/>(copie manuelle)"| assets

    %% Android
    app --> tflite
    app --> yolo
    app --> room
    assets -->|"bootstrap<br/>au démarrage"| room

    style adminweb fill:#C8A864,color:#1A1B4B
    style mlapi fill:#2FA971,color:#fff
    style app fill:#1A1B4B,color:#fff
    style db fill:#3ECF8E,color:#fff
```

## 3. Component — Pipeline ML

Le flux de données du training jusqu'au déploiement Android.

```mermaid
graph LR
    subgraph "Sources"
        numista_img["Image Numista<br/>obverse.jpg<br/>(scan studio)"]
        real_photos["Photos réelles<br/>003.jpg, 005.jpg...<br/>(optionnel)"]
    end

    subgraph "Augmentation"
        augment["augment_synthetic.py<br/>rotation 360°<br/>backgrounds aléatoires<br/>color jitter, blur<br/>masque circulaire"]
        aug_imgs["augmented/<br/>aug_0001.jpg<br/>...aug_0050.jpg"]
    end

    subgraph "Training"
        prepare["prepare_dataset.py<br/>split train/val/test<br/>(classes avec augmented/ only)"]
        train["train_embedder.py<br/>--mode arcface<br/>MobileNetV3-Small<br/>→ 256-dim embeddings"]
        model["best_model.pth<br/>poids PyTorch"]
    end

    subgraph "Post-training"
        compute["compute_embeddings.py<br/>centroïdes par classe<br/>(moyenne L2-norm)"]
        export["export_tflite.py<br/>PyTorch → TFLite<br/>via litert_torch"]
        validate["validate_export.py<br/>cosine sim > 0.99<br/>PyTorch vs TFLite"]
        seed["seed_supabase.py<br/>numista_id → eurio_id<br/>upsert coin_embeddings"]
    end

    subgraph "Artefacts"
        tflite["eurio_embedder_v1.tflite<br/>4.2 MB"]
        emb_json["coin_embeddings.json<br/>centroïdes par classe"]
        meta["model_meta.json<br/>classes, mode, dim"]
    end

    subgraph "Android"
        assets["app-android/assets/<br/>models/ + data/"]
        matcher["EmbeddingMatcher<br/>cosine similarity<br/>top-K matching"]
    end

    numista_img --> augment
    real_photos --> augment
    augment --> aug_imgs
    aug_imgs --> prepare
    numista_img --> prepare
    real_photos --> prepare
    prepare --> train
    train --> model
    model --> compute
    model --> export
    compute --> emb_json
    export --> tflite
    tflite --> validate
    validate -.->|"OK"| tflite
    compute --> seed
    seed -.->|"Supabase<br/>coin_embeddings"| seed

    tflite -->|"go-task deploy"| assets
    emb_json -->|"go-task deploy"| assets
    meta -->|"go-task deploy"| assets
    assets --> matcher

    style augment fill:#C8A864,color:#1A1B4B
    style train fill:#1A1B4B,color:#fff
    style seed fill:#3ECF8E,color:#fff
    style tflite fill:#2FA971,color:#fff
```

## 4. Component — Scan Pipeline (Android)

Ce qui se passe quand l'utilisateur pointe sa caméra sur une pièce.

```mermaid
graph TB
    camera["📷 CameraX<br/>ImageAnalysis<br/>frame toutes les 400ms"]

    subgraph "CoinAnalyzer"
        bitmap["imageProxyToBitmap<br/>YUV420 → Bitmap<br/>+ rotation correction"]

        subgraph "Stage 1 — Détection"
            yolo["CoinDetector (YOLO)<br/>320×320 letterbox<br/>conf > 0.40, NMS IoU 0.45"]
            hough["OpenCV Hough<br/>GaussianBlur + HoughCircles<br/>rayon 8-30% du frame"]
            merge["Merge IoU dedup<br/>YOLO prioritaire<br/>cap 5 candidats"]
        end

        subgraph "Stage 2 — Reranking"
            crop["Crop candidats<br/>+10% padding YOLO<br/>+25% padding Hough"]
            embed["CoinRecognizer<br/>MobileNetV3-Small<br/>224×224 → 256-dim"]
            match["EmbeddingMatcher<br/>cosine vs centroïdes<br/>top-3 par candidat"]
            decide["Décision<br/>top1 > 0.55 accept seul<br/>OU spread > 0.08"]
        end
    end

    consensus["ConsensusBuffer<br/>fenêtre 5 frames<br/>seuil 3/5 sticky"]

    subgraph "UI States"
        idle["Idle<br/>guide utilisateur"]
        detecting["Detecting<br/>animation analyse"]
        accepted["Accepted<br/>carte résultat<br/>+ ajouter au coffre"]
    end

    camera --> bitmap
    bitmap --> yolo
    bitmap --> hough
    yolo --> merge
    hough --> merge
    merge --> crop
    crop --> embed
    embed --> match
    match --> decide
    decide --> consensus
    consensus -->|"première détection"| detecting
    consensus -->|"consensus atteint"| accepted
    consensus -->|"4+ miss consécutifs"| idle

    style yolo fill:#1A1B4B,color:#fff
    style embed fill:#C8A864,color:#1A1B4B
    style consensus fill:#2FA971,color:#fff
```

## 5. Component — Admin Console

Les pages et leurs sources de données.

```mermaid
graph TB
    subgraph "Admin Web (:5173)"
        subgraph "Pages"
            coins["/coins<br/>Référentiel pièces<br/>grille + filtres"]
            coindetail["/coins/:id<br/>Détail pièce<br/>images + metadata"]
            sets["/sets<br/>Sets éditoriaux<br/>CRUD + DSL criteria"]
            training["/training<br/>Pipeline training<br/>queue + runs + export"]
            audit["/audit<br/>Audit log"]
            parity["/parity<br/>Proto ↔ Android"]
        end
    end

    subgraph "Supabase"
        db_coins["coins"]
        db_embeddings["coin_embeddings"]
        db_sets["sets + set_members"]
        db_audit["sets_audit"]
    end

    subgraph "ML API (:8042)"
        health["/health"]
        train_api["/train/*"]
        images["/images/*"]
        export["/export/*"]
    end

    coins -->|"select *"| db_coins
    coins -->|"select eurio_id"| db_embeddings
    coindetail -->|"select *"| db_coins
    coindetail -->|"select model_version"| db_embeddings
    sets -->|"CRUD"| db_sets
    audit -->|"select *"| db_audit

    coins -->|"POST /train"| train_api
    coindetail -->|"POST /train"| train_api

    training -->|"GET /health"| health
    training -->|"GET/POST /train/*"| train_api
    training -->|"GET /images/*"| images
    training -->|"POST /export/*"| export

    style coins fill:#C8A864,color:#1A1B4B
    style training fill:#2FA971,color:#fff
```

## 6. Deployment — Commandes go-task

```mermaid
graph LR
    subgraph "ML (cd ml/)"
        augment["go-task augment"]
        prepare["go-task prepare"]
        train_arc["go-task train-arcface"]
        embeddings["go-task embeddings"]
        export_tf["go-task export"]
        validate_tf["go-task validate"]
        deploy_assets["go-task deploy"]
        seed_sb["go-task seed"]
        api["go-task api<br/>:8042"]
    end

    subgraph "Android"
        build["go-task android:build"]
        install["go-task android:install"]
        run["go-task android:run"]
        logs["go-task android:logs"]
        snapshot["go-task android:snapshot"]
    end

    subgraph "Tokens"
        gen["go-task tokens:generate"]
    end

    augment --> prepare --> train_arc --> embeddings
    embeddings --> export_tf --> validate_tf
    embeddings --> seed_sb
    validate_tf --> deploy_assets --> build --> install --> run

    style api fill:#2FA971,color:#fff
    style run fill:#1A1B4B,color:#fff
```

## 7. Data Flow — Du scan Numista au scan utilisateur

```mermaid
sequenceDiagram
    participant N as Numista API
    participant ML as ML Scripts
    participant DS as Datasets (local)
    participant PT as PyTorch
    participant TF as TFLite
    participant SB as Supabase
    participant APK as Android APK
    participant U as Utilisateur

    Note over ML,N: Phase 1 — Collecte
    ML->>N: GET /types/{id} (image obverse)
    N-->>ML: image URL
    ML->>DS: save obverse.jpg

    Note over ML,DS: Phase 2 — Augmentation
    ML->>DS: augment_synthetic.py
    DS-->>DS: 50 variantes (rotation, bg, jitter)

    Note over PT,DS: Phase 3 — Entraînement
    ML->>DS: prepare_dataset.py (split)
    ML->>PT: train_embedder.py --mode arcface
    PT-->>PT: best_model.pth

    Note over PT,TF: Phase 4 — Export
    ML->>PT: compute_embeddings.py
    PT-->>ML: coin_embeddings.json (centroïdes)
    ML->>TF: export_tflite.py
    PT-->>TF: eurio_embedder_v1.tflite
    ML->>TF: validate_export.py (cos > 0.99)

    Note over SB,TF: Phase 5 — Déploiement
    ML->>SB: seed_supabase.py (upsert embeddings)
    ML->>APK: go-task deploy (copie assets)
    ML->>APK: go-task android:run (rebuild)

    Note over U,APK: Phase 6 — Utilisation
    U->>APK: pointe caméra sur pièce
    APK->>APK: YOLO detect + Hough
    APK->>APK: TFLite embed (256-dim)
    APK->>APK: cosine match vs centroïdes
    APK-->>U: "1€ Italie — Homme de Vitruve"
```
