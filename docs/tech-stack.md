# Tech Stack — Eurio

> Document consolidé des choix technologiques.  
> Mis à jour après analyse comparative (avril 2026) — passage de React Native Expo à **Kotlin natif**.

---

## Pourquoi Kotlin natif

La killer feature d'Eurio est le scan on-device. Le scan = caméra + preprocessing + inférence LiteRT + affichage. C'est 70% de l'app.

En Kotlin natif :
- **LiteRT** (ex-TFLite) est un SDK first-party Google — zéro wrapper, zéro bridge, zéro plugin custom
- **CameraX** est l'API caméra officielle Android — rock-solid, bien documentée
- **Jetpack Compose** est le framework UI moderne d'Android — déclaratif, réactif, performant
- **Zéro overhead** entre l'inférence ML et l'UI — tout tourne dans le même runtime

En React Native, le même pipeline passe par : JS → Worklet → C++ bridge → Java → TFLite → retour. Chaque couche est un point de failure. `react-native-fast-tflite` a 91 issues ouvertes et des rapports de crashes Android. De plus, les anciennes libs TFLite ne sont pas alignées 16KB (incompatibles Android 15+).

### Et iOS plus tard ?

**Compose Multiplatform** (par JetBrains) est stable pour iOS depuis mai 2025. Netflix, McDonald's, BiliBili l'utilisent en production. Quand Eurio sera prêt pour iOS :
- La logique métier (collection, gamification, prix) sera partagée via KMP
- Le code ML sera platform-specific (LiteRT Android / CoreML iOS)
- L'UI sera partagée via Compose Multiplatform

Ce n'est pas le focus du MVP. On construit Android d'abord, on porte ensuite.

---

## Stack applicatif

| Couche | Technologie | Justification |
|---|---|---|
| **App mobile** | Kotlin + Jetpack Compose | Natif Android, performance optimale, UI moderne |
| **Caméra** | CameraX (AndroidX) | API officielle Google, stable, gestion lifecycle automatique |
| **ML on-device** | LiteRT 1.4.2 (ex-TFLite) | SDK natif Google, GPU/NNAPI delegates, 16KB-aligned, zéro overhead |
| **Modèle ML** | MobileNetV3-Small fine-tuné, TFLite INT8 | ~2.5 MB, <5ms sur Pixel 9a, embedding extraction |
| **Training ML** | PyTorch + pytorch-metric-learning | Triplet loss, hard mining, export TFLite via ai-edge-torch (litert-torch) |
| **Backend** | Supabase (PostgreSQL + Auth + Storage + Edge Functions) | Zéro infrastructure perso, free tier généreux |
| **API prix** | eBay Browse API | Prix de marché réels, transactions datées |
| **API catalogue** | Numista API | Référence du domaine numismatique euro |
| **Stockage local** | Room (SQLite Android) | ORM officiel Android, performant, type-safe |
| **Graphes** | MPAndroidChart ou Vico | Sparklines prix, graphes historiques |
| **Navigation** | Jetpack Navigation Compose | Standard officiel Android |
| **DI** | Koin ou Hilt | Injection de dépendances |
| **HTTP client** | Ktor Client ou Retrofit | Appels API Supabase, Numista, eBay |

---

## Architecture de l'app

```
app/
├── data/
│   ├── local/              # Room DB (cache, collection)
│   ├── remote/             # Supabase client, API calls
│   └── repository/         # Sources de données unifiées
├── domain/
│   ├── model/              # Coin, Collection, Achievement, PriceHistory
│   └── usecase/            # ScanCoin, AddToVault, GetPriceHistory
├── ml/
│   ├── CoinEmbedder.kt     # Chargement modèle TFLite + inférence
│   ├── EmbeddingMatcher.kt # Cosine similarity vs base locale
│   └── CoinDetector.kt     # CameraX analyzer + preprocessing
├── ui/
│   ├── scan/               # Écran caméra + overlay + résultat
│   ├── vault/              # Le Coffre (collection)
│   ├── explore/            # Catalogue, recherche, tendances
│   ├── profile/            # Achievements, stats, settings
│   ├── coin/               # Fiche pièce détaillée
│   └── onboarding/         # Onboarding 3 écrans
└── di/                     # Modules d'injection de dépendances
```

