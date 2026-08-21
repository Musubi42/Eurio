# O2 · La vue « classe → 8 »

> **Statut : spec, non implémentée.** Station 0 du
> [flow](../FLOW-ADMIN.md). Dépend de [O1](O1-besoin-par-classe.md).

## Le geste

L'écran d'où part une session de travail. Il répond à *« quelle classe je
nourris maintenant, et par quel geste »* — et il est le seul endroit du système
qui sache dire **« pas celle-ci »**.

## Pourquoi il n'existe pas encore

Les six écrans de review et la pêche partent tous d'un **périmètre qu'on leur
donne** : une cible de scrape, une cohorte, une classe tapée dans l'URL. Aucun
ne part du **besoin**. C'est ce qui produit le chiffre central du chantier :

```
6 617 crops ouverts
    839  servent la cible de 8
  3 612  appartiennent à des classes déjà pleines (10 exemplaires, besoin 0)
  2 166  top-1 hors du grain de la banque
```

Les **12 classes les plus représentées font 24 % de la file, et toutes ont déjà
leurs 10 exemplaires.** Personne ne peut le voir aujourd'hui.

## La forme

Une ligne par classe, triée par **ce que l'action débloque**, pas par déficit
brut : une classe à qui il manque 8 exemplaires mais qui n'a aucun candidat ne
doit pas passer devant une classe à qui il en manque 2 et qui en a 30 sous la
main.

```
tri = (bottleneck == 'review') d'abord, puis min(need, pending_scoped) décroissant
```

```
CLASSE                        BANQUE      CANDIDATS   GOULOT      GESTE
be-2euro-philippe-t1          5/8  ██████░░  32 · 0,053  review    → pêcher
es-2euro-juan-carlos-i-t2     9/8  ████████   5 · 0,061  pleine    —
lu-2euro-henri-i-t1           0/8  ░░░░░░░░   0          scrape    → plan (groupe LU)
at-2012-2eur-10-years…        10/8 ████████ 109          pleine    ⚠ 109 crops à fermer
cy-2012-2eur-10-years…        4/8  ████░░░░ 155          image     → cf. O5
```

Quatre colonnes, et chacune existe pour une raison mesurée :

- **BANQUE** — `have/target`, plus le plafond visible quand `have ≥ cap`. C'est
  la voie B et l'en-tête doit le dire (cf. [`FLOW-ADMIN.md`](../FLOW-ADMIN.md) §4).
- **CANDIDATS** — `pending_scoped` **et la meilleure marge**. Un compte seul ment
  par omission : la file ES « 4 à l'unité » était faite de quatre annonces
  françaises à 0,023 de marge — quatre skips pour rien. Le précédent est déjà
  consigné dans `dino_candidates_summary`.
- **GOULOT** — le verdict d'O1, en toutes lettres.
- **GESTE** — un lien, jamais une action directe. Enfiler, scraper, fermer sont
  des **écritures** ; elles ne se déclenchent pas au fil d'une lecture.

## Les trois propriétés non négociables

**1. Elle dit quand le goulot n'est pas elle.** 347 classes déficitaires n'ont
aucun crop en file. Les afficher comme « à reviewer » enverrait l'opérateur vers
une file vide. Elles portent `scrape` et pointent vers la Station 1.

**2. Elle s'arrête au plafond.** Au-delà de 10 exemplaires, un crop validé
n'entre plus dans la banque. La médiane des classes pleines est de **25 crops
décidés** pour un plafond de 10 : ces classes ont été sur-reviewées d'un facteur
2,5. La vue doit le dire, pas le taire.

**3. Elle ne se ment pas sur zéro.** Une classe à `pending_scoped = 0` doit
distinguer trois causes, sinon elle produit exactement la panne muette
caractéristique du dépôt :

| ce qu'on voit | ce qu'il faut afficher |
|---|---|
| aucun crop en file, tous filtres levés | « rien scrapé » → Station 1 |
| des crops en file, tous coupés par le filtre pays | « 44 masqués par le filtre pays ES » + le lien qui les ramène |
| des crops en file, tous coupés par l'ère | « 12 contredits par le millésime du titre » |

Le deuxième cas n'est pas théorique : **le filtre pays vide entièrement la file
de 137 classes sur 338** (cf. [`VISION.md`](../VISION.md) §V3).

## Où elle vit

Route `meta: { heavy: true }` ? **Non, et c'est délibéré.** Le calcul d'O1 est du
SQL pur sur le canonique — pas de `:8042`, pas de cv2. La vue doit être
accessible en hébergé comme `peer-arbitration` l'est : savoir ce qui manque n'a
pas à dépendre d'un Mac allumé. Seuls les **gestes** qu'elle propose sont lourds,
et ils se grisent tout seuls.

Chemin proposé : `/besoin`. Backend : `GET /class-need` sur `eurio-api`, servi
par l'image lean.

⚠️ **Le front lit le canonique.** Toute route nouvelle exige un déploiement VPS
(`git fetch github && merge --ff-only`, puis `docker compose up -d --build` dans
`infra/eurio-api`), sinon rien ne bouge à l'écran. Et l'upstream du clone VPS
pointe encore sur `codeberg` : un `git pull` nu y répond « à jour » en toute
bonne foi.

## Comment on vérifie qu'il marche

- **Le compte à l'écran = le compte en base.** `SELECT COUNT(*)` sur les classes
  à `bottleneck='review'` doit égaler ce que la vue affiche. Un même fait porte
  partout le même nombre — c'est la règle qui a coûté le plus cher à réapprendre.
- **Le scénario du terrain d'essai** : ouvrir la vue doit faire remonter
  `be-2euro-philippe-t1` en haut (goulot review, 32 candidats, besoin 3) et
  ranger `ad-2014-…council-of-europe` en `pleine`.
- **Le zéro qui s'explique** : forcer `dino_country_only` sur une classe
  portugaise doit afficher « masqués », jamais une liste vide.

## Ce que cette vue n'est pas

- **Ce n'est pas un écran de review.** On n'y tranche aucun crop. Elle oriente.
- **Ce n'est pas le préflight de cohorte.** Celui-là décide si un entraînement
  peut démarrer (voie A, `min_real`). Les deux peuvent être en désaccord
  légitime sur la même classe.
- **Ce n'est pas un auto-accept.** Aucun crop n'entre en banque sans qu'un
  humain l'ait regardé.
