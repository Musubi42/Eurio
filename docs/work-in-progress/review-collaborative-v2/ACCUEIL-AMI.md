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

Non. Mais lire **la même source** (`/class-need`), et n'en montrer que ce qui a
un sens pour lui. Deux chiffres, pas un tableau :

```
   Tu as tranché 47 crops.          ← son travail à lui, cumulé
   Il en reste 128 qui comptent.    ← sum_reachable, inclut accepted_pending
   ────────────────────────────
   412 / 671 pièces ont leur image  ← palier 1, la barre qui se remplit
```

La troisième ligne est celle qui donne le sens : c'est le but du projet, dit en
une phrase, et elle avance. Les deux premières sont sa contribution.

⚠️ « Tu as tranché 47 » suppose de compter **ses** décisions à lui. La donnée
existe (`peer_review_decisions.reviewer_token`, et `review_queue.decided_by`
depuis le lot 2), mais il n'y a **pas** de route qui la sert par personne
aujourd'hui — `/peer-arbitration/reviewers` est sous `review:read` et donne
tous les reviewers. Il faudra soit un `GET /me/review-stats`, soit accepter de
n'afficher que les deux dernières lignes au premier jet.

## 3. Où vit l'aide — « à l'endroit où on en a besoin »

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

Ni un tableau de bord, ni la page besoin : **sa page à lui**.

1. une phrase qui dit ce qu'on lui demande et pourquoi ;
2. les trois lignes de progression ci-dessus ;
3. un bouton unique — *Commencer à trancher* ;
4. les exemples tranchés, dépliables.

Pour l'arbitre, `/` ne change pas : il garde ses KPI.

## 4. La réassurance — un revirement à trancher par le PO

Le lot 5 a délibérément caché à l'ami que sa décision part en quarantaine :
« sans les fliquer » (demande explicite du PO, cf. ROADMAP §lot 5).

Je propose de **revenir dessus**, et l'argument tient à un cadrage :

> « Ta décision est en attente de validation » → surveille.
> « Tu ne peux rien casser, tout est relu » → rassure.

Même fait, effet inverse. Le premier frein d'un ami n'est pas l'ergonomie, c'est
la peur d'abîmer le projet de quelqu'un. La phrase existe déjà côté serveur
(`{"status": "pending_arbitration"}`), le front la jette.

**Non tranché.** À décider avec le PO — c'est sa décision produit, pas la mienne.

## 5. Ce qu'on RETIRE

Nav d'un ami aujourd'hui : Tableau de bord · Pièces · Besoin · Review queue ·
Pêche. Proposition : **Review queue, et sa page d'accueil.**

| Entrée | Sort | Pourquoi |
|---|---|---|
| **Review queue** | ✅ garder | C'est le geste |
| **Tableau de bord** | 🔁 remplacer | Devient sa page à lui (§3) |
| **Besoin** | ❌ retirer | Instrument de décision, pas d'exécution (§2). Son intention est reprise dans les 3 lignes |
| **Pièces** | ❌ retirer | Doublon de la recherche libre `F` qu'il a déjà dans l'écran de review |
| **Pêche** | ❌ retirer | File scopée par prédiction : outil d'expert, et sans `/besoin` il n'a plus de porte d'entrée |

Mécanisme : `lab:read` sort du rôle `reviewer` (`ROLE_SCOPES`, `auth_principal.py`)
→ `/besoin` disparaît par le filtre existant, sans code neuf. Pour `Pièces` et
`Pêche`, il faut soit un scope plus fin, soit assumer un `hidden?: boolean` sur
`NavItem`. **À trancher** : D3 dit « les scopes SONT le modèle de droits » — un
troisième axe de nav serait une entorse à documenter, pas à glisser.

⚠️ Retirer `coins:read` à un reviewer **casserait la recherche libre `F`**, qui
est son outil principal quand il contredit DINO. Ne pas confondre « retirer
l'entrée de nav » et « retirer le scope ».

## 6. R1 s'applique

Un panneau d'aide, une page d'accueil, des coach marks : **trois rendus visuels
neufs**. Ils passent par le proto Vue (`admin/packages/proto/`) avant Compose ou
studio-local — cf. `docs/design/_shared/parity-rules.md`. Ce n'est pas une
formalité : c'est là que se décide à quoi ressemble « la première minute ».

## Ordre proposé

1. **Trancher les questions ouvertes** (elles changent le dessin) : la définition
   de « restantes » (§1), la réassurance (§4), le mécanisme de masquage (§5).
2. **Proto** : la page d'accueil de l'ami + le panneau d'aide.
3. **Implémenter** : nav réduite + atterrissage, puis la page, puis les coach marks.
4. Les exemples tranchés en dernier — c'est du contenu, pas du code, et il se
   choisit dans les crops déjà arbitrés.
