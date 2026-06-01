# Mapping psychologie → expérience

> **Doc d'intention** (pas de visuel). On part des leviers validés
> ([`psychologie-retention.md`](./psychologie-retention.md) + recherches
> [`01`](./psychologie-documentation/01-motivations-baseline.md)/[`03`](./psychologie-documentation/03-comparaison-sociale-classement.md))
> et on **mappe chaque surface** d'Eurio — écrans, notifs, partage — au(x) **drive(s)** qu'elle
> sert, ce qu'elle affiche, et son garde-fou. Brouillon à challenger ensemble.
>
> ⚠️ **R1 (proto-first)** : tout rendu *visuel* nouveau passe d'abord par le prototype HTML.
> Ce doc fixe **l'intention** (quel levier, quoi montrer), pas le pixel — la traduction visuelle
> va au proto avant Compose.

## Principes d'opération

1. **Chaque surface déclare sa motivation primaire.** Pas d'écran « fourre-tout ». Si un écran
   ne sait pas quel drive il sert, il n'existe pas encore.
2. **Acte rare vs rituel renouvelable.** Le scan (supply-gated) ≠ la boucle quotidienne. Les
   défis/notifs/classements s'accrochent au **renouvelable**, jamais à « scanne tous les jours ».
3. **Garde-fou SDT** (cf. [`01`](./psychologie-documentation/01-motivations-baseline.md)) : toute
   mécanique doit nourrir **compétence** (feedback de progrès) + **autonomie** (choix) +
   **relatedness** (social), sinon elle érode la motivation au lieu de l'alimenter.
4. **Servir ≥3 drives à la fois** sur les surfaces centrales (reveal, coffre), lentille **choisie
   pas devinée** — pas de moteur de profiling (R0).

## Carte maîtresse (surface → drive)

Drives (rappel) : **Complétion · Découverte/savoir · Statut/rareté · Valeur/€ · Sens/identité · Social**.

| Surface | Drive primaire | Drives secondaires | Ce qu'on affiche / l'interaction | Garde-fou |
|---|---|---|---|---|
| **Reveal post-scan** | Découverte | Valeur, Complétion, Statut | identité de la pièce + l'« angle » (voir §1) | pas le `+40€` seul en n°1 |
| **Coffre — par pays** | Complétion | Sens, Statut | grille remplie/silhouettes ; % par pays | montrer le *manque*, pas que le plein |
| **Coffre — par année** | Complétion | Découverte | timeline ; « tu n'as rien de 2004 » | — |
| **Coffre — sets perso** | Autonomie (SDT) | Complétion, Sens | l'user crée/organise ses sets | structure = contrôle (Cao, [`01`](./psychologie-documentation/01-motivations-baseline.md)) |
| **Carte eurozone** | Complétion + Sens | Social (partage) | % possédé par pays, à *bien* refaire | différenciateur, doit être beau |
| **Bandeau valeur** | Valeur/€ | Statut | valeur réelle (≠ faciale), évolution | jamais anxiogène, pas de cours-bourse |
| **Classement** | Statut/rareté | Social, Compétence | multi-échelle, mené par local/amis (voir §3) | jamais global brut à un débutant |
| **Défis du mois** | Complétion | Statut, Social | objectifs gagnables, adaptatifs (voir §4) | rien à perdre, tout à gagner |
| **Push notifs** | dépend (voir §5) | — | rareté / FOMO doux / défi / social | fréquence basse, jamais culpabilisant |
| **Partage** | Social | Statut, Sens | nouvelle pièce / complétion / carte (voir §6) | fierté, pas flex creux |

---

## §1 — Le reveal post-scan (la surface la plus chargée)

C'est notre **équivalent du pack opening**, sauf que le paquet = la pièce réelle. Donc le scan
doit *se sentir* comme un pull (juice : vibration, animation, 3D du lieu/monument — cat. 5).

**Sur le débat `+40€` :** la valeur n'est *une* corde sur six (cf. [`01`](./psychologie-documentation/01-motivations-baseline.md)).
La mettre seule en n°1 trahit l'historien et le complétionniste. Proposition de **reveal qui
sert 3 drives d'un coup**, ordre par défaut puis lentille au choix :

1. **Découverte** (toujours en 1ᵉʳ, universel) : « Allemagne 2023 — *50 ans du Traité de l'Élysée* »
   + le visuel 3D / l'histoire courte.
2. **Complétion** : « **nouvelle pièce !** » ou « tu l'avais déjà » → où ça te place (« 24/27 pays »).
3. **Statut/rareté** (si la pièce est notable) : « seulement **2%** la détiennent », « **1ᵉʳ** ce
   mois-ci » (N-effect, [`03`](./psychologie-documentation/03-comparaison-sociale-classement.md)).
4. **Valeur** : la cote par qualité, en *info* pas en *titre* (« ~12€ en TTB »).

