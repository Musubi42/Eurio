# Phase 0 — Setup & Prérequis

> Objectif : tout est installé, configuré et validé. L'app tourne sur le Pixel 9a. Les APIs sont accessibles. L'environnement ML est prêt pour l'entraînement. **Zéro code métier dans cette phase** — on valide que chaque brique fonctionne.

---

## 0.1 — Prérequis à valider AVANT de coder

### A. API Keys à obtenir

| API | Quoi faire | URL | Statut |
|---|---|---|---|
| **Numista** | Créer un compte dev, demander une API key | https://en.numista.com/api/ | [ ] |
| **eBay Browse API** | Créer un compte dev eBay, application OAuth, obtenir credentials | https://developer.ebay.com/ | [ ] |
| **Supabase** | Créer un projet, récupérer l'URL et la clé anon | https://supabase.com/dashboard | [ ] |

#### Test Numista API

```bash
# Tester que l'API répond (remplacer YOUR_API_KEY)
curl -H "Numista-API-Key: YOUR_API_KEY" \
  "https://api.numista.com/api/v3/types?q=2+euro+commemorative+germany&lang=en"
```

Résultat attendu : JSON avec une liste de pièces.

#### Test eBay Browse API

```bash
# 1. Obtenir un token OAuth (Application token)
curl -X POST "https://api.ebay.com/identity/v1/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "Authorization: Basic BASE64_CREDENTIALS" \
  -d "grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope"

# 2. Rechercher des ventes complétées
curl -H "Authorization: Bearer ACCESS_TOKEN" \
  "https://api.ebay.com/buy/browse/v1/item_summary/search?q=2+euro+commemorative+germany+2006&filter=buyingOptions:{FIXED_PRICE|AUCTION},conditions:{USED}"
```

Résultat attendu : JSON avec des items et des prix.

### B. Licences à vérifier

| Sujet | Action | Statut |
|---|---|---|
| **Images Numista** | Vérifier les conditions d'utilisation pour usage commercial. Si non autorisé, alternative : images ECB (libres de droits pour les designs standards) | [ ] |
| **Datasets Kaggle** | Vérifier la licence de chaque dataset (CC BY, CC0, etc.) | [ ] |
| **MobileNetV3 (PyTorch)** | Licence BSD — OK pour usage commercial | [x] |
| **LiteRT (ex-TFLite)** | Licence Apache 2.0 — OK pour usage commercial | [x] |

### C. Scope POC — 10 pièces

```
Commémoratives 2€ (faces uniques, plus faciles à distinguer) :
  1.  2€ Allemagne 2006 — Schleswig-Holstein (Holstentor)
  2.  2€ France 2012 — 10 ans de l'Euro
  3.  2€ Italie 2006 — JO Turin
  4.  2€ Espagne 2005 — Don Quichotte
  5.  2€ Finlande 2004 — Élargissement UE

Pièces courantes (face nationale) :
  6.  1€ France — Arbre
  7.  1€ Allemagne — Aigle fédéral
  8.  2€ Italie — Dante
  9.  50c Espagne — Cervantes
  10. 20c France — Semeuse
```

> Ajuster selon les pièces physiquement disponibles pour les photos.

---

## 0.2 — Setup Android Studio + Projet Kotlin

### Installation Android Studio

Télécharger depuis developer.android.com/studio et installer manuellement.

> **Note :** Android Studio n'est pas géré par le devShell Nix (IDE lourd avec ses propres SDK managers). Le JDK, Android SDK, Gradle et les outils CLI sont dans le `flake.nix`.

Au premier lancement :
1. Installer le SDK Android (API 35+)
2. Accepter toutes les licences SDK
3. Installer les NDK et CMake (nécessaires pour LiteRT natif)

### Créer le projet

Dans Android Studio :
1. **New Project** → **Empty Compose Activity**
2. Name : `Eurio`
3. Package : `com.musubi.eurio`
4. Language : **Kotlin**
5. Minimum SDK : **API 26 (Android 8.0)**
6. Build configuration language : **Kotlin DSL (build.gradle.kts)**

