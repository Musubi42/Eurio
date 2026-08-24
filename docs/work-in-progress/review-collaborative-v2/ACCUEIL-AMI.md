# L'accueil d'un ami — ce qu'il voit en arrivant, et où vit l'aide

> **Rien de ce document n'est implémenté.** C'est le brouillon de conception
> issu de la discussion du 2026-08-24, à reprendre dans une session dédiée.
> Le chantier technique, lui, est clos : cf. [`REPRISE.md`](REPRISE.md).

## Le problème, tel qu'il se pose

La boucle marche. Un ami peut trancher, recadrer, et le PO relit en lot. Ce qui
n'est pas fait, c'est **la première minute** : un ami qui reçoit l'URL atterrit
sur `/`, une grille de KPI filtrée par ses scopes — deux cartes, *Coins* et
*Review queue* — et une nav de cinq entrées dont quatre ne lui servent à rien.

Ce n'est pas cassé. C'est **la mauvaise première phrase** : ça ressemble à un
back-office dont il ne comprend rien, alors que son geste est à un clic.

## 1. « Restantes » — le mot n'a pas UNE définition, il en a quatre

C'est le cœur du sujet, et c'est ce qui doit être tranché avant de dessiner quoi
que ce soit. Toutes ces valeurs existent déjà dans `GET /class-need`
(`Totals`, cf. `useClassNeed.ts`), et **elles ne bougent pas ensemble** :

| Candidat | Ce que c'est | Pourquoi c'est un mauvais compteur pour un ami |
|---|---|---|
| `n_open` | Les crops ouverts dans la file | Le tas brut. Énorme, et largement composé de crops que le besoin met **hors travail** (`parked`) : trancher n'y changerait rien. Démoralisant ET faux |
| `sum_need` | Palier 2 : Σ `need`, ce qui manque à la banque pour atteindre la cible (5 ou 8 par classe) | Mesure un manque de **banque**, pas un travail de review. Une partie ne se comble que par du scrape, geste qu'un ami ne fait pas |
| `sum_reachable` | Σ `min(need, pending_scoped)` — ce que la file **peut réellement** poser aujourd'hui | ✅ Le seul honnête : « combien de décisions de plus changent quelque chose » |
| `by_bottleneck.review` | Le nombre de **classes** dont le goulot est « trancher » | Bon pour dire l'objectif (« 34 classes attendent un tri »), mauvais comme barre de progression : une classe se débloque d'un coup |

**Palier 1** (`coverage`) = le nombre de classes à `have >= 1`, c'est-à-dire
« chaque pièce a au moins une image de référence ». C'est le premier objectif
lisible du projet, et le seul qui se raconte en une phrase.

### ⚠️ Le piège qui tuerait la motivation

`have` ne bouge **qu'au rebuild de la banque**. Un ami qui tranche vingt crops un
dimanche soir ne verrait aucun chiffre bouger — son travail existe, mais aucun
compteur ne le dit. C'est exactement l'inverse de l'effet recherché.

Le contournement existe déjà et il est mesuré : `accepted_pending` (« validés,
pas encore bâtis », D8). Tout compteur montré à un ami **doit** l'inclure, sans
quoi il travaille dans le vide visible.

## 2. Ma critique de `/besoin`, correctement formulée

Elle n'était pas « cette page est mauvaise » — elle est excellente. Elle était :
**c'est l'instrument de celui qui DÉCIDE quoi faire, pas de celui qui EXÉCUTE.**

Elle répond à « où mettre l'effort » : quel goulot, quel pays, combien ça
coûterait de scraper, quelle classe est pleine. Ses chiffres sont **conditionnés
par des choses qu'un ami ne voit pas et ne contrôle pas** — la date du dernier
rebuild, le filtre pays qui se désarme tout seul, le plan d'achat, le palier
`min_exemplars`. Trois avertissements de la page portent d'ailleurs sur ces
conditions.

Donnée à un ami, elle produit deux effets :
- il lit des chiffres qu'il ne peut pas relier à son geste ;
- il croit devoir choisir **où** travailler, alors que la file le fait pour lui.

