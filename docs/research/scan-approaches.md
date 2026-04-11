# Scan de pièces — Comparatif des approches

> Recherche effectuée en avril 2026. Décision prise : **embedding on-device via MobileNetV3-Small**.

---

## 1. Feature Matching classique (ORB / SIFT / SURF)

**Principe** : Extraire des points d'intérêt sur l'image scannée et les comparer à un index de référence.

| Critère | Évaluation |
|---|---|
| Précision sur pièces | ~60-70% — insuffisant |
| Performance mobile | ORB rapide, SIFT/SURF lents |
| Robustesse reflets/usure | Très faible |
| Complexité d'intégration RN | Élevée (bridge C++ via OpenCV) |
| Coût | 0€ |

**Pourquoi on ne retient pas cette approche** :
- Les pièces sont rondes, réfléchissantes, souvent usées — les conditions exactes où le feature matching échoue
- La rotation symétrique des pièces crée des faux positifs
- L'intégration OpenCV complète dans React Native est plus complexe que TFLite
- C'est paradoxalement **plus de travail pour un résultat inférieur** au ML

**Usage retenu** : Uniquement pour la **détection de cercle** (Hough Transform) en preprocessing — détecter qu'il y a une pièce dans le cadre et la cropper.

---

## 2. Classification on-device (MobileNetV3 + TFLite)

**Principe** : Fine-tuner un réseau pré-entraîné pour classifier les pièces en N classes.

| Critère | Évaluation |
|---|---|
| Précision | 87-95% selon le modèle et le dataset |
| Performance mobile | 5-12ms sur Pixel 9a |
| Taille modèle | 2.5-5 MB |
| Complexité d'intégration RN | Moyenne (react-native-fast-tflite) |
| Coût | 0€ (inférence on-device) |

### Modèles candidats

| Modèle | Taille | Inférence (Pixel 9a) | Précision estimée |
|---|---|---|---|
| MobileNetV3-Small | ~2.5 MB | ~5ms | 87-93% |
| MobileNetV3-Large | ~5.5 MB | ~8ms | 90-95% |
| EfficientNet-Lite0 | ~4.5 MB | ~10-12ms | 92-95% |
| YOLOv8-Nano | ~6 MB | ~15ms | 90%+ (détection + classification) |

**Limitation majeure** : ajouter une nouvelle pièce = re-trainer tout le modèle + mise à jour de l'app. Incompatible avec l'objectif Day Zero pour les nouvelles commémoratives.

---

## 3. Embedding matching on-device (approche retenue)

**Principe** : Utiliser MobileNetV3 comme **extracteur de features** (pas comme classifieur). Comparer l'embedding de la pièce scannée avec une base d'embeddings de référence.

| Critère | Évaluation |
|---|---|
| Précision | 85-93% (comparable au classifieur) |
| Performance mobile | ~5ms inférence + ~2ms comparaison |
| Taille modèle | ~2.5 MB (modèle) + ~500 KB (base embeddings) |
| Ajout nouvelle pièce | 1 image → 1 embedding → push JSON via API |
| Re-training nécessaire | Non (sauf pour améliorer la qualité globale) |
| Coût | 0€ |

### Comment ça marche

```
Scan utilisateur (Kotlin natif)
  → CameraX ImageAnalysis.Analyzer
  → Center crop + resize 224×224 + normalize
  → TFLite Interpreter (SDK natif, zéro bridge)
  → MobileNetV3 feature extractor → embedding 256-dim
  → Cosine similarity vs base d'embeddings locale
  → Match : similarity > 0.90
  → Suggestions : similarity 0.75-0.90
  → Non identifié : similarity < 0.75
```

### Pourquoi c'est mieux que la classification

1. **Nouvelles pièces sans re-training** — une image officielle suffit pour calculer un embedding et l'ajouter à la base
2. **Mise à jour dynamique** — la base d'embeddings est un fichier JSON synchronisé via l'API, pas un modèle dans l'APK
3. **Scalabilité** — passer de 500 à 5000 pièces ne change rien au modèle, juste la taille du JSON
4. **Day Zero automatisable** — cron job détecte nouvelle pièce sur Numista → calcule embedding → push dans Supabase → app sync

### Fine-tuning avec Triplet Loss

Le modèle MobileNetV3 pré-entraîné sur ImageNet sait "voir" mais pas spécifiquement les pièces. Le fine-tuning avec triplet loss lui apprend à :
- Rapprocher les embeddings de photos d'une même pièce (même design, éclairages différents)
- Éloigner les embeddings de pièces différentes (même taille mais design différent)

```
Triplet : (anchor, positive, negative)
  anchor   = photo d'une 2€ Allemagne 2006
  positive = autre photo de la même pièce (angle/éclairage différent)
  negative = photo d'une 2€ France 2012

Loss = max(0, d(anchor, positive) - d(anchor, negative) + margin)
```

Entraînement : ~30 min sur 1080 Ti, ~1h sur Mac M4.

---

## 4. Cloud — non retenu pour l'inférence

| Service | Coût/1K inférences | Note |
|---|---|---|
| Google Vertex AI | ~1.50€ | Solide mais coûteux à l'échelle |
| Azure Custom Vision | ~2.00€ | En retrait prévu 2028 |
| AWS Rekognition | ~4€/h (always-on) | Modèle de prix inadapté au mobile |
| Roboflow hosted | Free tier 1K/mois | Utile pour le prototypage uniquement |

### Break-even

| Volume mensuel | Coût cloud (Google) | Coût on-device |
|---|---|---|
| 10K scans | 15€/mois | 0€ |
| 100K scans | 150€/mois | 0€ |
| 1M scans | 1 500€/mois | 0€ |

**Décision** : on-device pour toute l'inférence. Le modèle freemium ne supporte pas un coût par scan.

---

## 5. Décision finale

**Architecture retenue** :
- **App** : Kotlin natif + Jetpack Compose (accès direct TFLite SDK + CameraX, zéro bridge)
- **Preprocessing** : Center crop guidé (MVP) puis circle detection améliorée
- **Feature extraction** : MobileNetV3-Small fine-tuné avec triplet loss, exporté TFLite INT8
- **Matching** : Cosine similarity vs base d'embeddings synchronisée via Supabase
- **Ajout de pièces** : automatique via cron Numista, aucun re-training nécessaire
- **Backend** : Supabase (zéro VPS, zéro Fastify)

**Ce qui est écarté** :
- React Native Expo (react-native-fast-tflite trop fragile, 91 issues ouvertes, crashes Android)
- ORB/SIFT matching pour la classification
- Inférence cloud
- Classification softmax (trop rigide pour les nouvelles pièces)
- Fastify / VPS (remplacé par Supabase Edge Functions)
