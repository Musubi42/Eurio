# 01 — Taxonomie des motivations (baseline avant profiling)

> **Question de recherche** : avant de « profiler » qui que ce soit, quelles sont les
> motivations *connues et validées* qui poussent à jouer et à collectionner ? Sur quelle
> baseline ancrer le design du reveal post-scan et de la rétention, sans construire un
> moteur de personnalisation prématuré (R0) ?
>
> **Date** : 2026-06-01 · **Catégories liées** : profiling + transverse 1-8 ·
> **Statut** : brut, 1ʳᵉ passe littérature (pas encore de données *nos* users).

---

## Pourquoi cette recherche d'abord

Le débat « le `+40€` post-scan, c'est la bonne 1ʳᵉ info ? » est en réalité un débat de
**motivations** : la valeur ne parle qu'au profil *investisseur/statut* et trahit
l'historien et le complétionniste. Plutôt que deviner le profil de chaque user (dette,
prématuré), on pose une **baseline issue de la recherche** : un petit ensemble récurrent de
drives, qu'on peut **servir simultanément** dans un même écran, avec une lentille que le
user *choisit* plutôt qu'on devine.

Quatre corpus convergent vers les mêmes familles de motivations. Je les croise ci-dessous.

---

## 1. Gamer Motivation Model (Quantic Foundry)

