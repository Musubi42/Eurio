# Bench encodeurs zero-shot — banque `matrice60` · gold `matrice_eval_gold.jsonl`

```
==============================================================================
⚠ CALIBRATION PROVISOIRE — NE PAS RECOPIER CES SEUILS DANS dino_thresholds

  dinov2_vits14 :
    - P3: aucun build trace dans dino_anchor_builds pour matrice60/dinov2-vits14 — la fraicheur des predictions ne peut pas etre prouvee — batir la banque : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage] ; puis relancer scripts.backfill_dino_predictions --force
    - P1: couverture utile insuffisante pour matrice60/dinov2-vits14 — 0 classes a 2 exemplaires ou plus (attendu >= 118) — enrichir (eurio-enrichment, eurio-review) puis rebatir : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage]
  dinov2_vitb14 :
    - P3: aucun build trace dans dino_anchor_builds pour matrice60/dinov2-vitb14 — la fraicheur des predictions ne peut pas etre prouvee — batir la banque : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage] ; puis relancer scripts.backfill_dino_predictions --force
    - P1: couverture utile insuffisante pour matrice60/dinov2-vitb14 — 0 classes a 2 exemplaires ou plus (attendu >= 118) — enrichir (eurio-enrichment, eurio-review) puis rebatir : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage]
  dinov2_vitl14 :
    - P3: aucun build trace dans dino_anchor_builds pour matrice60/dinov2-vitl14 — la fraicheur des predictions ne peut pas etre prouvee — batir la banque : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage] ; puis relancer scripts.backfill_dino_predictions --force
    - P1: couverture utile insuffisante pour matrice60/dinov2-vitl14 — 0 classes a 2 exemplaires ou plus (attendu >= 118) — enrichir (eurio-enrichment, eurio-review) puis rebatir : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage]

  Ce qui reste VALIDE malgré ces bloqueurs : le classement des
  encodeurs (recall@1/@5, bande pays). Le banc ré-encode la banque et
  les crops à chaque run, il ne lit aucune prédiction stockée — P3 ne
  peut donc pas le fausser.
  Ce qui est BLOQUÉ : la proposition de seuil (spread_at_p97), qui se
  lit sur des prédictions et une banque dont la fraîcheur n'est pas
  prouvée. --allow-provisional rend le chiffre, marqué provisoire.
==============================================================================
```

- gold `5b161e789f0d` · 300 crops figés · 300 soumis (gold entier)
- banque `matrice60` : 893 ancres · 60 classes · build `inconnu`
- Recall mesuré sur crops in-scope (classe de banque présente) ; bande pays = ancres du pays de la VÉRITÉ tranchée (`truth_country`).
- Chaque modèle utilise SA transform recommandée (résolution/normalisation) — le zero-shot est un proxy du potentiel post-fine-tune ArcFace, pas une mesure absolue.

| Modèle | M params | px | dim | in-scope | non encodés | global@1 | global@5 | pays@1 | pays@5 | ms/img | provisoire |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dinov2_vits14 | 22.1 | 224 | 384 | 300 | 0 | 94.0% | 99.3% | 89.7% | 91.3% | 14 | oui |
| dinov2_vitl14 | 304.4 | 224 | 1024 | 300 | 0 | 95.3% | 100.0% | 89.3% | 91.7% | 139 | oui |
| dinov2_vitb14 | 86.6 | 224 | 768 | 300 | 0 | 96.3% | 99.7% | 89.0% | 91.3% | 34 | oui |

## Seuil d'auto-acceptation (spread)

