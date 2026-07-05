# exp-01-centroids — train_mean vs val_mean (rodage du funnel S0)

> Première expérience du funnel — son but premier est de **roder le funnel de
> bout en bout** (device SNAP → pull → import → replay → scorecard + McNemar),
> la question centroïdes est le prétexte. Réfs : [`corpus-spec.md`](./corpus-spec.md),
> [`exp-template.md`](./exp-template.md).
>
> **État (2026-07-06) : TERMINÉ.** Funnel S0 déroulé de bout en bout sur les
> 73 frames réelles (backfill device → import → replay apparié). Verdict §8 :
> **signal positif franc pour `train_mean` (+8,2 pts R@1 eq) mais non
> significatif (McNemar p=0,18)** — promotion différée, corpus à agrandir.

## 1. Hypothèse

Les centroïdes `train_mean` (moyenne sur le split train, toutes classes
couvertes) matchent au moins aussi bien que `val_mean` (défaut `auto` de
`compute_embeddings`) sur des frames in-the-wild.

## 2. Variable unique

| | Baseline | Candidat |
|---|---|---|
| **Centroïdes** | `val_mean` (bundle lab exact de la session) | `train_mean` |
| **Modèle** | `eurio_embedder_v1.tflite` (v35-arcface, id.) | identique |
| **Seuils** | aucun (matcher top-k pur, parité Android) | identiques |

- Baseline épinglée : `ml/state/scan_baselines/val_mean-5bf8edb0ad7d/` — copie
  gelée de `ml/output/cohort_test_5bf8edb0ad7d/` (le bundle qui a réellement
  tourné sur le device le 2026-07-04, shas dans `bundle_meta.json`).
- Candidat généré (fait) :

```bash
cd ml && .venv/bin/python training/compute_embeddings.py \
  --model lab/iterations/5bf8edb0ad7d/checkpoints/best_model.pth \
  --dataset lab/iterations/5bf8edb0ad7d/dataset \
  --output-dir state/scan_experiments/exp-01-centroids/train_mean \
  --model-version v35-arcface --centroid-source train_mean
```

## 3. Corpus

| Champ | Valeur |
|---|---|
| `corpus_version` | **`9b1bc705525d`** |
| `n_frames` | **73** (73/73 lignes JSONL appariées, 0 échec de hash) |
| Filtre | `source_iteration_id=5bf8edb0ad7d` (cohorte mix-zone-17 `b0299ca0252b`) |
| Conditions | bright n=20 · dim n=31 · tilt n=22 (session pré-`glare`/`inhand`) |
| Provenance | **backfill** `eurio_debug/photo_snaps` (session antérieure au Lot 2) — matching snap↔JSONL par signature top-3, crop transcodé JPEG q95→PNG (tracé en `notes`) |
| Chemin replay | `fast` (crop→embed→match) |

Note : le « 48 » du §I4d est le best-of par test (16×3) ; le corpus est par
FRAME, chaque re-capture compte → 73.

## 4. Commandes exécutées (2026-07-06, reproductibles)

```bash
adb pull /sdcard/Android/data/com.musubi.eurio.cohorttest/files/Documents/eurio_debug/photo_snaps \
  debug_pull/exp01_photo_snaps                        # 384 fichiers (128 snaps, toutes sessions)
go-task ml:scan-corpus:import ITERATION=5bf8edb0ad7d -- \
  --backfill-debug-snaps "$PWD/debug_pull/exp01_photo_snaps"   # chemins ABSOLUS (cwd tâche = ml/)
go-task ml:scan-corpus:replay -- \
  --candidate "$PWD/ml/state/scan_experiments/exp-01-centroids/train_mean" \
  --candidate-label "exp-01/train_mean" \
  --baseline  "$PWD/ml/state/scan_baselines/val_mean-5bf8edb0ad7d" \
  --baseline-label "val_mean@5bf8edb0ad7d" \
  --iteration 5bf8edb0ad7d
```