**Autonomie** : l'user peut épingler l'angle qui le motive (afficher la valeur en gros, ou
l'histoire en gros) — choix, pas profiling.

**Stratification (recherche [`05`](./psychologie-documentation/05-juice-du-scan.md))** : le reveal
n'a *pas* à tout dire (Miller/Hick → surcharge). **Héros = le 3D de la pièce (haut-centre)**, puis
**≤3 drives** (Découverte + Complétion + 1 *accent contextuel* piloté par la pièce : rareté **ou**
série **ou** valeur), puis **tap → page de la pièce** pour la profondeur (histoire complète, cote,
série). Le scan = le **pic resserré** ; la page pièce = la profondeur. Et c'est un **pull éthique** :
on garde anticipation + reveal + haptique (~400 ms) + son + célébration *réservée aux jalons*
(peak-end), mais **zéro hasard/near-miss** — notre dopamine vient de l'*incertitude épistémique*
(sens/statut/progrès), pas du tirage.

## §3 — Le classement (modèle Trackmania)

Détail théorique : [`03`](./psychologie-documentation/03-comparaison-sociale-classement.md).
- **Multi-échelle, mené par le local** : amis < région < pays < zone euro (local dominance).
- **Statut par rareté détenue**, pas par volume : exploiter le **N-effect** — « tu es **1 of 12** »,
  « 1ᵉʳ à scanner ce mois-ci ». C'est le hook le plus actionnable *et* il valorise pile les
  pièces rares qu'on veut faire chercher/scanner.
- **Grades de compétence** (médaille-like) à côté, pour un feedback solo non-démoralisant.
- Toujours une **comparaison gagnable** affichée à côté de l'aspirationnelle.

## §4 — Les défis du mois (le « streak » repensé)

Plutôt qu'une streak rigide « scanne chaque jour » (impossible, supply-gated → punit), des
**défis mensuels adaptatifs**, exemples de Raphaël :
- « **Scanne 10 pièces que tu n'as pas encore ce mois-ci** » → fait grandir la collection,
  gamifie l'**acquisition** réelle (cat. 2). Tout le monde peut le faire, même non-gamer.
- Récompense : point/grade/badge — **rien à perdre si non fait, bonus si fait** (asymétrie
  positive, évite le dark pattern de la streak punitive, cf. garde-fou cat. 3).
- Adaptatif : difficulté calée sur la taille de la collection (un débutant n'a pas le même 10
  qu'un avancé) — sans profiling, juste sur l'état du coffre.

> **Tranché** (recherche [`04`](./psychologie-documentation/04-streak-vs-defis.md)) : **défis
> adaptatifs = pilier, pas de streak rigide**. Règle d'or = **asymétrie positive** (le non-fait ne
> retire rien, le fait donne) → on garde la dopamine, on jette la peur (anti-dark-pattern). Une
> « cadence » forgiving (freezes, cadrée fierté, non-supply-gated) reste *optionnelle et à tester*,
> jamais un pilier. Boucle quotidienne = **Ability max + émotion positive** (Fogg), jamais « scanne ».

## §5 — Push notifications (par levier)

| Notif | Levier | Exemple |
|---|---|---|
| Rareté / FOMO doux | Statut + N-effect | « Cette commémo a déjà été scannée 3× ce mois-ci — sois le prochain » / « personne ne l'a encore : sois le **1ᵉʳ** » |
| Nouvelle sortie (**notre moat**) | Découverte + Complétion | « La commémo {pays} sort cette semaine — on l'a déjà au catalogue » |
| Défi | Complétion | « Plus que 3 pièces pour finir ton défi du mois » |
| Social | Relatedness | « {ami} vient de compléter l'Allemagne — et toi ? » |
| Valeur | Valeur/€ | « Une pièce de ton coffre a pris de la valeur » (parcimonie) |

**Garde-fous** : fréquence basse, jamais culpabilisant (« tu vas perdre… » = à éviter), toujours
une action *possible* derrière (sinon frustration : supply-gated).

**Fréquence adaptative (raffinement Raphaël)** : **pas de notif quotidienne** — quotidien = trop,
glisse vers le dark pattern. Viser l'effet *« ça fait longtemps, tiens, agréable surprise »* :
cadence **calée sur la fréquence d'ouverture** de l'user (moins il ouvre, plus on espace pour ne
pas harceler), **configurable**, et **qualité > régularité**. Une notif doit être un cadeau, pas
un rappel anxiogène.

## §6 — Le partage (le hook viral)

Quoi afficher quand on partage ?
- **Nouvelle pièce** : le visuel (3D), l'histoire courte (sens), « 2% la détiennent » (statut) →
  un *skit* renvoyable à un pote (cf. stratégie growth, contenu short-form).
- **Complétion** : « j'ai fini l'Allemagne 🇩🇪 » / « il me manque 3 pays sur la carte eurozone »
  (la carte est intrinsèquement partageable — cat. 6/7).
- **Valeur** (optionnel, lentille) : « ma collec vaut X, top 2% ».
- Garde-fou : **fierté/histoire**, pas flex creux ; la carte eurozone est le meilleur asset
  partageable (différenciateur visuel).

---

## Synthèse design

- **Coffre** = moteur **Complétion + Sens** (4 vues : pays / année / sets perso / carte) → c'est le
  cœur « collectionneur » ; la **carte eurozone** est le différenciateur, à refaire beau.
- **Classement + défis** = moteur **Statut/Social**, branché sur la **rareté** (N-effect) → fait
  *chercher/scanner les pièces rares*, et gamifie l'**acquisition** (résout en partie le bocal froid).
- **Reveal + notifs + partage** = la **boucle dopamine** (juice) et la **boucle virale**.
- Tout passe le **filtre SDT** (compétence/autonomie/relatedness) et le **filtre supply** (jamais
  une mécanique qui exige une pièce neuve qu'on n'a pas).

## Questions ouvertes (pour Raphaël)

1. **Streak oui/non** en plus des défis ? (→ recherche cat. 3)
2. **Grade de collectionneur** : par volume, par rareté détenue, par complétion de sets, ou un mix ?
3. Le **classement** est-il v1 ou plus tard ? (implique du social/serveur, vs offline-first actuel)
4. Le reveal : **angle par défaut** (Découverte d'abord) — OK, ou tu veux tester Valeur-d'abord
   sur un segment ?

## Statut

Brouillon de mapping (2026-06-01), issu des recherches 01-03. À challenger, puis les écrans
retenus passent par le **proto HTML** (R1) avant Compose, et s'inscrivent dans les phases app
(`docs/app-implem-phases/`).