Modèle empirique par analyse factorielle sur **140k → 250k+ joueurs**. **6 motivations / 12
facettes** (paires) ([modèle](https://quanticfoundry.com/gamer-motivation-model/),
[clusters](https://quanticfoundry.com/2015/12/21/map-of-gaming-motivations/),
[fiche de référence PDF](https://quanticfoundry.com/wp-content/uploads/2019/04/Gamer-Motivation-Model-Reference.pdf)) :

| Motivation | Facette A | Facette B |
|---|---|---|
| **Action** | Destruction (chaos, mayhem) | Excitement (rythme, surprises) |
| **Social** | Competition (duel, classement) | Community (collaboration, appartenance) |
| **Mastery** | Challenge (difficulté, pratique) | Strategy (anticiper, décider) |
| **Achievement** | **Completion** (tout obtenir, finir les sets) | Power (puissance, équipement) |
| **Immersion** | Fantasy (être ailleurs/autre) | **Story** (histoires, personnages) |
| **Creativity** | Design (expression, customisation) | **Discovery** (explorer, bidouiller) |

**Findings utiles** : les motivations se regroupent en 3 clusters de haut niveau ; *Completion*
et *Power* corrèlent (Achievement) ; *Challenge*/*Strategy* corrèlent (Mastery) ;
effets démographiques nets — l'âge fait **chuter** Action/Competition, et *Completion*,
*Fantasy*, *Design* scorent plus haut chez les femmes, *Competition*/*Destruction* chez les
hommes. → un public **large et plutôt mûr** (collectionneurs) pousse vers
**Completion / Discovery / Story**, *pas* vers Action/Competition.

## 2. Taxonomie de Bartle (4 types)

Issue des MUD, 1996, toujours la grille de référence en gamification
([Wikipedia](https://en.wikipedia.org/wiki/Bartle_taxonomy_of_player_types),
[IxDF](https://ixdf.org/literature/article/bartle-s-player-types-for-gamification)) :

- **Achievers** ♦ — battre des défis, accumuler points/statut/complétion.
- **Explorers** ♠ — découvrir le monde *et* les mécaniques (lore, détails).
- **Socializers** ♥ — la relation prime sur la victoire ; majorité du public grand-public.
- **Killers** ♣ — domination, compétition directe sur les autres.

Pour Eurio : Achievers (complétion) + Explorers (lore/histoire des pièces) sont le cœur de
cible naturel ; Socializers = le levier viral (partage) ; Killers = marginal (peu de PvP),
mais nourrissent les classements.

## 3. Psychologie du collectionneur (recherche conso)

La littérature dédié au **collectionner** (≠ jouer) ajoute des drives spécifiques
([Wikipedia](https://en.wikipedia.org/wiki/Psychology_of_collecting),
[Belk — perspective psycho-sociale](https://www.researchgate.net/publication/232980144_Collectors_and_Collecting_A_Social_Psychological_Perspective),
[modélisation set completion (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S0167487007000682)) :

- **Belk (1988-91)** : collectionner = **légitimation** + **extension de soi**. La collection
  affiche un soi élargi via **pouvoir, savoir, mémoire d'enfance, prestige, maîtrise**.
- **Pearce (1993)** : liste large — loisir, esthétique, compétition, risque, fantaisie,
  **sentiment de communauté**, prestige, domination, gratification sensorielle, **quête de
  perfection**.
- **Complétion = drive central** : posséder + **désir de compléter** définissent le
  collectionneur. Finir le set augmente la valeur **financière, psychologique ET sociale** ;
  Belk : *« compléter la collection complèterait symboliquement le soi »*.
- **Sécurité financière** apparaît explicitement comme motivation (≈ le profil « valeur/€ »).

## 4. Le drive « contrôle / structure » (Cao, Brucks & Reimann)

6 études : **le désir de contrôle motive le fait de collectionner**
([PDF](https://martinreimann.com/pdf/Cao,%20Brucks,%20Reimann.%20Seeking%20Structure%20in%20Collections.pdf)).
Collectionner = **mettre de l'ordre dans le chaos** : relier des items en un tout cohérent
donne structure et agentivité, surtout en période d'incertitude. Implications design
explicites des auteurs : **rendre visibles les jalons de complétion**, **structurer en
sous-ensembles modulaires** (catégories/sets), **cadrer l'activité comme ordonnée et
maîtrisable**.

## 5. Le méta-cadre — Self-Determination Theory (le *garde-fou*)

SDT (Ryan & Deci) : 3 besoins psychologiques fondamentaux — **autonomie, compétence,
relatedness** ([Yu-kai Chou](https://yukaichou.com/gamification-analysis/self-determination-theory-guide-to-ryan-and-decis-motivation-framework/),
[méta-analyse gamification](https://link.springer.com/article/10.1007/s11423-023-10337-7),
[mHealth/SDT](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8391751/)).

**Avertissement central pour nous** : points/badges utilisés comme **mécanismes de contrôle
extrinsèques** *minent* la motivation intrinsèque. Ce qui marche durablement : game mechanics
qui donnent un **feedback de compétence**, des **choix signifiants**, et de la **connexion
sociale**. La méta-analyse note un effet fort sur autonomie + relatedness, faible sur
compétence → la gamification doit *soutenir les 3* besoins, pas plaquer des récompenses.

→ Conséquence directe : le reveal « +40€ » seul est un **carrot extrinsèque**. Risqué s'il
écrase le sens (compétence, découverte). Il doit cohabiter avec du feedback de progression
(compétence) et du sens (story).

---

## Synthèse — la baseline de motivations Eurio

Convergence des 4 corpus → **6 drives** pour le collectionneur de pièces. (Aucun n'exclut
les autres ; un même user en a plusieurs, dosés différemment.)

| Drive Eurio | Sources qui convergent | Ce que ça veut voir dans l'app |
|---|---|---|
| **Complétion** | Quantic *Completion* · Bartle *Achiever* · Belk/ScienceDirect set-completion · Cao structure | « 9/10, il te manque celle-ci » ; barres dex + carte ; sous-sets |
| **Découverte / savoir** | Quantic *Discovery* · Bartle *Explorer* · Belk *savoir* | l'histoire de la pièce, le lore, le « tu savais que… » |
| **Statut / prestige / pouvoir** | Quantic *Power*+*Competition* · Bartle *Killer* · Belk *prestige* | classements, « top 2% », rareté affichée, légendaires |
| **Valeur / sécurité financière** | Belk/Pearce *sécurité financière* | le `+40€`, la cote, « combo qui se vend bien » |
| **Sens / identité** | Quantic *Story/Fantasy* · Belk *extension de soi* | « l'Histoire de l'Europe dans ta poche », objet qui *compte* |
| **Social / appartenance** | Quantic *Community* · Bartle *Socializer* · SDT *relatedness* | partage, comparaison aux potes, communauté |

+ un **drive transversal** (Cao) : **contrôle/structure** — collectionner pour *ordonner*.
Il ne demande pas un écran à lui, il **valide** que complétion + organisation modulaire (sets)
sont au cœur, pas un gadget.

## Ce qu'on en retient pour Eurio (→ remonte dans le doc vivant)

1. **Pas de profiling à construire.** La baseline littérature suffit pour designer. Le profiling
   adaptatif reste une piste *ultérieure*, à valider d'abord par de la donnée *réelle* (cf. trou
   ci-dessous).
2. **Le reveal post-scan doit servir ≥3 drives d'un coup**, pas seulement la valeur. Défaut
   proposé à débattre : **complétion** (où ça te place) + **sens** (l'histoire) + **valeur**
   (la cote) visibles ensemble ; `+40€` n'est *pas* la 1ʳᵉ info universelle.
3. **Lentille choisie, pas devinée** : laisser l'utilisateur mettre en avant ce qui le motive
   (valeur / histoire / complétion) = autonomie (SDT) sans moteur de profiling.
4. **Garde-fou SDT** : toute mécanique (streak, badges, €) doit donner *compétence* (feedback de
   progression) + *autonomie* (choix) + *relatedness* (social), sinon elle érode la motivation
   intrinsèque au lieu de la nourrir. C'est le critère de tri de toutes les catégories 3-7.
5. **Le cœur de cible naturel** = Achiever (complétion) + Explorer (lore) + Socializer (viral),
   public **large et mûr** → on ne mise PAS sur Action/Competition agressive.

## Trou / prochaine étape

Ceci est une baseline **littérature**, zéro donnée sur *nos* users. Avant tout profiling :
valider par de la donnée réelle (entretiens, mini-sondage in-app « qu'est-ce qui te plaît :
valeur / histoire / compléter ? », ou l'analytics du reveal). À garder pour plus tard —
pas un prérequis pour avancer sur le design baseline.

## Sources

- Quantic Foundry — [Gamer Motivation Model](https://quanticfoundry.com/gamer-motivation-model/) · [map des motivations](https://quanticfoundry.com/2015/12/21/map-of-gaming-motivations/) · [fiche PDF](https://quanticfoundry.com/wp-content/uploads/2019/04/Gamer-Motivation-Model-Reference.pdf)
- [Bartle taxonomy — Wikipedia](https://en.wikipedia.org/wiki/Bartle_taxonomy_of_player_types) · [Bartle pour la gamification — IxDF](https://ixdf.org/literature/article/bartle-s-player-types-for-gamification)
- [Psychology of collecting — Wikipedia](https://en.wikipedia.org/wiki/Psychology_of_collecting) · [Belk — Collectors and Collecting](https://www.researchgate.net/publication/232980144_Collectors_and_Collecting_A_Social_Psychological_Perspective) · [Set completion — ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0167487007000682)
- [Cao, Brucks & Reimann — Seeking Structure in Collections (PDF)](https://martinreimann.com/pdf/Cao,%20Brucks,%20Reimann.%20Seeking%20Structure%20in%20Collections.pdf)
- SDT : [Yu-kai Chou](https://yukaichou.com/gamification-analysis/self-determination-theory-guide-to-ryan-and-decis-motivation-framework/) · [méta-analyse gamification (Springer)](https://link.springer.com/article/10.1007/s11423-023-10337-7) · [mHealth & SDT (PMC)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8391751/)
