# Finding 02 — SOTA research is_coin scoring

## Approche A — Radial gradient + rim/ring profile (OpenCV pur)

- **Idée** : profil 1D du gradient en coordonnées polaires autour du centre. Une vraie pièce bien cadrée présente un pic de gradient marqué et continu sur 360° au rayon nominal (rim métallique), une variance moyenne sur le disque, et — pour les 2 € bimétal — un second anneau de gradient interne. Timbres/logos/watermarks n'ont pas ce double signal radial + continuité angulaire. Score = (intensité pic rim) × (continuité angulaire) × (uniformité radiale du disque).
- **Coût impl** : low (200 lignes OpenCV/NumPy, `cv2.warpPolar` + profils).
- **Coût runtime** : ~2-5 ms/crop CPU, 0 MB modèle.
- **Évidence** : foundations Hough/coin Geeksforgeeks / shrishailsgajbhar ([1](https://www.geeksforgeeks.org/cpp/opencv-c-program-for-coin-detection/), [2](https://shrishailsgajbhar.github.io/post/OpenCV-OpenCV-Basic-Project-1)) ; pas de paper dédié 2024-2026 sur rim-scoring spécifique, mais signal physique trivialement vérifiable sur nos crops.
- **Verdict** : **à tester en premier**. Coût quasi nul, interprétable, et cible directement les FP listés (timbre = pas de rim métallique continu ; anneau interne bimétal = pas de second rim externe → rejeté).

## Approche B — DINOv2 prototype similarity (réutilise modèle déjà en repo)

- **Idée** : on a déjà DINOv2 ViT-S/14 chargé pour le matcher. Calculer N prototypes (mean embedding) à partir de ~20-50 crops "bonne pièce" curés, et N′ prototypes "FP" (timbre, logo, crop intérieur). Score is_coin = cos(crop, proto_coin) − cos(crop, proto_FP). kNN sur banque d'ancres marche en zero/few-shot.
- **Coût impl** : low-med (embeddings déjà calculés dans pipeline, ajouter un banc d'ancres + 1 dot-product).
- **Coût runtime** : 0 ms additionnel (embedding déjà fait), ~85 MB modèle déjà chargé.
- **Évidence** : DINOv2 kNN 83.9% zero-shot sur fine-grained ([Towards AI](https://towardsai.net/p/computer-vision/harness-dinov2-embeddings-for-accurate-image-classification)) ; prototype feature bank validé pour OOD detection ([Finding Dino, arXiv 2404.07664](https://arxiv.org/html/2404.07664v2)).
- **Verdict** : **à tester en second**, complémentaire de A. Capte la sémantique ("ça ressemble à une pièce") là où A capte la géométrie.

## Approche C — SigLIP / CLIP zero-shot "a photo of a coin"

- **Idée** : prompts texte ("a photo of a euro coin" vs "a photo of a postage stamp / logo / watermark"), score softmax.
- **Coût impl** : low.
- **Coût runtime** : ~50-150 ms/crop CPU, 200-400 MB modèle (SigLIP base) ([HF SigLIP](https://huggingface.co/google/siglip-base-patch16-224), [OpenVINO SigLIP](https://docs.openvino.ai/2024/notebooks/siglip-zero-shot-image-classification-with-output.html)).
- **Verdict** : **à éviter** — dépasse budget 50 MB, redondant avec DINOv2 déjà en repo, et "coin" trop générique pour distinguer une vraie pièce d'un crop intérieur bimétal.

## Recommandation

Lancer **Approche A (radial/rim OpenCV)** en premier expé. Trois raisons : (1) coût impl et runtime quasi nuls, donc rétro rapide ; (2) interprétable — on saura *pourquoi* un FP est rejeté, ce qui informera le tuning des stages amont ; (3) cible le mode d'échec dominant (anneau interne bimétal pris pour pièce) que CLIP/DINOv2 sémantique ne distingue probablement pas. Si A laisse un résidu de FP sémantiques (logos circulaires métalliques), enchaîner avec **B (DINOv2 prototypes)** en cascade — A filtre la géométrie, B filtre la sémantique, sans charger de modèle supplémentaire.