**Ce qu'il faut lui garder de `/besoin`, c'est l'INTENTION de D4** — « reviewer à
l'infini sans voir à quoi ça sert, c'est fatigant » — **pas la page.**

### Donc : afficher `/besoin` à la racine ?

Non — mais lire **la même source** (`/class-need`), et n'en montrer que ce qui a
un sens pour lui. Ce n'est pas un accès bridé à l'outil de l'opérateur : c'est
**une page construite pour lui**, sur les mêmes chiffres. C'est la décision de
conception qui commande tout le reste (PO, 2026-08-24) :

> « il faut leur build quelque chose d'assez custom, et pas juste des accès
>   restreints. »

## 3. La bonne nouvelle : le rebuild est DÉJÀ abstrait

Le PO demande de « masquer le rebuild de la banque » à l'ami. C'est en grande
partie **déjà fait**, et pour exactement cette raison — `bottleneck_for()`
(`shared/class_need.py:163`) tranche sur `have + accepted_pending`, jamais sur
`have` seul, et sa docstring le dit :

> « `have` ne bouge qu'au `build_dino_anchors` suivant : pendant une session de
>   review il est FIGÉ, donc un verdict calculé sur lui seul continue de servir
>   une classe qu'on vient de remplir. »

Conséquence pour nous : **toute la page peut se bâtir sur `/class-need` tel
qu'il est**, sans nouveau calcul côté serveur. C'est beaucoup moins cher que
prévu. Il reste une seule donnée à servir : le compte personnel (§5).

## 4. Effort et effet — la distinction qui rend les chiffres honnêtes

Un ami travaille en quarantaine : sa décision attend un arbitrage, et la banque
ne bouge qu'au rebuild. Si on lie son compteur au RÉSULTAT, il tranche vingt
crops un dimanche et ne voit rien bouger pendant une semaine. Motivation
inversée.

D'où deux compteurs, et jamais un seul :

| | Quoi | Quand ça bouge | Source |
|---|---|---|---|
| **Son effort** | « tu as trié 47 images » | **Immédiatement**, à chaque décision | `peer_review_decisions` par `reviewer_token` |
| **Son effet** | « tu as contribué à 6 pièces complétées » | Après arbitrage (+ rebuild) | `review_queue.decided_by` → assets → classes ayant atteint leur cible |

L'effort est un fait sur **son geste** : il n'a aucune raison d'attendre la
validation de qui que ce soit. L'effet est un fait sur **le projet**. Les
séparer, c'est ce qui permet d'être honnête sans être décourageant.

⚠️ **« contribué à », pas « ajouté ».** Une pièce se complète à plusieurs, et
avec les crops déjà validés avant lui. Un compteur qui s'approprie la pièce
mentirait dès le deuxième ami — et se contredirait entre leurs deux écrans.

### ✅ Tranché : ses compteurs ne redescendent JAMAIS

> « je ne me vois pas faire le truc de "ah, là il y a ça qui a mal été validé, je
>   lui décoche, du coup ça lui retire une de ses contributions". Je ne vois pas
>   cette façon de faire comme étant nécessaire. » — PO, 2026-08-24

**Règle** : les compteurs personnels comptent **ce qu'il a fait**, sans jamais
consulter l'issue de l'arbitrage. Un rejet ne décrémente rien.

Conséquence assumée : si beaucoup de ses décisions étaient rejetées, son écran
serait plus flatteur que la réalité. Acceptable — c'est un compteur de
CONTRIBUTION, pas un bulletin de notes. Et si un jour l'écart devenait gênant,
c'est le signe d'un problème de formation, pas de compteur.

### ⚠️ La conséquence dure : sans arbitrage, RIEN d'autre ne bouge

Mesuré dans le code, et c'est la découverte la plus importante de la conception :
`accepted_pending` exige `training_eligible = 1` (`class_need.py:284`) — or une
décision en quarantaine ne l'écrit PAS, c'est tout l'objet de D7.

Donc, tant que le PO n'a pas arbitré :

| Ce qui bouge | Ce qui ne bouge PAS |
|---|---|
| Ses compteurs à lui (§ ci-dessus) | La barre `412 / 671` |
| | Le `3 / 8` de chaque pièce de sa liste |
| | Le goulot d'une pièce (donc l'ordre de la liste) |

