# Phase 5 — Rendu 3D ciblé (optionnelle)

> **Objectif** : pour les paires rouges qui restent irréductibles après les phases 1-4 (cartographie, augmentation 2D/2.5D, enrichissement eBay, sub-center), générer des augmentations issues d'un vrai rendu 3D avec matériaux métalliques physiquement réalistes et éclairage arbitraire.
>
> **Status** : phase OPTIONNELLE. Ne lancer que si les métriques de phase 4 montrent un goulot irréductible sur des paires spécifiques.

## Pourquoi cette phase est optionnelle

Les pièces sont des objets **quasi-planes** (relief de quelques mm sur 20-30mm de diamètre). Le normal-map approximatif généré en phase 2 (niveau 2.5D) capture 80-90% du bénéfice d'un vrai rendu 3D à 5% du coût pipeline.

Le vrai 3D n'apporte de la valeur que dans ces cas précis :
- Paires de pièces où la différence discriminante est un détail en **haut relief** (un motif proéminent vs un autre) dont le shading directionnel change drastiquement l'apparence selon l'angle de lumière. Le normal map approximatif (dérivé de la luminance 2D) sous-estime la hauteur réelle de ces détails.
- Pièces avec **matériau complexe** : bicolore (2€, 1€) dont les deux zones (anneau laiton + centre cupronickel) réagissent différemment à la lumière. Un vrai shader métallique PBR capture ce comportement.
- Effets de **parallaxe** à angle de caméra fort (> 30°) : à tilt élevé, le relief projette des ombres non-triviales que le shading 2.5D approximatif rate.

Si la phase 4 montre que sur les paires rouges résistantes, R@1 < 70%, **et** que l'inspection manuelle des erreurs révèle une des 3 situations ci-dessus, alors la phase 5 est justifiée. Sinon, on s'arrête avant.

## Dépendances

- Phase 4 livrée avec métriques chiffrées
- Identification précise des paires résistantes (< 10 paires probablement)
- Budget temps pour la config Blender/PyRender (compter 3-5 jours de setup pipeline)

## Livrables

### 1. Pipeline de rendu 3D

**Choix technique** : **Blender en mode headless via Python API**, ou **PyRender** (OpenGL-based, plus léger mais matériaux moins riches).

Recommandation : commencer par PyRender pour la rapidité (pas de dépendance Blender lourde), passer à Blender **uniquement** si PyRender ne suffit pas pour les shaders métalliques PBR.