### Dépendances initiales (build.gradle.kts app)

```kotlin
dependencies {
    // Compose (déjà inclus par le template)
    implementation(platform("androidx.compose:compose-bom:2025.01.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose")

    // CameraX
    val cameraxVersion = "1.4.1"
    implementation("androidx.camera:camera-core:$cameraxVersion")
    implementation("androidx.camera:camera-camera2:$cameraxVersion")
    implementation("androidx.camera:camera-lifecycle:$cameraxVersion")
    implementation("androidx.camera:camera-view:$cameraxVersion")

    // LiteRT (ex-TFLite) — 16KB page-size compliant (voir ADR-001)
    implementation("com.google.ai.edge.litert:litert:1.4.2")
    implementation("com.google.ai.edge.litert:litert-support:1.4.2")
    implementation("com.google.ai.edge.litert:litert-gpu:1.4.2")
    implementation("com.google.ai.edge.litert:litert-gpu-api:1.4.2")

    // Room (SQLite)
    val roomVersion = "2.6.1"
    implementation("androidx.room:room-runtime:$roomVersion")
    implementation("androidx.room:room-ktx:$roomVersion")
    ksp("androidx.room:room-compiler:$roomVersion")

    // Supabase
    implementation(platform("io.github.jan-tennert.supabase:bom:3.1.1"))
    implementation("io.github.jan-tennert.supabase:postgrest-kt")
    implementation("io.github.jan-tennert.supabase:auth-kt")
    implementation("io.github.jan-tennert.supabase:storage-kt")
    implementation("io.ktor:ktor-client-okhttp:3.0.3")

    // Navigation
    implementation("androidx.navigation:navigation-compose:2.8.5")

    // JSON
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")

    // Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    // Koin (DI)
    implementation("io.insert-koin:koin-androidx-compose:4.0.0")
}
```

### Permissions Android (AndroidManifest.xml)

```xml
<uses-feature android:name="android.hardware.camera" android:required="true" />
<uses-permission android:name="android.permission.CAMERA" />
<uses-permission android:name="android.permission.INTERNET" />
```

---

## 0.3 — Déploiement sur le Pixel 9a

### Setup device

1. Sur le Pixel 9a : **Paramètres → À propos → taper 7x sur "Numéro de build"**
2. **Options développeur → Débogage USB → ON**
3. Brancher en USB au Mac
4. Accepter la popup "Autoriser le débogage USB" sur le téléphone

### Vérification

```bash
# Vérifier que le device est détecté
adb devices
# Doit afficher : XXXXXXX  device

# Depuis Android Studio : Run → Select Device → Pixel 9a
# Build et deploy l'app template
```

### Checklist premier déploiement

| Test | Résultat attendu | Statut |
|---|---|---|
| `adb devices` affiche le Pixel | Device listé | [ ] |
| Build Gradle sans erreur | BUILD SUCCESSFUL | [ ] |
| App s'ouvre sur le Pixel | Écran Compose "Hello World" | [ ] |
| Hot reload (Apply Changes) | Modification visible en ~2s | [ ] |

---

## 0.4 — Validation CameraX

Créer un écran de test minimaliste pour valider que CameraX fonctionne.

```kotlin
// Test rapide — à supprimer après validation
@Composable
fun CameraTestScreen() {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current

    AndroidView(
        factory = { ctx ->
            PreviewView(ctx).apply {
                val cameraProviderFuture = ProcessCameraProvider.getInstance(ctx)
                cameraProviderFuture.addListener({
                    val cameraProvider = cameraProviderFuture.get()
                    val preview = Preview.Builder().build().also {
                        it.surfaceProvider = surfaceProvider
                    }
                    cameraProvider.bindToLifecycle(
                        lifecycleOwner,
                        CameraSelector.DEFAULT_BACK_CAMERA,
                        preview
                    )
                }, ContextCompat.getMainExecutor(ctx))
            }
        }
    )
}
```

