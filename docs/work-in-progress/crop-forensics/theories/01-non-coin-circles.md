# Théorie 01 — Le pipeline détecte des cercles non-pièce

## Hypothèse

Le pipeline accepte comme "pièce" toute détection circulaire YOLO + Hough
suffisamment confiante, sans valider que l'objet ressemble vraiment à une
pièce de monnaie. Conséquence : timbres ronds, logos circulaires, watermarks,
médaillons décoratifs, capsules vides sont taggés "crops valides".

Cf. cat. A de [[findings/01-observation-pass-1]].

## Évidence (observation)

- Cards AT-2005-yolo+hough #8, DE-2007-yolo+hough #2, IT-2016 panel
  Donatello : bbox sur éléments graphiques non-monétaires.
- Volume estimé visuellement : ~10-15 % des crops.

## Test falsifiable

Sur un échantillon de 50 crops aléatoires du run, classer humainement
"pièce" / "non-pièce". Si on observe ≥ 5 % de "non-pièce", l'hypothèse
est confirmée. Si < 2 %, infirmée.

## Fix prédit

Un **post-detection scoring "is_coin"** appliqué APRÈS Hough/polish, AVANT
de produire un image_asset. Trois signaux candidats à combiner :

1. **Contraste rim/interieur** : une pièce a un rim métallique distinct du
   centre (motif visible). Un logo ou timbre est plus uniforme. Calcul :
   `var(intensity inside ring r-3..r) / var(intensity inside disk 0..r-5)`.
2. **Pattern radial gradient** : une pièce a une signature radiale (rim +
   gravures concentriques) absente sur un logo plat.
3. **Couleur dominante** : les pièces sont gris/argent/or/cuivre — un timbre
   ou logo est souvent coloré (rouge, bleu).

Implémentation : `is_coin_score(bgr, cx, cy, r) -> float in [0, 1]`. Si
score < seuil τ, marquer le crop comme `rejected` (pas inséré, ou inséré
avec `resolution_status='rejected'`).

## Coût d'implémentation

Bas. ~50 lignes Python OpenCV. Pas de modèle ML. Le seuil τ à calibrer
sur un set humain (50 crops labellés).

## Statut

`pending` — à tester en expérience 01.
