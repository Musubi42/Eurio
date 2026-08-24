# Limites connues — à garder en tête avant d'analyser

## L1. `area_ratio` ≠ undercrop bimétal

Le signal `area_ratio = bbox / min(raw)²` calculé serveur n'est PAS un
détecteur fiable d'undercrop bimétal. Sondage sur run 059dc8d9 :

| seuil | % crops flagged |
|-------|-----------------|
| 0.50  | 99.2 %          |
| 0.20  | 91.2 %          |
| 0.10  | 74.1 %          |
| 0.05  | 48.9 %          |
| 0.03  | 13.8 %          |

Distribution graduelle sans palier par méthode. Cause : une photo eBay
peut légitimement cadrer une pièce sur 5 % du raw (vue large + arrière-plan).
La heuristique ne distingue pas ce cas du vrai bug bimétal où Hough vote
l'inner ring.

**Conséquence pour ce chantier** : ne pas se fier au flag is_undercrop_suspect
comme oracle. Utiliser le jugement visuel humain (= moi qui regarde les
screenshots).

## L2. `quality_score` jamais wiré

Le champ existe en schema, dedup.py l'accepte en input, mais aucun
producer ne calcule de valeur. Toujours NULL sur tout le run. La section
"quality histogram" de la vue analytics est masquée.

**Conséquence** : pas de signal automatique de qualité. À nouveau : œil
humain.

## L3. La bbox stockée = cercle inscrit (cx-r, cy-r, 2r, 2r)

Pas la région exacte du crop (qui inclut margin + edge clamp + square snap).
Petite discrepancy de ~2 % entre ce que la bbox indique et ce que le crop
résultant contient. Acceptable pour un debug visuel.

## L4. `normalize_listing` est déterministe mais pipeline-dépendant

Si on change le code Python (passes Hough, polish, YOLO conf threshold),
les ordres de crops sortent différemment et `crop_index` ne matche plus
les anciens image_assets. Le backfill nécessitera un re-run complet pour
des changements significatifs.

## L5. Les recherches eBay sont des QUERIES, pas des vérités terrain

`target_eurio_id` sur un listing eBay = ce que la query cherchait (ex:
"2 € Italie 2002"). Le contenu RÉEL du listing peut être une autre pièce
(eBay rempli de bruit), un lot multi-pièce, un certificat, etc. On ne
peut pas considérer le `target_eurio_id` comme "ground truth" du contenu.

## L6. Photos d'album = multi-pièce dans un raw

Beaucoup de listings 2 € commémo vendent des ALBUMS (sets) contenant
plusieurs pièces. Le pipeline détecte chaque pièce comme crop séparé,
mais souvent ce sont des pièces différentes (millésimes ou pays
différents). On ne peut pas évaluer "la pièce est-elle la bonne" sans
ground truth — uniquement "le crop est-il bien centré et complet" sur
quelque pièce que ce soit.