Un ami peut trier trente images sur une pièce et la voir rester à `3 / 8`.

**Ce n'est pas un bug, c'est le prix de la quarantaine.** Trois façons de vivre
avec, dans l'ordre où je les recommande :

1. **Arbitrer souvent.** La cadence d'arbitrage n'est PAS un confort : c'est une
   dépendance dure de cette page. C'est le contrat social du dispositif.
2. **Projeter ses propres décisions dans SA vue** (`3 / 8` → `5 / 8, dont 2 en
   attente`). Honnête, mais ça peut redescendre — donc ça rouvre exactement ce
   que le PO vient d'écarter. À ne faire que si le point 1 ne suffit pas.
3. **Auto-valider les décisions que DINO confirme** — 62,6 % des décisions
   rejoignent DINO top-1. Le chantier existe déjà :
   `docs/work-in-progress/review-autovalidation/PROBLEME.md`. C'est la vraie
   réponse de fond, et elle est hors de ce chantier-ci.

## 5. La page d'accueil, telle qu'on la veut

```
   ┌──────────────────────────────────────────────────────────────────────┐
   │  Tu ne peux rien casser : tout ce que tu tries est relu.              │
   ├──────────────────┬──────────────────────┬────────────────────────────┤
   │       47         │  tu as contribué à   │  412 / 671 pièces ont      │
   │  images triées   │  6 pièces            │  assez d'images            │
   │                  │                      │  ▓▓▓▓▓▓▓▓▓░░░░░            │
   │   SON EFFORT     │      SON EFFET       │      LE BUT COMMUN         │
   ├──────────────────┴──────────────────────┴────────────────────────────┤
   │  Comment reconnaître une bonne image ?                    [déplier]   │
   ├──────────────────────────────────────────────────────────────────────┤
   │  2 € Belgique 2016 — Rio                        3 / 8      [Trier]   │
   │  2 € Autriche 2018 — 100 ans République         0 / 8      [Trier]   │
   │  2 € Slovénie 2011 — Franc Rozman               5 / 8      [Trier]   │
   │  2 € France 2024 — Jeux Olympiques              1 / 8      [Trier]   │
   │  …                                                                    │
   └──────────────────────────────────────────────────────────────────────┘
```

**La bande de chiffres tient sur UNE ligne**, en trois composants côte à côte —
elle peut prendre de la hauteur, pas de la place. Ce qui doit dominer l'écran,
c'est **la liste**. C'est là qu'il travaille.

La phrase de réassurance est **en haut**, avant les chiffres (§8).

Trois précisions qui ne s'inventent pas :

1. **La cible est 8 OU 5.** `target_for_family()` rend 5 pour les émissions
   communes, 8 sinon. Écrire « sur 8 » en dur serait faux pour toute une
   famille — la ligne doit lire le `target` de SA pièce.
2. **N'afficher que les pièces à goulot `review`.** `scrape` = il n'y a rien à
   trier, l'ami cliquerait pour tomber sur une file vide ; `pleine` = c'est
   fini. C'est le filtre qui garantit qu'un clic mène toujours à du travail.
3. **`412 / 671` doit se lire `have + accepted_pending`**, comme le verdict.
   Sinon la barre ne bouge pas de la semaine.

### « Trier » ouvre la pêche — qui existe déjà

Le geste que le PO décrit — « ça ouvre la vue review filtrée précisément par les
crops que DINO rattache à cette pièce » — **c'est exactement `/review/peche?class=…`**,
livré et non-`heavy` depuis le lot 1. Il n'y a rien à construire côté file : la
page d'accueil est une **façade** sur la pêche.

🔁 **Ça corrige ce que je proposais au §9** : on ne retire pas la Pêche, on
retire son entrée de NAV. La page reste, elle devient la destination.

Et l'enchaînement que le PO décrit (« une fois les 8 atteints on passe à la
suite ») est déjà la logique de la pêche cadrée par le besoin — le crop cesse
d'être servi quand la classe est pleine (D9 de la pêche, cadrage par le besoin
par défaut).

## 6. Le vocabulaire — « classe » est notre mot, pas le sien

