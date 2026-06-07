# Feature : Scrape — élargir le corpus de photos par pièce

> Question centrale : **combien de photos différentes par pièce
> on a, et d'où elles viennent ?**
>
> Cible : passer de 1 photo (Numista canonique) à N photos
> diversifiées par pièce, validées en confiance, prêtes à nourrir
> training et augmentation.

## État actuel

- **1 source** : Numista. Une seule photo canonique par eurio_id,
  qualité studio, déjà scrapée et utilisée comme image source du
  pipeline.
- **0 augmentation par photo distincte** : tout le training repose
  sur la photo unique Numista + variantes synthétiques.
- **Conséquence empirique** (cf. test-2, test-1 v2) : le gap
  studio→wild ne se ferme pas par augmentation seule. Live R@1
  plafonne autour de 86% sur 7 classes faciles. Pour des cohorts
  plus larges et des conditions plus variées, ce plancher montera
  rapidement et l'app ne tiendra pas en prod.

## Pourquoi c'est un mur, pas un détail

La littérature (Pl@ntNet, PictureThis, Numista API search,
Coinoscope) converge sur un point : **les apps qui marchent en prod
ont un corpus de photos réelles user-contribuées ou scrapées**.
Aucune n'a réussi avec photo-unique + augmentation. Cf. brainstorm
meta du 2026-05-02 (résumé dans
[`harvest/README.md`](../training-pipeline/harvest/README.md)).

On n'a pas les pièces physiquement, donc on doit aller chercher les
photos ailleurs. C'est le sens de cette feature.

## Trois flux de photos à câbler

### 1. Scraping web (sources publiques)

Aller chercher des photos in-the-wild sur :

- **eBay** (volume énorme, label noisy mais texte exploitable)
- **Catawiki, MA-Shops, Sixbid** (maisons de vente, photos
  qualité, labels précis)
- **Numista user-uploads** (galerie photo de chaque page coin, à
  vérifier API)
- **Colnect, Wikimedia Commons** (catalogues complémentaires)
- **Reddit, forums numismatiques** (volume aléatoire, à voir en
  dernier)

Chaque source a sa propre stratégie d'accès, sa propre confiance
label, son propre volume estimé. Cf.
[`harvest/sources.md`](../training-pipeline/harvest/sources.md)
pour la table de référence détaillée.

### 2. Cloud fallback en production

Quand l'app on-device hésite, elle interroge un service cloud
(notre infra ou tiers). Si l'utilisateur **confirme** la prédiction
cloud, photo + label sont capturés avec confiance haute.

Source de données vertueuse :
- L'utilisateur a un intérêt à confirmer (il veut savoir ce que
  c'est).
- La donnée est par construction "wild" — c'est ce qu'on cherche.
- Échelle naturelle : croît avec le nombre d'utilisateurs.

Cf. [`harvest/user-harvest.md`](../training-pipeline/harvest/user-harvest.md).

### 3. Scans in-app (cold-start helper)

Quand le on-device ET le cloud échouent, on aide l'utilisateur à
pointer la bonne pièce dans le catalogue (top-k visuel, filtres
par pays/valeur/année, recherche libre). Photo + label capturés
avec confiance moyenne.

Pareil, doc détaillée dans
[`harvest/user-harvest.md`](../training-pipeline/harvest/user-harvest.md).

## Le verrou : auto-validation

Le scraping massif ne sert à rien sans **validation automatique**
des photos rapatriées. Sans ça, le pool est pollué (faux labels,
photos multi-pièces, photo stock dupliquée, mauvais cadrage) et
contamine le training.

Approche : pipeline multi-signal **texte + image** avec seuils
calibrés. DINOv2 (ou foundation équivalent) sert de **verifier**
en comparant chaque photo candidate à l'ancre Numista canonique.
Auto-accept si convergence ; review humaine sinon.

C'est précisément la phase 2 du track harvest. Cf.
[`harvest/auto-validator.md`](../training-pipeline/harvest/auto-validator.md).

## Pistes ouvertes

- **Numista user-uploads** : à investiguer en priorité — corpus déjà
  curé par leur communauté, label fiable.
- **Photos d'enchères** (Heritage, Sixbid, CoinArchives) : qualité
  haute mais accès parfois payant — ROI à mesurer.
- **Notre propre pipeline de capture studio** : acheter quelques
  pièces clés (les standards UE qui collapsent en live) et faire un
  shoot multi-angle nous-mêmes. Limité par le coût mais permet de
  cibler les classes faibles.
- **Échange avec une communauté** (forum, Reddit) où des
  collectionneurs photographient leurs pièces sur demande. Faisable
  à petite échelle.

## Métriques pour piloter cette feature

Volume :
- Photos validées par eurio_id (objectif : ~10-50 minimum par classe
  selon difficulté)
- Diversité : photos par classe × conditions différentes (lumière,
  angle, fond, usure)

Qualité :
- Précision spot-check du validateur auto (cible 99%+ sur
  auto-accept)
- Taux de revue humaine (goulot d'étranglement à minimiser)

Effet sur le modèle (à mesurer en lab) :
- Bench R@1 et live R@1 sur classes "enrichies en photos réelles"
  vs classes "1 photo Numista seule"
- Gain par photo additionnelle (loi de rendements décroissants)

## Implémentation

Toute l'implémentation vit dans
[`docs/training-pipeline/harvest/`](../training-pipeline/harvest/).

| Phase | Doc |
|---|---|
| 1. DINOv2 bring-up (verifier + backbone) | [`harvest/phase-1-dinov2-bring-up.md`](../training-pipeline/harvest/phase-1-dinov2-bring-up.md) |
| 2. Auto-validateur eBay (commémo only) | [`harvest/auto-validator.md`](../training-pipeline/harvest/auto-validator.md) |
| 3. Sources étendues | [`harvest/sources.md`](../training-pipeline/harvest/sources.md) |
| 4. User harvest in-app | [`harvest/user-harvest.md`](../training-pipeline/harvest/user-harvest.md) |
| 5. Review humaine admin | [`harvest/human-review.md`](../training-pipeline/harvest/human-review.md) |

## Liens vers feature voisines

- **Augmentation** : plus de photos sources = augmentation par
  diversité réelle au lieu de variantes synthétiques d'une seule
  image. Change radicalement la stratégie d'aug. Cf.
  [`augmentation.md`](./augmentation.md).
- **Model** : le verifier de scrape réutilise DINOv2, qui est aussi
  le candidat backbone du model. Dépendance technique partagée.
  Cf. [`model.md`](./model.md).
