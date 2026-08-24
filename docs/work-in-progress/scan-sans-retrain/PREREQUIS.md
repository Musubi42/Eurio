# Prérequis avant le bench — ce qu'il faut avoir en main

## 🧭 Note d'état — clôture de la session du 2026-08-20

> **À lire en premier si tu reprends froid.** Ce bloc dit où on en est, ce qui
> attend un geste humain, et dans quel ORDRE. Le détail est plus bas ; les
> preuves sont dans [`FINDINGS.md`](FINDINGS.md). Tout ce qui suit est mesuré
> sur `ml/state/eurio.replica.db` (réplique du canonique) — **jamais** sur
> `ml/state/eurio.db`, qui est périmée (6205 assets contre 12454).

### L'état, en cinq lignes

| Quoi | Où on en est | La requête qui le dit |
|---|---|---|
| **Banque `2eur_all`** | **1495 ancres** · 671 classes · **124 classes à exemplaires** · build `365dcab2a253` du `2026-08-20T14:27:56+00:00`, bâtie **avec** le plancher `min_exemplars=2` (68 classes ramenées au canonique seul). ⚠️ **Le plancher a depuis été retiré du code** — la banque servie le porte, le builder ne l'applique plus | `SELECT COUNT(*), COUNT(DISTINCT class_id), COUNT(DISTINCT CASE WHEN method='fps' THEN class_id END) FROM dino_class_references WHERE anchors_kind='2eur_all'` → `1495 \| 671 \| 124` (2026-08-20 17:13 UTC) |
| **Prédictions (P3)** | **12 454**, 0 erreur, poussées au canonique, calculées contre la banque ci-dessus | `calibration_blockers(conn, anchors_kind='2eur_all', encoder_version='dinov2-vitl14')` → `[]`. Critère de complétude : **0 périmée** |
| **Tests** | **1929 passed** (mesuré en clôture, `pytest tests -q` et `-p no:randomly` rendent le même compte ; 1883 était la référence d'avant les lots du soir) | `cd ml && ./.venv/bin/python -m pytest tests -q -p no:randomly` |
| **Migrations** | ✅ **toutes appliquées** — le canonique est à `0013` (mesuré le 2026-08-25). `0009`, `0010`, `0011` l'ont été le 2026-08-21, `0012` et `0013` avec la review collaborative | `docker exec eurio-api python -c "import sqlite3;print(sqlite3.connect('/var/lib/eurio/eurio.db').execute('SELECT * FROM _schema_migrations ORDER BY 1 DESC LIMIT 1').fetchone())"` → `0013_dino_prediction_perimee_par_recadrage.sql` |
| **Quota eBay** | **intact** — aucun appel émis par les sessions des 19 et 20 août | `sqlite3 -readonly ml/state/eurio.local.db "select period, calls from api_call_log where source='ebay' order by period desc limit 1"` → `2026-08-16\|740` |

### 🔴 Le résultat qu'il ne faut pas rater : le plancher a DÉGRADÉ, puis il a été RETIRÉ

Le re-bench held-out après application du plancher, à N=10 (c'est-à-dire la
banque réellement servie) :

| held-out, N=10 | avant plancher (1533 ancres) | après (1495) | delta |
|---|---:|---:|---:|
| `dinov2_vits14` | 75,5 % | **74,1 %** | **−1,4** |
| `dinov2_vitl14` | 85,7 % | **84,8 %** | **−0,9** |

Le contrôle qui autorise la comparaison : **à N=0 les deux banques sont
identiques** (671 canoniques, aucun exemplaire) et rendent le même score à
0,1 pt près — 53,1 → 53,2 % (`vits14`), 76,1 → 76,2 % (`vitl14`). Les
populations sont donc comparables, malgré le passage de 1100 à 1179 crops
held-out.

**La faute de raisonnement qui a produit le plancher** : la courbe mesure N=1 à
50,1 % contre N=0 à 53,1 %, mais ce point signifie *« toutes les classes
plafonnées à 1 »*, **pas** *« 68 classes en ont 1 et les autres sont pleines »*.
On a extrapolé d'un **agrégat** à une **règle par classe**. Consigné au journal
des croyances de [`VISION.md`](../../model-efficiency/VISION.md).

**Réserves à garder avec ce delta** — la banque n'a pas changé que par le
plancher : le FPS a rejoué sur un pool qui avait bougé (10 classes ont gagné
des exemplaires), les crops fuités sont passés de 858 à 779, et 1495 ancres
offrent mécaniquement moins de matière que 1533. Curiosité **non expliquée** :
à N=2 la nouvelle banque est **meilleure** (55,9 % contre 54,6 % en `vits14`)
avec moins de lignes ; elle ne perd qu'à N=8 et N=10. Ce delta **seul** n'aurait
donc pas suffi à conclure — et c'est bien la mesure par classe, ci-dessous, qui
a tranché.

### ✅ Ce qui a tranché : la mesure PAR CLASSE — le plancher est retiré

Le geste demandé par le paragraphe précédent a été fait le soir même, sans
rebuild, en restreignant la courbe. Trois mesures appariées (McNemar exact) :

1. **La population visée est inévaluable.** Les classes sans exemplaire mais à
   pool éligible non vide totalisent **77 crops** dans le gold, dont **61 sont
   exactement le crop qui deviendrait leur ancre** : il reste **16 crops
   held-out pour ~70 classes**. Aucun verdict n'est possible sur elles.
2. **Un exemplaire unique AIDE sa classe.** Sur le proxy le plus proche — les 57
   classes riches plafonnées à 1, le reste de la banque intact — `vitl14` passe
   de **67,6 à 69,1 %** (p=0,048) et `vits14` de **41,6 à 45,5 %** (p=4,5e-10)
   sur leurs propres crops. La prémisse du plancher est fausse **dans le sens
   où elle était affirmée**.
3. **Le creux agrégé vient de l'ORDRE du FPS, pas du nombre.** Il n'est pas
   significatif en `vits14` (53,2 → 52,1 %, **p=0,279**) ; il l'est en `vitl14`
   (76,2 → 73,8 %, p=0,0056), mais à **nombre d'ancres identique** (795 lignes),
   garder le rang le *moins* diversifiant rend **77,8 %** au lieu de 73,8 %. Le
   creux disparaît.

```bash
cd ml && EURIO_DB_PATH=$PWD/state/eurio.replica.db ./.venv/bin/python \
  -m scripts.bench_refs_curve --model dinov2_vitl14 --refs 0 1 2 \
  --bank-classes @rich57.txt --gold-classes @rich57.txt
cd ml && EURIO_DB_PATH=$PWD/state/eurio.replica.db ./.venv/bin/python \
  -m scripts.bench_refs_curve --model dinov2_vitl14 --refs 0 1 2 3 --rank-order last
```

**Décision** : `min_exemplars` revient à **1** (plancher inactif) pour les deux
couples dans `ml/shared/dino_threshold_defaults.py`. Le mécanisme reste entier
et couvert par 14 tests ; **reposer 2 se fait en une ligne dans
`dino_thresholds`**, sans toucher au code.

⚠️ **La conséquence qu'il faut avoir en tête avant tout rebuild.** La banque
**servie** porte encore le plancher ; le code ne l'applique plus. **Le prochain
rebuild changera la forme de la banque** — les 68 classes ramenées au canonique
seul retrouveront leur exemplaire, la colonne « 1 » de la distribution se
remplira — et **le garde P1 ne le dira pas** : il compte les classes à ≥ 2
exemplaires, un compte que ce retour laisse invariant. Le découplage est voulu
(cf. `ml/store/encoder_bench.py`), l'inversion sera donc **silencieuse**.

⚠️ **Ce qui n'est PAS prouvé pour autant.** La mesure décisive porte sur un
**proxy** (classes riches plafonnées à 1), pas sur les 68 classes visées —
celles-ci n'ont que 16 crops held-out. L'argument que le proxy est
*conservateur* est un raisonnement sur le code du FPS, pas une mesure. Et le
levier réel — amorcer le FPS au médoïde plutôt qu'au point le plus lointain —
**n'est pas implémenté** : `--rank-order last` est une sonde, pas un builder.
La configuration livrée est donc celle dont le tort est le mieux étayé, sans son
correctif de mécanisme.

### Ce qui attend le PO — les deux vrais chantiers d'abord

Les deux premières lignes sont des chantiers de **jours ou de semaines** ; les
suivantes sont du court terme qui ne les bloque pas.

| # | Geste | Pourquoi | Coût |
|---|---|---|---|
| **1** | **Le scrape.** `go-task ml:ebay:allocate` (dry-run) puis `-- --execute --yes --max-groups 2` | **331 des 547 classes au canonique seul n'ont AUCUN crop en file ouverte** (mesuré 2026-08-20 17:14 UTC, cf. §P1). Pour elles le goulot n'est pas la review, c'est qu'on n'a jamais interrogé eBay. Balayer le déficit = **~47 800 appels, ~10 jours de quota** ([`ALLOCATEUR-SCRAPE.md`](ALLOCATEUR-SCRAPE.md)) | argent réel · ~10 j |
| **2** | **Les photos — MinIO d'abord, capture ensuite.** | Il n'y a **0 capture versionnée** mais **2 264 images device** sur ce Mac (114 dans `ml/datasets/eval_real_norm`, 2 150 dans `debug_pull`), **aucune sur MinIO, aucune dans la chaîne de sauvegarde** : un `git clean -xdf` les détruit. Les protéger coûte une tâche de publication ; en produire 985 de plus avant de les protéger, c'est parier le travail. Détail et remède : [`../scan-quality/DURABILITE-CORPUS.md`](../scan-quality/DURABILITE-CORPUS.md), puis [`PROTOCOLE-CAPTURE.md`](PROTOCOLE-CAPTURE.md) | jours · puis semaines |
| 3 | **Redémarrer `eurio-api` sur le VPS** (`git pull` + `docker compose up -d --build` dans `infra/eurio-api`) | C'est le redémarrage qui applique **0009, 0010, 0011**. Sans 0010, le premier build d'un encodeur *candidat* écrase les références de production (M1) ; sans 0011, `min_exemplars` n'est pas posable en base ; sans 0009, un run de banc n'a nulle part où se tracer. 🔍 **Contradiction non expliquée** : le build du 20 août 14:27 **a pourtant tracé** ses 1495 lignes au canonique alors que le garde `_exige_encodeur_dans_la_cle` lève toujours sur la réplique et que `_schema_migrations` y dit `0008` — lire le schéma du canonique lui-même avant de conclure | minutes · [`eurio-vps-deploy`](../../../.claude/skills/eurio-vps-deploy/SKILL.md) |
| 4 | **Pousser les 4 payloads de banc en attente** (`state/encoder_bench_pending/`, run `20260820T011143Z`) | Ils n'ont jamais pu être tracés : la table `encoder_bench_runs` n'existe pas au canonique. Faisable **seulement après (3)**. ⚠️ Ils notent la banque **d'avant le plancher** — les republier tels quels sans le dire ferait croire à un état courant | minutes |
| 5 | **Amorcer le FPS autrement (médoïde), et re-mesurer.** | La question « le plancher, on le garde ? » est **tranchée** (retiré, cf. ci-dessus). Ce qui reste est le vrai levier : `--rank-order last` prouve que le rang 1 du FPS est un faux attracteur (**77,8 %** contre 73,8 % en `vitl14`, à nombre d'ancres identique). Changer l'amorce de `farthest_point_select` demande un rebuild + P3 pour être mesuré | ½ journée + 237 s + ~41 min |

### Ce qui reste ouvert et ne bloque rien de ce qui précède

**Q6** (aucun lecteur de `dino_class_references` n'est scopé par encodeur — à
fermer **avant** le premier build de banque d'un encodeur *candidat*, pas avant
un rebuild de production) ; **S6** (la courbe ne simule pas ce que le builder
produit : `bench_refs_curve.py` ignore `min_exemplars` — moins grave depuis que
le plancher est inactif, mais la leçon de méthode reste : un palier N est
« toutes les classes à N », jamais « ces classes-ci à N ». Cf.
[`COURBE-REFERENCES.md`](COURBE-REFERENCES.md)) ; **S3** (le préflight quota est
aveugle — la seule ligne 🔴 qui puisse coûter de l'argent) ; et les autres lignes
🔴 du registre [`FINDINGS.md`](FINDINGS.md) §8.

**Deux chantiers ont été posés par écrit et attendent une session dédiée** — ils
ne sont dans aucun backlog, ce lien est leur seule porte d'entrée :

- [`../review-autovalidation/PROBLEME.md`](../review-autovalidation/PROBLEME.md)
  — *« 90 % des reviews demandent un geste humain sur le crop »* : on a passé
  deux jours à améliorer l'**attribution de classe** alors que le temps humain
  part probablement dans le **recadrage**. Rien n'est implémenté.
- [`../scan-quality/DURABILITE-CORPUS.md`](../scan-quality/DURABILITE-CORPUS.md)
  — les 2 264 images device et leur absence de réplique (chantier 2 ci-dessus).

**État de la machine à la clôture** : rien de commité (c'est le PO qui commite),
aucun appel eBay, aucune migration appliquée à une base réelle, aucun droit de
fichier modifié. La banque **a** été rebâtie et les prédictions **ont** été
poussées au canonique — ce sont les deux seules écritures de la session.

---


> Écrit le 2026-08-19, après le travail « banque unique et traçable ». Liste
> ce qui doit être vrai **avant** de comparer des encodeurs, sinon le banc
> mesurera une banque amputée et le chiffre ne vaudra rien.
>
> **Mis à jour le 2026-08-20 (soir, après le rebuild avec plancher)** — **P1, P2
> et P3 sont 🟢.** La banque a été rebâtie **deux fois** : le 19 à 16:36 (1533
> ancres, 182 classes à exemplaires, build `23c637d93b43`), puis le 20 à 14:27
> **avec le plancher `min_exemplars=2`** — c'est celle qui est servie
> aujourd'hui : **1495 ancres, 671 classes, 124 classes à exemplaires**, build
> `365dcab2a253`, 68 classes ramenées au canonique seul. ⚠️ **Le plancher a été
> retiré du code le soir même** (défaut revenu à 1) : la banque servie le porte,
> un rebuild ne le porterait plus. Les 7 avers manquants
> sont rapatriés, et **P3 a abouti** sur la banque courante : 12 454 prédictions
> recalculées, 0 erreur, **0 périmée**, poussées au canonique. P4/P6/P7 étaient
> déjà traités. **Il ne reste que P5** — et sa formulation a changé : ce n'est
> pas « 0 photo » mais **0 capture versionnée pour 2 264 images device non
> protégées**. Les mesures et les preuves : [`FINDINGS.md`](FINDINGS.md).
>
> 🔴 **Et le plancher a DÉGRADÉ le held-out de ~1 pt** — voir la note d'état en
> tête de ce document. Les chiffres « 1533 / 182 » qu'on croise plus bas dans ce
> doc décrivent la banque du 19 août : ils sont **historiques**, pas courants.
>
> 🔴 **Et une correction qui invalide un chiffre de ce doc** : la requête de
> complétude P3 écrite plus bas (`computed_at < built_at`) compare deux formats
> de date **en chaînes** et rend **12454** même sur une réplique fraîche. La
> bonne (`datetime()` des deux côtés) rend **0**. Le §P3 porte le détail ; ne pas
> conclure « P3 non abouti » sur l'ancienne requête.
>
> Décision-cadre : [`DECISION.md`](DECISION.md). Mesures du chantier frère :
> [`../banque-dino/CONSTAT.md`](../banque-dino/CONSTAT.md).
>
> Base lue : `ml/state/eurio.replica.db` (réplique du canonique), sauf mention.
> Chaque chiffre porte sa requête.

## Le tableau de bord

| # | Prérequis | État au 2026-08-20 (réplique du 03:22) | Qui | Reste |
|---|---|---|---|---|
| P1 | La banque voit tout le travail de review déjà fait | 🟢 **fait** — rebuild du 2026-08-19 16:36 (1533 ancres, 182 classes à exemplaires, contre 125 avant), **puis rebuild du 2026-08-20 14:27 avec le plancher** : `SELECT COUNT(*), COUNT(DISTINCT class_id), COUNT(DISTINCT CASE WHEN method='fps' THEN class_id END) FROM dino_class_references WHERE anchors_kind='2eur_all'` → `1495 \| 671 \| 124` (17:13 UTC). Le plancher a ramené **68 classes** au canonique seul → **547 classes sur 671 (82 %)** sont désormais au canonique Numista seul, dont **331 sans aucun crop en file ouverte** (17:14 UTC) | — | — |
| P2 | Les 7 classes aveugles ont un avers | 🟢 **fait** — 7/7 rapatriés, `n_no_canonical` 7 → 0 | — | — |
| P3 | Les prédictions sont calculées contre la banque servie | 🟢 **refait le 2026-08-20 après le rebuild à plancher** — 12 454 prédictions, 0 erreur, **0 périmée**, poussées au canonique (14:28:14 → 15:09:34 UTC). Preuve : `calibration_blockers(anchors_kind='2eur_all', encoder_version='dinov2-vitl14')` → **`[]`**. Le critère de complétude est **0 périmée**, pas le code de sortie du backfill (M8) | — | — |
| P4 | Un gold review figé et versionné | 🟢 **fait** — 1958 crops, `gold_version=0ecbb1d70e3c`, **0 crop non encodé** au run du banc | — | — |
| P5 | Un corpus de scan rempli | 🟠 **plan livré**, **0 capture versionnée** — mais **2 264 images device existent** et ne sont **pas protégées** (cf. §P5 et [`../scan-quality/DURABILITE-CORPUS.md`](../scan-quality/DURABILITE-CORPUS.md)). **Le seul prérequis restant**, et le seul juge de la voie B (D4) | **humain (toi)** | MinIO d'abord (jours), capture ensuite (semaines) |
| P6 | Le banc sait porter deux encodeurs sans les écraser | 🟠 **côté écriture, oui** — scoping du `.npz`, stats, store, routes, banc câblé (D4/D5), et depuis le 2026-08-20 l'encodeur est dans la **clé primaire** de `dino_class_references` (migration 0010, M1 fermé). **Côté lecture, non** : aucun lecteur de cette table n'est scopé par encodeur (**Q6**, [`FINDINGS.md`](FINDINGS.md) §8.10) | machine | fermer **Q6** avant le premier build de banque d'un candidat · appliquer 0010 au canonique (redémarrage `eurio-api`) · un run RÉEL sur GPU |
| P7 | Les poids DINOv3 et leur licence | 🟢 **fait** — lue, poids téléchargés, latences mesurées | — | avis juridique avant Play Store |

Rien ci-dessous n'est bloqué par autre chose que ce qui le précède, **sauf P3
qui doit venir après P1 et P2** — sinon on recalcule 12 454 prédictions contre
une banque qu'on va rebâtir juste après. ~~P1 et P2 sont faits : la condition est
levée, P3 est le geste suivant.~~ **Les trois sont faits ; l'ordre a été
respecté.**

> ✅ **Le premier bench réel a tourné le 2026-08-20** (run `20260820T011143Z`,
> gold `0ecbb1d70e3c`, 1958 crops, 0 non encodé). Résultat et **trois réserves** :
> [`BENCH-ENCODEURS.md`](BENCH-ENCODEURS.md). Conclusion : **DINOv3 réfuté sur
> notre tâche** (−7,2 pts à taille égale), `dinov2_vitl14` garde la review,
> `dinov2_vits14` devient le candidat léger. Ces prérequis ont donc **servi** —
> et sans P1, le banc aurait mesuré une banque amputée de 57 classes.

> ⚠️ **La dette du lot P4/P6 a été traitée en trois passes, elle n'est pas
> soldée — et elle a grossi.** Le registre daté est
> [`FINDINGS.md`](FINDINGS.md) §8. Au **2026-08-20 (soir, après vérification de
> la QUATRIÈME passe — plancher, allocateur, skill)**, sur **62 lignes** :
> **22 ✅ · 3 ⚠️ · 6 ⏭ · 1 🔍 · 30 🔴** (§8.12 ajoute S1..S12, dont cinq fermées
> dans la même passe). Compte précédent, après la troisième passe, sur **45
> lignes** : **17 ✅ · 3 ⚠️ · 3 ⏭ · 1 🔍 · 21 🔴**. (La passe de correction revendiquait 33 lignes à 18 ✅ · 9 🔴 ; ses
> deux vérifications ont fait passer **M2** de ✅ à ⚠️ et ajouté **12 lignes**,
> toutes 🔴.)
>
> **Fermé et vérifié le 2026-08-20 : M1.** L'encodeur est entré dans la **clé
> primaire** de `dino_class_references` (migration **0010**), le writer refuse
> une table à l'ancienne clé, et la migration a été rejouée par le vrai runner
> sur copie `/tmp` de la réplique : **1250 → 1250 lignes, contenu
> byte-identique**, puis à 1536 lignes construites, NULL compris.
>
> **Requalifié ⚠️ : M2.** L'invariant est bien dans la porte d'écriture
> (`record_run`) et il tient — mais le **prédicat** qu'il évalue laisse passer
> quatre payloads mensongers (gold menti à 3 crops, baseline inexistante, run
> baseline de lui-même, re-push qui promeut une ligne démotée), et le test
> d'inventaire censé voir le chemin de demain est aveugle à un nom de table
> interpolé. Détail : [`FINDINGS.md`](FINDINGS.md) §8.10, Q1..Q5.
>
> 🔴 **Le défaut à connaître avant tout autre geste de ce chantier : Q6.** Le
> correctif M1 rend la coexistence de deux encodeurs **possible** — c'était son
> but — mais **aucun lecteur** de `dino_class_references` ne nomme
> `encoder_version`. Mesuré sur données réelles : `get_class_references` rend
> **22 lignes au lieu de 11** avec **deux canoniques** pour une classe ; le
> badge de review affiche la banque du **candidat** à la place de celle servie ;
> et le vrai CLI du plan de capture P5 déplace deux classes possédées de
> `moyenne` vers `riche` (22→24 / 21→19, et 9 classes sur les 664). **Latent
> aujourd'hui, armé au premier build de banque d'un encodeur candidat.**
>
> **Les deux verrous du premier run réel du banc sont levés** : **D1** (volet
> P1 : `_p1_blockers` filtre maintenant `encoder_version`) et **N1** (les crops
> non encodés sont comptés, imprimés et retirés de la couverture du gold) sont
> corrigés **et vérifiés par un tiers**, avec mutation rouge/vert. D5, D8, D16,
> N2 et N6 le sont aussi.
>
> **La seconde vérification avait rendu 11 défauts neufs**
> ([§8.8](FINDINGS.md)), dont **M1** et **M2** — tous deux traités ci-dessus.
>
> **Et la même maladie est revenue une septième fois.** Cinq instances en deux
> jours étaient déjà consignées (D1/P3, D1/P1, M1, M2) ; la vérification du soir
> en ajoute trois faces inédites — le **prédicat** qui dit faux alors que le
> garde est appelé (Q1..Q4), le **détecteur** aveugle à la forme du chemin
> suivant (Q5), et les **lecteurs** rendus faux par le correctif qui protège les
> écrivains (Q6, Q8). La note de motif, écrite pour quelqu'un qui n'était pas
> là : [`FINDINGS.md`](FINDINGS.md) **§8.9**.
>
> Sur le chemin de P3 précisément : **M8** (le backfill sort en code 0 même
> avec des erreurs) et **M7** (face/denom recalculés puis jetés). Ni l'un ni
> l'autre n'empêche de lancer — [`GESTE-P3.md`](GESTE-P3.md) dit quoi regarder.

---

## P1 · La banque ne voyait pas 57 classes de travail déjà validé — 🟢 fait le 2026-08-19

> **Rebuild effectué le 2026-08-19 à 16:36**, après correction du `--db` codé en
> dur. Build `23c637d93b43` poussé au canonique, **237 s**.
>
> 🔴 **Ce n'est plus la banque servie.** Un **second** rebuild a eu lieu le
> **2026-08-20 à 14:27** (build `365dcab2a253`), cette fois avec le plancher
> `min_exemplars=2` : **1495 ancres, 671 classes, 124 classes à exemplaires**,
> note du build = `min_exemplars=2 (source=code); 68 classes ramenées au
> canonique seul; 0 sans canonique gardées sous le plancher`. Tous les chiffres
> de ce §P1 (**1533 / 862 / 182**) décrivent l'état du 19 août — ils restent
> justes comme **histoire du défaut**, ils ne décrivent plus la production.
> Et le plancher a **dégradé** le held-out de ~1 pt, puis il a été **retiré** :
> note d'état en tête.

| | avant | après | Δ |
|---|---:|---:|---:|
| classes | 664 | **671** | +7 (les canoniques rapatriés par P2) |
| lignes d'ancres | 1250 | **1533** | +283 |
| exemplaires réels (`fps`) | 586 | **862** | +276 |
| **classes avec exemplaires** | **125** | **182** | **+57** |
| classes en canonique seul | 539 | **489** | −50 |

**Critère de sortie : atteint.** L'objectif était ≥ 180 classes à exemplaires ;
la banque en porte **182** — c'est-à-dire exactement les 182 classes que la
sélection du builder rendait sur la réplique (voir « la cause » ci-dessous). Le
déficit de 57 classes est intégralement résorbé.

Mesuré **sur la banque servie elle-même**, pas sur un rapport :

```bash
cd ml && ./.venv/bin/python -c "
import numpy as np
d = np.load('state/foundation_anchors_2eur_all.npz', allow_pickle=True)
e, a = d['eurio_ids'], d['asset_ids']
canon = sum(1 for x in a if x == '')
cls_ex = set(e[i] for i in range(len(e)) if a[i] != '')
print('lignes', len(e), '| classes', len(set(e)), '| canonique', canon,
      '| exemplaires', len(e) - canon, '| classes avec exemplaires', len(cls_ex),
      '| canonique seul', len(set(e)) - len(cls_ex))"
# lignes 1533 | classes 671 | canonique 671 | exemplaires 862
# | classes avec exemplaires 182 | canonique seul 489
# meta : {"encoder_version": "dinov2-vitl14", "anchors_kind": "2eur_all",
#         "built_at": "2026-08-19T14:36:14+00:00", "count": 1533, "dim": 1024,
#         "bank_id": "a0fec2b0696743edbde6e5ab8137f822"}
```

⚠️ **La réplique locale affiche encore `1250 / 125` — c'est NORMAL, ne pas
« corriger ».** Direction A : la trace du build part au canonique par HTTP
(`POST /ingest/dino-references`), la base locale n'est pas écrite. Le canonique
porte bien le build `23c637d93b43` et ses 1533 lignes. Corollaire immédiat, et
attendu : `calibration_blockers` lu **sur la réplique** rend toujours
`P1: … ne couvre que 125 classes à exemplaires (attendu >= 180)`. Le garde
s'ouvrira quand la réplique aura rattrapé le canonique.

**Ce que ce rebuild déclenche : P3.** Les 12 454 prédictions sont désormais
antérieures au build courant, donc périmées — c'était le prix connu.

⚠️ **Ce qu'il ne faut PAS faire maintenant** : rebâtir la banque d'un encodeur
**candidat** (DINOv3). La raison a changé le 2026-08-20, l'interdit non.

- **Hier (M1)** : un tel build **écrasait** les 182 classes ci-dessus — la PK de
  `dino_class_references` ne portait pas `encoder_version`. Reproduit sur le DDL
  réel : `prod=200 cand=0` → `prod=0 cand=200`. **Corrigé** : l'encodeur est
  entré dans la clé primaire (migration **0010**), et le writer **refuse
  bruyamment** une table à l'ancienne clé au lieu d'écraser. Rejoué sur les 1250
  lignes réelles de la réplique : les deux banques coexistent, la production
  garde ses 664 canoniques et ses 586 `fps`.
- **Aujourd'hui (Q6, [`FINDINGS.md`](FINDINGS.md) §8.10)** : plus rien n'est
  détruit, mais **tout ce qui LIT la table devient faux**. Aucun lecteur ne
  nomme `encoder_version` — ils n'avaient jamais eu à le faire, la coexistence
  étant impossible. Mesuré : la route admin rend 22 lignes au lieu de 11 avec
  **deux canoniques** pour une classe, le badge de review affiche la banque du
  candidat, et le plan de capture P5 déplace 9 classes de strate. **Le geste
  reste interdit tant que Q6 n'est pas fermé** — et il faut aussi que 0010 soit
  appliquée au canonique (redémarrage `eurio-api`), sinon le writer refuse.

---

### L'état d'origine, pour mémoire

Ce qui suit décrit la banque **avant** le rebuild. Conservé parce que c'est la
reproduction du défaut, et qu'elle a coûté cher à obtenir.

La banque couvrait 664 classes. Mais sur ces 664, **539 n'avaient
que le canonique Numista** — zéro crop réel :

```sql
WITH per AS (SELECT class_id, SUM(method='fps') n
               FROM dino_class_references GROUP BY 1)
SELECT CASE WHEN n=0 THEN '0 (canonique seul)' WHEN n=1 THEN '1' WHEN n<=2 THEN '2'
            WHEN n<=4 THEN '3-4' WHEN n<=8 THEN '5-8' ELSE '9+' END bucket,
       COUNT(*) FROM per GROUP BY 1 ORDER BY MIN(n);
-- 0 (canonique seul)|539   1|41   2|19   3-4|16   5-8|9   9+|40
```

**81 % du catalogue était en régime canonical-only.** Et H4 a mesuré exactement
ce régime : vitl14 zero-shot y fait **62,8 %** top-1, contre **72,7 %** en
régime wild-rich (H1). Autrement dit, un bench lancé avant le rebuild aurait
mesuré surtout la pauvreté de la banque, pas la qualité des encodeurs.

Après le rebuild : **489 sur 671, soit 73 %**. Le régime canonical-only reste
donc largement dominant — le rebuild lève un défaut, il ne remplit pas le
catalogue. C'est P5 (la campagne de capture) qui porte ce sujet-là.

### Une partie est du travail déjà fait qui n'arrive pas

En rejouant la sélection du builder sur la base d'aujourd'hui, **sans encoder**
(pur SQL, `_class_specs_2eur_all` + `_candidate_crops_for_class`) :

```
specs=671  avec_canonique=664  sans=7
classes_avec_au_moins_1_candidat = 182   candidats_total = 1662
--- banque actuelle ---
classes_dans_refs=664  classes_avec_exemplaires=125
```

**182 classes avaient des candidats éligibles, la banque n'en servait que
125.** Il manquait **57 classes**, et 1 662 candidats disponibles contre 586
retenus. Le rebuild a rendu **exactement les 182** annoncées : la sélection SQL
prédisait le résultat, ce qui vaut confirmation de la cause.

Exemples, avec leur volume de crops validés qui n'atteint pas la banque :

| Classe | Crops validés éligibles | Exemplaires en banque |
|---|---:|---:|
| `cy-2026-…-cypriot-presidency…` | 22 | 0 |
| `de-2006-2eur-state-of-schleswig-holstein` | 22 | 0 |
| `cy-2012-2eur-10-years-of-euro-cash` | 16 | 0 |
| `de-2009-…-economic-and-monetary-union` | 14 | 0 |
| `de-2009-2eur-federal-state-of-saarland` | 11 | 0 |

Vérification sur un cas, avec la requête **exacte** du builder :

```sql
SELECT COUNT(*) FROM image_assets
 WHERE eurio_id='de-2006-2eur-state-of-schleswig-holstein'
   AND face='obverse' AND (denom IS NULL OR denom!='not_2eur')
   AND resolution_status IN ('manual','auto_name','auto_phash')
   AND training_eligible=1 AND storage_status='present';
-- 22
```

Et la classe est bien dans la banque — **avec sa seule ligne canonique** :

```sql
SELECT method, rank FROM dino_class_references
 WHERE class_id='de-2006-2eur-state-of-schleswig-holstein';
-- canonical|0
```

### La cause, trouvée le 2026-08-19 (soir)

**`ml/scripts/build_dino_anchors.py` codait son `--db` par défaut en dur sur
`ml/state/eurio.db` au lieu d'honorer `EURIO_DB_PATH`.** La banque servie a donc
été bâtie sur une base de travail périmée, pas sur la réplique.

```python
DB_PATH = ML_DIR / "state" / "eurio.db"                    # ← avant
DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.db")   # ← après (corrigé, non commité)
```

`ml/tasks.yml:91` lance la commande **sans `--db`** : le défaut fautif
s'appliquait donc à chaque build. `grep -rn resolve_db_path ml --include=*.py` →
70 fichiers l'utilisent ; ce builder était le seul à ne pas le faire.

L'écart entre les deux bases est massif :

```bash
for f in state/eurio.db state/eurio.replica.db; do
  sqlite3 "file:$f?mode=ro" \
    "select (select count(*) from image_assets),
            (select count(*) from image_assets where training_eligible=1),
            (select count(*) from review_queue
              where status='done' and decided_eurio_id is not null);"
done
# state/eurio.db          →  6205 | 1257 | 1264
# state/eurio.replica.db  → 12454 | 1948 | 1958
```

Les 22 crops de Schleswig-Holstein **n'existent pas du tout** comme lignes dans
`eurio.db` (0 sur 22). Ce n'est ni un filtre, ni un seuil, ni le FPS.

**Preuve que la cause est suffisante** — rejouer la sélection du builder sur
chaque base, sans encoder :

| Base lue | Classes avec ≥1 candidat | Candidats |
|---|---:|---:|
| `state/eurio.replica.db` | 182 | 1662 |
| `state/eurio.work-dino.db` | 182 | 1659 |
| **`state/eurio.db`** | **125** | **1100** |

Et les 125 classes obtenues sur `eurio.db` sont **strictement les mêmes** que
les 125 classes à exemplaires de la banque servie ; les 586 `asset_id` de la
banque sont tous inclus dans ses 1100 candidats. Ensembles vides des deux côtés
du diff. Dossier clos.

Détail et sortie brute : [`FINDINGS.md`](FINDINGS.md) §2.1.

### Ce que j'avais éliminé comme cause — et qui reste juste

La liste garde sa valeur : cinq de ces six pistes étaient **correctement**
écartées, et les revérifier coûterait une session.

- **Les fichiers ne seraient pas sur le disque** (le `except: continue` qui
  avale `local_path`) — non : testé, 5/5 présents sur les classes orphelines.
- **Le filtre `face='obverse'`** — non : il ne coûte que 5 classes sur 193
  (`188` vs `193` sans lui). Schleswig est `obverse` sur ses 22 crops.
- **Le filtre `denom != 'not_2eur'`** — non : 3 assets concernés en tout.
- **Des exclusions manuelles** — non : `dino_class_references` ne contient que
  `canonical` (664) et `fps` (586), aucun `manual_exclude`.
- **Les décisions seraient postérieures au build** — non : les 22 crops de
  Schleswig sont décidés le 2026-08-18 entre 16:00 et 21:37 UTC, le build date
  du 2026-08-19T00:28:21 UTC. Aucune décision n'est postérieure au build.
- 🔴 **« Le build aurait tourné sur une autre base » — C'ÉTAIT ÇA.** Cette
  piste avait été écartée sur un raisonnement **faux** : « la réplique porte à
  la fois les 22 crops éligibles *et* les 1 250 références ». Elle porte les
  références parce qu'elles y sont **poussées par HTTP**
  (`/ingest/dino-references`), ce qui ne dit **rien** de la base *lue* au
  moment du build.

> **Leçon transposable** : la présence d'un résultat dans une base ne prouve
> pas que le calcul y a lu ses entrées. Sous Direction A, calcul et écriture
> vivent à deux endroits différents — c'est le principe même du modèle.

### Le geste — exécuté le 2026-08-19 à 16:36

Le correctif du `--db` est écrit et testé
(`tests/test_build_dino_anchors_cli.py::test_db_path_defaut_honore_eurio_db_path`),
**non commité**. Le rebuild a été lancé dessus :

```bash
cd ml && .venv/bin/python -m scripts.build_dino_anchors --kind 2eur_all --force -v --push
```

**Résultat** : 671 classes / 1533 ancres / 862 exemplaires / **182 classes à
exemplaires**, build `23c637d93b43` poussé au canonique en **237 s**.

**L'estimation d'avant-rebuild était bonne sur les classes, généreuse sur le
volume.** Elle annonçait « ~182 classes, banque autour de 671 canoniques +
~1050 exemplaires ». Le réel : **182 classes** (exact) et **862 exemplaires**
(−18 %). L'écart vient du plancher `floor_sim = 0.45`, appliqué **après**
encodage — le seul terme qui n'était pas simulable, et il coupe environ un
candidat retenu sur cinq.

**Critère de sortie** : ✅ atteint. `COUNT(DISTINCT class_id) … WHERE
method='fps'` = **182** ≥ 180, et le `dino_anchor_builds` correspondant est
écrit au canonique.

⚠️ **Cette mesure n'est pas lisible sur la réplique locale** (elle rend encore
125) : la trace part au canonique par HTTP, cf. l'encadré en tête de §P1. Le
chiffre ci-dessus est mesuré sur le `.npz` servi, qui est l'artefact que la
review et le scan consomment réellement.

> ✅ P3 est débloqué, et **lancé le 2026-08-20** — résultat non encore établi,
> cf. §P3. Voir [`GESTE-P3.md`](GESTE-P3.md).

---

## P2 · Sept classes n'ont ni avers ni crop — 🟢 fait le 2026-08-19

> **Rapatriement effectué.** `n_no_canonical` est passé de **7 à 0** :
> `_class_specs_2eur_all(replica, DATASETS_DIR)` → `specs: 671, sans canonique: 0`.
> Les 7 classes n'entreront en banque qu'au **prochain build** (P1, non lancé).

`n_no_canonical = 7` au dernier build. Contrairement à ce qui était supposé,
**les sept ont un `numista_id`** — elles ne sont pas absentes du référentiel,
c'est leur image qui n'est pas sur le disque :

| Classe | numista_id | Candidats crops |
|---|---:|---:|
| `cy-2026-…-cypriot-presidency…` | 576180 | 22 |
| `cy-2023-…-60th-anniversary-foundation…` | 375327 | 1 |
| `ee-2020-2eur-centenary-of-the-tartu-peace-treaty` | 194605 | **0** |
| `ee-2026-2eur-sipsik` | 581307 | **0** |
| `fi-2026-2eur-100-years-yle-broadcasting` | 581165 | **0** |
| `hr-2026-…-croatian-radiotelevision` | 578765 | **0** |
| `ie-2026-2eur-irish-presidency-of-the-e-u-council` | 576181 | **0** |

**Cinq classes n'ont strictement rien** : ni avers canonique, ni crop validé.
Elles existent au catalogue et sont invisibles au modèle. Toute pièce scannée
parmi elles sera rattachée à autre chose, silencieusement.

**Le geste, exécuté.** Aucun mécanisme existant ne pouvait les rapatrier : les
7 sont absentes de `datasets/coin_catalog.json` (donc `import_numista
--retry-images`, qui rejoue des URLs cachées sans appel API, est un **no-op**)
**et** de `datasets/numista_review_queue.json` (11 items, intersection vide). Il
fallait un appel API par pièce.

Le bon outil est `referential/fetch_review_images.py` (KeyManager +
`get_type_details` + `download_image`) : il n'écrit **que** le filesystem, donc
il est sûr sous le flip Direction A. Un drapeau `--ids` lui a été ajouté plutôt
que de polluer la file de review.

```bash
cd ml && .venv/bin/python -m referential.fetch_review_images \
  --ids 375327,576180,194605,581307,581165,578765,576181
# Done: 7 downloaded, 0 failed
```

7 avers + 7 revers, images réelles (55 ko / 642 px pour la plus petite, 899 ko /
2540 px pour la plus grande). Coût réel : **7 appels** `get_type_details`.

**Critère de sortie** : ✅ `n_no_canonical = 0`.

⚠️ **Effet de bord à connaître** : `ml/datasets/coin_catalog.json` est modifié
dans l'arbre (+7 entrées) et 14 images sont sur le disque (dossier gitignoré).
Les chiffres « 664 classes / 7 sans canonique » ne sont plus reproductibles à
l'identique sur cette machine.

**Écarté** : traiter ça comme un cas particulier des 2026. Ce n'est pas une
question de millésime — `ee-2020` traîne depuis quatre ans.

---

## P3 · Les 12 454 prédictions étaient périmées — 🟢 fait le 2026-08-20

> **Mode d'emploi complet, avec les témoins et la conduite en cas d'arrêt :
> [`GESTE-P3.md`](GESTE-P3.md).** Ce §P3 dit *pourquoi* ; le mémo dit *comment*.

> ### ✅ Verdict au 2026-08-20, sur la réplique fraîche (pull de 03:22)
>
> **P3 a abouti — et a été REFAIT le 2026-08-20 après le rebuild à plancher.**
> État courant : **12 454 prédictions**, 0 erreur, **0 périmée**, poussées au
> canonique, calculées de `14:28:14` à `15:09:34` UTC contre le build
> `365dcab2a253` (`2026-08-20T14:27:56+00:00`) — postérieures de quelques
> secondes, ce qui est le bon ordre. Le critère de complétude est **0 périmée**,
> pas le code de sortie du backfill (M8 : il sort en 0 même en erreur).
>
> *Pour mémoire, la première exécution* : 12 454 prédictions en ~28 min contre le
> build `23c637d93b43`, de `23:20:42` à `23:48:36` le 19 août.
>
> La preuve à utiliser désormais — elle passe par le code du garde, pas par du
> SQL recopié :
>
> ```bash
> cd ml && ./.venv/bin/python -c "
> import sqlite3; from store.encoder_bench import calibration_blockers
> c = sqlite3.connect('file:state/eurio.replica.db?mode=ro', uri=True)
> print(calibration_blockers(c, anchors_kind='2eur_all', encoder_version='dinov2-vitl14'))"
> # → []
> ```
>
> ### 🔴 Le piège : la requête de complétude ci-dessous est FAUSSE
>
> Elle compare `p.computed_at < b.m` en **chaînes**, or les deux colonnes n'ont
> pas le même format d'écriture :
>
> ```
> image_asset_dino_predictions.computed_at → '2026-08-19 23:48:36'
> dino_anchor_builds.built_at              → '2026-08-19T14:36:14+00:00'
> ```
>
> L'espace vaut `0x20`, le `T` vaut `0x54` : **toute prédiction paraît antérieure
> à tout build du même jour**, quelle que soit l'heure. Mesuré sur la réplique
> fraîche :
>
> ```bash
> sqlite3 "file:ml/state/eurio.replica.db?mode=ro" "
> SELECT SUM(computed_at < '2026-08-19T14:36:14+00:00'),
>        SUM(datetime(computed_at) < datetime('2026-08-19T14:36:14+00:00'))
>   FROM image_asset_dino_predictions
>  WHERE anchors_kind='2eur_all' AND encoder_version='dinov2-vitl14';"
> # → 12454|0
> ```
>
> Le sens de l'erreur **sur-bloquait** — jamais de faux « promouvable » — mais
> rendait P3 **impossible à satisfaire**. `store/encoder_bench.py::_p3_blockers`
> est corrigé (`datetime()` des deux côtés, avec le commentaire qui l'explique) ;
> **la doc ne l'était pas**, et c'est ce qui a fait rapporter « résultat non
> établi » le soir du 2026-08-20. Le décalage de réplication était réel, mais il
> n'était pas la seule cause : même rafraîchie, la vieille requête rend 12454.
>
> ~~### État au 2026-08-20 (soir) — lancé, résultat NON établi~~ *(périmé,
> conservé pour la traçabilité du diagnostic)*
>
> Le geste a été lancé le 2026-08-20 : **12 454 candidats en périmètre** et une
> **banque à 1533 ancres** confirmée au démarrage — les deux témoins qui
> comptent (lignes 2 et 3 de [`GESTE-P3.md`](GESTE-P3.md)) sont donc bons. Ce
> qui n'est **pas** établi, c'est son aboutissement.
>
> La requête de complétude, passée le soir même **en lecture seule** :
>
> ```bash
> sqlite3 "file:ml/state/eurio.replica.db?mode=ro" "
> SELECT COUNT(*) FROM image_asset_dino_predictions p
>   JOIN (SELECT MAX(built_at) m FROM dino_anchor_builds
>          WHERE anchors_kind='2eur_all' AND encoder_version='dinov2-vitl14') b
>  WHERE p.anchors_kind='2eur_all' AND p.encoder_version='dinov2-vitl14'
>    AND p.computed_at < b.m;"
> # rend : 12454        (sur 12454 au total)
> ```
>
> **Ce `12454` ne veut rien dire, et il faut savoir pourquoi.** La réplique
> locale est **antérieure au rebuild lui-même** :
>
> ```bash
> ls -l ml/state/eurio.replica.db          # → 19 Aug 16:31
> sqlite3 "file:ml/state/eurio.replica.db?mode=ro" \
>   "SELECT MAX(built_at) FROM dino_anchor_builds WHERE anchors_kind='2eur_all';"
> # → 2026-08-19T00:28:21+00:00
> ```
>
> Le build `23c637d93b43` porte `2026-08-19T14:36:14+00:00` : la réplique ne le
> connaît même pas, elle ne peut donc rapporter ni le rebuild ni le backfill.
> C'est le décalage de réplication annoncé par [`GESTE-P3.md`](GESTE-P3.md), pas
> un échec — mais **le verdict n'existe pas tant qu'on n'a pas rafraîchi**.
>
> Deux autres faits mesurés le même soir : **aucun processus de backfill ne
> tourne** (`ps aux | grep backfill_dino` → rien) et **aucun scratch
> `dino-backfill-*` ne subsiste**. Le geste est donc terminé — abouti ou
> interrompu, on ne le sait pas d'ici.
>
> **Pour conclure, deux commandes** :
>
> ```bash
> go-task ml:db:pull-replica     # rafraîchit la réplique depuis le canonique
> # puis rejouer la requête de complétude ci-dessus  → attendu : 0
> ```
>
> ⚠️ Ne **pas** relancer le backfill avant d'avoir rafraîchi : on relancerait 18
> minutes de calcul sans savoir si elles sont nécessaires. Si la requête rend
> toujours 12454 sur une réplique à jour, le run n'a pas abouti — relancer la
> même commande à l'identique, elle est sûre à relancer
> ([`GESTE-P3.md`](GESTE-P3.md) §« Si ça s'arrête en route »).

```sql
SELECT anchors_kind, encoder_version, COUNT(*)
  FROM image_asset_dino_predictions GROUP BY 1,2;
-- 2eur_all|dinov2-vitl14|12454      2eur_commemo|dinov2-vits14|7780
```

Elles ont été calculées contre la banque à 546 classes. Les 118 classes
récupérées existent maintenant comme cibles, mais **aucun crop ne leur a encore
été comparé** : un crop luxembourgeois reste rattaché à ce que l'ancienne
banque connaissait de plus proche.

Conséquence directe sur le bench : le gold de review (P4) est construit à partir
de `review_queue.decided_eurio_id` joint aux prédictions. Tant que les
prédictions sont périmées, **toute mesure de précision top-1 est fausse dans les
deux sens** — elle punit le modèle pour des classes qu'il ne pouvait pas
proposer.

**Le geste**, vérifié le 2026-08-20 :

```bash
cd ml && ./.venv/bin/python -m scripts.backfill_dino_predictions \
  --kind 2eur_all --force --verbose
```

**Sans `--db`** (sous `--push`, actif par défaut dans le devShell, il est
ignoré — le script le dit désormais dans un avertissement) et **sans
`--no-push`** (ce serait le seul cas où le chemin local est ouvert). P1 et P2
sont faits : la condition d'antériorité est levée.

⚠️ **Durée : estimation, non mesurée à l'échelle réelle.** Extrapolée de deux
points mesurés sur copie `/tmp` (4 assets → 5,0 s ; 60 assets → 9,7 s, soit une
pente de ~84 ms/asset après ~4,5 s de chargement du modèle sur MPS) :
**≈ 18 min de calcul** pour 12 454, plus le pull de la réplique scratch
(~106 Mo). L'ancienne estimation « plusieurs heures » venait d'une hypothèse de
retéléchargement MinIO massif ; les 1958 crops du gold sont dans le cache local
(comptés fichier par fichier, 0 manquant), le reste ne l'est pas nécessairement.

**Le témoin qui compte** : `auto_validate backfill: N candidate assets in scope
2eur_all` doit dire **≈ 12 454**, jamais ≈ 6 205. C'est la mesure directe du
défaut de chemin de base ([§8.7](FINDINGS.md)) ; si le chiffre est faux, arrêter
**avant** les 18 minutes. Vérifié sur le vrai module :

```
EURIO_DB_PATH=<copie de la réplique>  → 12454 candidats 2eur_all
EURIO_DB_PATH=<ml/state/eurio.db>     →  6205 candidats 2eur_all
(fonction de sélection du script : sources._base.steps.auto_validate
 ._select_assets_for_backfill(conn, limit=None, anchors_kind='2eur_all'))
```

⚠️ **Deux défauts connus sur ce chemin, aucun bloquant** :
**M8** — le script se termine par un `return 0` inconditionnel : un backfill
avec 3 000 erreurs sort en code 0 et `go-task` dit « réussi ». Lire
`Errors:` à l'œil.
**M7** — le backfill recalcule `face` (2 997 valeurs nulles) et `denom` (6 185)
sur sa réplique scratch, et `export_run` ne les récolte pas : ce travail est
**jeté** à la fin du process. Préexistant, mesuré, pas corrigé.

**Critère de sortie** : zéro prédiction antérieure au build courant. C'est
désormais **mesurable en SQL**, sans nouvelle colonne, et
`store.encoder_bench.calibration_blockers()` l'émet automatiquement :

```sql
SELECT COUNT(*) FROM image_asset_dino_predictions p
  JOIN (SELECT MAX(built_at) m FROM dino_anchor_builds
         WHERE anchors_kind='2eur_all' AND encoder_version='dinov2-vitl14') b
 WHERE p.anchors_kind='2eur_all' AND p.encoder_version='dinov2-vitl14'
   AND p.computed_at < b.m;                          -- 12454 sur 12454
```

**`build_id` n'a PAS été ajoutée**, et c'est délibéré : aucun code livré ne la
lit, ce serait une colonne morte, et la migration 0009 s'interdit tout `ALTER`
nu (les migrations ne sont pas auto-suffisantes, cf. [`FINDINGS.md`](FINDINGS.md)
§6.5). Le jour où on veut le verdict par jointure plutôt que par date, ce sera
une migration dédiée — **la prochaine libre, 0011** : le numéro 0010 est pris
depuis le 2026-08-20 par `0010_dino_refs_encoder_dans_la_cle.sql` (défaut M1,
l'encodeur entre dans la clé primaire de `dino_class_references`). ALTER +
miroir `schema.sql` + `_ensure_column`, les trois — comme 0004 l'a fait pour
`run_id`.

> ✅ **Dette D1, fermée.** `calibration_blockers()` émet bien ce bloqueur pour
> un encodeur **candidat** (`_p3_blockers` distingue quatre états, dont « aucun
> build tracé »), et son volet P1 filtre désormais `encoder_version`. Vérifié
> par mutation rouge/vert et par deux tiers. Détail :
> [`FINDINGS.md`](FINDINGS.md) §8.1.
>
> ⚠️ **Mais le garde n'est appelé sur aucun chemin canonique (M2)** : un run
> poussé par `POST /ingest/encoder-bench` avec `provisional=0` est accepté tel
> quel, sans que les bloqueurs soient recalculés. À fermer avant que la page
> admin du banc ne serve de base de décision.

---

## P4 · Le gold de review — 🟢 figé le 2026-08-19

**Livré** : `ml/review/bench_gold.py` (bibliothèque stdlib-only), CLI
`ml/scripts/bench_gold.py` (`build` / `show` / `diff`), et le manifeste
**committable** `ml/state/validation_gold/encoder_bench_gold.jsonl` (855 ko,
1958 lignes) + son sidecar `.meta.json`.

**`gold_version = 0ecbb1d70e3c`**, reproductible byte-pour-byte :

```bash
cd ml && EURIO_DB_PATH=$PWD/state/eurio.replica.db \
  .venv/bin/python -m scripts.bench_gold build
# 1958 crops · 194 truth_eurio_id · 188 class_id · gold_version=0ecbb1d70e3c
```

**1958** crops décidés (et non 1911 : le filtre `training_eligible=1` en retire
47, il est conservé comme **colonne** et non comme filtre — le banc mesure un
encodeur *gelé en zero-shot*, il n'entraîne rien, et `COUNT(DISTINCT
decided_eurio_id)` vaut 194 avec **et** sans le filtre).

**Le piège attrapé au passage** : les 194 `eurio_id` se replient sur **188
`class_id`** de banque, et 8 classes / **105 crops (5,4 %)** ont un `class_id`
différent de leur `eurio_id` (`at-2008` → `at-2002` en porte 82). Un gold naïf
aurait **plafonné le recall à 94,6 %** sur tous les encodeurs, sans rien
signaler.

Le manifeste ne contient **aucune prédiction** : le gold est donc indépendant de
P3, comme prévu, et a pu être figé tout de suite.

> ✅ **Dettes D2 et D6 corrigées** (cf. [`FINDINGS.md`](FINDINGS.md) §10).
> `gold_version` hache maintenant `asset_id|truth_eurio_id|class_id` : une
> re-décision humaine la fait bouger, et `diff_gold` signale aussi les `class_id`
> changés. ⚠️ **Ce que D2 ne couvre toujours pas** : le hash est **déclaré et
> jamais vérifié** — `load_meta` relit le sidecar, rien ne recalcule
> `gold_version(load_gold(p))` à la consommation. Un `.jsonl` édité à la main
> laisse les runs estampillés de l'ancien hash (sonde : `deadbeef1234` estampillé
> pour un contenu qui hache `1cb756ca4a63`). Le gold committé est sain
> aujourd'hui : sidecar = recalcul = `0ecbb1d70e3c` sur 1958 lignes. Le pays du gold s'appelle `truth_country` et vient de
> `decided_eurio_id` — les 33 pays faux et 209 nuls sont corrigés (242 lignes,
> 12,4 %). Conséquence assumée : le gold a été **régénéré**,
> `9b15176b3309` → `0ecbb1d70e3c`.

---

## P5 · Le corpus de scan n'est pas versionné — 🟠 plan livré, 0 capture

🔴 **Correction de formulation, 2026-08-20.** Ce document a longtemps dit
« **0 photo** ». C'était juste sur la lettre et **faux sur le fond**, et le PO a
eu raison de le relever : le zéro décrit le **store versionné**, pas la matière
première. Le juste est **« 0 capture versionnée, 2 264 images device non
protégées »** :

```bash
ls -la ml/state/scan_corpus.db                                      # 0 octet — le store dédié, vide
find ml/datasets/eval_real_norm -type f \( -name '*.jpg' -o -name '*.png' \) | wc -l   # 114  (19 classes)
find debug_pull -type f -name '*.jpg' | wc -l                       # 2150 (frames caméra réelles)
```

Ces 2 264 images ne sont **ni labellisées, ni versionnées, ni répliquées** :
aucune sur MinIO, aucune dans la chaîne de sauvegarde (qui ne tourne que sur le
VPS), les deux dossiers gitignorés — **un `git clean -xdf` les détruit**. Le
gisement intéressant est `debug_pull` : 2 150 vraies frames de caméra qui ne
demandent qu'une annotation. Le problème, son chiffrage et le remède (MinIO
d'abord, capture ensuite) :
[`../scan-quality/DURABILITE-CORPUS.md`](../scan-quality/DURABILITE-CORPUS.md).

Tout l'outillage existe : le store, le schéma (`capture_id` = sha256 des octets
bruts, `eurio_id`, `condition` dans un vocabulaire ouvert incluant `glare` et
`inhand`), le versioning append-only, l'import depuis les bundles cohort-test,
le replay avec scorecard et McNemar apparié (`bd4888b`, `0a11294`). Et l'app de
capture existe, avec sa prescription par classe et par condition.

**Il ne manque que les photos.** C'est le seul prérequis que la machine ne peut
pas produire.

> **Livré le 2026-08-19** : le plan de capture existe —
> [`PROTOCOLE-CAPTURE.md`](./PROTOCOLE-CAPTURE.md) (à lire téléphone en main),
> [`plan-capture-scan.csv`](./plan-capture-scan.csv) (80 classes, 400 cellules,
> 985 captures, 11 sessions), régénérable par
> `go-task ml:scan-corpus:prescribe`. La composition retenue diffère de la
> proposition ci-dessous : voir `PROTOCOLE-CAPTURE.md` §5.
>
> **Composition** : 22 riches / 21 moyennes / 30 canonique-seul / 7 hors banque.
> Les 7 « hors banque » ne sont pas aveugles — chacune a **exactement un** frère
> de son `design_group` dans la banque, donc reste scorable en maille `eq`
> (requête : [`FINDINGS.md`](FINDINGS.md) §5.1). Les exclure aurait coûté 7
> pièces déjà en main pour zéro gain.
>
> 🔴 **Le piège qui ferait perdre la campagne en silence** :
> `build_cohort_bundle.py:65` échantillonne à **3 pièces** dès 30, sans message.
> Sans `NO_SAMPLE=1`, la campagne photographierait **3 classes sur 80**. Et
> `cohort-test:bundle:prod` n'expose ni `PRESCRIBE_COHORT` ni `NO_SAMPLE` : ce
> chemin est inutilisable. Contrôle bloquant avant la première photo :
> `sampled=False`, 400 tests, 80 classes dans `live_tests_manifest.json`.
>
> ⚠️ Non vérifié faute de device : que le build cohortTest active bien
> `snapArchiveDir` (`CoinAnalyzer.archiveSnap` est opt-in, `null` en prod). S'il
> est inactif, les sessions produisent le JSONL mais **aucune frame corpus** — la
> requête de contrôle du protocole §3 l'attrape dès la première session.
>
> ⚠️ **Dette D12** : `build_scan_prescription.py:54` code `DEFAULT_DB` en dur sur
> la réplique — le motif exact corrigé le même jour dans `build_dino_anchors.py`.

### 🔴 Ce que la courbe du 2026-08-20 change au plan de capture

La courbe « références par classe » ([`COURBE-REFERENCES.md`](COURBE-REFERENCES.md))
a été mesurée **sur la tâche review**. Elle ne remplace pas P5 — au contraire,
elle en fait le chemin critique de façon plus aiguë qu'avant. Mais elle
**invalide la maille des strates** du plan actuel, et cela se corrige avant la
première photo, pas après.

**Le fait qui casse la maille** : la relation « plus de références → plus de
précision » **n'est pas monotone**. La première référence FAIT BAISSER la
précision (−3,0 pts en `vits14`, −3,6 en `vitl14`), et en encodeur de production
il faut **N=5** pour repasser au-dessus du canonique seul — N=3 rend
*exactement* le chiffre de N=0 (76,09 % dans les deux cas).

Or la strate **« moyennes (1-8 exemplaires) »** du CSV mélange, dans un même
seau, des classes en **régression** (N=1, N=2) et des classes déjà rentables
(N=5..8). **Toute moyenne prise sur cette strate est ininterprétable** : elle
additionne deux régimes de signe opposé. C'est le piège de composition exact que
la strate « pauvre » avait évité.

**Composition recommandée pour la campagne** — quatre strates au lieu de trois,
alignées sur les régimes que la courbe distingue :

| Strate | Exemplaires en banque | Ce qu'elle mesure | Pourquoi elle doit exister |
|---|---:|---|---|
| canonique seul | 0 | le régime de **489 classes sur 671 (73 %)** | c'est le catalogue réel |
| **régression** | **1-2** | le creux, **sur la tâche scan** | le seul palier où l'effort de review peut **nuire** ; jamais mesuré hors review |
| montée | 3-7 | le segment à ~2,5 pt/réf | c'est là que le budget s'arbitre |
| riche | 8-10 | la borne haute atteignable | plafond de ce que la banque sait faire |

⚠️ **Ce que cela ne dit pas** : rien ne garantit que le creux à N=1 existe aussi
sur une frame caméra. C'est précisément **pourquoi il faut la strate** — si le
creux est un artefact de la tâche review, on veut le savoir avant de faire de
« jamais un seul exemplaire » une règle de peuplement de la banque APK.

**À faire suivre** (non fait, hors périmètre de la mesure) :
[`PROTOCOLE-CAPTURE.md`](./PROTOCOLE-CAPTURE.md) §5 et le CSV
`plan-capture-scan.csv` portent la maille à trois strates
(22 riches / 21 moyennes / 30 canonique-seul / 7 hors banque), et
`build_scan_prescription.py::_strate_of` la code. Les trois doivent bouger
ensemble, régénération par `go-task ml:scan-corpus:prescribe`. ⚠️ **Et Q6 est à
fermer avant** : le script somme `n_fps` sur **tous** les encodeurs, donc la
strate d'une classe changera silencieusement au premier build de banque d'un
candidat ([`FINDINGS.md`](FINDINGS.md) §8.10, Q6 — 9 classes déplacées mesurées).

**Ce que la courbe ne change PAS** : le nombre de captures par classe. Elle
porte sur les références *dans la banque*, pas sur les frames *du corpus*.
La cible « ≥ 3 conditions par classe, dont une difficile » tient.

**Et l'ordre de grandeur qu'elle ajoute au chantier** : amener les 671 classes
à N=8 demande **4 622 crops validés en review**, soit **2,4× tout ce qui a été
reviewé depuis le début du projet**. Ce budget-là est parallèle à P5, il ne le
remplace pas — et c'est lui qui décide de ce que la banque saura reconnaître le
jour où les photos existeront.

### Ce qu'il faut décider avant de builder l'APK de capture

Le CSV de prescription est le vrai livrable de cette étape, et il mérite d'être
pensé, parce que **tu ne referas pas les photos**. Trois questions :

1. **Quelles classes ?** Le réflexe serait de prendre les classes riches — ce
   sont celles qu'on a sous la main. C'est exactement le biais qui rend les 317
   snaps `eval_real_norm` inexploitables (ils couvrent ~17 classes, celles où le
   modèle est déjà bon). **Il faut des classes pauvres dans le corpus**, sinon
   on ne mesurera jamais le régime canonical-only qui représente 81 % du
   catalogue.
2. **Combien par classe ?** L'étape 3 de `DECISION.md` veut faire varier le
   nombre de références *dans la banque*, pas dans le corpus. Côté corpus, ce
   qui compte c'est la couverture en conditions. Cible proposée : **≥ 3
   conditions par classe**, dont au moins une difficile (`glare` ou `inhand`).
   *(Confirmé le 2026-08-20 : la courbe mesurée sur la review ne touche pas à
   ce chiffre. Ce qu'elle touche, c'est la **maille des strates** — voir le
   bloc ci-dessus.)*
3. **Combien de classes ?** ≥ 50 distinctes pour que le chiffre veuille dire
   quelque chose, ≥ 500 captures au total.

**Proposition de composition**, à discuter — ⚠️ **périmée le 2026-08-20**, la
strate « Moyennes (1-8) » mélange deux régimes de signe opposé (bloc ci-dessus) :

| Strate | Classes | Pourquoi |
|---|---:|---|
| Riches (≥ 9 exemplaires en banque) | 15 | plafond atteignable, borne haute |
| ~~Moyennes (1-8 exemplaires)~~ | ~~15~~ | ~~la zone où la courbe P3/étape 3 se joue~~ — **à scinder en 1-2 (régression) et 3-7 (montée)** |
| Pauvres (canonique seul) | 20 | **le régime réel de 81 % du catalogue** |

C'est la strate « pauvres » qui donnera le chiffre le plus utile du chantier,
et c'est celle qu'on est le plus tenté d'oublier parce qu'elle donnera les plus
mauvais scores.

**Critère de sortie** : ≥ 500 captures, ≥ 50 classes, ≥ 3 conditions/classe,
`glare` et `inhand` représentées, corpus figé et versionné.

---

## P6 · Le banc porte deux encodeurs — 🟢 fait le 2026-08-19

> **Les deux blocages sont levés, les trois manques sont comblés.** Ce qui reste
> est le **câblage** du banc lui-même (dettes D4/D5) : `bench_encoder_dino.py`
> rejoue encore sa propre requête de sélection et n'écrit rien dans
> `encoder_bench_runs`.
>
> | Point | État | Où |
> |---|---|---|
> | `anchor_path` scopé par encodeur | ✅ `anchor_path(kind, encoder_version)`, double-écrit legacy conditionnel | `training/foundation/anchors.py` |
> | `_get_bank` multi-encodeurs | ✅ cache par couple, comportement prod identique (1250 / dim 1024 / vitl14 toujours servies) | `sources/_base/steps/auto_validate.py` |
> | test apparié | ✅ `mcnemar_exact` **déplacé** (pas dupliqué) — 0 divergence sur 3600 couples | `shared/stats/paired.py` |
> | balayage de seuils par encodeur | ✅ seuils dérivés de la plage **observée**, jamais [0,1] ; `propose_threshold` lève `CalibrationBlocked` | `shared/stats/sweep.py`, `calibration.py` |
> | `encoder_bench_runs` / `_predictions` | ✅ migration 0009 **+ miroir** `schema.sql` (verrouillé par `tests/test_schema_mirror.py`), store, `POST /ingest/encoder-bench`, `GET /lab/encoder-bench/runs`, routeur monté. Depuis le 2026-08-20, `record_run` **refuse** d'écrire `provisional=0` dans une base qui mesure des bloqueurs, et la route remesure sur sa propre connexion puis corrige (M2) | `serving/`, `store/encoder_bench.py` |
> | `dino_class_references` scopée par encodeur | ✅ migration **0010** + miroir `schema.sql` : `PRIMARY KEY (anchors_kind, encoder_version, class_id, eurio_id, asset_id)`, `encoder_version NOT NULL DEFAULT ''`. Le writer refuse une table à l'ancienne clé (M1). ⚠️ **Non appliquée au canonique** : elle attend le redémarrage de `eurio-api`, à faire AVANT le premier build de banque d'un encodeur candidat | `serving/migrations/0010_*.sql`, `store/dino_references.py` |
>
> Le paquet `shared.stats` est **stdlib pur** (test par sous-processus) : il
> s'importe sur l'image lean du VPS sans faire disparaître son routeur en
> silence.
>
> ⚠️ **Dettes D3, D10, D11** : le scoping a rendu **muet** le cas « banque legacy
> périmée » (plus de `logger.error`) ; il ne protège **pas** l'arm baseline
> `dinov2-vitl14`, qui reste l'encodeur servi ; et 9 des 10 lecteurs de
> `load_anchors` lisent encore le legacy. Détail : [`FINDINGS.md`](FINDINGS.md) §8.

### L'état d'origine, pour mémoire

Deux blocages structurels, déjà identifiés dans
[`PROTOCOLE-BENCH.md`](../banque-dino/PROTOCOLE-BENCH.md) et toujours ouverts :

- `anchor_path(kind)` (`anchors.py:136`) ne met pas l'encodeur dans le nom du
  `.npz` : deux encodeurs sur le même kind **s'écrasent** ;
- `_get_bank` (`ml/sources/_base/steps/auto_validate.py:130`) traite une banque
  comme absente si son encodeur ne correspond pas au mapping — la banque
  « autre encodeur » serait invisible pendant la comparaison.

Plus les trois autres manques du protocole : test apparié (extraire
`mcnemar_exact` de `replay_corpus.py`), balayage de seuils **par encodeur**
(chaque encodeur a sa propre échelle de spread), et les tables
`encoder_bench_runs` / `encoder_bench_predictions`.

En revanche `image_asset_dino_predictions` est **déjà prête** : sa clé primaire
inclut `(encoder_version, anchors_kind)` et deux séries y coexistent
aujourd'hui.

---

## P7 · Les poids et la licence — 🟢 fait le 2026-08-19

**Disponibilité : vérifiée, rien à installer.**

```
$ ml/.venv/bin/python -c "import timm; print(timm.__version__,
    len(timm.list_models('*dinov3*', pretrained=True)))"
1.0.27 18
```

`bench_encoder_dino.py` les accepte déjà via `timm:<model>` — **aucune ligne de
code modèle à écrire.** `ml/scripts/bench_encoder_dino.py:109-114` applique
`create_transform(**resolve_model_data_config(model))` : la résolution et la
normalisation sont prises automatiquement.

### Les poids, téléchargés et vérifiés

Aucun gate, aucun token : `timm` ne tape pas les dépôts `facebook/*` (gatés)
mais ses propres miroirs `timm/*`.

| Modèle | Téléchargement | Params | Sortie | Entrée résolue |
|---|---:|---:|---:|---|
| `vit_small_patch16_dinov3.lvd1689m` | 91,2 Mo en 11,3 s | 21,59 M | (1, 384) | **256×256** |
| `convnext_tiny.dinov3_lvd1689m` | 115,4 Mo en 13,2 s | 27,82 M | (1, 768) | 224×224 |

⚠️ La résolution du ViT-S/16 est **256**, pas les 224 annoncés par la carte
`facebook/*`. Les deux s'instancient en extracteur (`num_classes=0`) et
produisent un vecteur sur un vrai crop de pièce.

**Poids** : ViT-S/16 86,3 Mo fp32 / 43,2 fp16 / 21,6 int8 ; ConvNeXt-T 111,3 /
55,6 / 27,8. À comparer aux **4,43 Mo** de l'ArcFace MobileNetV3 de l'APK — un
facteur 5 à 6 même en int8.

### 🔴 Ce que la version précédente de ce §P7 disait de faux

- **« Les variantes EUPE sont explicitement non commerciales »** — EUPE n'est
  **pas** une variante de DINOv3. C'est une famille de modèles **séparée** (Meta
  Reality Labs + FAIR, sous FAIR Noncommercial Research License). Les 18 modèles
  de `timm.list_models('*dinov3*')` ne contiennent **aucun** `eupe` : seulement
  des suffixes `.lvd1689m` et `.sat493m`. Ces deux-là sont des **jeux de
  données** d'entraînement, sous la **même** licence DINOv3, commercialement
  identiques (`timm.get_pretrained_cfg(n).license` → `'dinov3-license'` pour les
  deux). Pour Eurio, LVD-1689M est le seul pertinent : SAT-493M est satellite et
  n'existe qu'en ViT-L/16 et ViT-7B.
- **« attribution + inclusion de la licence »** — insuffisant. L'obligation
  inclut aussi la **mention de marque** « Built with DINOv3 ».

### Le verdict de licence

**Redistribution permise, y compris commerciale.** §1.a : licence
« non-exclusive, worldwide, non-transferable and royalty-free » pour « use,
reproduce, distribute, copy, create derivative works of, and make
modifications ». Aucun seuil d'utilisateurs, aucune restriction commerciale.
Aucune Acceptable Use Policy attachée (contrairement à Llama).

Trois obligations, §1.b.i : **(A)** ne distribuer que sous ce même accord ;
**(B)** joindre une copie de l'accord aux DINO Materials ; **(C)** afficher de
façon proéminente « Built with DINOv3 ».

⚠️ **Les deux copies publiées de la licence diffèrent.** Le `LICENSE.md` de
GitHub (« Last Updated: August 19, 2025 ») ne porte que (A) et (B) ; la page
`ai.meta.com` (« August 14, 2025 »), celle vers laquelle pointent **toutes** les
cartes de modèle Hugging Face, ajoute (C).

```bash
curl -sfL https://raw.githubusercontent.com/facebookresearch/dinov3/main/LICENSE.md | grep -c 'Built with'   # 0
# page Meta : occurrence de "Built with" à l'offset 2682                                                      # 1
```

**Conduite retenue** : se conformer à la version **la plus stricte**. Le §8 dit
que Meta peut modifier l'accord avec effet immédiat — la version live prime sur
une copie figée dans un dépôt. Coût : une ligne de texte. Coût de la
non-conformité : une violation de licence sur une app Play Store.

Un **dérivé** (fine-tuné, distillé, quantifié TFLite/int8) reste couvert :
§1.b.i vise « DINO Materials, **and any derivative works thereof** », et « DINO
Materials » inclut nommément « trained model weights ». La quantification ne
lave pas la licence.

⚠️ **estimation** : la **banque de vecteurs** relève des « outputs and results »
(§3), que Meta ne revendique pas — elle nous appartient probablement librement,
seul le backbone porte la licence. **hypothèse** : la clause anti-reverse-
engineering §1.b.iv ne vise pas la conversion TFLite (sinon le §1.a serait vidé
de sens). Ces deux points méritent un avis juridique avant publication.

**Ce que DINOv2 → DINOv3 fait perdre** : la liberté de sous-licencier, la
stabilité du contrat (§8), la clause brevets explicite d'Apache 2.0 §3, et
l'obligation de branding. On **ne perd pas** le droit commercial, ni celui de
modifier, ni celui de redistribuer, ni la propriété de ses dérivés. Le coût est
administratif, pas stratégique.

### La mesure inattendue : ConvNeXt s'effondre en CPU batch 1

Mac, torch 2.9.1, 8 threads, 10 itérations après 3 de chauffe :

| Encodeur | Params | CPU bs1 | CPU bs32 | MPS bs1 | MPS bs32 |
|---|---:|---:|---:|---:|---:|
| dinov3 ViT-S/16 | 21,6 M | **24,5 ms** | 19,19 | 15,0 | 12,93 |
| dinov3 ConvNeXt-T | 27,8 M | **292,8 ms** | 49,13 | **9,5** | **7,38** |
| dinov2 ViT-S/14 | 21,7 M | 20,4 ms | 18,53 | 10,0 | 8,56 |
| dinov2 ViT-L/14 *(review)* | 304,4 M | 217,9 ms | 166,25 | 93,2 | 93,1 |

Le 292,8 ms est **reproduit** machine libre (292,6 ms sur 20 itérations, 286,0
en `channels_last`). ⚠️ **Mesures Mac/PyTorch, pas Android/TFLite** — elles ne
prédisent pas la latence dans l'APK. Mais le scan Android est un **CPU batch 1**,
exactement le régime où ConvNeXt s'effondre : **le ViT-S/16 devient le candidat
par défaut pour l'APK**, ce qui inverse l'ordre proposé par `DECISION.md` §4a.
ConvNeXt-Tiny reste le meilleur pour bâtir la banque côté Mac (MPS).

**Critère de sortie** : ✅ licence lue et tranchée, poids téléchargés, latences
mesurées. **Reste** : avis juridique avant Play Store, et bench TFLite/NNAPI sur
device réel pour départager ViT-S/16 et ConvNeXt-Tiny côté embarqué.

---

## L'ordre que je propose

```
P2 (7 appels Numista)  ──┐
                         ├──▶ P1 (rebuild ~6 min) ──▶ P3 (backfill, heures)
                         │              │
P7 (licence + poids) ────┘              └──▶ P4 (gold figé) ──▶ P6 (banc) ──▶ BENCH review
                                                                                   │
P5 (capture, en parallèle, des semaines) ─────────────────────────────────────────┴──▶ BENCH scan
```

**En parallèle dès maintenant** : P5 est le chemin critique en temps réel
(semaines de capture), et il ne dépend de rien. Builder l'APK de capture avec
son CSV de prescription est donc le geste à faire **en premier**, même si son
résultat arrive en dernier.

**Et pendant que tu photographies** : P2 → P1 → P4 → P6 → bench review. Ce
bench-là ne décide rien pour l'APK (cf. `DECISION.md` §D4), mais il décide
quel encodeur sert la review — ce qui accélère ta validation, donc remplit la
banque plus vite. Le gain se cumule.

### Où on en est sur ce graphe, au soir du 2026-08-20

**P1, P2, P4, P7 sont derrière ; P3 est lancé, P6 est à moitié.** Le chemin
restant, dans l'ordre :

```
1. ✅ rebuild banque (P1) — fait le 19/08 à 16:36, 237 s, build 23c637d93b43
2. 🟠 backfill prédictions (P3) — LANCÉ le 20/08, résultat non établi
      → conclure : go-task ml:db:pull-replica, puis la requête de complétude
3. ✅ M1 (l'encodeur dans la PK, migration 0010) — fermé et vérifié le 20/08
3b. 🚫 redémarrage eurio-api  ← applique 0009 + 0010 au canonique (geste humain)
3c. 🔴 Q6 (les LECTEURS de dino_class_references)  ← AVANT tout build candidat
4. bench review (run RÉEL sur GPU) → décision d'encodeur
      ⚠️ Q1..Q5 décident de ce que la page admin appellera « promouvable »
   ────────────────────────────────────────────
   en parallèle, dès maintenant : cohorte + APK cohortTest + photos (P5)
```

Les gestes 3b et 3c s'intercalent : ils ne bloquent pas P3 (qui ne touche pas
`dino_class_references`), mais ils bloquent le geste 4, dont la première étape
est de bâtir la banque d'un encodeur candidat. **3b** parce que, sans 0010 au
canonique, le writer refuse (bruyamment — c'est le correctif M1, pas une panne).
**3c** parce que, une fois 0010 en place, ce build ne détruit plus rien mais
rend faux tout ce qui **lit** la table : la page admin, le badge de review, et
le plan de capture P5. Voir [`FINDINGS.md`](FINDINGS.md) §8.10, Q6.

Les gestes 1 et 2 sont des **écritures** : le rebuild pousse sa trace par
`--push` au canonique, la cohorte de P5 part par `POST /lab/cohorts`. Jamais en
SQLite direct (Direction A, skill `eurio-data-writes`).

## Ce qui reste ouvert

- ~~**La cause du retard de P1.**~~ **Trouvée le 2026-08-19 (soir)** : un `--db`
  codé en dur dans `build_dino_anchors.py`. **Rebuild lancé le 19/08 à 16:36 :
  182 classes à exemplaires, exactement la prédiction.** Cf. §P1 et
  [`FINDINGS.md`](FINDINGS.md) §2.1 ; le motif générique est
  [`FINDINGS.md`](FINDINGS.md) §8.7. ⚠️ Le même défaut est **toujours** dans
  `build_dino_anchors.py:57` sous sa forme atténuée — le repli est
  `eurio.db`, pas `eurio.replica.db` (M4).
- ~~**Le `build_id` dans les prédictions.**~~ **Tranché : pas de colonne.** P3
  se mesure par `computed_at < MAX(built_at)`, requête ci-dessus §P3. Une
  migration dédiée (0011, cf. ci-dessus) le jour où on veut le verdict par
  jointure.
- **La dette du lot P4/P6** — registre daté : [`FINDINGS.md`](FINDINGS.md) §8.
  État au **2026-08-20 (soir, après vérification de la troisième passe)**, sur
  **45 lignes** : **17 ✅ · 3 ⚠️ · 3 ⏭ · 1 🔍 · 21 🔴**. ~~D1 volet P1~~,
  ~~D5~~, ~~D6~~, ~~D8~~, ~~D16~~, ~~N1~~, ~~N2~~, ~~N6~~ et, le 2026-08-20,
  ~~**M1**~~ (l'encodeur entre dans la clé primaire, migration 0010) sont
  corrigés **et vérifiés par un tiers**. **M2 est ⚠️** : l'invariant est dans la
  porte d'écriture et il tient, mais le prédicat qu'il évalue dit faux
  (Q1..Q4) et son détecteur de chemin est aveugle (Q5). La note de motif —
  écrite pour quelqu'un qui n'était pas là — est
  [`FINDINGS.md`](FINDINGS.md) **§8.9**, « le garde branché sur le chemin qu'on
  avait en tête » ; les douze défauts neufs sont au **§8.10**.
  Priorité restante, dans l'ordre :
  **Q10** (le garde M1 arrive après 4 min d'encodage, et son message se perd en
  500 générique par HTTP — la fenêtre est ouverte **maintenant**) ·
  **le redémarrage de `eurio-api`** (0009 + 0010, geste humain) ·
  **Q6** (les lecteurs non scopés — avant le premier build d'un candidat) ·
  **Q1..Q4** (ce que la page admin appellera « promouvable ») ·
  **Q5** (tant qu'il tient, on se croit protégé) ·
  **M4** (`build_dino_anchors` et `bench_gold` hors de la convention de repli,
  deux lignes) · puis **N4** / **N5** (deux portes que la session avait cru
  fermer) et **M3** (la règle de repli promet ce que l'exécution dément).
- ~~**Le câblage du banc**~~ — **fait le 2026-08-19** : `bench_encoder_dino.py`
  lit le gold figé, mesure `calibration_blockers()`, imprime la bannière en tête
  **et** en pied, refuse le seuil tant qu'un bloqueur tient, et pousse par
  `client.ingest.push_encoder_bench`. ⚠️ Le **câblage** est prouvé, pas les
  chiffres : aucun run réel n'a tourné (pas de GPU ici, P3 non lancé). Deux
  champs à relire au premier run — `bank_build_id` et `n_out_of_scope`.
  ~~`n_not_encoded`, qui ne va nulle part~~ : **corrigé (N1)**, il est imprimé,
  porté au rapport et retiré de la couverture du gold. ⚠️ `bank_build_id` garde
  une réserve : il trace le build de l'encodeur de **production** pour tous les
  runs, candidat compris ([`FINDINGS.md`](FINDINGS.md) §8.6, non instruit).
- **Le cap `exemplars_per_class = 10`** (`anchors.py:204`) et le plancher
  `floor_sim = 0.45` (`anchors.py:200`) n'ont jamais été mesurés — ce sont des
  valeurs choisies. L'étape 3 de `DECISION.md` les mesurera ; d'ici là, ne pas
  les traiter comme des faits.
- ~~**La composition du CSV de prescription** (P5)~~ — tranchée le 2026-08-19 :
  80 classes en 4 strates (22/21/30/7), 400 cellules, 985 captures, 11 sessions,
  strate canonique-seul sur-représentée à 45,7 % des captures. Argumentation :
  [`PROTOCOLE-CAPTURE.md`](PROTOCOLE-CAPTURE.md) §5. Le quota 15/15/20 reste
  reproductible en une option.
- **L'avis juridique DINOv3** (P7) — l'écart entre les deux versions publiées de
  la licence, et la portée de la clause anti-reverse-engineering §1.b.iv. Non
  bloquant pour le bench, bloquant avant publication Play Store.
- **Le bench TFLite/NNAPI sur device** — les latences de P7 sont sur Mac. Le
  verdict ViT-S/16 vs ConvNeXt-Tiny pour l'APK l'exige.
