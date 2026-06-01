# 05 — La « juice » du scan (le moment qui fait kiffer)

> **Question de recherche** : le scan est notre équivalent du *pack opening*. Comment le rendre
> **satisfaisant** (game feel, animation, haptique, son, reveal) — *sans* tomber dans le poison
> du loot box/gacha (que Raphaël refuse) ? Et comment afficher **beaucoup d'infos** (collection,
> histoire, prix, rareté « énième à scanner », complétion de série) **sans surcharge**, avec le
> **modèle 3D de la pièce** en héros, sur un écran de téléphone ?
>
> **Date** : 2026-06-01 · **Catégorie** : 5 (juice) · lié 6 (complétion), 4 (statut) ·
> **Statut** : 🟢.

---

## L'insight central — notre dopamine est *éthique par construction*

Le gacha tire sa dopamine d'une **incertitude aléatoire** (le hasard sur *ce que tu obtiens*) :
calendrier de renforcement **à ratio variable** (Skinner) — le système le plus addictif connu,
celui des machines à sous ([Outsider Gaming](https://outsidergaming.com/loot-boxes-gacha-mechanics-mobile-games/),
[PC Gamer](https://www.pcgamer.com/behind-the-addictive-psychology-and-seductive-art-of-loot-boxes/)).
Les cellules à dopamine sont **maximalement actives sous incertitude maximale**, et **l'anticipation
d'un gros gain libère plus de dopamine que la réception** d'une petite récompense garantie. C'est
aussi là que vit l'**effet near-miss** (rater d'un cran ressemble à gagner) — du **jeu d'argent
déguisé**, la frontière qu'on **refuse**.

**Chez Eurio, il n'y a pas de hasard** : tu scannes une pièce que tu **tiens déjà**, tu sais
laquelle. Donc notre dopamine ne peut pas venir de l'aléatoire — et **tant mieux** : elle vient
d'une **incertitude épistémique** (ce que tu *ne savais pas encore*) :

- *Qu'est-ce que cette pièce raconte ?* (histoire/sens — découverte)
- *Est-elle rare ? je suis le combien à la scanner ?* (statut — N-effect)
- *Où ça me place ? ça complète une série ?* (complétion)
- *Combien elle vaut ?* (valeur)

→ **Le scan EST le pull, mais le payload est du SENS/STATUT/PROGRÈS, pas un tirage.** Déterministe,
mérité par un objet réel. On garde **l'anticipation et le reveal** (les vrais moteurs dopamine),
on jette **le hasard, le near-miss, la boucle de jeu d'argent**. C'est notre ligne, claire et nette.

On garde aussi l'**investissement émotionnel social** (légitime) : recevoir un objet convoité
active un circuit proche du **lien social** ; partager une pièce rare = statut/validation sociale
(cf. partage, cat. 4/6). Ça, c'est sain.

## Game feel & juice (la couche sensorielle)

« Juicing » = prendre une interaction qui marche et ajouter des couches d'**animation + audio**
satisfaisantes ([GameDeveloper](https://www.gamedeveloper.com/design/squeezing-more-juice-out-of-your-game-design-),
[GameAnalytics](https://www.gameanalytics.com/blog/squeezing-more-juice-out-of-your-game-design)).
Références : **Vlambeer, *The Art of Screenshake*** (maître du screenshake) ; **Steve Swink,
*Game Feel: A Designer's Guide to Virtual Sensation***. L'UX suit des règles objectives ; le juice
est **personnel et émotionnel** — c'est la signature de marque.

Pour Eurio, le **héros = le modèle 3D de la pièce** (rotatable, dans une scène/décor 3D), en
**haut-centre** (la demande de Raphaël). Le reveal s'**anime vers** ce héros (l'objet « atterrit »,
tourne, capte la lumière) — c'est notre screenshake à nous, premium et pas criard.

## Le multisensoriel (haptique + son + célébration)

- **Haptique** : la réponse-récompense aux vibrations **culmine à ~400 ms** ; des vibrations
  *gratifiantes* augmentent l'envie de réitérer l'action
  ([JCR / Oxford](https://academic.oup.com/jcr/advance-article/doi/10.1093/jcr/ucaf025/8120234)).
  → un buzz court et *qualitatif* au moment du reveal, modulé par la rareté (légendaire = haptique
  plus riche).
- **Son** : ping/chime court au reveal, renforce le succès
  ([Glance](https://thisisglance.com/blog/microinteractions-boosting-user-engagement-in-mobile-app-design)).
  Designer une **signature sonore** (la « note Eurio »).
- **Célébration & peak-end** : une animation de célébration sur un **moment significatif** (compléter
  un set, une légendaire) booste la satisfaction et s'ancre via le **peak-end rule** (on retient le
  *pic* et la *fin*). → on **réserve** le grand feu d'artifice aux vrais jalons (pas à chaque scan,
  sinon inflation et le « pic » s'aplatit).

## Architecture de l'info (beaucoup à dire, petit écran)

Le risque de Raphaël (« on a bien plus que 3 infos ») se gère par 3 lois UX
([Laws of UX](https://lawsofux.com/hicks-law/), [Miller](https://www.cursorup.com/blog/millers-law),
[IxDF — progressive disclosure](https://ixdf.org/literature/topics/progressive-disclosure)) :

- **Miller (7±2)** : la mémoire de travail tient ~5-7 items. **Grouper**, limiter par section.
- **Hick** : plus d'options/infos = décision plus lente. **Moins = plus rapide, plus fort.**
- **Progressive disclosure** : montrer **l'essentiel d'abord**, la profondeur à la demande.
  Hiérarchie visuelle (taille/contraste/espace) pour guider l'œil.

→ **Le reveal de scan n'a PAS à tout dire.** Structure recommandée :

| Couche | Contenu | Principe |
|---|---|---|
| **Héros** | 3D de la pièce (haut-centre), animé | game feel, focal point |
| **Primaire (≤3 drives)** | Découverte (titre + une ligne d'histoire) · Complétion (« nouvelle ! 24/27 ») · 1 accent contextuel (rareté **ou** valeur, selon la pièce) | Miller/Hick : on plafonne à 3 |
| **Profondeur** | tap → **page de la pièce** : histoire complète, cote par qualité, tous les détails, série complète | progressive disclosure |

L'idée de Raphaël est juste : **le scan = le pic émotionnel resserré ; la page pièce = la
profondeur**. On ne sacrifie aucune info, on la **stratifie**.

**Accent contextuel** (le 3ᵉ slot, dynamique, *pas* du profiling — juste la pièce) :
- pièce rare → « tu es le **3ᵉ** à la scanner ce mois-ci » / « 2% la détiennent » (N-effect, cat. 4) ;
- pièce qui **boucle une série** → « ça complète : Allemagne 2023 X/Y » (complétion, cat. 6) ;
- pièce de valeur notable → « ~12€ en TTB » (valeur) ;
- sinon → la découverte respire (histoire un peu plus longue).

**Lentille au choix** (autonomie SDT, [`01`](./01-motivations-baseline.md)) : l'user peut épingler
l'accent qu'il préfère voir en gros (valeur / histoire / complétion). Le **défaut = Découverte**
(universel). Pas de moteur qui devine.

## La ligne du dark pattern (spécifique juice)

- ❌ **Pas de hasard / tirage / near-miss** — pas de boucle de jeu d'argent. (Notre force : il n'y
  en a pas besoin, le payload est déterministe.)
- ❌ Pas de **célébration inflationniste** (tout célébrer = ne rien célébrer + manipuler).
- ❌ Pas d'**haptique/son agressif** ou trompeur (vibration de « gain » sur un non-événement).
- ✅ Anticipation + reveal + multisensoriel **au service de l'info réelle**, pic réservé aux jalons.

## Ce qu'on en retient (→ doc vivant + mapping §1)

1. **Le scan = un pull éthique** : on garde anticipation + reveal + multisensoriel ; on jette le
   hasard/near-miss. Dopamine = **incertitude épistémique** (sens/statut/progrès), pas aléatoire.
2. **Héros 3D haut-centre**, reveal animé vers lui, haptique ~400 ms modulée rareté, signature
   sonore, célébration **réservée aux jalons** (peak-end).
3. **Stratifier l'info** : héros + **≤3 drives** (Découverte + Complétion + 1 accent contextuel) →
   tap vers la **page pièce** pour la profondeur. On ne perd rien, on hiérarchise (Miller/Hick).
4. **Accent contextuel** piloté par *la pièce* (rareté/série/valeur), **lentille épinglable** par
   l'user — toujours sans profiling (R0).

## Questions ouvertes (pour Raphaël)

1. **Plusieurs vues de reveal** proposées (puis défaut), ou un seul reveal + lentille épinglable ?
   (mon penchant : un reveal, lentille épinglable — moins de surface, plus net.)
2. Le **3D** : scène/décor unique de marque, ou décor qui évoque le **thème de la pièce**
   (monument/événement) — et est-il *généré* (cf. ton idée) ou *stylisé* manuellement ? (impacte
   le coût ; à arbitrer, sans doute proto d'abord — R1.)
3. Quels **jalons** méritent le grand feu d'artifice (set complété, pays complété, légendaire,
   100ᵉ pièce) ? → ça définit l'économie des célébrations.

## Sources

- Game feel / juice : [GameDeveloper](https://www.gamedeveloper.com/design/squeezing-more-juice-out-of-your-game-design-) · [GameAnalytics](https://www.gameanalytics.com/blog/squeezing-more-juice-out-of-your-game-design) · Vlambeer *The Art of Screenshake* · Swink *Game Feel*
- Loot box / gacha / variable reward : [Outsider Gaming](https://outsidergaming.com/loot-boxes-gacha-mechanics-mobile-games/) · [PC Gamer](https://www.pcgamer.com/behind-the-addictive-psychology-and-seductive-art-of-loot-boxes/) · [near-miss (Geek Vibes)](https://geekvibesnation.com/loot-boxes-gacha/)
- Haptique / microinteractions / peak-end : [JCR Oxford — haptic rewards](https://academic.oup.com/jcr/advance-article/doi/10.1093/jcr/ucaf025/8120234) · [Glance](https://thisisglance.com/blog/microinteractions-boosting-user-engagement-in-mobile-app-design)
- Charge cognitive / hiérarchie : [Hick's Law](https://lawsofux.com/hicks-law/) · [Miller's Law](https://www.cursorup.com/blog/millers-law) · [Progressive disclosure — IxDF](https://ixdf.org/literature/topics/progressive-disclosure)