Le PO l'a dit pour « classe » : *« on peut parler de pièces, sinon ça va les
perdre — classe, c'est un terme pour nous »*. La remarque vaut au-delà d'un mot :
**tout le lexique de l'écran est celui du pipeline, pas celui d'un collectionneur.**

Table à tenir, et à respecter partout où un ami lit :

| Notre mot | Le sien | Pourquoi |
|---|---|---|
| classe / `class_id` | **pièce** | Une classe est une maille de banque. Lui voit une pièce |
| crop | **image** (ou *photo*) | « Crop » est un geste d'outil. Il trie des images |
| trancher / review | **trier** | « Trancher » suppose de savoir ce qu'on arbitre |
| banque d'ancres, exemplaires | **images de référence** | La banque n'existe pas pour lui |
| enrichissement | *(à éviter)* | Ne dit rien à personne hors du projet |
| training_eligible, cohorte | *(jamais montrés)* | — |

⚠️ **Le piège** : « pièce » a DEUX sens chez nous. La `coins.eurio_id` (la pièce
au catalogue) et la `class_id` (la maille de la banque, qui peut regrouper
plusieurs `eurio_id` via `design_group`). Dire « pièce » à l'ami est le bon
choix produit, mais le compteur « 412 / 671 pièces » compte des **classes**. Ce
n'est pas un mensonge — c'est une simplification qu'il faut assumer en connaissance
de cause, et ne jamais laisser fuiter dans un chiffre qui prétendrait au
catalogue. Cf. la skill `eurio-banque` §maille.

## 7. Où vit l'aide — « à l'endroit où on en a besoin »

Le principe est le bon, et il tranche le placement tout seul :

| Aide | Où | Pourquoi là |
|---|---|---|
| **Coach marks** — « ça, c'est pour recadrer ; ça, pour chercher une pièce à la main ; ça, pour passer » | **Dans l'écran de review**, ouverts par un bouton « Comment ça marche » | Ce sont des repères sur des boutons : hors de l'écran qui les porte, ils ne veulent rien dire |
| **Exemples déjà tranchés** — 5 cas avec la réponse ET le pourquoi | **Sur `/`** | Ça s'apprend au calme, avant ou entre deux sessions. Ce n'est pas un repère d'interface, c'est du métier |
| **« Tu ne peux rien casser »** | **Dans l'écran de review**, en permanence, discret | C'est au moment de cliquer que la peur existe |

Le bouton « Comment ça marche » **rejoue** les coach marks à la demande : c'est
ce qui les rend « toujours accessibles » sans imposer un tour au premier passage
à quelqu'un qui n'en veut pas.

### Ce que `/` devient pour un ami

Le dessin est au §5. En une phrase : **ni un tableau de bord, ni la page besoin —
sa page à lui**, où ses chiffres, l'aide et son travail du jour tiennent ensemble.

Pour l'arbitre, `/` ne change pas : il garde ses KPI.

## 8. La réassurance — ✅ tranchée : oui

Le lot 5 avait délibérément caché à l'ami que sa décision part en quarantaine :
« sans les fliquer » (demande explicite du PO, cf. ROADMAP §lot 5).

**Revirement acté le 2026-08-24.** La phrase va **en haut de la page d'accueil** :

> **Tu ne peux rien casser : tout ce que tu tries est relu.**

Ce qui a changé, c'est le cadrage, pas le fait :

| Formulation | Effet |
|---|---|
| « ta décision est en attente de validation » | surveille |
| « tu ne peux rien casser, tout est relu » | rassure |

Le premier frein d'un ami n'est pas l'ergonomie, c'est la peur d'abîmer le projet
de quelqu'un d'autre.

⚠️ **Ce qui NE change pas** : l'écran de review continue d'ignorer le
`{"status": "pending_arbitration"}` renvoyé par le serveur — pas de bandeau
par décision, pas de compteur « en attente ». La réassurance est **une phrase
d'accueil**, pas un statut collé à chaque geste. C'est la différence entre
rassurer une fois et fliquer en continu.

## 9. Les trois vues d'un ami — ✅ tranché

