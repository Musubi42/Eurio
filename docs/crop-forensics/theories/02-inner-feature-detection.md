# Théorie 02 — Hough vote un cercle intérieur sur les macro shots

## Hypothèse

Quand un raw est dominé par UNE seule grande pièce (macro shot, vendeur
pro), Hough trouve un cercle intérieur (le "10", l'inner gold ring du
bimétal, un détail gravé) avec un score local fort, et le pipeline le
retient comme "le crop" au lieu de prendre la pièce entière.

Variante du bug bimétal ancestral mais plus large : tout cercle intérieur
peut bouffer le vrai cercle pièce.

## Évidence (observation)

- Card DE-2010-yolo+hough #4 : raw 1600×1280 avec énorme pièce, bbox tiny
  sur le millésime "10".
- Card DE-2007-yolo+hough+polish #1 : énorme pièce sur fond noir, bbox sur
  une feature interne.

## Test falsifiable

Pour chaque crop du run :
- `image_dominance = max_circle_inscribed_in_raw / current_bbox_area`
- Si dominance > 5x et le raw a un seul "vrai" cercle externe → c'est un
  inner feature.

Échantillonner 30 crops à dominance > 5, vérifier humainement combien sont
des inner features. Si > 50 %, confirmé.

## Fix prédit

**Re-rank Hough candidates par taille** quand la 2e taille est >> 2× la 1ère :
- Détecter tous les cercles cohérents (même cx,cy ± tolerance) dans la roi.
- Si on a candidates C1 (small) et C2 (large) avec C2.r > 1.8 × C1.r, et
  C2 est cohérent (centre proche de C1, structure score acceptable),
  **prendre C2 au lieu de C1**.

Implémentation dans `_hough_refine_in_roi` côté `normalize_snap.py`. ~30
lignes.

## Coût d'implémentation

Moyen — modif du Hough refine est délicate (peut casser des cas qui
marchaient). Test A/B nécessaire sur un set.

## Statut

❌ **Refuted comme post-filter** (S5 + S6, 2026-05-27).

- S5 (full DE/2010, 221 assets) : TOP-30 ≈ 13 % cat B authentique,
  dominé par cat C album. → [experiments/04](../experiments/04-anti-b-inner-feature.md)
- S6 (true singles, n_crops_detected=1, 30 raws) : signal plus propre
  mais TOP-30 cat B fort ≈ 33-40 %. Loin du seuil 80 %.
  → [experiments/05](../experiments/05-anti-b-inner-feature-singles.md)

Cause racine : le ratio max-circle/bbox est saturé sur tout macro shot
(zoom fort → grand cercle plausible toujours trouvable). Pour
discriminer cat B strict, il faudrait un signal "rim manquante à un
radius > bbox" plutôt qu'une simple comparaison de tailles.

Le fix prédit (re-rank Hough candidates *upstream* dans
`_hough_refine_in_roi`) reste théoriquement viable mais hors-scope
"post-filter pur" — à reprendre seulement si on autorise des modifs
producer.
