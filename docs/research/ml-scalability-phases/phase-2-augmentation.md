# Phase 2 — Augmentation 2D avancée + re-lighting 2.5D

> **Objectif** : combler le gap entre "pièce scannée studio Numista" et "pièce dans la main de l'utilisateur" par des augmentations synthétiques avancées. Cible les zones verte + orange en priorité (les 70-85% du catalogue où enrichissement photo n'est pas strictement nécessaire).

## Pourquoi cette phase après la cartographie

- La cartographie (phase 1) nous dit **quelles pièces** bénéficient le plus de meilleures augmentations (zones verte/orange où on n'ira pas chercher de vraies photos eBay).
- Pour les zones rouges, l'augmentation seule ne suffira jamais — on y ajoutera de vraies photos (phase 3). Mais même sur zone rouge, de meilleures augmentations aident.
- Mesurer l'effet de la nouvelle augmentation **à carte constante** permet d'isoler la contribution de la phase 2 avant de rajouter la variable "nouvelles photos" en phase 3.

## Dépendances

- Phase 1 livrée (cartographie consultable pour cibler les zones)
- Pipeline d'augmentation actuel dans `ml/` (rotation, color jitter, blur, backgrounds aléatoires, masque circulaire)

## Gap identifié dans le pipeline actuel

Inventaire de ce qu'on fait **déjà** :
- Rotation 360° ✓
- Color jitter ✓
- Blur ✓
- Backgrounds aléatoires (bois, tissu, gradient) ✓
- Masque circulaire ✓

Inventaire de ce qui **manque** et qui compte :
- ❌ **Perspective warp (tilt)** — la caméra utilisateur n'est jamais parfaitement perpendiculaire à la pièce
- ❌ **Saleté / patine** — les pièces circulées sont sales, tarnies, avec des taches
- ❌ **Spécularités métalliques** — reflets/hotspots directionnels sur une surface métallique
- ❌ **Re-lighting directionnel** — ombres portées dans les creux du relief selon l'angle de la lumière
- ❌ **Flou de bougé caméra** (motion blur) — différent du blur gaussien
- ❌ **Dégradation d'usure** — relief aplati des pièces anciennes (partiel : color desat + low-pass)

## Livrables

### Niveau 1 — Augmentations 2D avancées

Extension du pipeline `ml/training/augmentations.py` (ou équivalent) :

**1. Perspective warp**
- OpenCV `cv2.warpPerspective` avec homographie aléatoire
- Paramètres : tilt angle jusqu'à ±25° sur X et Y, plus rotation 2D (déjà présente)
- Probabilité d'application : 0.6 (fréquent)

**2. Dirt / patina overlays**
- Banque de textures `ml/data/overlays/` :
  - `patina/*.png` — textures de patine cuivre/laiton (~20 textures, générables via Blender procedural ou scraping libre de droits)
  - `scratches/*.png` — rayures et micro-rayures
  - `fingerprints/*.png` — traces de doigts
  - `dust/*.png` — poussière et particules
- Blend modes : multiply (pour assombrir), overlay, screen, avec opacité aléatoire 0.1-0.4
- Probabilité : 0.5, avec 1-3 overlays cumulés
- Masquage circulaire pour rester dans la pièce

**3. Spécularités métalliques**
- Génère 1-3 "hotspots" ellipsoïdaux aléatoires sur la pièce
- Blend mode : screen (éclaircit)
- Simule un reflet de lumière ambiante sur métal
- Probabilité : 0.4

**4. Motion blur directionnel**
- `cv2.filter2D` avec kernel directionnel
- Angle aléatoire, magnitude 3-15px
- Probabilité : 0.2

**5. Color grading non-uniforme**
- Ternissement par zone : vignette sombre + virage chromatique local (vert pour cuivre oxydé, brun pour laiton)
- Probabilité : 0.3

### Niveau 2 — Re-lighting 2.5D

Ajout d'une étape optionnelle dans le pipeline : **générer un normal map approximatif depuis la luminance de l'image Numista**, puis re-éclairer avec une source directionnelle.

**Pourquoi ça marche sur les pièces** : une pièce est quasi-plane avec un relief de quelques mm. Sur un scan Numista parfaitement éclairé et perpendiculaire, la luminance locale corrèle fortement avec l'altitude du relief (creux = ombre, haut = lumière). Donc `normal_map ≈ f(gradient(luminance))`.

**Pipeline** :
1. Convertir image Numista → grayscale, lisser (Gaussien σ=2)
2. Calculer gradients Sobel X et Y
3. Construire normal map `(-dx, -dy, 1)` normalisé
4. Pour chaque sample augmenté :
   - Tirer une direction de lumière aléatoire (hémisphère au-dessus)
   - Calculer Lambertian shading : `dot(normal, light_dir)` clamped
   - Multiplier l'image par ce shading
   - Résultat : l'image a maintenant des ombres dans les creux qui dépendent de l'angle de lumière

**Coût** : O(pixel count). Calculable en pré-process ou à la volée. Une fois le normal map généré par design (une fois pour toute, cacheable), le shading par-frame est ~5ms.

**Probabilité d'application** : 0.5

Ce niveau 2 est **clé** : il transforme une image Numista unique en N images convaincantes sous N éclairages différents, ce qui attaque directement le problème "l'éclairage user ne sera pas studio".

### Paramétrage par zone

Le pipeline accepte un paramètre `zone` en entrée et adapte l'intensité :
- **Zone verte** : augmentations modérées (on ne veut pas casser les features distinctives d'un design déjà isolé)
- **Zone orange** : augmentations standard
- **Zone rouge** : augmentations maximales + test-time augmentation prévu en phase 4

Implémentation : preset `mild` / `standard` / `aggressive` dans la config.

### Script de prévisualisation admin

`ml/scripts/preview_augmentations.py` :
- Prend un `eurio_id` en entrée
- Génère une grille 4×4 de samples augmentés
- Sort une PNG visible dans l'admin

Intégration admin : dans `CoinDetailPage.vue`, ajouter un bouton "Prévisualiser augmentations" qui appelle le backend ML local et affiche la grille. Permet de voir visuellement si les augmentations sont réalistes ou si elles déforment trop.

### Re-training et re-cartographie

Après implémentation des augmentations :
1. Re-train le modèle ArcFace avec le nouveau pipeline d'augmentation (mêmes 7 classes pour commencer, validation sur dataset de test existant)
2. Re-run la cartographie de phase 1 **avec notre modèle re-entraîné** comme encodeur (pas DINOv2 cette fois)
3. Comparer :
   - La distribution des similarités intra-classe (devrait être plus serrée = le modèle reconnaît la même pièce sous variations diverses)
   - La distribution des similarités inter-classes (devrait être plus spread = le modèle distingue mieux)
   - Le nb de paires en zone rouge (devrait diminuer)

## Non-livrables (explicites)

- Pas d'enrichissement avec de vraies photos (phase 3)
- Pas de sub-center ArcFace (phase 4)
- Pas de rendu 3D Blender (phase 5)
- Pas de changement de backbone ou de loss

## Métriques de sortie

Avant/après pour comparer :
- **Distribution des spreads top1-top2** sur le test set actuel
- **R@1 / R@3** sur test set actuel (devrait rester ≥ 99%)
- **Robustness test** : test set tenu de côté avec images **vraiment perturbées** (tiltées à la main, sous éclairage crappy si on peut en produire quelques-unes). On attend une amélioration notable ici.
- **Redistribution des zones** après re-cartographie avec nouveau modèle

## Critères de passage à la phase suivante

- Pipeline d'augmentation niveau 1 + 2 implémenté et utilisé par défaut
- Preview admin fonctionnel
- Re-training effectué, métriques avant/après consignées
- Confirmation empirique qu'il reste des paires en zone rouge qui **ne** s'améliorent **pas** significativement avec de meilleures augmentations (ce qui justifie la phase 3 : de vraies photos)

## Risques / points d'attention

- **Overfitting aux artefacts d'augmentation** : si les overlays sont générés de façon trop répétitive, le modèle peut apprendre à les reconnaître plutôt qu'à les ignorer. Diversité de la banque de textures cruciale.
- **Sur-augmentation qui casse les features** : si on détruit trop de signal (blur maxi + dirt maxi + hotspots maxi cumulés), le modèle ne peut plus apprendre. D'où les presets par zone.
- **Normal map approximatif faux sur pièces à très haut relief** : sur une commémorative avec un haut relief marqué, l'approximation luminance→altitude peut être moyenne. Acceptable pour commencer, raffinable en phase 5 si besoin (normal map scanné).
- **Coût compute training** : plus d'augmentations = plus de variété, potentiellement plus d'epochs nécessaires. À surveiller.
