# Scan — ML pipeline

> Cette page résume le pipeline ML utilisé par le scan et pointe vers les docs de recherche existantes. Ne pas dupliquer ici ce qui est déjà dans `docs/research/` ou dans les mémoires Claude.

---

## Vue d'ensemble

```
Frame CameraX (ARGB_8888)
  ↓
  [CoinDetector] — app/src/main/java/com/musubi/eurio/ml/CoinDetector.kt
  → bounding box de la pièce dans la frame, ou null si rien
  ↓
  Crop + resize + normalisation
  ↓
  [CoinEmbedder] — CoinEmbedder.kt, modèle TFLite ArcFace
  → vecteur d'embedding (dim typique : 128 ou 256)
  ↓
  [EmbeddingMatcher] — EmbeddingMatcher.kt, KNN sur embeddings canoniques
  → top-K candidats avec scores de similarité cosine
  ↓
  Si top-1 > seuil ET (top-1 - top-2) > marge → match
  Sinon → état "non identifié"
  ↓
  Résolution eurio_id → lecture Room coin → affichage fiche
```

---

## État actuel des briques

| Brique | État | Note |
|---|---|---|
| CoinDetector | POC en place (YOLOv8n tenté, faux positifs massifs) | À retravailler ou remplacer. Voir [`docs/research/yolo-detection-findings.md`](../../research/yolo-detection-findings.md) si existe. |
| CoinEmbedder | Phase 1 classification bridge en cours (Phase 2A) | Bloquant pour le scan utilisateur réel. |
| Modèle ArcFace 500+ classes | **Pas encore entraîné** (Phase 2B) | Bloquant pour le matching multi-classes. |
| EmbeddingMatcher | Scaffold Kotlin en place | Nécessite `coin_embeddings.npy` pré-calculé. |
| Coin embeddings pré-calculés | Table Supabase vide (0 rows) | À populer après Phase 2B. |

## Décisions ML clés (mémoire projet)

- **Classification triplet loss a échoué** sur le POC initial → pivot vers classification bridge + ArcFace metric learning (mémoire `project_phase1_decisions.md`).
- **ArcFace validé sur 5 classes** (Phase 2B.1) : R@1 = 100% sur un petit set → l'approche est saine. Reste à passer à 500+ classes.
- **LiteRT (ex-TFLite) est la runtime** sur Android. Choix acté par ADR `docs/adr/001-litert-over-tflite.md`.

## Contraintes de perf

- **Latence cible** : 
  - Detection per frame : < 30ms sur un device moyen (Pixel 6a)
  - Embedding : < 100ms
  - Matching KNN sur ~3000 vecteurs : < 20ms
  - **Total frame → résultat** : < 200ms pour que le scan se sente instantané
- **Throughput** : au moins 3-5 fps de détection pour que le pulse soit fluide.
- **Thermique** : pas de scan continu qui chauffe le device. Backoff si la température monte.

## Références

- [`docs/research/data-referential-architecture.md`](../../research/data-referential-architecture.md) — comment les embeddings sont générés côté bootstrap
- [`docs/phases/phase-2c-referential.md`](../../phases/phase-2c-referential.md) — pipeline de matching multi-stage (stage 4 = visual, branchera ArcFace)
- Mémoire Claude : `project_phase1_decisions.md` — historique des décisions ML

---

## Questions ouvertes

- [ ] Quelle est la taille exacte du modèle ArcFace après export TFLite ? Impact sur la taille de l'APK.
- [ ] Le détecteur de pièce (bounding box) : on garde YOLO ou on simplifie avec un détecteur de cercle OpenCV ? Tradeoff entre qualité et simplicité.
- [ ] Est-ce qu'on fait de la détection multi-pièces ou strictement mono-pièce par scan ? Impact UX + code.
- [ ] Faut-il une étape d'alignement rotation avant l'embedding (la pièce peut être tournée dans n'importe quel sens) ? ArcFace 2D est sensible aux rotations.
