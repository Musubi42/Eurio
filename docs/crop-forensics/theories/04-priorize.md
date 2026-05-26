# Théorie 04 (méta) — Priorisation pour le premier expé

## Lecture combinée 01 + 02 + 03

Les 3 théories partagent un dénominateur commun : **on a besoin d'un score
"is_this_really_a_well_cropped_coin" qu'on peut appliquer post-pipeline**.

- Th. 01 demande "est-ce une pièce ?" → bg_uniformity + inside_metalness
- Th. 02 demande "n'est-ce pas un inner feature ?" → radial_grad_score
  externe vs interne + dominance check
- Th. 03 demande "comment remplacer area_ratio ?" → composite des 3 ci-dessus

Donc la 1ère expé optimale : **construire ce scorer composite, l'appliquer
sur le run 059dc8d9, et inspecter visuellement si le tri par score capture
bien les cas A+B**. Si oui, on aura un filtre opérationnel sans toucher au
pipeline (juste un post-filter au moment de l'insert image_assets).

## Plan expérience 01

1. Écrire `ml/scripts/crop_exp/score_crops.py` :
   - Pour chaque image_asset du run, charger le crop (224×224) et le raw +
     bbox.
   - Calculer 3 signaux : bg_uniformity, inside_metalness, radial_grad_score.
   - Ajouter une colonne JSON `crop_quality_signals` dans `image_assets`
     (migration légère) OU stocker dans un sidecar fichier.
2. Construire le sampler "tri par score croissant" — les pires scores en
   haut.
3. Inspection : sur 30 cards lowest-score, combien sont des cat A ou B ?
   Sur 30 cards highest-score, combien sont des cat D ?
4. Verdict : si bottom-30 est ≥ 70 % A+B et top-30 ≥ 80 % D → win.

## Bénéfice de garder le pipeline producer intact

Si l'expé valide le scorer, on a un filtre downstream qu'on peut :
- afficher comme overlay sur le bench (remplace le rouge area_ratio)
- utiliser comme tri par défaut
- éventuellement plus tard, brancher comme reject automatique côté pipeline
  (image_asset.resolution_status='rejected' si score < τ)

Aucune modif risquée du pipeline de détection. Faible coût.

## Décision

→ Exécuter cette expé 01 en priorité.
