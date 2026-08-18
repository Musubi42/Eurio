# Décisions — la banque DINO

> Écrit le 2026-08-19. Chaque décision dit ce qu'elle **écarte**, sinon on la
> rejouera. Les mesures qui les fondent sont dans [`CONSTAT.md`](CONSTAT.md).

## D1 · Le tri de la file s'appuie sur `2eur_all`, pas sur la banque du verdict

**Décidé** : la file de review se trie par ce que le modèle reconnaît, et ce
tri joint la banque des **suggestions** (`2eur_all`) — la seule qui contienne
des pièces courantes. Le verdict, lui, **reste sur `2eur_commemo`** tant qu'il
n'est pas recalibré.

Concrètement : une seconde jointure `ps`, dédiée au tri et au filtre, à côté de
la jointure `p` du verdict. Deux jointures sur la même table, deux usages
séparés.

**Écarté** : basculer le verdict tout de suite pour n'avoir qu'une jointure.
Les seuils de décision sont calibrés sur les similarités de vits14 ; les
appliquer telles quelles à vitl14 déplacerait le taux de faux positifs sans
qu'on le mesure. Le tri est réversible et ne décide rien — la bascule du verdict
décide, et attend sa calibration.

**Écarté aussi** : trier côté page cohorte en passant une liste d'identifiants
triée (`?ids=`). Le back ne préserve pas l'ordre du CSV, et la présence de
`ids` désactive le filtre de lane.

## D2 · Le tri met la classe travaillée devant, pas le plus net

Premier essai : trier par spread décroissant seul. Vu à l'écran, la file
« Philippe » s'ouvrait sur un Spa-Francorchamps 2025 à 0,28 de spread — le
modèle en était très sûr, **sûr que ce n'était pas la classe**.

**Décidé** : deux étages. D'abord ce que le modèle rattache à la classe
travaillée, puis du plus net au plus flou. Les crops jamais scorés finissent en
queue (`COALESCE(spread, -1)` explicite, pour ne pas dépendre de la place des
NULL dans le tri SQLite).

## D3 · Traduire l'identifiant avant de trier ou de filtrer

La banque n'indexe pas une pièce courante sous son `eurio_id`, ni sous son
`design_group_id`, mais sous celui du **plus ancien millésime de son ère**
(mesuré : `be-1999` présent, `be-2007` absent ; idem FR, DE, IT).

**Décidé** : `shared/bank_classes.bank_class_ids` traduit, et il est appelé
pour le tri **comme** pour le filtre.

**Pourquoi c'est écrit ici plutôt que laissé au bon sens** : un filtre naïf sur
l'identifiant demandé renvoie zéro ligne. Pas une erreur — une liste vide,
parfaitement plausible. C'est le genre de panne que ce projet paie cher, d'où
un test dédié qui exerce le cas d'une courante **non** représentante.

## D4 · Palier d'auto-acceptation : spread ≥ 0,10

**Décidé** (PO) : 97,1 % de précision mesurée sur 1 952 crops étiquetés, soit
799 crops décidables immédiatement sur la file ouverte.

**Écarté** : ≥ 0,05, qui doublerait le volume (1 463 crops) pour 94,5 % de
précision — environ 80 erreurs attendues au lieu de 23. Réversible
(`reopen-review` existe), mais une erreur non rattrapée part à l'entraînement.

## D5 · Les seuils DINO vont en base — dans leur propre table

**Décidé** : une table `dino_thresholds` distincte de `training_thresholds`.

**Pourquoi pas la table existante**, alors que le patron est le même :
- `value` y est un `INTEGER CHECK (value >= 1)` ; les seuils DINO sont des
  flottants dans ]0,1[ ;
- `key` est sous contrainte `CHECK` — ajouter une clé impose de reconstruire la
  table de toute façon (SQLite ne modifie pas un CHECK) ;
- surtout, **la portée n'est pas la même**. Un seuil de 0,55 calibré sur vits14
  ne veut rien dire pour vitl14 : l'axe pertinent est le couple
  `(anchors_kind, encoder_version)`, pas la cohorte. Le loger dans un
  `scope_id` composite serait le fourre-tout que le module d'origine refuse.

## D6 · Le pool ambigu entre dans le périmètre du scoring

**Décidé** : pour le kind `2eur_all` seulement, scorer aussi les crops dont le
listing n'a pas de pièce attribuée. Ils viennent d'une recherche 2 € de toute
façon, et ce sont ceux dont personne ne sait rien — donc ceux où le modèle
apporte le plus.

**Écarté** : élargir aussi les kinds scopés (`2eur_commemo`, `2eur_standard`).
Leurs banques ne couvrent qu'une moitié du référentiel : les scorer sur le pool
ambigu produirait des prédictions structurellement bancales.

## Ce qui reste ouvert

- Le seuil par classe (une classe difficile pourrait exiger plus) — même
  réponse que pour les seuils d'entraînement : le schéma le portera, l'écran ne
  l'exposera pas tant qu'aucune mesure ne dira laquelle est difficile.
- Le choix de l'encodeur. Cf. [`PROTOCOLE-BENCH.md`](PROTOCOLE-BENCH.md).