Pipeline :
1. **Reconstruction géométrique** : pour chaque design zone rouge résistante, reconstruire une approximation 3D à partir de :
   - Image obverse Numista → normal map raffiné (pas juste la luminance brute, avec dé-éclairage pour enlever le shading Numista d'origine)
   - Image reverse Numista → idem
   - Épaisseur constante (paramètre de la pièce, connue)
   - Matériau métallique PBR paramétrable (cuivre pour 1c-2c-5c, laiton pour 10c-50c, cupronickel pour 1€-2€ centre, laiton bimétallique pour 1€-2€ anneau)
2. **Rendu paramétrique** :
   - Caméra à angle variable (tilt, rotation, distance)
   - Éclairage HDR variable (map d'environnement aléatoire, ou 1-3 point lights)
   - Exposition variable
3. **Export** : images PNG à 512×512 ou 1024×1024, puis downsampling pour matcher le format training

**Cache** : une reconstruction 3D par design est faite **une seule fois** et sérialisée (mesh + textures). Seul le rendu final est recalculé pour chaque variation.

### 2. Textures saleté 3D

Pour aller au-delà des overlays 2D (phase 2) :
- Applique des textures de saleté **en espace 3D** avant rendu
- La saleté s'accumule dans les creux de manière physiquement correcte (via AO — ambient occlusion calculé sur le mesh)
- Résultat : une pièce qui a "vécu", avec de la crasse dans les gravures profondes et des surfaces planes plus propres

### 3. Banque de rendus pré-calculés

Pour éviter de faire tourner le 3D en temps réel à chaque epoch de training :
- Pré-calculer 100-200 rendus par design zone rouge résistante
- Variations : angles caméra, éclairage, saleté
- Stockés dans `ml/data/rendered/{eurio_id}/*.jpg`
- Ingested par le dataset loader au même titre que Numista + eBay

### 4. Vue admin `RenderingPage.vue` (minimale)

Emplacement : `admin/packages/web/src/features/rendering/pages/RenderingPage.vue`.

- Liste des `eurio_id` qui ont un modèle 3D reconstruit
- Preview des rendus par design (grille de 16)
- Bouton **"Re-rendre"** pour regenerer la banque d'un design (utile si on ajuste les params)
- Stats : nb rendus par design, taille totale sur disque

### 5. Intégration training

Le dataset loader `ml/training/dataset.py` lit maintenant 3 sources :
- Images Numista (toujours)
- Photos eBay validées (phase 3)
- Rendus 3D (phase 5, uniquement pour les coins flaggés `needs_3d_augmentation`)

Ratio d'échantillonnage : tunable par zone. Pour un coin avec 3D : ~40% Numista (+ aug 2D), ~30% eBay, ~30% rendus 3D.

## Non-livrables (explicites)

- Pas de scan 3D physique des pièces (hors scope)
- Pas de modélisation manuelle dans Blender (trop coûteux humainement)
- Pas d'extension à l'ensemble du catalogue (uniquement paires rouges résistantes, probablement < 20 designs)

## Métriques de sortie

Sur les paires cibles uniquement :
- R@1 avant / après ajout du 3D
- Distribution des erreurs : est-ce que les erreurs résiduelles viennent d'angles particuliers, de conditions d'éclairage particulières ?
- Gain marginal par rapport à sub-center seul

## Critères d'arrêt

Cette phase est bounded : soit elle débloque les paires cibles (R@1 ≥ 85% sur celles-ci), soit elle montre qu'il y a un plafond intrinsèque (deux designs trop proches physiquement pour être distingués avec certitude → décision produit : accepter la confusion et afficher un UI "2 candidats" à l'utilisateur plutôt que forcer un choix).

## Risques / points d'attention

- **Coût pipeline élevé** : Blender/PyRender + shaders PBR + reconstruction auto depuis 2D = plusieurs jours de setup. À ne faire que si le payoff est clair.
- **Sim-to-real gap** : les rendus 3D peuvent être trop "parfaits" visuellement et créer leur propre artefact de style (rendering artifacts). Le modèle peut apprendre à reconnaître "c'est un rendu" plutôt que le design. Mitigation : post-traitement des rendus avec du bruit camera-like, compression JPEG, chromatic aberration.
- **Reconstruction 3D auto peu fiable** : la profondeur inférée depuis une seule image 2D est inherently ambiguous. Un vrai scan 3D physique des pièces cibles (avec un téléphone iPhone Pro + LiDAR) serait plus fiable mais hors scope.
- **Plafond fondamental** : si deux pièces commémoratives partagent littéralement 99% de leur design (ce qui arrive pour les émissions communes eurozone), aucune augmentation ne les distinguera. Il faut accepter ce plafond et le matérialiser UX-side (proposer les 2 candidats à l'utilisateur, fallback date/millésime via OCR fin si possible).
- **ROI diminishing** : chaque phase après la 4 a un ROI décroissant. Bien garder à l'esprit qu'atteindre 100% est impossible et probablement pas l'objectif produit — 90-95% R@1 global avec une UX propre pour les 5-10% ambigus est probablement un meilleur target que 99% R@1 forcé.

## Alternative à considérer avant de lancer cette phase

**Plan B : fallback UX plutôt que perfection ML.**

Au lieu d'investir dans la phase 5, accepter qu'il reste des paires ambiguës et construire côté app :
- Quand le scan retourne 2 candidats à similarité proche (spread < 0.05), afficher une UI "2 candidats possibles, clique sur la bonne" avec les 2 images Numista
- L'utilisateur tranche en 1 clic
- Ce signal est remonté (implicitly labeled data) et peut réalimenter le training set

Cette approche est **beaucoup moins chère** que la phase 5 et apporte probablement une meilleure UX (transparence > fausse certitude). À comparer honnêtement au coût de la phase 5 avant de la lancer.