---

## Architecture ML — Pipeline de scan

```
┌─ ON-DEVICE (Kotlin) ───────────────────────────────────┐
│                                                         │
│  CameraX ImageAnalysis → Analyzer callback              │
│       ↓                                                 │
│  Preprocessing (Kotlin) :                               │
│    Center crop + Resize 224×224 + Normalize              │
│       ↓                                                 │
│  LiteRT Interpreter (SDK natif, ex-TFLite)                         │
│    MobileNetV3-Small INT8 → Embedding 256-dim           │
│       ↓                                                 │
│  Cosine similarity vs embeddings locaux                  │
│       ↓                                                 │
│  Résultat + score de confiance → UI via StateFlow       │
│                                                         │
└─────────────────────────────────────────────────────────┘

┌─ BACKEND (Supabase — zéro VPS) ────────────────────────┐
│                                                         │
│  PostgreSQL : catalogue, prix, embeddings, collections  │
│  Auth : comptes utilisateurs (optionnel MVP)            │
│  Storage : images de référence des pièces               │
│  Edge Functions : cron eBay/Numista, API enrichissement │
│  pg_cron : scheduling des jobs de mise à jour           │
│                                                         │
└─────────────────────────────────────────────────────────┘

┌─ TRAINING (local, hors app) ───────────────────────────┐
│                                                         │
│  Python + PyTorch + pytorch-metric-learning             │
│  Dataset : Kaggle + photos perso + augmentation         │
│  Triplet loss → MobileNetV3 feature extractor           │
│  Export : PyTorch → TFLite via ai-edge-torch (litert-torch)            │
│  Résultat : .tflite embarqué dans l'APK                │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## Environnement de développement

| Outil | Usage |
|---|---|
| **Mac M4** | Dev principal + training ML |
| **PC 1080 Ti** | Training ML (GPU CUDA, plus rapide) |
| **Google Pixel 9a** | Device de test Android |
| **Android Studio** | IDE principal (Kotlin + Compose) |

---

## Infrastructure — zéro VPS

| Besoin | Solution | Coût |
|---|---|---|
| Base de données | Supabase PostgreSQL | 0€ (free: 500 MB) |
| Auth | Supabase Auth | 0€ (free: 50K MAU) |
| Stockage fichiers | Supabase Storage | 0€ (free: 1 GB) |
| API / fonctions serveur | Supabase Edge Functions | 0€ (free: 500K invocations/mois) |
| Cron jobs | Supabase pg_cron + Edge Functions | 0€ |
| Scan ML | On-device (LiteRT) | 0€ |
| Training ML | Mac M4 / PC 1080 Ti | 0€ |
| **Total** | | **0€/mois** |

Passage au Pro Supabase (25$/mois) uniquement quand il y a de la traction.

---

## Décisions techniques clés

| Décision | Choix | Alternative écartée | Raison |
|---|---|---|---|
| Framework mobile | Kotlin + Jetpack Compose | React Native Expo | Accès natif TFLite/CameraX, zéro bridge overhead, scan = 70% de l'app |
| Inférence scan | On-device (LiteRT natif) | Cloud (Vertex AI) | Coût marginal 0€, offline, latence <10ms |
| Approche ML | Embedding matching | Classification softmax | Nouvelles pièces sans re-training, Day Zero auto |
| Backend | Supabase (full) | Fastify custom | Zéro infra perso, all-in-one, free tier |
| API backend | Supabase Edge Functions | Fastify sur VPS | Pas de serveur à maintenir |
| Cross-platform futur | Compose Multiplatform (KMP) | React Native | Même langage, UI partagée, ML platform-specific |
| BDD locale | Room | SQLite brut | Type-safe, migrations, coroutines |
