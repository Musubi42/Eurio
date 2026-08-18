# Les 5 vues — écran par écran

> Cible, pas état actuel. À corriger avant toute implémentation.

## Règles communes aux 5 vues

1. **On compte en CLASSES.** La pièce est un détail dépliable, jamais l'unité.
2. **Chaque vue ne liste que les classes qui n'y sont pas encore.** Elles se
   vident quand on avance. Une vue vide est une bonne nouvelle, pas un bug — elle
   le dit explicitement.
3. **Une vue = une question = une action.** Pas de tableau à sept colonnes d'où
   partent cinq boutons.
4. **On montre le résultat de l'effort, pas l'étage technique.** « +12 photos
   pour Italie standard », pas « 412 annonces retenues ».
5. **Aucun écran ne ment en silence.** Un compteur qui ne bouge pas dit pourquoi
   (en attente de synchro, crop passé en revers, photo attribuée à une autre pièce…).
6. **Les seuils viennent du back.** Le front n'en définit aucun.

## Vue 0 — L'en-tête, commun aux 5

Deux éléments seulement :

- **La frise des 5 étapes**, cliquable, qui dit où l'on est et ce qu'il reste à
  chacune. Elle est le routeur, pas un tableau de bord.
- **Une ligne d'arrivée** : les classes placées selon leurs photos, avec le
  plancher marqué. On voit d'un coup le peloton et les retardataires.

## Vue 1 — Classes

**Question** : qu'est-ce qu'on veut reconnaître ?

- La liste des classes de la cohorte, avec **le nombre de pièces regroupées**
  et lesquelles (dépliable).
- Ajouter / retirer une classe.
- Signale les pièces sans face de référence.

**Attention** : afficher le regroupement en clair. « Drapeau européen 2015 —
21 pièces » doit être lisible sans ouvrir quoi que ce soit ; c'est l'information
qui explique pourquoi trier une photo maltaise fait monter la classe.

## Vue 2 — Matière

**Question** : a-t-on des images pour ces classes ?

- Ne liste **que** les classes que le tri seul n'amènera pas au plancher.
- Sélection multiple, **un seul bouton**, estimation du quota avant de lancer.
- Pendant le run : progression. Après : **ce que ça a rapporté à cette classe**,
  et ce que ça a rapporté aux autres (découverte par pays).
- Dit toujours : *la découverte se fait par pays entier*.

## Vue 3 — Crops

**Question** : a-t-on des découpes exploitables ?

- Ne liste que les classes ayant des **images jamais découpées**.
- Un bouton par classe (ou groupé) : relancer la découpe, avec la passe de
  secours **toujours active** — c'est un mode d'enrichissement hors ligne, jamais
  le scan téléphone.
- Après le run : combien de crops récupérés, et « épuisé » **uniquement** quand
  ça l'est vraiment.

## Vue 4 — Validées

**Question** : quelles photos sont sûres ?

C'est la vue où l'on passe du temps. **Une cascade, pas cinq écrans.**

- La file : les classes sous le plancher, **la plus rapide à débloquer en tête**.
- Pour la classe en main : le compteur `n / plancher`, ce qui manque, et le stock
  restant à chaque niveau de la cascade (auto / single / lot).
- On entre dans la review **existante**, scopée sur la classe. On ne la réécrit pas.
- Un bandeau suit la classe pendant qu'on tranche, survit à la bascule
  single ↔ lot, et propose de passer à la suivante une fois le plancher franchi.
- **L'auto-résolu tourne avant** : si une classe est réglée sans intervention,
  elle n'apparaît jamais.

**Ordre de préférence** : auto → single → lot → rejetés à récupérer. La bascule
d'un niveau au suivant est **proposée, jamais imposée** : les raccourcis clavier
changent entre single et lot (`S` requalifie en single dans la vue lot), basculer
sans prévenir fait appuyer sur une touche qui ne fait plus la même chose.

## Vue 5 — Modèle

**Question** : est-ce que ça marche ?

- L'état du contrôle avant entraînement, et **ce qui bloque** s'il bloque.
- Lancer l'itération, choisir la machine (Mac pour un essai, PC pour un vrai run).
- Le résultat : taux de reconnaissance **par classe**, et surtout **les
  confusions** — c'est ce qui teste la règle de regroupement.
- Les captures device se branchent ici. Optionnelles : leur absence n'empêche pas
  d'entraîner, elle empêche de **mesurer**, et l'écran le dit.

## Ce qu'on garde de l'existant

- La page cohorte actuelle **reste** telle quelle.
- `/lab/cohorts-test/:id` est le bac à sable où l'on éprouve ces vues.
- Les écrans de review (single, lot, auto-accept, récupération) sont **réutilisés**,
  jamais réécrits.

## Dette du 2026-08-18 — retirée le jour même

- ~~`FLOOR = 10` et `GOAL = 30` en dur dans `useCohortFloor.ts`~~ → le plancher
  vient du canonique (`/lab/cohorts/{id}/thresholds`) et s'affiche **avec sa
  provenance** (« défaut du code » / « défaut global » / « réglage de cette
  cohorte »).
- ~~`GOAL = 30`~~ n'a pas été remplacé par un autre chiffre : **il a disparu**.
  Ce « plafond utile » n'était fondé sur rien. Au-dessus du plancher, ce qui se
  mesure vraiment est le **facteur d'augmentation** que le bake calcule déjà
  (`ceil(cible / sources réelles)`) : ×10 veut dire que neuf images sur dix
  seront des variations de la même photo. Trois endroits en dépendaient :
  - le tour 2 de la file trie désormais par facteur décroissant ;
  - le bandeau de review affiche « plancher franchi · augmentation ×N » ;
  - la bascule automatique ne se déclenche plus sur un compteur atteint mais
    quand la classe **n'a plus rien à trancher** — un fait, pas un seuil.
- Reste ouvert : deux vues font le même travail à moitié (page cohorte et page
  test). À trancher maintenant que les 5 vues existent.

## État d'implémentation (2026-08-18)

Les 5 vues vivent sur `/lab/cohorts-test/:id`, paramètre d'URL `?etape=`
(**pas** `?vue=` : c'est le marqueur interne de `@vitejs/plugin-vue`, une URL qui
le porte fait répondre 500 au serveur de dev).

| Vue | Composant | État |
|---|---|---|
| 0 · en-tête | `CohortRail` (frise-routeur 5 étapes) + `CohortFinishLine` + `CohortThresholdBar` | ✅ |
| 1 · Classes | `CohortClassList` | ✅ — 129 pièces / 40 classes, membres dépliables, les 7 « invisibles au sourcing » nommées |
| 2 · Matière | `CohortSourcingList` | ✅ (existant, plancher passé en prop) |
| 3 · Crops | `CohortCropList` | ✅ — 4 486 images, découpe par pièce, fuite vers les sœurs affichée |
| 4 · Validées | `CohortFloorQueue` + `CohortReviewStrip` + review existante | ✅ — les crops hors file y sont annoncés |
| 5 · Modèle | `CohortModelPanel` | ✅ — blocages nommés, R@1 et confusions par classe |
