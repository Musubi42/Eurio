# C0 — Benchmark & vérité terrain

**Statut : 🟡 en cours**  ·  Dépend de : —  ·  Débloque : tout le reste

## Objectif

Établir une **vérité terrain mesurée et persistée** : un jeu de test de
**vraies pièces** + un harness de métriques reproductible, dont les **données
sont sauvegardées** (versionnées ou sur MinIO) pour que chaque session future
parte de chiffres, pas d'intuitions.

C'est la colonne vertébrale : C1→C6 se mesurent **contre** ce benchmark.

## Pourquoi à cette place

Sans baseline réelle, toute optimisation est aveugle. Le R@1 66.67% actuel est
sur 60 images val / 27 classes — non représentatif (H6). On ne peut pas dire
« +X% » sans un référentiel stable.

## Hypothèses (à challenger)

- **H6 — Le R@1 val reflète la perf réelle sur tout le catalogue.**
  Croyance : probablement **non**. Test : monter un set held-out de vraies
  photos device couvrant un échantillon stratifié des 546 classes, mesurer R@1
  dessus, comparer au R@1 val.
- **Hypothèse infra — l'infra `ml/bench/` existante est réutilisable.**
  À **auditer** avant de réinventer : `ml:bench:annotate`, `ml:bench:calibrate`,
  `ml:bench:replay`, `ml:bench:compare`, `android:bench:pull`, et le gold
  `theme_match_gold.jsonl`. Ne pas supposer — lire et vérifier ce que ça couvre.

## Benchmark à semer

À définir précisément, mais l'intention :

1. **Jeu de test réel** : photos device (pas catalogue) de pièces physiques,
   annotées (eurio_id + best-frame). Stratifié par pays/année/type. Cible de
   taille à fixer (ex. ≥ N classes × ≥ K photos).
2. **Métriques** : R@1 / R@3 / R@5, par classe et agrégé ; matrice de confusion ;
   taux de « faux confiant » ; latence on-device (lien C5).
3. **Persistance** : dataset + rapport (JSON + markdown) sauvegardés et datés.
   Emplacement à décider (MinIO `eurio-db/bench/` ? `ml/bench/reports/` ?).
4. **Rejouabilité** : une commande qui régénère le rapport pour un checkpoint
   donné (`go-task ml:bench:...`).

## Audit infra existante (fait — 2026-06-11)

On **ne réinvente pas** : il existe déjà un harness d'éval sur vraies photos.

- **`vision/eval_real_snaps.py`** (tâche `ml:eval-real:eval`) : lit
  `datasets/eval_real_norm/<class>/<step>.jpg`, calcule le cosinus vs chaque
  centroïde, sort top-1 + marge + un agrégat `Total: n_ok/n_total`. Flag
  `--from-checkpoint-W` pour comparer **déployé vs ArcFace-W**. `--model` requis.
  ⚠️ Corrigé : il hardcodait `CoinEmbedder` (mobilenet) → patché en
  `build_embedder` (supporte dinov2). Même bug que `compute_embeddings`.
- **`datasets/eval_real_norm/`** : **337 vraies photos device**, ~17 classes 2€
  (recouvrent nos 27 classes fiables). Normalisées via `ml:eval-real:sync`.
- **`ml/bench/`** : harness séparé de **replay de sessions device**
  (`replay.py`, `annotate_session.py`, `calibrate_thresholds.py`,
  `compare_runs.py`), orienté seuils/conditions de scan. 1 session capturée
  (`sessions/Pixel9a/20260516…`). Réutilisable plus tard pour le bench *device*.

**Gaps à combler** : l'éval ne couvre que ~17 classes (pas 546) ; pas de
persistance auto du rapport ; pas de R@3/confusion agrégés (juste top-1).

## Plan

- [x] Auditer l'infra `ml/bench/` + `eval_real` existante.
- [x] Produire une **première baseline `arcface-vits14-v1`** sur vraies photos.
- [ ] Élargir `eval_real_norm` vers un échantillon stratifié des 546 classes.
- [ ] Persister le rapport (JSON + md daté) + emplacement (MinIO `eurio-db/bench/` ?).
- [ ] Ajouter R@3 / matrice de confusion / latence (lien C5) à l'agrégat.

## Résultats

| Date | Checkpoint | Set | Centroïdes | Top-1 | Notes |
|---|---|---|---|---|---|
| 2026-06-11 | arcface-vits14-v1 | eval_real_norm (317 snaps, ~17 cl.) | déployés (val-mean+W) | **77.60%** | 246/317 |
| 2026-06-11 | arcface-vits14-v1 | eval_real_norm (317 snaps, ~17 cl.) | ArcFace-W pur | **82.65%** | 262/317 — bat les val-mean (cf. H2) |
| _(rappel)_ | arcface-vits14-v1 | val (60 img, 27 cl.) | — | 66.67% | R@1 d'entraînement |

## Décisions & next

- **Surprise mesurée** : sur ce set, réel **>** val, et ArcFace-W **>** val-mean
  (→ journal VISION, H2/H6). À **ne pas généraliser** avant d'élargir le set.
- Prochain geste C0 : étendre `eval_real_norm` à plus de classes pour fiabiliser
  ces conclusions, puis persister un rapport reproductible.
