# Coin 3D Viewer — décisions

Format : décision | raison | conséquences. Inclut explicitement les **chemins
rejetés** pour ne pas re-brainstormer dans 6 mois.

> **Toutes les décisions D1–D8 ci-dessous sont validées en proto Three.js
> ET en production Android (SceneView/Filament).** Les paramètres PBR
> (metalness/roughness/normalScale, IBL, tone mapping ACES, ratio 2-key) se
> transposent 1:1. Pour les décisions spécifiques au portage Android (matc
> toolchain, lifecycle textures Filament, custom material `.filamat`,
> animation flip Compose), voir `porting-android.md` (D-PORT-1 à 7).

## Décisions actées

### D1. Mesh procédural unique pour les 2€
- **Décision** : un mesh bimétal partagé pour TOUTES les 2€ (même géométrie : Ø 25.75, anneau argent, disque or, tranche, rebord saillant).
- **Raison** : règlement EU impose des cotes physiques identiques par dénomination. Pas besoin de 500 modèles 3D.
- **Conséquence** : la **photo Numista** porte toute la variation visuelle (design d'avers, étoiles plus ou moins entremêlées, année sur le rebord, etc.). Le mesh ne change pas.

### D2. Mapping UV "XY direct" depuis la photo
- **Décision** : chaque vertex de la face d'anneau ou du disque tire son UV de sa position (x, y) en 3D, normalisée par les dimensions de la pièce. Continuité photo automatique entre anneau, disque et rebord.
- **Raison** : c'est la projection orthogonale top-down de la photo Numista. Aucune couture à gérer.
- **Conséquence** : le rebord saillant (R_OUT − RIM_WIDTH à R_OUT) hérite naturellement du contenu photo correspondant — la bande lisse de bord, voire les pointes des étoiles selon le design.

### D3. Normal map subtile via Sobel sur luminance
- **Décision** : calcul d'une normal map au runtime (~100ms, JS pur) via gradient Sobel de la luminance de chaque photo. `normalScale = 0.30` par défaut.
- **Raison** : le scan Numista contient déjà la majorité de l'info de relief sous forme de variations lumineuses. La normal map est un **enhancer subtil** qui anime la lumière sur les reliefs sculptés, pas un substitut de relief.
- **Conséquence** : sous éclairage statique, l'effet est indiscernable. Mais quand la lumière balaye (rotation, animation flip), les highlights glissent sur les reliefs comme sur un objet vrai.

### D4. Pré-mirroir horizontal du reverse
- **Décision** : la photo reverse est flippée horizontalement avant d'être plaquée sur la face arrière du mesh.
- **Raison** : géométriquement, regarder la face arrière d'un disque opaque depuis la caméra opposée donne une image **mirrorée** de ce qu'on voit côté face. Mais l'utilisateur s'attend à lire le reverse comme sur le scan Numista (lisible). On corrige cette dissonance.
- **Conséquence** : le texte du reverse ("VON WARSCHAU", "EURO", etc.) se lit normalement quand on tourne la pièce. La normal map du reverse est dérivée du canvas pré-mirroré pour cohérence highlights/relief.

### D5. Tranche procédurale haute résolution
- **Décision** : la texture de la tranche est générée au runtime (canvas 4096×256) avec moletage vertical (~280 stries) + 6× "2 ★ ★ ★" alternés upright/inverted en incisé sombre.
- **Raison** : aucune source publique propre d'unwrapped edge scan trouvée. Le scan FR Wikimedia testé donnait du 162×14 — qualité dégradée par rapport aux faces.
- **Conséquence** : tranche **non spécifique au pays** pour le moment. Acceptable pour le proto et probablement la v1 prod. À industrialiser per-pays si besoin (table d'inscriptions par ISO + générateur).

### D6. Lighting deux clés (front + back-key)
- **Décision** : deux DirectionalLight, l'une à `(2.5, 3.5, 4.0)` intensité 1.4, l'autre opposée à `(-2.5, -3.5, -4.0)` intensité 1.0.
- **Raison** : avec une seule lumière directionnelle, la face arrière de la pièce reçoit le contre-jour quand la caméra tourne — face plate et sombre. Deux lumières (style studio photo key + back-key) donnent des deux côtés un rendu vivant.
- **Conséquence** : les deux faces brillent quel que soit l'angle. Légèrement non-physique (deux soleils), mais conforme à l'attente utilisateur (Numista shoote chaque face avec son propre rig).

### D7. Boost normalScale +33% sur le reverse
- **Décision** : le reverse a un multiplicateur `REVERSE_RELIEF_BOOST = 1.33` sur sa `normalScale`.
- **Raison** : le design reverse standard 2€ (carte d'Europe gravée en lignes fines) est intrinsèquement plus plat que les avers commémoratifs. Sans boost, la face arrière paraît systématiquement moins riche.
- **Conséquence** : compensation visuelle qui tend à équilibrer la perception entre les deux faces. À retuner en cas de design reverse exceptionnellement riche.

### D8. Métadonnées per-photo, pas de modification des photos
- **Décision** : pour gérer les variations Numista (cadrage, centrage), on stocke `{cx_uv, cy_uv, radius_uv}` par photo en métadonnées séparées. Au runtime, le mapping UV utilise ces metas. Les photos originales restent **intouchées**.
- **Raison** : les photos Numista sont notre **source de vérité** historique. Les modifier (crop, white-balance, etc.) crée une dette de fidélité — quand on voudra ré-évaluer, comparer, valider.
- **Conséquence** : un script offline (`ml/measure_photo_meta.py`) calcule les metas une fois, exporté en JSON. Le moteur 3D applique au render. Aucune transformation destructive.

## Chemins rejetés

### R1. ❌ Pré-cropper les photos pour les uniformiser
- **Pourquoi rejeté** : modifie les originaux. Voir D8.
- **Alternative retenue** : metadata + crop virtuel via UV.

### R2. ❌ Delighting (retirer la lumière baked dans la photo)
- **Pourquoi rejeté** :
  - Méthode 1 (low-pass divide) : risque de dégrader les couleurs et de produire des artefacts sur les zones uniformes. Probablement échec.
  - Méthode 2 (modèle ML — Stable Diffusion ControlNet, etc.) : trop lourd pour un viewer 3D. Sort du scope.
  - **Bonus** : accepter la variabilité d'éclairage des scans Numista est en fait un bénéfice — sans ça, les pièces auraient toutes le look "modèle 3D synthétique uniforme", on perd l'authenticité.
- **Alternative retenue** : on accepte la variance. Notre clé directionnelle reste assez subtile (1.4 + 1.0 d'intensité, vs IBL ~1.0) pour ne pas trop combattre la lumière déjà cuite dans la photo.

### R3. ❌ Photogrammétrie / scan 3D des pièces
- **Pourquoi rejeté** : nécessite un workflow physique (scanner ou ~50 photos sous angles différents par pièce). 500+ pièces de 2€, infaisable.
- **Alternative retenue** : mesh procédural + photo plaquée. La normal map dérivée capture suffisamment de l'illusion de relief pour le scope du viewer.

### R4. ❌ Rejeter les photos Numista de basse qualité
- **Pourquoi rejeté** : Numista est notre meilleure source. Filtrer = perdre des entrées de catalogue. On préfère un rendu inégal qu'un catalogue incomplet.
- **Alternative retenue** : on score la qualité (variance Laplacien) à l'ingestion future et on flag `low_quality = true` en metadata, mais on rend quand même.

### R5. ❌ Tranches per-pays scrapées de Wikimedia
- **Pourquoi reporté** :
  - Pas de banque centralisée d'unwrapped edge scans.
  - Licences hétérogènes par image Wikimedia (CC-BY-SA, public domain, fair use… variable).
  - 20+ pays émetteurs actuels = 20+ images à curer/vérifier/attribuer.
- **Alternative retenue (v0)** : tranche procédurale unique pour toutes les pièces (D5).
- **Si on veut industrialiser** : table `edge_inscriptions[iso]` + générateur procédural per-pays (texte + style), pas scraping.

### R6. ❌ Lumière qui suit la caméra
- **Pourquoi rejeté** : casse l'illusion d'un objet réel dans un environnement. Le rendu paraît "videogame-y", on perd la signature studio photo.
- **Alternative retenue** : deux clés fixes en world-space (D6).

### R7. ❌ Mesh par variante 2€ (commémorative vs commune)
- **Pourquoi rejeté** : règlement EU impose des cotes physiques identiques pour TOUTES les 2€. La variation est purement visuelle, donc capturée par la photo. Le mesh reste un.
- **Note** : ce **rejet ne s'applique PAS aux autres dénominations** (1€, 50¢, etc.) qui ont des géométries distinctes. À traiter via factory quand on étendra.

## Decision queue

- ✅ **Q1.** ~~Comment l'animation flip s'intègre dans le flow scan → fiche~~ — résolu en Phase 5 du portage Android : `rotationY 0→720°` (tween 600 ms) + `scale 0.85→1.0` (spring) via `Modifier.graphicsLayer`, `ScanAcceptedCard` slide-in à +400 ms. Cf. `porting-android.md`.
- ✅ **Q4.** ~~Photo Numista manquante~~ — résolu : `CoinDetailScreen` retombe sur le `CoinImageCarousel` (180dp gold disc avec face value) quand `coin.imageObverseUrl == null`. Pareil pattern dans `Coin3DViewer` qui rend des matériaux flat silver/gold tant que les textures ne sont pas chargées.
- ⏳ **Q2.** Présentation pour les pièces non-2€ : factory de mesh par dénomination, ou rendu 2D dégradé en attendant ?
- ⏳ **Q3.** Tranche per-pays : générateur procédural avec inscriptions textuelles, vraie banque scannée curée, ou rester sur la tranche générique ?
