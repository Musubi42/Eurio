# Psychologie & rétention Eurio

> **Doc vivant.** La colonne vertébrale émotionnelle d'Eurio : *pourquoi on revient*.
> Index missions : [`README.md`](./README.md) · Stratégie : [`product-strategy.md`](./product-strategy.md).
> Ce doc est **affiné** par les recherches brutes de [`psychologie-documentation/`](./psychologie-documentation/) —
> il en est la synthèse vivante, pas la source. Une affirmation ici sans source = à creuser ou à sourcer.

## Le recadrage fondateur — on n'est pas un demi-Pokémon GO

La tentation est de se comparer aux collectibles **numériques** (paquets Pokémon TCG Pocket,
gacha, Duolingo) et de se sentir amputé : « eux fabriquent de la supply / de la rareté à
volonté, moi pas ». **C'est une fausse blessure.**

- Les paquets numériques sont du dopamine **infini, fabriqué, et creux** (et de plus en plus
  régulé — frontière jeu d'argent). Personne ne se vante d'avoir *ouvert un paquet*.
- Le collectible d'Eurio est **réel, rare, historique, acquis en vivant sa vie**. On se vante
  d'avoir **trouvé / gagné / complété**.
- C'est exactement le ressort du produit-médaille (**The Conqueror** / défis virtuels) : les
  gens **paient cher ET fournissent un effort réel** pour *mériter* un objet qui a du sens.

→ **L'edge est plus fort, pas plus faible.** Le lien au réel est le moat émotionnel.
Le design ne doit **pas** fabriquer de la fausse supply ; il doit (1) **maximiser la dopamine
du moment réel** (« dans ma monnaie, une pièce que je n'avais pas ») et (2) **tenir
l'anticipation et le statut entre deux moments** (quand le bocal physique est sec).

## Le problème central — le « bocal froid »

> Nouvel utilisateur : il vide son bocal, scanne 10 pièces en 30-60 min (super burst), puis
> le 2ᵉ jour **il n'a plus rien de neuf à scanner**. Sa réserve physique est sèche.

C'est *le* trou de rétention. La métaphore Pokédex casse ici : on capture en scannant une
pièce **qu'on possède déjà**, donc la boucle dépend du monde réel. Tout le design de
rétention découle de la réponse à : *quel est l'engagement renouvelable quand la supply est sèche ?*

## Le principe directeur — acte rare vs rituel renouvelable

> **Sépare l'acte rare (scanner une pièce neuve — *supply-gated*) du rituel renouvelable
> (l'action quotidienne toujours possible sans nouvelle pièce). La streak / la boucle
> quotidienne s'accroche au rituel renouvelable, jamais à l'acte rare.**

Sinon la streak *punit* (impossible de scanner tous les jours). Candidats de rituel
renouvelable (à valider en recherche) : pièce vedette du jour + son histoire, un
« devine la pièce », mise à jour de la wishlist, évolution de la cote / alerte nouvelle
sortie (notre moat), micro-quiz numismatique.

## La question du profiling — baseline avant personnalisation

Le reveal post-scan (« +40€ » ? l'histoire ? « 9/10, il te manque celle-ci → ici ») parle à
des **motivations différentes** (valeur/dealer, histoire, complétion). Tentation : détecter le
profil et adapter. **Pushback (R0)** : pas de moteur de personnalisation avant d'avoir une
**baseline** de motivations. La recherche existe déjà (Bartle, Quantic Foundry, psycho du
collectionneur — cf. recherche [`01`](./psychologie-documentation/)). Premier move :
**un reveal qui sert plusieurs motivations d'un coup**, défaut sensé + lentille choisie par
l'utilisateur, pas devinée. Le profiling adaptatif est une piste *ultérieure*, pas un prérequis.

---

## Les 8 catégories (grille « biais → idée qui remplit le gap »)

Regroupées en 4 clusters. Chaque catégorie = **levier psychologique** + **tension propre
à Eurio** + **références à étudier** + **statut recherche**.

### Cluster A — Le problème structurel

| # | Catégorie | Levier / mécanisme | Tension Eurio | À étudier | Recherche |
|---|---|---|---|---|---|
| 1 | **Supply physique finie** (« bocal froid ») | contrainte structurelle (pas un biais) | collectible fini par user, gated par le réel | Pokémon GO (gating géo/œufs), geocaching, Discogs, apps philatélie/numismatique | 🔄 contexte [`02`](./psychologie-documentation/02-qui-paie-en-especes.md) |
| 2 | **Gamifier l'acquisition réelle** | quêtes, chasse au trésor, déclencheurs comportementaux | on ne crée pas de pièces, mais on incite la *chasse* (casser un billet, demander aux potes, fouiller sa monnaie) | design de quêtes/missions, nudges d'habitude, chasse IRL ; relie affiliation + marketplace | 🔄 contexte [`02`](./psychologie-documentation/02-qui-paie-en-especes.md) |

### Cluster B — Les moteurs d'engagement

| # | Catégorie | Levier / mécanisme | Tension Eurio | À étudier | Recherche |
|---|---|---|---|---|---|
| 3 | **Streak / aversion à la perte** | loss aversion + coût irrécupérable ; « rien derrière », pur levier psy | sur quoi accrocher la streak ? (cf. rituel renouvelable) | Snapchat flammes, Duolingo (streak freeze/repair), ligne du dark pattern à ne pas franchir | 🟢 [`04`](./psychologie-documentation/04-streak-vs-defis.md) → **défis adaptatifs, pas streak rigide** |
| 4 | **Statut, classement & comparaison sociale** | position relative = dopamine | « ta collection vaut €X, top 2% », classements, « plus loin que tes potes » | Spotify Wrapped, leaderboards (+ côté sombre : démotive les perdants), preuve sociale | 🟢 [`03`](./psychologie-documentation/03-comparaison-sociale-classement.md) |
| 6 | **Complétion & double axe de progression** | pulsion de complétion (Zeigarnik, endowed progress), paliers de rareté | **2 barres** que Pokémon n'a pas : dex + carte eurozone ; rareté *objective* (tirages → Monaco/Vatican = légendaires) | psycho de complétion de sets, effet quasi-complétion, tiers de rareté | 🟢 [`06`](./psychologie-documentation/06-completion-double-axe.md) → double Zeigarnik + sous-sets + carte à gratter |

### Cluster C — L'expérience ressentie

| # | Catégorie | Levier / mécanisme | Tension Eurio | À étudier | Recherche |
|---|---|---|---|---|---|
| 5 | **La « juice » du scan** | game feel + récompense variable | scan → vibration → reveal → valeur ; **équivalent du pack opening** mais le paquet = la pièce réelle (chaque scan doit *se sentir* comme un pull) ; 3D auto-généré du lieu/monument | game juice, animations de reveal (pull gacha, pack opening), reward schedules | 🟢 [`05`](./psychologie-documentation/05-juice-du-scan.md) → **pull éthique** (incertitude épistémique, pas hasard) |
| 7 | **Sens & storytelling** | objet qui a du sens + effort pour le mériter > objet acheté | chaque pièce = un bout d'Histoire de l'Europe dans ta poche ; checklist → collection qui *compte* | narration dans les produits de collection, psycho des objets signifiants, The Conqueror, « gagner » vs « acheter » | 🟢 [`07`](./psychologie-documentation/07-sens-storytelling.md) → IKEA effect natif + transportation |

### Cluster D — L'emballage

| # | Catégorie | Levier / mécanisme | Tension Eurio | À étudier | Recherche |
|---|---|---|---|---|---|
| 8 | **Marque & positionnement** | identité, ton, naming | gamifié **mais** premium (« Leica × Pokémon »), audience large ; nom élastique : **Eurio = parapluie** (tient jusqu'à la marketplace) / **Eurodex = nom de la feature** | positionnement, naming, identité visuelle collector-premium-joueur | 🟢 [`08`](./psychologie-documentation/08-marque-positionnement.md) → Eurio parapluie + « collection sans manipulation » |

---

## Système de docs

- **Ce doc** (`psychologie-retention.md`) = synthèse vivante, décisions, principes.
- **[`psychologie-documentation/`](./psychologie-documentation/)** = recherches **brutes**
  sourcées, une par sujet (`NN-slug.md`). On y creuse une catégorie à la fois, puis on
  **remonte** les conclusions ici (statut 🔲 → 🟢, et on raffine les principes ci-dessus).
- **[`psychologie-experience-mapping.md`](./psychologie-experience-mapping.md)** = la **synthèse
  design** : mapping des leviers ci-dessus vers les surfaces de l'app (écrans, notifs, partage).
  C'est là qu'on traduit la psycho en UX (avant proto/Compose).

## Statut

Grille posée (2026-06-01). Recherches : à lancer, **une catégorie à la fois**, chunk-by-chunk.
Premier sujet : la **baseline motivations** (catégorie profiling / sert 1-8).
