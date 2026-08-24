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

⚠️ **Contrat social à connaître** : si le PO n'arbitre pas pendant deux
semaines, l'effort de l'ami grimpe et son effet reste à zéro. Le mécanisme de
motivation s'inverse. Arbitrer régulièrement fait partie du dispositif, pas du
confort.

## 5. La page d'accueil, telle qu'on la veut

```
   ┌──────────────────────────────────────────────────────┐
   │   47                                                 │  ← effort, gros
   │   images triées                                      │
   │   tu as contribué à 6 pièces complétées              │  ← effet
   │                                                      │
   │   412 / 671 pièces ont assez d'images                │  ← le but commun
   │   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░                      │
   │   il reste 128 images à trier pour que le modèle     │
   │   reconnaisse toutes les pièces                      │
   ├──────────────────────────────────────────────────────┤
   │   Comment reconnaître un bon recadrage ?  [déplier]   │  ← les exemples
   ├──────────────────────────────────────────────────────┤
   │   2 € Belgique 2016 — Rio          3 / 8   [Trier]   │
   │   2 € Autriche 2018 — République   0 / 8   [Trier]   │
   │   2 € Slovénie 2011 — Rozman       5 / 8   [Trier]   │
   └──────────────────────────────────────────────────────┘
```

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

## 8. La réassurance — un revirement à trancher par le PO

Le lot 5 a délibérément caché à l'ami que sa décision part en quarantaine :
« sans les fliquer » (demande explicite du PO, cf. ROADMAP §lot 5).

Je propose de **revenir dessus**, et l'argument tient à un cadrage :

> « Ta décision est en attente de validation » → surveille.
> « Tu ne peux rien casser, tout est relu » → rassure.

Même fait, effet inverse. Le premier frein d'un ami n'est pas l'ergonomie, c'est
la peur d'abîmer le projet de quelqu'un. La phrase existe déjà côté serveur
(`{"status": "pending_arbitration"}`), le front la jette.

**Non tranché.** À décider avec le PO — c'est sa décision produit, pas la mienne.

## 9. Ce qu'on RETIRE

Nav d'un ami aujourd'hui : Tableau de bord · Pièces · Besoin · Review queue ·
Pêche. Proposition : **Review queue, et sa page d'accueil.**

| Entrée | Sort | Pourquoi |
|---|---|---|
| **Review queue** | ✅ garder | C'est le geste |
| **Tableau de bord** | 🔁 remplacer | Devient sa page à lui (§3) |
| **Besoin** | ❌ retirer | Instrument de décision, pas d'exécution (§2). Son intention est reprise dans les 3 lignes |
| **Pièces** | ❌ retirer | Doublon de la recherche libre `F` qu'il a déjà dans l'écran de review |
| **Pêche** | 🔁 **garder la PAGE, retirer l'entrée de nav** | C'est la destination du bouton « Trier » (§5) : `/review/peche?class=…`. Il n'y accède plus par un menu, mais par une pièce qu'il a choisie |

Mécanisme : `lab:read` sort du rôle `reviewer` (`ROLE_SCOPES`, `auth_principal.py`)
→ `/besoin` disparaît par le filtre existant, sans code neuf. Pour `Pièces` et
`Pêche`, il faut soit un scope plus fin, soit assumer un `hidden?: boolean` sur
`NavItem`. **À trancher** : D3 dit « les scopes SONT le modèle de droits » — un
troisième axe de nav serait une entorse à documenter, pas à glisser.

⚠️ Retirer `coins:read` à un reviewer **casserait la recherche libre `F`**, qui
est son outil principal quand il contredit DINO. Ne pas confondre « retirer
l'entrée de nav » et « retirer le scope ».

## 10. R1 s'applique

Un panneau d'aide, une page d'accueil, des coach marks : **trois rendus visuels
neufs**. Ils passent par le proto Vue (`admin/packages/proto/`) avant Compose ou
studio-local — cf. `docs/design/_shared/parity-rules.md`. Ce n'est pas une
formalité : c'est là que se décide à quoi ressemble « la première minute ».

## Ordre proposé

1. **Trancher les questions ouvertes** — elles changent le dessin :
   - la réassurance « tu ne peux rien casser » (§8), qui revient sur une demande
     explicite du PO ;
   - le mécanisme de masquage de la nav (§9), qui frotte contre D3 ;
   - l'attribution de l'« effet » (§4) : par personne, ou partagée.
2. **Servir le compte personnel** — la seule donnée manquante côté serveur :
   un `GET /me/review-stats` (effort + effet). Tout le reste vient de
   `/class-need`, qui existe et qui abstrait déjà le rebuild (§3).
3. **Proto** (R1) : la page d'accueil de l'ami, puis le panneau d'aide.
4. **Implémenter** : nav réduite + atterrissage sur `/`, puis la page, puis les
   coach marks.
5. **Les exemples tranchés en dernier** — c'est du contenu, pas du code, et il
   se choisit dans les crops déjà arbitrés.

## Ce qui est acquis, et n'a pas à être rediscuté

- La page se bâtit sur `/class-need`, pas sur une nouvelle agrégation (§3).
- Deux compteurs, effort et effet, jamais un seul (§4).
- La cible est **8 ou 5** selon la famille, lue par ligne (§5).
- Seules les pièces à goulot `review` sont proposées (§5).
- « Trier » ouvre la **pêche existante**, `/review/peche?class=…` (§5).
- Le lexique du §6 s'applique partout où un ami lit.