- `dinov2_vits14` : **aucun seuil rendu** — Seuil non promouvable : P3: aucun build trace dans dino_anchor_builds pour matrice60/dinov2-vits14 — la fraicheur des predictions ne peut pas etre prouvee — batir la banque : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage] ; puis relancer scripts.backfill_dino_predictions --force | P1: couverture utile insuffisante pour matrice60/dinov2-vits14 — 0 classes a 2 exemplaires ou plus (attendu >= 118) — enrichir (eurio-enrichment, eurio-review) puis rebatir : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage]. Relancer avec allow_provisional=True (CLI : --allow-provisional) pour obtenir un chiffre explicitement marque provisoire.
- `dinov2_vitb14` : **aucun seuil rendu** — Seuil non promouvable : P3: aucun build trace dans dino_anchor_builds pour matrice60/dinov2-vitb14 — la fraicheur des predictions ne peut pas etre prouvee — batir la banque : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage] ; puis relancer scripts.backfill_dino_predictions --force | P1: couverture utile insuffisante pour matrice60/dinov2-vitb14 — 0 classes a 2 exemplaires ou plus (attendu >= 118) — enrichir (eurio-enrichment, eurio-review) puis rebatir : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage]. Relancer avec allow_provisional=True (CLI : --allow-provisional) pour obtenir un chiffre explicitement marque provisoire.
- `dinov2_vitl14` : **aucun seuil rendu** — Seuil non promouvable : P3: aucun build trace dans dino_anchor_builds pour matrice60/dinov2-vitl14 — la fraicheur des predictions ne peut pas etre prouvee — batir la banque : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage] ; puis relancer scripts.backfill_dino_predictions --force | P1: couverture utile insuffisante pour matrice60/dinov2-vitl14 — 0 classes a 2 exemplaires ou plus (attendu >= 118) — enrichir (eurio-enrichment, eurio-review) puis rebatir : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage]. Relancer avec allow_provisional=True (CLI : --allow-provisional) pour obtenir un chiffre explicitement marque provisoire.

## Apparié McNemar (référence : `dinov2_vits14`)

- `dinov2_vitb14` : b=6 c=13 · p = 0.1671
- `dinov2_vitl14` : b=7 c=11 · p = 0.4807

## Traçabilité

- `20260826T165314Z-5b161e789f0d-dinov2-vits14` — provisional=1
- `20260826T165314Z-5b161e789f0d-dinov2-vitb14` — provisional=1
- `20260826T165314Z-5b161e789f0d-dinov2-vitl14` — provisional=1

```
==============================================================================
⚠ CALIBRATION PROVISOIRE — NE PAS RECOPIER CES SEUILS DANS dino_thresholds

  dinov2_vits14 :
    - P3: aucun build trace dans dino_anchor_builds pour matrice60/dinov2-vits14 — la fraicheur des predictions ne peut pas etre prouvee — batir la banque : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage] ; puis relancer scripts.backfill_dino_predictions --force
    - P1: couverture utile insuffisante pour matrice60/dinov2-vits14 — 0 classes a 2 exemplaires ou plus (attendu >= 118) — enrichir (eurio-enrichment, eurio-review) puis rebatir : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage]
  dinov2_vitb14 :
    - P3: aucun build trace dans dino_anchor_builds pour matrice60/dinov2-vitb14 — la fraicheur des predictions ne peut pas etre prouvee — batir la banque : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage] ; puis relancer scripts.backfill_dino_predictions --force
    - P1: couverture utile insuffisante pour matrice60/dinov2-vitb14 — 0 classes a 2 exemplaires ou plus (attendu >= 118) — enrichir (eurio-enrichment, eurio-review) puis rebatir : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage]
  dinov2_vitl14 :
    - P3: aucun build trace dans dino_anchor_builds pour matrice60/dinov2-vitl14 — la fraicheur des predictions ne peut pas etre prouvee — batir la banque : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage] ; puis relancer scripts.backfill_dino_predictions --force
    - P1: couverture utile insuffisante pour matrice60/dinov2-vitl14 — 0 classes a 2 exemplaires ou plus (attendu >= 118) — enrichir (eurio-enrichment, eurio-review) puis rebatir : go-task ml:dino-anchors:build -- --kind matrice60 --force --push [le --push est ce qui la fait passer sous le devShell : la trace part au canonique par HTTP ; sans lui, EURIO_DB_READONLY=1 fait refuser la commande AVANT l'encodage]

  Ce qui reste VALIDE malgré ces bloqueurs : le classement des
  encodeurs (recall@1/@5, bande pays). Le banc ré-encode la banque et
  les crops à chaque run, il ne lit aucune prédiction stockée — P3 ne
  peut donc pas le fausser.
  Ce qui est BLOQUÉ : la proposition de seuil (spread_at_p97), qui se
  lit sur des prédictions et une banque dont la fraîcheur n'est pas
  prouvée. --allow-provisional rend le chiffre, marqué provisoire.
==============================================================================
```

