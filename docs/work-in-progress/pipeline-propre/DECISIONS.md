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

## D7 · Deux paliers : couvrir d'abord, approfondir ensuite

Arbitrée le **2026-08-22** en session design, après l'A/B médoïde du JOURNAL.

Sous l'ancienne amorce `fps` la courbe montait tout du long (76,2 → 84,3) —
c'est de là que venait « 8 ». Sous l'amorce **médoïde**, elle change de forme :

| N | bras `fps` (témoin) | bras médoïde |
|---:|---:|---:|
| 0 | 76,2 % | 76,0 % |
| 1 | 71,8 % | **86,8 %** |
| 10 | 84,3 % | 88,0 % |

**Le premier exemplaire vaut +10,8 points, les neuf suivants +1,2 à eux tous.**
La Station 0 affiche donc **deux barres**, pas une :

| palier | définition | état au 23/08 (banque `a55e6594`) |
|---|---|---|
| **1 · couverture** | `have ≥ 1` | **250 / 671** — **92** à portée, 329 à scraper |
| **2 · profondeur** | `have ≥ target` (D1/D4) | Σ `need` **4 066** — **557** à portée |

⚠️ **Les chiffres « 147 à portée » et « 908 à portée » du 22/08 sont PÉRIMÉS**,
et l'écart n'est pas une régression : depuis le lot 6, `pending_scoped` applique
les filtres O4 (ère, pays). Les classes disparues n'avaient que des candidats
**contredits par le titre de l'annonce** — 49 d'entre elles ne pesaient que 100
crops au total. Le compte d'avant surévaluait le travail atteignable de 27 %.

Le tri par défaut sert le palier 1.

⚠️ **Réserve non levée.** Le `N` de `bench_refs_curve` est **plafonné par ce que
chaque classe possède** : à N=1, seules les 250 classes déjà pourvues bougent.
Une courbe « exactement 1 exemplaire partout » est nécessaire pour confirmer —
demandée à la session ML, cf. `design/QUESTIONS-OUVERTES.md` Q1.

*Écarte* : trier par distance à 8, ce qui ferait passer 90 classes bien nourries
devant 421 classes aveugles. **Ne contredit pas D1** — la cible 8 reste la
cible, elle devient explicitement le second palier.

## D8 · `accepted_pending` — ce qui est acquis mais pas encore bâti

Arbitrée le **2026-08-22**.

Accepter un crop écrit `training_eligible = 1`. Ça n'ajoute **aucun exemplaire à
la banque** : `have` ne bouge qu'au `build_dino_anchors` suivant — c'est l'arête
que FLOW-ADMIN §3 signale comme n'existant « sous aucune forme ». Conséquence :
pendant une session, `have` et `bottleneck` sont figés, et **la file ressert une
classe qu'on vient de remplir**. D9 seule ne suffit donc pas.

`ClassNeed` gagne un champ, et `bottleneck_for` compare `have +
accepted_pending` à `target` :

```python
accepted_pending: int   # training_eligible=1, storage_status='present',
                        # face != 'reverse', asset_id absent de la banque
```

Mesuré le 2026-08-22 : **1 451 crops acceptés hors banque** → un rebuild
poserait **76 exemplaires**, rendrait 8 classes pleines, sortirait 10 classes de
zéro (couverture 250 → 260). Le rapport 1 451 → 76 est la mesure directe de la
sur-review ; cas extrême, `at-2002-2eur-standard-1st-map` porte **138 acquis**
pour un plafond de 10.

La Station 0 **affiche** ce qu'un rebuild poserait et **propose** le geste ; elle
ne le déclenche jamais seule (un rebuild déplace les prédictions de toute la
file, donc les verdicts, en pleine session).

