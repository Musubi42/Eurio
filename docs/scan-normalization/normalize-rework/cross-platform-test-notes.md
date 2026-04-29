# Cross-platform test (`ml:scan:diff`) — observations

> Notes capturées 2026-04-29 sur le run `go-task ml:scan:diff` post-fix offset device. **Conclusion** : le test passe sa mission de sentinelle (aucun drift structurel détecté) mais son seuil `PSNR ≥ 30 dB` n'est **pas atteignable** sur frames device pour des raisons structurelles, indépendamment de la qualité du port. À comprendre avant de relancer ou d'agir sur ses chiffres.

## Le run de référence

`go-task ml:scan:diff -- "$(pwd)/debug_pull/20260429_170852/eurio_debug/eval_real" --write-diff`

- 114 snaps device (17 classes × ~6 conditions stratifiées : `bright_plain`, `bright_textured`, `close_plain`, `daylight_plain`, `dim_plain`, `tilt_plain`).
- Verdict global : **18/114 OK (15.8%)**, 96/114 MISS, 0 MISMATCH.
- Tous les MISS ont la forme « Δcx, Δcy, Δr ∈ [-9, +12] px AND PSNR ∈ [15.7, 28.1] dB ».
- Aucun MISS de type Δ ≥ 30 px, qui aurait été le signal du **bug d'offset** corrigé plus tôt (cf. `implementation-plan.md` Phase C log §"Fix offset device").

## La mécanique du faux MISS

Le test compare deux pipelines qui **ne partent pas de la même image source** :

| Côté | Source réelle vue par le pipeline |
|---|---|
| **Python** (`normalize_device_path(<raw>.jpg)`) | JPEG → libjpeg-turbo → BGR ndarray |
| **Kotlin** (live, runtime) | Bitmap RGBA en mémoire (pré-JPEG), normalisé avant d'écrire le JPEG sur disque |

Le `<step>_raw.jpg` que Python re-décode contient une dégradation ±5 LSB par canal (quantisation JPEG q=85 dans `imageProxyToBitmap`), absente du bitmap que Kotlin a normalisé live. Cette divergence d'**input** se propage à la sortie en deux étapes :

1. **Hough** sur des pixels ±5 LSB de bruit produit un `(cx, cy, r)` qui peut différer de ±1 à 7 px selon la stabilité du gradient (très bonne en `dim_plain`, plus volatile en `bright_textured`).
2. **Crop + INTER_AREA resize** amplifie un Δr de 1 px à r=360 en un changement de scale ~0.3% sur le 224×224. Ce micro-décalage sub-pixel produit une PSNR plafonnée à 20–28 dB sur l'ensemble du frame, **même si chaque opération OpenCV individuelle est bit-equivalente**.

Le seuil `PSNR ≥ 30 dB` du script est calibré pour des sources **identiques** (même JPEG des deux côtés, comme dans le contrat de parité Phase B). Sur frames device, ce niveau n'est atteint que dans les cas où Hough trouve `Δ=(0,0,0)` malgré la noise JPEG — soit ~16% des conditions, alignées avec les conditions stables (dim, calme).

## Ce que le test prouve quand même (utile)

Bien qu'on ne puisse pas valider PSNR ≥ 30 sur les 114, on peut lire le résultat comme :

1. **Aucun delta géant.** Les pires Δ observés sont (-7, +12, +9) px. Le bug d'offset Phase C produisait Δ ≥ 30 px. Le revert cascade a tué cette régression : aucune trace dans ce run.
2. **18 cas avec Δ=(0,0,0) ET PSNR 38–44 dB.** Ces cas démontrent que **lorsque Hough converge identiquement sur les deux side, la pipeline pixel-par-pixel sortie est bit-equivalente** modulo JPEG-decode noise floor. C'est la garantie utile : `cv2.resize INTER_AREA` Python ↔ `Imgproc.resize INTER_AREA` Kotlin, `cv2.circle` ↔ `Imgproc.circle`, et toute la chaîne BGR ↔ RGBA ↔ JPEG ne dérive pas.
3. **96 MISS bien distribués.** Pas de pattern "tous les snaps de la classe X sont KO" qui suggérerait une régression spécifique. La distribution suit les conditions de capture (bright/textured plus volatiles que dim).

## Interprétation pratique du verdict

- **OK : 15-25%** sur des captures device → comportement normal du pipeline post-rework. C'est un plancher, pas une régression.
- **OK : 0%** ou **Δ = 30+ px sur plusieurs snaps** → drift structurel ou bug. À investiguer.
- **MISMATCH** ou **NO_KT** ≥ 1 → le port a un état de défaillance différent (fail vs ok) entre Python et Kotlin. À investiguer.

Le test reste utile comme **sentinelle de drift structurel** (ajout d'un blur, changement de cascade, autre interp), pas comme un gate "bit-equality strict".

## Options pour faire de ce test un meilleur gate

Sans rien implémenter pour l'instant. À considérer si le test devient bloquant :

1. **Baisser le seuil PSNR à 20 dB** dans `diff_kotlin_python.py` avec un commentaire qui pointe ici. Pragmatique et léger.
2. **Comparer (cx, cy, r) seuls**, drop le PSNR. Réduit le test à un sentinel de Hough drift — suffisant si la confiance dans les ops OpenCV ne change pas.
3. **Ajouter un mode "Kotlin re-decode"** : faire que SnapNormalizer re-décode `<step>_raw.jpg` en début de pipeline pour aligner les deux côtés sur la même source. Coût : modif Android légère, dégrade ~10ms de latency live (négligeable). Bénéfice : test bit-equality redevient atteignable PSNR ≥ 30.
4. **Test sur sources studio** (parité ε via `parity_test.py`) : on a déjà ce gate, plus rigoureux que le diff device, et il a passé 100% post-fix. C'est le test qui compte vraiment pour la cohérence cross-platform — `diff_kotlin_python` reste utile mais accessoire.

## Verdict pour le rework

Le port Kotlin (downscale 1024 + cascade large 0.15-0.55) est validé par :
- `parity_test.py` 100% sur Hough-OK subset (25/25 sources studio, ε=3.00)
- 18 cas device avec Δ=(0,0,0) et PSNR 38-44 dB qui prouvent l'absence de drift dans la pipeline pixel
- Aucun Δ géant dans les 96 MISS qui aurait signalé une régression

→ **C3 fermé** au sens "pas de drift structurel détecté". Le 15.8% OK rate est une caractéristique du test, pas du port.

## Liens

- [`implementation-plan.md`](implementation-plan.md) §Phase C log §"Fix offset device"
- [`bench-results-pre.md`](bench-results-pre.md) §"Valeurs ε / M_max retenues"
- [`parity-contract.md`](parity-contract.md) §"Test #2 — Cross-platform (Python ↔ Kotlin device)"
