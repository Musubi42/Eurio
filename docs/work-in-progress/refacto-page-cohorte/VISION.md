# Refacto page cohorte — vision

> Écrit le 2026-08-18, après une session où l'on a construit avant d'avoir défini.
> Ce dossier existe pour poser la réflexion AVANT l'implémentation. Rien ici
> n'est un chantier lancé : c'est la cible qu'on se donne, à relire et à corriger.

## Le but

Reconnaître **toutes les pièces de 2 € qui existent**. Des centaines. On n'y va
pas d'un coup : on entraîne par lots, et chaque lot ajoute des classes à ce que
l'app sait reconnaître.

## Le grain : la CLASSE, jamais la pièce

Le modèle n'apprend pas « une pièce », il apprend **un dessin**. Plusieurs pièces
qui partagent leur face nationale forment **une seule classe**, et **leurs photos
s'additionnent**.

Mesuré sur `giga-40-vague1` : **129 pièces = 40 classes**. Le drapeau européen
2015 regroupe à lui seul 21 pièces.

**Tous les écrans comptent en classes.** La pièce n'est qu'un détail dépliable.
C'est la première cause du désordre actuel : la page cohorte compte par pièce
(129 lignes), le contrôle avant entraînement compte par classe (40). Même
question, deux nombres.

## Ce qu'est une cohorte

**Une sélection de classes qu'on décide d'amener à l'entraînement.** Rien de plus.

Une classe porte son état **toute seule**, indépendamment de la cohorte :
une classe qui a ses photos les garde. Une nouvelle cohorte qui reprend 40
classes déjà prêtes et en ajoute 40 neuves démarre donc avec **40 classes prêtes
et 40 à travailler**. On ne redemande rien aux prêtes ; si on veut leur ajouter
des photos, c'est un choix, pas une obligation.

> ⚠️ Rien ne « se cumule ». Il n'y a pas d'empilement de cohortes. Il y a des
> classes, qui ont ou n'ont pas ce qu'il faut.

## La règle de regroupement se MESURE, elle ne se décrète pas

La règle actuelle (même face nationale = même classe) n'a jamais été éprouvée.
Elle le sera par l'entraînement lui-même, avec des données déjà produites
(`confused_with`, `r_at_1` par classe) :

| Ce qu'on observe après un run | Ce qu'on en conclut |
|---|---|
| deux classes se confondent systématiquement | c'était la même — on fusionne |
| une classe se reconnaît mal malgré ses photos | regroupement trop large — on coupe |
| une classe marche | la règle tient pour ce cas |

**C'est un argument pour entraîner tôt** : le premier run n'est pas seulement un
modèle, c'est le test de la règle de classes.

## « Fini » pour une classe

**Fini = entraînable.** Les captures device sont **optionnelles** et peuvent se
faire à n'importe quel moment — elles servent à *mesurer*, pas à *autoriser*.

Une classe est entraînable quand elle a assez de photos réelles validées. « Assez »
est un **seuil configurable**, pas une vérité (cf. `SEUILS.md`).

## Les 5 artefacts, donc les 5 vues

Chaque vue répond à UNE question, produit UN artefact, et **ne liste que les
classes qui n'y sont pas encore**. Les vues se vident à mesure qu'on avance —
c'est l'antidote au scroll infini d'aujourd'hui.

| Vue | La question | Entre | Sort |
|---|---|---|---|
| **1. Classes** | qu'est-ce qu'on veut reconnaître ? | référentiel | classes + pièces membres |
| **2. Matière** | a-t-on des images ? | classes sans assez | annonces téléchargées |
| **3. Crops** | a-t-on des découpes ? | images brutes | crops candidats |
| **4. Validées** | lesquelles sont sûres ? | crops candidats | **photos d'entraînement** |
| **5. Modèle** | est-ce que ça marche ? | photos validées | itération + mesure |

Les captures device se branchent sur la vue 5 quand elles existent, sans jamais
bloquer les autres.

Détail écran par écran : `FRONT.md`. Ce que fait le back et où : `BACK.md`.

## La vue 4 est une cascade, pas cinq écrans

Aujourd'hui le tri est éclaté : queue manuelle, auto-accept, lots, rejetés à
récupérer, arbitrage. Ce ne sont pas cinq métiers — c'est **un ordre de
préférence** pour obtenir le même artefact :

1. **Auto-résolu d'abord.** C'est son travail. S'il trouve les photos tout seul,
   la classe est finie sans qu'on la voie passer.
2. **Single ensuite.** Rapide et net.
3. **Lot en dernier.** Plus coûteux à trancher.
4. **Rejetés à récupérer** : pas une étape, un recours quand le reste est à sec.

L'écran ne demande jamais « où veux-tu aller ». Il dit : *il manque 6 photos à
cette classe, l'auto en a trouvé 3, il reste 12 singles.*

## Le principe qui manque partout aujourd'hui : montrer le RÉSULTAT

La pipeline produit des artefacts, mais les écrans montrent des **étages**
(annonces, téléchargements, crops, files) au lieu du **résultat de l'effort**.

Un scrape ne doit pas répondre « 412 annonces retenues ». Il doit répondre
**« +12 photos validables pour Italie standard »** — et dire l'autre moitié de
la vérité : la découverte se fait **par pays**, donc le run a aussi nourri les
commémoratives italiennes. C'est un gain, encore faut-il l'afficher.

## Le défaut le plus grave n'est pas le désordre

**Les pannes sont muettes.** Relevé en une seule journée sur `giga-40-vague1` :

- un recrop annonçant « épuisé » alors qu'il tournait amputé de sa passe de
  secours bimétal (0 crop récupéré sur 193 ; 144 après correction) ;
- 33 crops ni tranchés ni visibles en review ;
- 56 crops partis sur 37 pièces sœurs **hors cohorte**, donc jamais entraînés ;
- un compteur figé jusqu'à 2 minutes parce qu'il lisait une copie locale.

À chaque fois l'interface affiche un état **plausible et faux**. La refacto doit
traiter ça comme une exigence de premier rang : **aucun écran ne doit pouvoir
mentir en silence.** Quand un compteur ne bouge pas, il doit dire pourquoi.

## Ce que la refacto ne touche pas

- La page cohorte actuelle **reste**. `/lab/cohorts-test/:id` est le bac à sable
  où l'on éprouve les vues avant de trancher.
- Les écrans de review existants restent : on les réutilise, on ne les réécrit pas.

## Ordre de lecture

1. `VISION.md` — ce fichier
2. `SEUILS.md` — d'où viennent les seuils, et où ils devraient vivre
3. `DONNEES.md` — ce qui entre, sort, et se transforme ; où c'est stocké
4. `FRONT.md` — les 5 vues, écran par écran
5. `BACK.md` — qui calcule quoi, sur quelle machine, et comment ça se synchronise
