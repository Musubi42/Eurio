# Décisions — la pêche DINO

> Écrit le 2026-08-20, à la livraison. Chaque décision dit ce qu'elle **écarte**,
> sinon on la rejouera. Les mesures qui les fondent sont dans
> [`CONSTAT.md`](CONSTAT.md).

## D1 · Le périmètre par prédiction REMPLACE celui par cible, il ne s'y ajoute pas

`dino_class` court-circuite `eurio_id` / `cohort_id` / `design_group`.

**Pourquoi** : les combiner garderait le filtre `kind='single'` que le scope
standard impose, et les crops de LOTS resteraient inatteignables — or ils sont
136 sur 137 du gisement italien. Un « et » aurait rendu la fonctionnalité
inutile tout en ayant l'air de marcher.

**Écarté** : un repli automatique « pêche si elle donne quelque chose, sinon
cible ». Le périmètre deviendrait dépendant de l'item, deux crops voisins
seraient servis par deux règles, et l'écran ne pourrait plus dire ce qu'il
montre.

## D2 · Trois paliers de rang (1 / 3 / 5), pas un curseur

**Pourquoi** : le rang n'est pas une grandeur continue, et un champ libre
inviterait à demander un top-20 dont la précision n'a jamais été mesurée. Un
rang hors paliers lève (`422`) au lieu de servir un périmètre plausible et faux.

**Écarté** : un rang par défaut plus large que 1. Le top-3 double le pool
(139 → 321 sur IT) mais y ajoute du bruit ; c'est un recours pour une classe
affamée, pas un défaut.

## D3 · La marge est un signal affiché, pas un filtre par défaut

Le palier de marge existe (`toutes` / `≥ 0,05` / `≥ 0,10`), avec la précision
mesurée en infobulle, mais le défaut est `toutes`.

**Pourquoi** : à `≥ 0,10`, BE ne garde que 2 candidats pour 5 crops à trouver —
filtrer par défaut affamerait précisément les classes qu'on vient nourrir. Le
tri `order=dino` fait déjà couler le flou en bas de file.

**Écarté** : `≥ 0,05` par défaut, tentant après avoir vu une pièce de 1 cent
remonter. On a traité ce cas autrement (D5).

## D4 · Les lots sont ordonnés par NOMBRE de candidats, pas par meilleure marge

**Pourquoi** : mesuré. Trier la file belge par meilleure marge met six coffrets
**autrichiens** en tête (0,126 · 0,107 · 0,071…). Sur les standards à portrait,
une marge élevée signale souvent une erreur confiante, pas une trouvaille.
L'ordre par nombre met les coffrets belges devant — là où une Philippe se
trouve vraiment, même si le modèle y est peu sûr.

**Écarté** : l'ordre historique « le plus ancien d'abord », qui ouvrait la file
italienne sur un coffret français de 36 crops dont **un** appartenait à la
classe.

## D5 · Le lot s'ouvre sur le crop de MEILLEURE MARGE, pas sur le premier

`LotCrop` porte `dino_spread` ; les crops marqués sont triés par marge
décroissante et le curseur se pose sur le premier.

**Pourquoi** : un coffret mélange 1 cent et 2 €. La banque ne contient que des
2 € — une piécette se fait donc rattacher à la classe la plus proche avec une
marge dérisoire (0,018 mesuré). Ouvrir par index, c'était ouvrir sur elle.

**Écarté** : exclure les crops à marge faible du marquage ⌁. Ils restent
marqués et visibles — c'est une file où un humain regarde, et masquer serait
décider à sa place.

## D6 · Les orphelins sont COMPTÉS en lecture, ENFILÉS sur un clic

Les crops `needs_review` sans ligne de review ouverte apparaissent au compteur ;
un bouton explicite appelle `POST /coins/assets/reflag-needs-review`.

**Pourquoi** : enfiler est une écriture. Une écriture déclenchée au fil d'une
lecture est invisible à celui qui la provoque. Et taire ce stock, c'est le
laisser invisible pour toujours — il n'apparaît dans aucune autre file.

**Écarté** : l'enfilage automatique à l'ouverture de la page.

## D7 · Un seul corps pour les deux jumeaux

`review/review_queue_routes.py` (lourd, `:8042`) délègue à
`serving/review_queue/repository.py` (lean, VPS) pour la liste de lots, les
voisins et le résumé ; les deux partagent `shared/dino_scope.py`.

**Pourquoi** : les deux servaient deux copies du même SQL. Les faire diverger
n'aurait levé aucune erreur — seulement rendu deux réponses différentes selon
l'hôte interrogé.

**Écarté** : une fusion complète des deux modules. Hors périmètre, et le lourd
porte des routes que l'image lean ne peut pas monter (cv2).

## D8 · Plus aucun repli sur des données fictives

Supprimé du chemin de lecture **et** d'écriture (cf. `CONSTAT.md` §Pannes).
Seule exception : `fetchDinoCandidates` rend `null` — c'est un compteur
d'en-tête, `null` s'affiche « … », soit « on ne sait pas », un état honnête.

**Écarté** : garder le mock derrière un drapeau de développement. Un drapeau
s'oublie, et le coût du mock n'est pas son existence mais le fait qu'il soit
**indiscernable du vrai** à l'écran.

---

## Q1 · La question ouverte, pour la prochaine session

**Faut-il restreindre la pêche aux annonces du pays de la classe ?**

Les chiffres sont dans `CONSTAT.md` : ça coûterait **~6 %** des vrais positifs
(93,8 % des standards validés viennent d'une annonce du bon pays) et couperait
**82 % du bruit** sur l'Espagne (76 → 14).

Trois formes possibles, à trancher :

1. **filtre par défaut + échappatoire** — le plus efficace, mais il cache 6 % de
   matière sans le dire à qui ne connaît pas le réglage ;
2. **un palier de plus à côté de la marge** (`tous pays` / `pays de la classe`) —
   cohérent avec ce qui existe, laisse le choix, ne cache rien ;
3. **ne rien filtrer, et lire le top-1 SCOPÉ PAYS** (`top1_country_eurio_id`,
   déjà en base et déjà utilisé par le verdict) — potentiellement le vrai
   correctif, à mesurer avant tout code.

⚠️ **Mesurer 3 avant d'implémenter 1 ou 2.** Si le top-1 scopé pays fait le
travail, un filtre applicatif serait une rustine posée par-dessus une colonne
qui existait déjà.

## Q2 · Ce que ce chantier ne prétend pas résoudre

La banque confond les standards à portrait entre eux. C'est un sujet
d'**encodeur et de banque**, pas d'écran : il vit dans
[`../banque-dino/`](../banque-dino/) et
[`../scan-sans-retrain/`](../scan-sans-retrain/). La pêche rend ce défaut
visible et navigable ; elle ne le corrige pas.
