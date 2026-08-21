# Décisions — pipeline propre

> Arbitrées avec le PO le **2026-08-21**, après la revue de
> [`VISION.md`](VISION.md) et [`FLOW-ADMIN.md`](FLOW-ADMIN.md) contre la
> réplique et le code. Chaque décision dit ce qu'elle écarte. Les mesures
> citées sont dans les docs liés, avec leur requête.

## D1 · « 8 photos par classe » = la voie B, la banque DINO

La cible du chantier est **8 exemplaires `fps` par `class_id` de banque**
(`dino_class_references`, `anchors_kind='2eur_all'`), plafond dur 10
(`DEFAULT_EXEMPLARS_PER_CLASS`). Pas les 10 `min_real` du préflight de cohorte
(voie A, ArcFace). La Station 0 compte la voie B et le dit dans son en-tête ;
la voie A s'affiche à côté, sur sa propre ligne, et n'entre dans aucun verdict.

*Écarte* : une barre unique « x/10 » qui mélangerait les deux comptes.

## D2 · Une classe à ≥ 8 en banque ne reçoit plus de travail de review

Les classes pleines (`have ≥ cap`) sortent de la liste de travail avec le
verdict `pleine`. Le tri se fait **par la prédiction DINO** : un crop dont le
top-1 (banque `2eur_all` / `vitl14`, via `bank_classes`) tombe dans une classe
pleine n'est pas servi. Ces classes ont assez d'exemplaires pour que le filtre
soit fiable — c'est ce qu'on attend d'elles.

*Écarte* : continuer à servir les 3 612 crops ouverts de classes pleines
(55 % de la file), et la médiane de 25 crops décidés pour un plafond de 10.

*Précision du 2026-08-21 (soir)* : « pleine » se déclenche à la **cible**
(`have ≥ target`, 8 ou 5 selon la famille), pas au plafond 10 du builder —
O1 disait `have ≥ cap`. Le plafond reste exposé (`ClassNeed.cap`) pour
l'affichage. Implémenté dans `shared/class_need.py::bottleneck_for`, gardé
par `test_pleine_a_la_cible_pas_au_plafond`. Mesuré sur la réplique :
671 classes, Σ need 4 426 (4 663 avec 8 partout — D4 économise 237),
pleine 67 · review 328 · scrape 276.

## D3 · Les crops des classes pleines sont GARDÉS, pas traités

On ne ferme pas, on ne supprime pas : ces crops serviront la voie A et les
classes qu'on voudra approfondir plus tard. Ils sont **parqués** — hors des
files de travail, toujours en base, toujours retrouvables. Le mécanisme
(nouvelle `lane`, statut, ou simple filtre d'affichage piloté par O1) est à
concevoir dans la phase design (D6) ; la contrainte est que « parqué » soit
une lecture **réversible** et **visible** (le compte des parqués s'affiche),
jamais une écriture de masse sur 55 % du stock.

*Écarte* : la fermeture en masse envisagée en VISION §8 Q2.

## D4 · Émissions communes : on reconnaît le DESSIN, le pays vient d'ailleurs

Pour les 87 classes `emission_commune` (5 `design_group_id` multi-pays),
l'objectif de la banque est de reconnaître **l'émission** (97,7 % mesurés),
pas le pays (64,4 %, et aucune quantité de crops ne le corrigera). Le pays
vient des **autres signaux** : texte de l'annonce, pays de la recherche,
lecture humaine. Conséquences pour O1/O5 : la cible 8 se mesure au grain
**dessin** pour ces classes.

**Mesuré le 2026-08-21** (courbe restreinte aux 87 classes, `vitl14`,
held-out 102 crops / 15 classes — population mince, p non significatifs) :

```bash
cd ml && EURIO_DB_PATH=$PWD/state/eurio.replica.db ./.venv/bin/python \
  -m scripts.bench_refs_curve --model dinov2_vitl14 --refs 0 1 2 3 5 8 10 \
  --bank-classes @emissions_communes.txt --gold-classes @emissions_communes.txt
# emissions_communes.txt = les 87 eurio_id des design_group_id multi-pays
```

| N | global@1 (pays compris) | global@5 | **pays@1** (banque scopée au pays) |
|---:|---:|---:|---:|
| 0 | 17,6 % | 63,7 % | **90,2 %** |
| 1 | 20,6 % | 66,7 % | 94,1 % |
| 5 | 21,6 % | 66,7 % | **97,1 %** |
| 8 | 25,5 % | 75,5 % | 97,1 % |
| 10 | 29,4 % | 84,3 % | 97,1 % |

Lecture : sans le pays, le top-1 est un tirage au sort entre 13–19 jumeaux
(17–29 %) et aucun N ne le répare. **Avec le pays connu** (`pays@1` =
`top_k_match_country`, banque restreinte au pays de vérité), on est à 90 %
sans exemplaire et **97 % dès N=5, plat ensuite**. Donc pour ces classes la
cible pratique est **5**, et le pays doit être résolu **avant** DINO. À
remesurer quand la population held-out dépassera 15 classes.

*Écarte* : fusionner les 18 classes en une (l'app doit rendre le pays), et
leur donner 8 exemplaires **par pays** sans mesure.

## D5 · Le reprocess des `zero_crops` passe devant O6

Mesuré le 2026-08-21 : 2 950 annonces sur 7 662 sans aucun crop, 70 % de
pièces seules plein cadre dans l'échantillon, remède (`score_recover`) livré
et jamais actif en prod, 76 % de récupération à la sonde, zéro quota. C'est
le premier geste. Périmètre initial : les 808 annonces visant des classes
déficitaires (cohérent avec D2/D3). Spec : [`outils/O7`](outils/O7-reprocess-zero-crops.md).

*Écarte* : « instrumenter d'abord » (c'est fait) et « O6 d'abord » (O6 reste
le geste n°2, avec son préalable `min_exemplars`).

## D6 · Écrans admin : pas de proto, mais une phase de design AVANT le code

O2 (la vue besoin) et O4 (les filtres de pêche) sont des écrans admin dans
`studio-local` : la règle R1 (proto-first) ne s'applique pas, comme pour
`peer-arbitration`. En revanche on **conçoit avant d'intégrer** : exploration
du flow et des états (vide, parqué, désarmé, plein) avec la skill
`frontend-design`, maquettes jetables, validation du parcours — puis
l'implémentation lourde une seule fois.

*Écarte* : coder O2 directement depuis la spec et découvrir au branchement
que le parcours ne convient pas.

## Ordre qui en découle

```
0. O7  reprocess zero_crops (808 annonces déficitaires → puis le reste, parqué)
1. O6  amorce médoïde — après avoir posé min_exemplars=2 en base (dino_thresholds est vide)
2. O1 + O5  calcul (class_need, class_family) — sans écran
3. design O2 + O4 (D6), puis implémentation
4. O3  entonnoir à huit plaques, au grain annonce
5. scrape réel, piloté par O2
```

## Ce qui reste ouvert

- VISION §8 Q3 : le tri sur titre avant téléchargement — à chiffrer.
- VISION §8 Q4 : `quality_score` manquant sur 54 % des crops.
- Le résidu Q13 (99 crops du gold dont le `class_id` ne se replie pas sur le
  représentant) — diagnostic posé en VISION §V4, cause non trouvée.
- Le mécanisme concret de « parqué » (D3) — sort de la phase design.