| Vue | Statut | Ce que c'est |
|---|---|---|
| **Accueil** (`/`) | 🆕 à construire | Réassurance + les trois chiffres + l'aide + la liste des pièces à trier (§5) |
| **Pièces** (`/coins`) | ✅ existante, gardée telle quelle | Le catalogue. Il peut **flâner** dedans, indépendamment de son travail du jour — c'est aussi ça, aimer les pièces |
| **Review / Pêche** | ✅ existante | Atteinte par le bouton **Trier**, jamais par le menu |

Ce qui **disparaît de sa nav** :

| Entrée | Sort | Pourquoi |
|---|---|---|
| **Tableau de bord** | 🔁 remplacé | Devient l'Accueil (§5) |
| **Besoin** | ❌ la PAGE part | Instrument de décision, pas d'exécution (§2). Mais **son composant de liste est réimporté** sur l'Accueil — c'est lui qu'on veut, pas la page. Le reste de ses données (histogramme, ACHETER, paliers, rebuild) ne sert pas à un ami |
| **Pêche** | 🔁 la page RESTE, l'entrée part | Elle est la destination de « Trier » (§5). Il n'y accède plus par un menu, mais par une pièce qu'il a choisie |
| **Review queue** | 🔁 l'entrée part | Même raison : on entre par une pièce, pas par une file anonyme |

⚠️ **Ne pas confondre entrée de nav et scope.** Retirer `coins:read` casserait la
recherche libre `F` — son outil principal quand il contredit DINO — ET la vue
Pièces qu'on garde. Retirer `lab:read` ferait disparaître `/besoin` par le
filtre existant, ce qui est le bon mécanisme pour CELLE-LÀ ; pour les autres, il
faut trancher entre un scope plus fin et un `hidden?: boolean` sur `NavItem`.
**Question ouverte** — D3 dit « les scopes SONT le modèle de droits », donc un
troisième axe serait une entorse à documenter, pas à glisser.

## 10. R1 s'applique

Un panneau d'aide, une page d'accueil, des coach marks : **trois rendus visuels
neufs**. Ils passent par le proto Vue (`admin/packages/proto/`) avant Compose ou
studio-local — cf. `docs/design/_shared/parity-rules.md`. Ce n'est pas une
formalité : c'est là que se décide à quoi ressemble « la première minute ».

## Ordre proposé

1. **Servir le compte personnel** — la seule donnée qui manque côté serveur :
   un `GET /me/review-stats` (effort + effet, comptés sur SES décisions, sans
   consulter l'arbitrage — §4). Tout le reste vient de `/class-need`, qui existe
   et abstrait déjà le rebuild (§3).
2. **Proto** (R1) : l'Accueil, puis le panneau d'aide.
3. **Implémenter** : l'Accueil + l'atterrissage, la nav réduite, puis les coach
   marks.
4. **Les exemples tranchés en dernier** — c'est du contenu, pas du code, et il
   se choisit dans les crops déjà arbitrés.

Une seule question reste ouverte : **par quel mécanisme masquer les entrées de
nav** (scope plus fin, ou `hidden` sur `NavItem`) — §9.

## Ce qui est acquis, et n'a pas à être rediscuté

- **Trois vues** : Accueil, Pièces (`/coins`, gardée), Review/Pêche. §9
- La page se bâtit sur **`/class-need`**, pas sur une nouvelle agrégation. §3
- **Deux compteurs**, effort et effet — et ils **ne redescendent jamais** : un
  rejet d'arbitrage ne retire rien à personne. §4
- Sans arbitrage, **rien d'autre ne bouge** : la cadence d'arbitrage est une
  dépendance dure de cette page, pas un confort. §4
- La cible est **8 ou 5** selon la famille, lue par ligne. §5
- Seules les pièces à goulot **`review`** sont proposées. §5
- « Trier » ouvre la **pêche existante**, `/review/peche?class=…`. §5
- La bande de chiffres tient sur **une ligne** ; c'est la **liste** qui domine. §5
- **« Tu ne peux rien casser »** en haut de l'Accueil — et nulle part ailleurs :
  pas de statut « en attente » collé à chaque décision. §8
- Le **lexique** du §6 s'applique partout où un ami lit : pièce, image, trier.
- `/besoin` : la **page** part, son **composant de liste** est réimporté. §9