*Écarte* : n'afficher que `have` (l'écran ment sur le travail en cours) et le
rebuild automatique (les verdicts bougeraient sous la main de l'opérateur).

## D9 · `need_only` devient le régime par défaut

Arbitrée le **2026-08-22**, sur exigence explicite du PO.

`need_only` existe de bout en bout depuis le 2026-08-21
(`need_filter_clause`, `repository.py:123`) mais il est **opt-in** (`?need=1`),
et **la pêche ne le passe pas du tout** (`PechePage.vue` ne l'émet nulle part).

Le défaut se renverse : **la file sert le besoin**, et on lève le filtre
explicitement (`?need=0`). Mesuré le 2026-08-22 : **4 804 des 6 574 crops
ouverts (73 %)** tombent dans une classe à sa cible.

Corollaire pour D3 : **le mécanisme de « parqué » ne reste pas à concevoir, il
est déjà là.** `RunParked` (`models.py:200`) compte le complément en deux causes
(`full_class`, `no_prediction`), sans `lane`, sans statut, **sans aucune
écriture**, réversible en levant le filtre. Il manque seulement le même compte
**global et par classe** — il n'existe aujourd'hui que par run.

## D10 · O4c est un prérequis d'O2, pas son voisin

Arbitrée le **2026-08-22**. Corrige l'ordre ci-dessous.

En appliquant le filtre pays — *actif par défaut aujourd'hui* — au pool de
chaque classe :

```
classes 'review'                                  293
  que le filtre pays viderait ENTIÈREMENT         147  (50 %)
  crops rendus inatteignables                     558
  LU 14 · PT 13 · GR 12 · VA 12 · MC 10 · FI 9 · LT 9 · SM 9 · LV 8 · MT 8

palier 1 : sur les 147 classes à zéro AVEC candidats,
           120 seraient vidées par le filtre pays        (82 %)
```

VISION §V3 mesurait 137/338 (41 %) ; c'est désormais **50 % des classes en
besoin et 82 % du palier 1**. **Sans le désarmement automatique d'O4c, le palier
1 fait 27 classes au lieu de 147**, et la Station 0 affiche un écran faux le jour
de son branchement.

Donc : **O4c se livre AVANT O2**, et la Station 0 compte `pending_scoped`
(filtres appliqués), jamais `pending` brut.

*Écarte* : livrer O2 sur le pool brut « en attendant » — la page annoncerait 13
candidats au-dessus d'une file qui en sert 0.

## Ordre qui en découle

```
0. ✅ O7  reprocess zero_crops (811 annonces rejouées, 669 récupérées)
1. ✅ O6  amorce médoïde — banque a55e6594, +3,7 pts à N=10
2. ✅ O1 + O5  calcul (class_need, class_family) — sans écran
3. ✅ design O2 + O4 (D6) — 2026-08-22, cf. `design/`
4. ✅ O4c  désarmement du filtre pays (D10)
5. ✅ implémentation O2 + O4 — 7 lots, cf. `design/PLAN-IMPLEM.md`
      ⛔ lots 5-6 + correctifs de revue : commités, PAS déployés
6.    O3   entonnoir à huit plaques, au grain annonce — débloqué, jamais commencé
7.    scrape réel, piloté par O2 — 323 classes jamais visées, ~1 800 annonces

👉 **Reprise : [`REPRENDRE-ICI.md`](REPRENDRE-ICI.md)**
```

## Ce qui reste ouvert

- VISION §8 Q3 : le tri sur titre avant téléchargement — à chiffrer.
- VISION §8 Q4 : `quality_score` manquant sur 54 % des crops.
- Le résidu Q13 (99 crops du gold dont le `class_id` ne se replie pas sur le
  représentant) — diagnostic posé en VISION §V4, cause non trouvée.
- ~~Le mécanisme concret de « parqué » (D3)~~ — **clos le 2026-08-22** : c'est
  `need_filter_clause` + `RunParked`, rien à construire (cf. D9).
- La courbe « exactement 1 exemplaire partout », qui confirme ou infirme D7
  (`design/QUESTIONS-OUVERTES.md` Q1).
