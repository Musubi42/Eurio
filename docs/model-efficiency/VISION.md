# Model Efficiency — VISION

> North star et règles du jeu pour faire évoluer le modèle de scan d'Eurio.
> Doc **vivante** : elle est mise à jour à chaque test réel, et nos croyances
> y sont remises en question dès qu'un benchmark les contredit.

## North star

**Reconnaître toutes les pièces 2€ de notre DB** (couverture catalogue
complète), avec un modèle assez **léger et rapide** pour tourner largement —
du haut de gamme jusque, à terme, l'entrée de gamme.

Aujourd'hui on couvre **27 classes fiables** (cf. état ci-dessous). La cible
est **l'intégralité des classes de la DB** (~546 designs 2€ et au-delà à mesure
que le référentiel grossit).

## Règles de travail (non négociables)

1. **Pas d'hypothèse cachée.** Toute supposition est écrite explicitement comme
   une **Hypothèse (à challenger)** dans le chantier concerné, et on **sème un
   benchmark** pour la stress-tester. Le registre global est plus bas.
2. **Benchmark-first.** Avant d'optimiser, on établit une **vérité terrain
   mesurée et persistée** (C0). Chaque session future repart de chiffres.
3. **Test réel dès que possible** → résultat consigné dans la doc → on
   réinterroge la croyance.
4. **Un chiffre non mesuré n'est pas un fait.** Les estimations sont taguées
   `⚠️ estimation` tant qu'un benchmark ne les a pas confirmées.

## État actuel — mesuré (2026-06-11)

Modèle de référence : **`arcface-vits14-v1`** (checkpoint sur MinIO
`eurio-db/transfers/arcface_vits14_v1_best_model.pth`).

| Dimension | Valeur | Source |
|---|---|---|
| Type | Embedder métrique (retrieval), pas classifieur | code |
| Backbone | DINOv2 ViT-S/14 + `Linear(384→384)`, 21,7M params | `train_embedder.py` |
| Loss | ArcFace, marge ≈ 28.6°, scale 30, `MPerClassSampler(m=4)` | log run |
| Entrée / sortie | 224×224 RGB (ImageNet norm) / embedding 384-dim | code |
| Données train | 546 classes, 1004 img train / 60 val @224px, ×3 aug | log run |
| Qualité | **Recall@1 = 66.67%, R@3 = 68.33%** sur le val (60 img / 27 classes) | `training_log.json` |
| Centroïdes déployés | **27 val-mean fiables** + 519 ArcFace-W (non re-vérifiés) | `compute_embeddings` |
| Poids fp32 / fp16 | 83.3 MB / **41.8 MB** | export réel |
| Coût calcul | 5.68 GMACs / inférence | export réel |
| Déployé | fp16 + 27 centroïdes fiables, testé sur Pixel 9a (concluant) | smoke test |

> ⚠️ **Le R@1 66.67% est sur 60 images val / 27 classes** — ce n'est PAS un test
> held-out représentatif sur tout le catalogue. La perf réelle « in the wild »
> sur les 546 classes est **inconnue** (→ C0).

## Carte des chantiers

Ordre = dépendances. Statut : 🔲 pas commencé · 🟡 en cours · ✅ fait.