| Test | Résultat attendu | Statut |
|---|---|---|
| Permission caméra demandée | Popup Android "Autoriser Eurio à prendre des photos" | [ ] |
| Flux vidéo affiché | Prévisualisation caméra en temps réel | [ ] |
| Pas de crash en rotation | L'app survit à une rotation écran | [ ] |
| Retour arrière propre | La caméra est libérée | [ ] |

---

## 0.5 — Validation LiteRT

Tester que LiteRT charge et exécute un modèle dans l'app.

### Modèle de test

Télécharger un modèle MobileNetV3 pré-entraîné (ImageNet, pas encore fine-tuné) :

```bash
# Télécharger le modèle de test
curl -L -o mobilenet_v3_small.tflite \
  "https://storage.googleapis.com/mediapipe-models/image_classifier/efficientnet_lite0/float32/1/efficientnet_lite0.tflite"

# Le placer dans le projet
# → app-android/src/main/assets/models/test_model.tflite
```

### Code de test

```kotlin
// Test rapide — charger le modèle et vérifier qu'il tourne
fun testLiteRT(context: Context) {
    val model = FileUtil.loadMappedFile(context, "models/test_model.tflite")
    val interpreter = Interpreter(model)

    // Input : image 224×224×3 (float32)
    val input = ByteBuffer.allocateDirect(224 * 224 * 3 * 4)
    input.order(ByteOrder.nativeOrder())

    // Output : probabilities
    val output = Array(1) { FloatArray(1000) }

    interpreter.run(input, output)

    // Si on arrive ici sans crash, LiteRT fonctionne
    Log.d("Eurio", "LiteRT OK — output size: ${output[0].size}")
    interpreter.close()
}
```

| Test | Résultat attendu | Statut |
|---|---|---|
| Modèle chargé sans crash | Log "LiteRT OK" | [ ] |
| Inférence exécutée | Output de 1000 floats | [ ] |
| Temps d'inférence | < 50ms (log le temps) | [ ] |
| GPU delegate (optionnel) | Inférence plus rapide avec GPU | [ ] |

---

## 0.6 — Setup Supabase

### Créer le projet

1. Aller sur https://supabase.com/dashboard
2. **New Project** → Nom : `eurio` → Région : `eu-west-1` (Frankfurt)
3. Noter :
   - **Project URL** : `https://xxxxx.supabase.co`
   - **Anon Key** : `eyJhbGciOiJIUzI1NiIs...`
   - **Service Role Key** : (pour les cron jobs, à sécuriser)

### Créer les tables initiales

```sql
-- Catalogue de pièces
CREATE TABLE coins (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  numista_id INTEGER UNIQUE NOT NULL,
  name TEXT NOT NULL,
  country TEXT NOT NULL,
  year INTEGER,
  face_value DECIMAL(4,2) NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('circulation', 'commemorative')),
  mintage INTEGER,
  rarity TEXT CHECK (rarity IN ('common', 'uncommon', 'rare', 'very_rare')),
  image_obverse_url TEXT,
  image_reverse_url TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Embeddings pour le matching (synchronisés vers l'app)
CREATE TABLE coin_embeddings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  coin_id UUID REFERENCES coins(id) ON DELETE CASCADE,
  embedding FLOAT4[] NOT NULL,
  model_version TEXT NOT NULL DEFAULT 'v1',
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Historique de prix (rempli par cron eBay)
CREATE TABLE price_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  coin_id UUID REFERENCES coins(id) ON DELETE CASCADE,
  price_median DECIMAL(10,2),
  price_p25 DECIMAL(10,2),
  price_p75 DECIMAL(10,2),
  source TEXT NOT NULL DEFAULT 'ebay',
  recorded_at DATE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Collections utilisateur
CREATE TABLE user_collections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  coin_id UUID REFERENCES coins(id),
  scan_image_url TEXT,
  added_at TIMESTAMPTZ DEFAULT now(),
  value_at_addition DECIMAL(10,2)
);

-- Index pour les performances
CREATE INDEX idx_coins_numista ON coins(numista_id);
CREATE INDEX idx_price_history_coin ON price_history(coin_id, recorded_at DESC);
CREATE INDEX idx_user_collections_user ON user_collections(user_id);
```

