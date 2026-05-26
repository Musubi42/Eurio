# Théorie 03 — `area_ratio` est un signal trop bruité pour servir de filtre

## Hypothèse

Le `area_ratio = bbox / min(raw)²` du bench backend confond deux choses :
- vrai undercrop (Hough a manqué le rim, ex: cas bimétal)
- petite pièce légitimement cadrée large par le vendeur eBay

Le mask rouge "undercrop suspect" crie au loup ~75 % du temps. Inutile
comme filtre. C'est confirmé dans [[01-known-limits.md#L1]] et observé
dans [[findings/01-observation-pass-1]].

## Évidence

Sondage : à seuil 0.10, 74 % des crops sont flag. Pas de palier par méthode.

## Test falsifiable

Échantillonner 30 crops avec area_ratio < 0.05 ; classer "vrai undercrop"
vs "petite pièce légitime". Si > 70 % sont légitimes, le signal est
inutile.

## Fix prédit

**Remplacer area_ratio par un score composite** :
- `bg_uniformity` : variance des pixels HORS bbox. Faible = vendeur a mis
  un fond uniforme (légitimement petit) ; forte = la pièce est noyée dans
  un environnement, suspect.
- `inside_metalness` : ratio de pixels avec saturation < 30 et valeur
  100-220 (gris/argent/or) DANS la bbox. Faible = pas vraiment une pièce.
- `radial_grad_score` : amplitude du gradient radial entre r-5 et r+5.
  Forte = vrai rim. Faible = bord flou ou cercle factice.

Le composite remplace `is_undercrop_suspect` côté serveur. Sera aussi utile
pour la théorie 01.

## Coût d'implémentation

Bas. ~80 lignes Python OpenCV. Mais nécessite calibration du seuil sur set
labellisé.

## Statut

`pending`. Possible mutualisation avec théorie 01 (mêmes signaux).
