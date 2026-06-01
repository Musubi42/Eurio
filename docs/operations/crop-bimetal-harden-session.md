# Session de reprise — Harden crop bimétal + retrain ArcFace 17-coins

> **À donner à une session Claude Code fraîche sur le Mac** (`Musubi42s-MacBook-Air-Oim`,
> profil Nix `mac`, où `ml/state/eurio.db` + MinIO sont disponibles).
> Objectif de la session : **fixer le sous-crop bimétal des 2 €**, garantir la
> **parité crop train ↔ mobile**, puis **ré-entraîner ArcFace sur les 17 pièces
> cohort** et **redéployer sur le téléphone** pour tester en live.

---

## TL;DR — ce qu'on veut

Sur les 2 € (bimétal : disque central doré + anneau extérieur argenté), le crop
**capture parfois uniquement le disque doré et perd l'anneau argenté**. L'anneau
porte du signal d'identité (étoiles, lettrage du pourtour). C'est un bug de
**détection de cercle**, pas de margin. Il faut :

1. **Quantifier** le taux de sous-crop bimétal (baseline mesurée).
2. **Fixer la détection** pour verrouiller sur le **rim extérieur** (pas le
   cercle interne or↔argent), côté Python ET Kotlin, **bit-identique**.
3. **Ré-entraîner** ArcFace sur les 17 pièces avec le crop durci, **exporter
   TFLite**, **pousser sur le téléphone**, **tester**.

---

## Contexte — ce qui a été fait la session précédente (PC, 2026-06-01)

On a mené un **bench d'ablation format crop** (margin × edge_mode) pour trouver
le meilleur crop. Bilan :

- **On a abandonné Supabase pour l'entraînement** : `eurio.db` (SQLite local,
  source de vérité) a beaucoup drifté vs Supabase sur les `eurio_id`. On résout
  désormais les classes **offline depuis le CSV cohort**
  `ml/state/cohort_csvs/mix-zone-17.csv` (`eurio_id;numista_id;display_name`) via
  `--cohort-csv` (nouvelle fonction `build_resolver_from_cohort_csv` dans
  `ml/eval/class_resolver.py`). Cf. memory `project_crop_ablation_offline_training`.
- **Résultat ablation** (12 combos, 17-class closed set, hold-out = 337 captures
  device, puis confirmation 3 seeds sur le top-2) :
  - `m02-hard` (margin 0.02, edge `hard`, 224) ≈ `m10-hard` → **égalité
    statistique** (mean R@1 83.0 % vs 82.2 %, std ~0.75 pt, n=387).
  - Signal robuste : **edge_mode `hard` > `feathered` > `none`** ; margin 2–10 %
    équivalents, 15 % légèrement pire.
  - **`m02-hard-s224` = le défaut déjà déployé** (Python `normalize_snap.py`
    `COIN_MARGIN=0.02`/`edge="hard"`/224 ; Kotlin `SnapNormalizer.kt` idem). Le
    bench confirme donc que le crop actuel est optimal **À CONDITION que la
    détection de cercle soit correcte**.

> ⚠️ **Le point clé** : ce bench ne testait que margin/edge **sur des cercles
> déjà bien détectés** (les 337 captures device étaient toutes normalisées avec
> succès). Il n'adresse **pas** le sous-crop bimétal. Le margin ne peut PAS le
> fixer : le disque interne ≈ 0.6× le rayon externe → il faudrait ~65 % de
> margin pour récupérer l'anneau, ce qui détruirait les bons crops.

Commit de cette session : voir l'historique `sources-jo-wikipedia` (offline
cohort-CSV bench + runbook réécrit). Runbook bench : `docs/operations/crop-ablation-pc-runbook.md`.

---

## Le problème à fixer (déjà documenté)

Bug connu, déjà tracké : **`docs/operations/crop-bimetal-undercrop.md`**
(découvert 2026-05-24, "à reprendre dans une session dédiée crop/Hough"). Lire
ce fichier en premier — il contient signal, impact, hypothèses, données de
repro et **critères de fix**.

Fait quantifié par l'auteur (commentaire dans `ml/scan/normalize_snap.py` près de
`_DEVICE_HOUGH_PASSES`, ~ligne 122) :

> *« sur bimétal, Hough pick le cercle interne cupro/or plutôt que le rim **~36 %
> du temps**. La règle "largest centred" mitige mais ne fixe pas. Ajouter un
> guard `fill_ratio` équivalent à `_STUDIO_FILL_RATIO_MIN` est un sprint séparé —
> fermerait le drift train↔inference sur les classes bimétal. »*

### Les 3 chemins de crop (architecture)

Tout est dans `ml/scan/normalize_snap.py` :

| Fonction | Usage | Guard bimétal ? |
|---|---|---|
| `normalize_studio` | **données d'entraînement** (Numista/eBay via `prepare_dataset`) | ✅ `fill_ratio` (`_STUDIO_FILL_RATIO_MIN=0.70`) |
| `normalize_device` | **mobile** (`SnapNormalizer.kt`) + eval cohort | ❌ aucun → 36 % inner-ring |
| `normalize_listing` | **listings eBay** (YOLO bbox → Hough refine dans ROI) | partiel (à vérifier) |

**Conséquence parité** : l'entraînement utilise le chemin *studio* (guardé), le
téléphone utilise le chemin *device* (non guardé). Sur bimétal ils détectent des
rayons différents → **drift train↔inference**. Les 17 pièces cohort sont **toutes
des 2 € commémoratives = toutes bimétal**, donc ça touche directement la boucle
de retrain.

---

## Plan de la session (3 phases)

