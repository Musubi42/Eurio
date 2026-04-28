# Parity Contract — Studio ↔ Device

> Ce qui définit "deux pipelines sont cohérentes". Trois tests indépendants, chacun gate un type de régression différent. Le test principal du rework — **cross-algo sur image identique** — remplace l'idée précédente de "MAE sur paires train↔device" qui confondait divergence d'algo et divergence d'acquisition.

## Vue d'ensemble — la matrice des 3 tests

| # | Test | Mesure | Trigger CI | Fichier de test |
|---|---|---|---|---|
| 1 | **cross-algo** | `MAE_pixel(N_studio(I), N_device(I))` sur image studio identique I | PR touchant `ml/scan/normalize_*.py` | `ml/tests/parity_test.py` (nouveau) |
| 2 | **cross-platform** | `MAE_pixel(N_device_py(I), SnapNormalizer.kt(I))` sur image identique I | PR touchant `ml/scan/normalize_snap.py` ou `SnapNormalizer.kt` | `ml/scan/diff_kotlin_python.py` (existant, à conserver) |
| 3 | **R@1 end-to-end** | R@1 KNN ArcFace sur `eval_real_norm/` | PR touchant `prepare_dataset.py`, `train_embedder.py`, ou un normalizer | training pipeline |

**Aucun de ces tests ne mesure la divergence sur des paires `(I_studio, I_device)` du même coin physique.** Cette métrique est dominée par la divergence d'acquisition (lumière, angle, reflet) et ne peut pas distinguer une régression normalizer d'une dispersion de capture. Le seul juge cross-acquisition légitime est le test #3 (R@1).

## Test #1 — Cross-algo (le test principal du rework)

### Définition

Soit un set d'images studio `D_studio = {I_1, ..., I_N}` (sources Numista variées). Pour chaque `I_i` :

```
diff_i = | N_studio(I_i).image - N_device(I_i).image |    # 224×224×3 uint8
MAE_i  = mean(diff_i)                                     # sur 150528 valeurs
max_i  = max(diff_i)
```

`N_studio` et `N_device` satisfont le contrat de parité ε si :

> Pour ≥ 95% des images `i`, `MAE_i ≤ ε`,
>
> **et** `max_i ≤ M_max` pour 100% des images.

### Pourquoi cross-algo sur image identique

Quand on donne la *même* image en entrée aux deux algos, la seule source de divergence est l'algo lui-même (et le rounding de `(cx, cy, r)`). Pas l'éclairage, pas l'angle, pas la balance des blancs. Donc ε mesure exactement ce qu'on veut tester : "les deux normalizers convergent-ils sur les mêmes pixels ?"

Sur des paires (capture studio, capture device) du *même coin physique*, la dispersion est dominée par :
- rotation in-plane différente (~1° = 10–20/255 MAE),
- reflets spéculaires absents en studio,
- shift colorimétrique 5500K↔3000K (~20–40/255),
- bruit capteur device.

Le ε qu'on mesurerait sur ces paires serait de l'ordre de 30–60, ce qui est trop laxiste pour détecter une régression d'algo (typiquement <5/255). Donc on ne le fait pas.

### Choix de ε et M_max

Procédure (à exécuter en Phase B) :