| # | Chantier | Statut | Dépend de |
|---|---|---|---|
| **C0** | [Benchmark & vérité terrain](./C0-benchmark-ground-truth.md) | 🔲 | — |
| **C1** | [Centroïdes fiables](./C1-reliable-centroids.md) | 🔲 | C0 |
| **C2** | [Flywheel données — review eBay](./C2-data-flywheel-ebay-review.md) | 🔲 | C0, C1 |
| **C3** | [Couverture catalogue complète](./C3-full-catalog-coverage.md) | 🔲 | C1, C2 |
| **C4** | [Efficacité — quantization + distillation](./C4-efficiency-quant-distill.md) | 🔲 | C0 |
| **C5** | [Accélération on-device](./C5-on-device-acceleration.md) | 🔲 | C0 |
| **C6** | [Gate d'éval continue](./C6-eval-gate.md) | 🔲 | C0 |

## Passations de session

- [HANDOFF-C2.md](./HANDOFF-C2.md) — démarrage d'une session dédiée au flywheel
  eBay (C2) : mission bout-en-bout, infra existante cartographiée, décisions à
  prendre, premiers pas. Écrit fin session 1.

## Registre global des hypothèses (à challenger)

Chaque hypothèse vit en détail dans son chantier ; ici c'est l'index pour ne
jamais en perdre une de vue.

| H | Hypothèse | Croyance actuelle | Testée par | Statut |
|---|---|---|---|---|
| H1 | Plus d'images **réelles** par classe ↑ précision **et** ↑ fiabilité des centroïdes | Forte (mécanisme plausible) | C0 + C1 | ❓ non mesuré |
| H2 | Les centroïdes ArcFace-W sont peu fiables (vs moyennes d'images) | **Réfutée** : le faible est val-mean, pas W | C1 | ⚠️ train-mean≈W > val-mean (set étroit) |
| H3 | fp16 ≈ sans perte ; int8 dégrade un ViT | Moyenne (typique, pas mesuré ici) | C4 | ❓ non mesuré |
| H4 | Les gains DINOv2 transfèrent à la **classification eBay scrape** | Moyenne (idée produit, plausible) | C2 | ❓ non mesuré |
| H5 | La perf fp16 ViT-S est OK sur milieu/haut de gamme | Faible (aucune latence mesurée) | C5 | ❓ non mesuré |
| H6 | Le R@1 val reflète la perf réelle sur tout le catalogue | **Non** (val ≠ réel) | C0 | ⚠️ **réel > val** sur set étroit |

## Journal des révisions de croyances

> On consigne ici, daté, chaque fois qu'un benchmark **renverse** une hypothèse.
> (Vide pour l'instant — c'est bon signe, ça veut dire qu'on n'a pas encore
> triché en supposant.)

- **2026-06-11 — Premier test réel (C0) renverse H2 et H6.** Éval de
  `arcface-vits14-v1` sur **317 vraies photos device** (`eval_real_norm`, ~17
  classes) via `vision/eval_real_snaps.py` :
  - Centroïdes **déployés** (val-mean + ArcFace-W) : **top-1 = 77.60%** (246/317).
  - Centroïdes **ArcFace-W purs** : **top-1 = 82.65%** (262/317).
  - Rappel R@1 **val** = 66.67%.
  - **H2 (ArcFace-W est mauvais) → contredit** sur ce modèle : W bat val-mean de
    **+5 pts**. On allait construire C1 sur la croyance inverse (héritée du run
    F2). À confirmer sur un set plus large avant d'en faire une règle.
  - **H6 → le val sous-estime** ici le réel (66.67% val vs 77-82% réel).
  - ⚠️ Caveat : set étroit (~17 classes, recouvrant nos classes fiables), 5 pts
    ≈ 16 snaps. Signal, pas preuve. → élargir le set (C0) avant conclusion.

- **2026-06-11 — 3-way centroïdes (C1) précise H2.** Même set (317 snaps),
  `--centroid-source` : **train-mean 82.97%** · **ArcFace-W 82.65%** ·
  **val-mean 77.60%**. Le maillon faible est **val-mean** (peu d'images val),
  pas ArcFace-W. train-mean ≈ W (égalité). Implication : l'app déployée priorise
  val-mean (le pire) → gain immédiat possible en train-mean. Et train-mean tient
  déjà avec `n=1`/classe → devrait progresser avec plus d'images (H1). Toujours
  set étroit → à confirmer large.

## Sources de vérité (code)

- Entraînement : `ml/training/train_embedder.py`
- Export TFLite : `ml/training/export_tflite.py` (`--fp16`)
- Centroïdes : `ml/training/compute_embeddings.py`
- Spike quantization : `ml/scripts/spike_vits14_litert.py`
- Inférence Android : `app-android/.../ml/CoinEmbedder.kt`, `EmbeddingMatcher.kt`
- Résolution match→pièce : `CoinRepository.resolveByClassifierName` (`findByEurioId`)
- Pipeline scrape/review eBay : `ml:scrape-ebay`, `ml:src:ebay`, `ml:review:*`, `ml:dino-predictions:*`
- Infra bench existante (à auditer en C0) : `ml/bench/`, tâches `ml:bench:*`, `android:bench:*`