### Phase 1 — Quantifier (baseline, read-only)
- Mesurer le taux de sous-crop bimétal sur du vrai data :
  - Listings eBay : `cd ml && .venv/bin/python -m scripts.bench_listing_bimetal --n 25`
    (besoin `eurio.db` + MinIO → **OK sur Mac**). Sort `ml/state/listing_bimetal_bench/`
    (overlays + `summary.md`). Voir aussi `scripts/measure_listing_radius_distribution.py`.
  - Chemin device : faire tourner `normalize_device` sur les captures device des
    17 pièces (`debug_pull/<ts>/eval_real/`) et `normalize_studio` sur leurs raws
    Numista (`ml/datasets/<numista_id>/obverse.jpg`), comparer les rayons
    détectés + visualiser. (Le diff Python↔Kotlin existe : `ml/scan/diff_kotlin_python.py`.)
- **But** : connaître le taux d'échec réel AVANT de toucher la détection.

### Phase 2 — Fixer la détection
- Porter un guard **`fill_ratio` / biais rim-extérieur** dans `normalize_device`
  (et vérifier `normalize_listing`). Hypothèses cause (cf. crop-bimetal-undercrop.md) :
  1. Hough vote le cercle interne or↔argent (plus saillant que pièce/fond).
  2. YOLO bbox trop serrée sur le centre brillant (chemin listing).
  3. Merge IoU privilégie la plus petite détection → l'inverser pour bimétal.
- **Mirror bit-identique dans `app-android/.../ml/SnapNormalizer.kt`** (les passes
  Hough sont déjà `Mirrored bit-for-bit by SnapNormalizer.kt::PASSES`). Vérifier
  la parité avec `ml/scan/diff_kotlin_python.py`.
- **Critères de fix** (de crop-bimetal-undercrop.md) :
  - [ ] Majorité des crops 2 € capture l'anneau argenté (bbox réelle ≥ ~85 % de
        la silhouette re-segmentée).
  - [ ] Pas de régression sur 1 €/50c/autres bimétaux ni mono-métaux.
  - [ ] Bench (Dino/ArcFace) stable ou en hausse — s'il baisse, on apprenait sur
        le mauvais signal.
  - [ ] Parité Python↔Kotlin OK (`diff_kotlin_python.py`).

### Phase 3 — Retrain + redéploiement
- Ré-entraîner ArcFace **sur les 17 pièces** avec le crop durci, offline :
  ```bash
  cd ml
  env -u SUPABASE_URL -u SUPABASE_SERVICE_ROLE_KEY -u SUPABASE_ANON_KEY -u SUPABASE_SERVICE_KEY \
  .venv/bin/python -m scripts.sweep_ablation \
      --device-pull "../debug_pull/<ts>" \
      --class-kind eurio_id \
      --cohort-csv state/cohort_csvs/mix-zone-17.csv \
      --margin-frac 0.02 --edge-mode hard --epochs 12 --force-from recrop
  ```
  (ou directement `prepare_dataset` + `train_embedder` si on veut le full set,
  mais l'objectif énoncé est "les 17".)
- **Exporter TFLite** : `go-task ml:export` (puis `go-task ml:validate` pour
  vérifier cosim PyTorch↔TFLite > 0.99).
- **Pousser le modèle + snapshot sur le téléphone** et tester le scan en live.
  (Modèle dans `app-android/src/main/assets/` ; cf. tasks `go-task android:*`.)

---

## Pourquoi sur le Mac

- `ml/state/eurio.db` (référentiel, source de vérité) **n'est pas sur le PC**
  (gitignored, per-machine) → présent sur le Mac.
- **MinIO** (raws eBay) accessible côté Mac → nécessaire pour
  `bench_listing_bimetal.py` et le chemin listing.
- Le déploiement device + l'export sont rodés côté Mac.

Le chemin **device** (parité-critique pour le retrain) serait faisable sur PC,
mais le chemin **listing eBay** (ton pain point initial) a besoin du Mac.

---

## Pointeurs

- **Bug doc (à lire en 1er)** : `docs/operations/crop-bimetal-undercrop.md`
- Code crop : `ml/scan/normalize_snap.py` (`normalize_studio` / `normalize_device`
  / `normalize_listing`, `detect_circles_multi`, `_DEVICE_HOUGH_PASSES`,
  `_STUDIO_FILL_RATIO_MIN`)
- Parité Kotlin : `app-android/src/main/java/com/musubi/eurio/ml/SnapNormalizer.kt`
  · diff harness : `ml/scan/diff_kotlin_python.py`
- Benches bimétal : `ml/scripts/bench_listing_bimetal.py`,
  `ml/scripts/measure_listing_radius_distribution.py`, `ml/scripts/bench_listing_detection.py`
- Pipeline scan : `docs/research/detection-pipeline-unified.md`
- Bench crop margin/edge (session PC) : `docs/operations/crop-ablation-pc-runbook.md`
- CSV cohort : `ml/state/cohort_csvs/mix-zone-17.csv` (17 pièces, 2 € commémo)
- Résultats ablation : `ml/state/ablation_eval/_sweep_results.md` (sur le PC)
- Memories : `project_crop_bimetal_harden` (objectif réel), `project_crop_ablation_offline_training`
  (offline CSV), `project_obverse_only_matching`, `feedback_output_contract_parity` (parité)

---

## Garde-fous (CLAUDE.md)

- Toujours `go-task` (jamais `task`). Staging git **explicite par fichier**
  (jamais `git add -A`/`.`). `Color.kt`/`Shape.kt`/`Spacing.kt` auto-générés —
  jamais à la main. Secrets via `sops secrets/dev.env`.
- Parité = **contrat de sortie** train↔Android (mêmes crops à ε près), pas
  forcément même code. Cf. `feedback_output_contract_parity`.