1. Sur le set `D_studio` (≥ 30 images, cf. ci-dessous), calculer la distribution de `MAE_i` et `max_i` en utilisant **le même algo des deux côtés** (par exemple `N_device(I) ↔ N_device(I)` qui devrait donner ε≈0 si l'algo est déterministe). C'est le contrôle de bruit de fond.
2. Calculer la même chose en utilisant `N_studio(I) ↔ N_device(I)` — c'est la mesure cible.
3. Poser `ε = max(percentile_95(MAE_studio_vs_device) × 1.2, 3.0)` (plancher à 3 pour absorber le rounding entier de `(cx, cy, r)`).
4. Poser `M_max = percentile_99(max_studio_vs_device) × 1.2`.

**Valeurs cibles à valider** (estimation pré-mesure, à raffiner) :
- `ε` autour de **3–5 / 255** (~1.2–2%).
- `M_max` autour de **40–80 / 255** sur des pixels isolés (typiquement les pixels au bord du masque où un Δr de 1 px crée un saut binaire BG↔coin).

### Dataset `D_studio`

**Source** : 30+ images studio sélectionnées dans `ml/datasets/<numista_id>/obverse.jpg`, stratifiées :

- 8 mono-métal commun (1c, 2c, 5c, 10c, 20c, 50c, 1€, 2€ standard).
- 6 bi-métal 2 EUR (le cas-piège du Hough actuel et le cas-test critique pour Otsu polarité).
- 8 commémoratives variées (relief atypique, contrastes différents).
- 4 cas low-contrast (vieille pièce sale, ou scan avec BG légèrement coloré).
- 4 outliers (très petite ou très grande dans le frame, légèrement off-center).

**Avantage majeur sur l'ancienne approche** : ces 30 images existent déjà dans `ml/datasets/` (sources Numista). **Aucune capture terrain n'est nécessaire** pour ce test, contrairement aux paires train↔device qui exigeaient un protocole de capture coûteux.

**Manifest** : `ml/tests/parity_dataset.yaml` (≤ 50 lignes) listant les `numista_id` + tags (`bimetal`, `low_contrast`, `commemorative`, `outlier`, etc.) pour analyser la dispersion par catégorie.

### Test invocation

```bash
go-task ml:scan:parity-test
# ou
python -m ml.tests.parity_test --manifest ml/tests/parity_dataset.yaml --epsilon 3.0 --m-max 60
```

Sortie :
- Tableau par image : `numista_id, tag, MAE, max_diff, pass/fail`.
- Stats globales : `pct_pass`, `MAE_mean`, `MAE_p95`, `max_diff_p99`.
- Stats par tag : pour repérer si bimétal ou low-contrast tire la queue.
- Exit code : `0` si `pct_pass ≥ 95% && all(max_diff ≤ M_max)`, sinon `1`.
- Dump des pires cas (triptyque `studio_norm | device_norm | abs_diff`) dans `ml/tests/_parity_out/`.

### Comparaison en mémoire, pas via JPEG

Le test charge les images source une fois, exécute `N_studio` et `N_device` en RAM, et compare directement les `np.ndarray` `uint8` 224×224×3. **Aucune sérialisation JPEG intermédiaire** — la quantization JPEG ajouterait 0.5–1.0 de bruit MAE et mangerait 30% de la marge ε.

## Test #2 — Cross-platform (Python ↔ Kotlin device)

### Définition

`N_device_py(I)` et `SnapNormalizer.kt(I)` doivent produire le même 224×224 sur la même image, à ε_pf près.

### État actuel

L'outil `ml/scan/diff_kotlin_python.py` existe déjà et compare un crop produit par `python -m scan.preview_normalized` avec un crop pull-é depuis l'APK debug (cf. parent README, `go-task ml:scan:diff`). Ce test reste valide et continue de gate les modifications de `SnapNormalizer.kt`.

### Seuil

`ε_pf ≈ 1 / 255` (sub-LSB attendu : OpenCV C++ et OpenCV Java appellent les mêmes binaires, drift attendu = nul). Si > 2 / 255, c'est un drift de port à investiguer.

### Trigger

À chaque modification de `SnapNormalizer.kt` ou `normalize_snap.py::_detect_coin_circle` (la partie qui doit rester miroir bit-pour-bit).

## Test #3 — R@1 end-to-end (juge final)

### Définition

R@1 KNN ArcFace sur `eval_real_norm/` (golden set device, déjà constitué Phase 0 de la roadmap parente).

### Procédure

1. Avant tout changement : capturer la baseline R@1 sur le pipeline actuel. Stocker dans `bench-results-pre.md`.
2. Après chaque changement structurel d'un normalizer : re-run training → re-eval R@1.
3. Critère : `R@1_after ≥ R@1_baseline` global, et **aucune classe** qui passe de ≥ 90% à < 80%.

### Pourquoi indispensable

Le test cross-algo garantit que les algos convergent sur les mêmes pixels. Mais il ne garantit pas que ces pixels sont les *bons* pixels (i.e. qu'ils discriminent bien les classes en pratique). Seul R@1 sur des captures réelles peut juger ça. Un changement qui passe cross-algo mais dégrade R@1 est invalide.

### Coût

Un cycle complet = `prepare_dataset` + `train_embedder` + eval. Sur 18 classes, après le rework (`prepare_dataset` < 5 min) : training ~30 min, eval ~2 min. Tournable une fois par PR de fond, pas à chaque commit.

## Intégration CI / dev loop

| Quand | Tests à passer |
|---|---|
| Commit local touchant `normalize_*.py` | #1 cross-algo |
| Commit local touchant `SnapNormalizer.kt` | #2 cross-platform |
| Pré-merge sur main (PR ML) | #1 + #2 |
| Avant un release training (modèle TFLite à exporter) | #1 + #2 + #3 |

Le commit message d'une PR qui modifie un normalizer doit inclure le résumé :

```
normalize_studio: tighten Otsu morph kernel
parity-cross-algo: pct_pass=98.3% (was 95.0%), MAE_p95=2.8 (was 3.4)
parity-cross-platform: ε_pf=0.4/255 (unchanged)
```

Régression alerting : si `pct_pass` baisse sous la baseline (même au-dessus de 95%), c'est une régression à justifier dans le commit.

Régénération du seuil : tous les ~6 mois ou à chaque évolution majeure d'un normalizer, ré-évaluer ε / M_max via la procédure ci-dessus. Documenter dans `bench-results-pre.md` (ou un fichier successeur).

## Ce que ce contrat NE garantit PAS

- **Pas un substitut au R@1 ArcFace.** La parité cross-algo est nécessaire mais pas suffisante. Le KPI final reste R@1 sur `eval_real_norm`. Régression R@1 même avec parité OK = retour arrière.
- **Pas de garantie sur des cas hors-distribution.** Le test mesure sur les ~30 images du `parity_dataset.yaml`. Une pièce extrêmement atypique (médaille non-circulaire, doré ancien sur fond doré) sortirait du test ; ce n'est pas une fuite, c'est hors scope. Étendre le manifest si un nouveau cas-piège émerge.
- **Pas une métrique d'usage produit.** Latency, robustesse à éclairage faible, taux d'échec en main shaky — tout ça reste à mesurer ailleurs (cf. Phase 5 backlog parent). En particulier, le rework ne traite pas le problème "angle + lumière" identifié comme dominant côté device, qui est adressé par : (a) la stratégie photo-mode + ring déjà en place, (b) la Phase F optionnelle (snap haute-res via `ImageCapture`), (c) éventuellement Phase 5 backlog (sharpness gate, exposure gate).

## Faillibilité du contrat

Si un changement passe le test mais dégrade R@1 :
- Le test est trop laxiste (ε trop large, dataset non-représentatif).
- Action : étudier les images les plus dispersées dans le test, raffiner ε, étendre le manifest, re-baseliner.

Si un changement échoue le test mais améliore intuitivement le pipeline :
- Le contrat actuel sur-contraint un cas légitime (ex. nouveau bug Hough latent corrigé par le contour, comme observé sur `327887` Δr=+35 dans le bench pré).
- Action : raisonner. Si divergence = vrai bug latent corrigé, on met à jour la baseline ; sinon retour arrière.
- Toute exception explicite dans le commit message + ajouter le cas au `parity_dataset.yaml` si récurrent.