### Test de connexion depuis l'app

```kotlin
// Test rapide — vérifier la connexion Supabase
val supabase = createSupabaseClient(
    supabaseUrl = "https://xxxxx.supabase.co",
    supabaseKey = "eyJhbGciOiJIUzI1NiIs..."
) {
    install(Postgrest)
}

// Tester une requête
suspend fun testSupabase() {
    val coins = supabase.from("coins").select().decodeList<CoinDto>()
    Log.d("Eurio", "Supabase OK — ${coins.size} coins")
}
```

| Test | Résultat attendu | Statut |
|---|---|---|
| Projet créé | Dashboard accessible | [ ] |
| Tables créées | 4 tables visibles dans le SQL editor | [ ] |
| Connexion depuis l'app | Log "Supabase OK" | [ ] |
| Insert + Select | Round-trip fonctionnel | [ ] |

---

## 0.7 — Setup environnement ML (Python)

### Ce qu'il faut installer

L'entraînement du modèle se fait en **Python + PyTorch**, sur ton Mac M4 ou ton PC 1080 Ti. Ce n'est pas du LLM — pas besoin d'Ollama ni de plateforme externe. C'est un script Python classique qui tourne en local.

Tout est géré par le **Nix devShell** (`flake.nix`) — voir [ADR-002](../adr/002-nix-devshell.md).

```bash
# Entrer dans le devShell (automatique avec direnv, sinon :)
nix develop

# Packages fournis par Nix (Python 3.12) :
#   torch, torchvision, pillow, numpy, matplotlib, scikit-learn, tqdm, uv

# Package pip-only (pas dans nixpkgs) — installé via uv dans un venv local :
cd ml/
uv venv .venv
source .venv/bin/activate
uv pip install ai-edge-torch   # Note : deprecated, renommé litert-torch
```

### Pas besoin de plateforme externe

| Outil | Nécessaire ? | Pourquoi |
|---|---|---|
| Ollama | **Non** | C'est pour les LLM. On entraîne un CNN, pas un modèle de langage |
| Roboflow | **Non** (backup) | On entraîne en local. Roboflow pourrait servir pour l'augmentation de données si besoin |
| Google Colab | **Non** | Tu as un GPU (1080 Ti). Colab = backup si problème hardware |
| HuggingFace | **Non** | On n'utilise pas de modèle pré-entraîné HF. MobileNetV3 vient de torchvision |
| Weights & Biases | **Optionnel** | Pour tracker les expériences d'entraînement. Pas nécessaire pour le MVP |

### Validation du setup ML

```bash
nix develop --command python3 -c "
import torch
import torchvision.models as models

# Vérifier le device
if torch.cuda.is_available():
    print(f'GPU CUDA: {torch.cuda.get_device_name(0)}')
elif torch.backends.mps.is_available():
    print('GPU Apple MPS (Mac M4)')
else:
    print('CPU only')

# Charger MobileNetV3-Small
model = models.mobilenet_v3_small(weights='IMAGENET1K_V1')
print(f'MobileNetV3-Small chargé — {sum(p.numel() for p in model.parameters())/1e6:.1f}M paramètres')

# Test forward pass
x = torch.randn(1, 3, 224, 224)
out = model(x)
print(f'Output shape: {out.shape}')
print('Setup ML OK')
"
```

| Test | Résultat attendu | Statut |
|---|---|---|
| PyTorch installé | `import torch` sans erreur | [ ] |
| GPU détecté | "GPU CUDA: GTX 1080 Ti" ou "GPU Apple MPS" | [ ] |
| MobileNetV3 chargé | "2.5M paramètres" | [ ] |
| Forward pass OK | "Output shape: torch.Size([1, 1000])" | [ ] |
| ai-edge-torch installé | `import ai_edge_torch` sans erreur (venv `ml/.venv/`) | [ ] |