Sortie complète : `ml/state/scan_corpus_runs/exp-01/train_mean__9b1bc705525d/`
(`scorecard.json`, `predictions.jsonl`, `predictions.baseline.jsonl`).

## 5. Rodage effectué (ce qui EST validé)

Le funnel a tourné de bout en bout sur un **corpus smoke jetable** (8 crops
val studio injectés dans une DB scratch, jamais dans `scan_corpus.db`) avec le
**vrai** tflite, les **vrais** centroïdes train_mean/val_mean et la **vraie**
map d'équivalence design_group :

- chemin `fast` (crop→embed→match) : scorecard complète §8 + McNemar §8bis
  émis (`primary`, `by_condition`, `abstention`, contingence, p-value) ;
- chemin `full` (raw→`normalize_device` parité SnapNormalizer→embed→match) : OK ;
- fix au passage : `TFLiteEmbedder` (bench partagé) supposait un layout NHWC —
  le bundle exporté est NCHW comme l'Android `CoinEmbedder` ; détection de
  layout ajoutée, chemin NHWC intact.

⚠️ Les chiffres smoke (R@1 0.75 fast / 0.875 full, n=8 studio) **ne valent
rien** comme mesure — c'est un test de plomberie, pas un banc.

## 6. Scorecard (extrait — complet dans `scan_corpus_runs/`)

| Métrique | `val_mean` (baseline) | `train_mean` (candidat) | Δ |
|---|---|---|---|
| **R@1 eq** | 0.6849 | **0.7671** | **+8.2 pts** |
| R@5 eq | 0.9315 | 0.9178 | −1.4 pts |
| bright (n=20) | 0.80 | 0.90 | +10.0 pts |
| dim (n=31) | 0.5161 | 0.6129 | +9.7 pts |
| tilt (n=22) | 0.8182 | 0.8636 | +4.5 pts |

Abstention : coverage 1.0 des deux côtés (pas de seuils — parité matcher
Android top-k pur). Taille modèle identique (4.23 MB, Δ=0).

## 7. McNemar (§8bis)

- Contingence : both_correct=46, **candidate_only=10, baseline_only=4**,
  both_incorrect=13 → 14 paires discordantes, **p = 0.180**.
- Lecture des bascules : les 10 gains sont concentrés et cohérents —
  `at-2002` standard (5×, dim), `de-2020` reconciliation (3×),
  `at-2005` treaty (2×) : des classes que val_mean confondait avec des
  commémoratives voisines. Les 4 pertes sont dispersées (aucun pattern).

## 8. Décision go/no-go

| Étage | Verdict |
|---|---|
| **S0** replay offline | 🟡 **non concluant côté stat, signal franc côté delta** — pas de promotion sur cette seule mesure |
| S1 re-scan device | différé (attendre corpus élargi ou re-mesure) |
| S2–S3 | — |

## 9. Verdict écrit

**Signal positif franc pour `train_mean`, mais pas de conclusion « gain »
possible : p=0.18.** Le delta (+8.2 pts R@1 eq, gain sur les 3 conditions,
10 bascules gagnées contre 4 perdues, toutes cohérentes) dépasse le seuil
« delta franc ≥ ~5 pts » qu'on s'était fixé, mais le McNemar exact ne rejette
pas H0 à n=73 — un vrai verdict demanderait ~2× plus de paires discordantes.
Décision : **ne pas promouvoir train_mean maintenant** ; agrandir le corpus
(prochaine session cohort-test avec archivage natif + `glare`/`inhand`, cible
150–300 frames) et re-répliquer — si le delta tient, promotion S1. Le R@5
légèrement en retrait (−1.4 pts) est à surveiller au re-test. **Objectif
premier atteint : le funnel S0 (SNAP → pull → import → replay → scorecard +
McNemar) est rodé de bout en bout sur données réelles.**