---

## 0.8 — Téléchargement des datasets

```bash
# Les datasets sont dans le repo : ml/datasets/

# Option 1 : Kaggle (nécessite kaggle CLI)
nix develop --command bash -c '
  uv pip install --system kaggle 2>/dev/null || pip install kaggle
  # Configurer ~/.kaggle/kaggle.json avec ton API token Kaggle
  kaggle datasets download -d janstaffa/euro-coins-dataset -p ml/datasets/
  unzip ml/datasets/euro-coins-dataset.zip -d ml/datasets/kaggle-euro
'

# Option 2 : Git clone des repos GitHub
git clone https://github.com/kaa/coins-dataset.git ml/datasets/kaa-coins
git clone https://github.com/iambarge/CV-coins-project.git ml/datasets/cv-coins

# Vérifier le contenu
ls ml/datasets/
```

| Test | Résultat attendu | Statut |
|---|---|---|
| Dataset Kaggle téléchargé | Dossier avec images de pièces | [ ] |
| Images exploitables pour les 10 classes POC | Au moins 10-20 images/classe | [ ] |
| Photos perso prises | 20-30 photos par pièce disponible | [ ] |

---

## 0.9 — Structure du projet final

```
Eurio/                              # Ce repo
├── PRD.md                          # Product Requirements Document
├── docs/
│   ├── tech-stack.md
│   ├── research/
│   │   ├── scan-approaches.md
│   │   ├── training-pipeline.md
│   │   ├── embedding-vs-classification.md
│   │   └── cloud-vs-ondevice-costs.md
│   └── phases/
│       ├── phase-0-setup.md        # ← Tu es ici
│       ├── phase-1-data.md
│       ├── phase-2-scan.md
│       ├── phase-3-coffre.md
│       ├── phase-4-gamification.md
│       └── phase-5-polish-beta.md
├── flake.nix                       # Nix devShell (JDK, SDK, Python, etc.)
├── .envrc                          # direnv → use flake
├── app-android/                    # Projet Android (Kotlin + Compose)
│   └── ... (créé par Android Studio)
└── ml/                             # Scripts d'entraînement Python
    ├── train_embedder.py
    ├── compute_embeddings.py
    ├── export_tflite.py
    ├── evaluate.py
    ├── .venv/                      # venv uv pour ai-edge-torch
    └── datasets/                   # Images d'entraînement (gitignored)
```

---

## 0.10 — Checklist Phase 0 complète

### APIs & Comptes

- [ ] API key Numista obtenue et testée
- [ ] Credentials eBay Browse API obtenus et testés
- [ ] Projet Supabase créé (tables, connexion testée)

### Licences

- [ ] Licence images Numista vérifiée
- [ ] Licences datasets Kaggle vérifiées

### Android

- [ ] Android Studio installé et configuré
- [ ] Projet Kotlin + Compose créé
- [ ] Dépendances ajoutées (CameraX, LiteRT, Room, Supabase, etc.)
- [ ] App déployée sur le Pixel 9a
- [ ] CameraX : flux vidéo affiché
- [ ] LiteRT : modèle de test chargé et exécuté
- [ ] Supabase : connexion testée depuis l'app

### ML

- [ ] Nix devShell fonctionnel (Python 3.12 + PyTorch + GPU MPS/CUDA)
- [ ] MobileNetV3-Small chargé et testé
- [ ] ai-edge-torch installé (venv ml/.venv/)
- [ ] Datasets téléchargés
- [ ] Photos perso des pièces POC prises

---

## Durée estimée

**3-5 jours** en comptant :
- Les délais d'obtention des API keys (~1-2 jours pour eBay)
- Le setup Android Studio + résolution de problèmes de build
- La prise de photos des pièces
