# Le scan sans réentraînement — décision

> Écrit le 2026-08-19. Ouvre une **seconde voie** vers le modèle embarqué :
> un backbone gelé + une banque de vecteurs, où ajouter une classe ne coûte
> plus un entraînement.
>
> Chantier frère, à lire d'abord : [`../banque-dino/CONSTAT.md`](../banque-dino/CONSTAT.md)
> et [`PROTOCOLE-BENCH.md`](../banque-dino/PROTOCOLE-BENCH.md). Ce doc-ci ne
> réécrit rien de ce qui y est décidé — il l'étend du côté **scan**.
>
> **Mis à jour le 2026-08-19 (soir).** Cette décision est désormais enregistrée
> comme [ADR-008](../../adr/008-deux-voies-backbone-gele-et-arcface.md). Les
> mesures qui ont bougé depuis la première rédaction — cause de P1, latences,
> licence — sont dans [`FINDINGS.md`](FINDINGS.md) ; les passages concernés
> ci-dessous portent un encart daté.
>
> 🔴 **Mis à jour le 2026-08-20 (clôture de session) — une décision de ce doc a
> été mesurée, elle coûte, et elle est ANNULÉE.** **D5** (le plancher
> `min_exemplars=2`) a été implémentée et appliquée : la banque est passée de
> 1533 ancres / 182 classes à exemplaires à **1495 / 124**, 68 classes ramenées
> au canonique seul. Le re-bench held-out à N=10 dit **74,1 %** pour `vits14`
> (contre 75,5) et **84,8 %** pour `vitl14` (contre 85,7) : **le plancher a
> dégradé, pas amélioré.** Puis la mesure **par classe** — celle que ce document
> réclamait — a été faite le soir même : elle réfute la prémisse, et **D5 est
> annulée** (défaut revenu à `min_exemplars = 1`, plancher inactif). Voir §D5, et
> la **note d'état en tête de [`PREREQUIS.md`](PREREQUIS.md)** pour l'état
> complet et l'ordre des gestes qui attendent le PO.
>
> Deux chantiers ont par ailleurs été **posés par écrit** pendant cette session
> et attendent une session dédiée — rien n'y est implémenté :
> [`../review-autovalidation/PROBLEME.md`](../review-autovalidation/PROBLEME.md)
> (90 % des reviews demandent un geste humain sur le **crop**, pas sur la
> classe) et
> [`../scan-quality/DURABILITE-CORPUS.md`](../scan-quality/DURABILITE-CORPUS.md)
> (2 264 images device, aucune réplique).

## Ce que ce doc décide

- Qu'on ouvre la voie « backbone gelé » **en parallèle**, sans rien retirer de
  la chaîne cohorte → bake → entraînement → promotion.
- L'ordre des quatre étapes, et le critère de sortie de chacune.
- Le point unique où les deux voies se départageront : le corpus de scan.

## Ce que ce doc NE décide pas

- Quel encodeur gagne. C'est l'étape 2 qui le dira, sur nos données.
- S'il faut une tête de projection. C'est l'étape 4, et elle est
  **conditionnelle** au résultat de l'étape 3.
- Le sort de la voie ArcFace. Elle continue ; on tranchera sur une mesure.

---

## 1. La question posée, et la réponse en trois lignes

> « Ces images qu'on valide en review vont créer un vecteur, et ce vecteur peut
> être directement utilisé sans avoir besoin d'entraîner le modèle ? »

**Oui, et c'est exactement ça.** Précisément :

1. Le **backbone** (DINOv2, DINOv3, ConvNeXt…) est une fonction figée :
   image → vecteur. Il ne connaît rien aux pièces euro et il n'apprendra
   jamais rien d'elles. On ne le touche pas.
2. La **banque** est une liste de couples `(classe, vecteur)`. Reconnaître =
   encoder le crop de la caméra, comparer par cosinus à la banque, prendre les
   plus proches. Ajouter une classe ou une référence = **ajouter des lignes**.
3. La **tête de projection** est une troisième chose, **optionnelle** et
   séparée des deux premières. Elle n'est pas nécessaire pour que 1 et 2
   fonctionnent.

### La tête de projection, puisque c'est le point qui coince

Le backbone gelé produit un espace **générique** : il place « deux objets
ronds en métal gravé » près l'un de l'autre parce que c'est vrai visuellement,
même si ce sont deux commémoratives différentes. C'est sa force (il marche sur
une classe qu'il n'a jamais vue) et sa limite (il ne sait pas quels écarts
comptent **pour nous**).

Une tête de projection est une toute petite couche — un `Linear(1024 → 256)` —
qui prend le vecteur générique et le réécrit dans un espace où les écarts qui
nous intéressent sont amplifiés.

Ce qui la rend économiquement différente d'un entraînement ArcFace classique :

| | Fine-tune ArcFace (voie A) | Tête de projection (voie B) |
|---|---|---|
| Ce qui apprend | le backbone entier, 21,7 M params | une matrice, ~0,26 M params |
| Entrée de l'entraînement | des **images** (à décoder, augmenter, charger) | des **vecteurs déjà calculés** |
| Matériel | GPU (la 1080 Ti, Xid 79 compris) | CPU du Mac |
| Durée mesurée / estimée | ~7 h (log run v2, 35 min/epoch) | minutes ⚠️ estimation |
| Nouvelle classe sans réentraîner ? | non | **oui** — la tête est générique, elle s'applique à n'importe quel vecteur |

Le dernier point est le plus important et le moins intuitif : **même avec une
tête de projection, ajouter une classe reste gratuit.** La tête ne contient pas
la liste des classes (contrairement à un classifieur) ; elle transforme un
vecteur en vecteur. On la ré-entraîne de temps en temps, quand le volume de
review a beaucoup grossi, pour qu'elle profite des nouvelles données — mais
c'est une amélioration opportuniste, jamais un prérequis à la couverture.

### Donc, la boucle cible

```
review humaine → crop validé → encode (backbone gelé) → ligne dans la banque
                                                          → l'APK reconnaît
```

Aucun GPU, aucune cohorte, aucun bake, aucune promotion destructive dans ce
chemin. C'est la promesse, et c'est ce que les quatre étapes vont vérifier.

---

## 2. Ce qui est déjà vrai — mesuré

### 2.1 Les deux lignes de modèle ont divergé sans qu'on le voie

Ce que l'APK embarque réellement, `shared/model-assets.json` (épinglé
2026-08-15) + `app-android/src/main/assets/data/model_meta.json` :

```json
{ "mode": "arcface", "backbone": "mobilenet_v3_small",
  "num_classes": 17, "embedding_dim": 256 }   // 4,43 Mo
```

Pas de DINO. Un MobileNetV3-small, 17 classes. La dernière itération du lab
(`ml/lab/iterations/4aaac6865ca9/`, 16 août) en a **6**, avec un R@1 de 0,9722
mesuré sur 36 images de validation — un chiffre qui ne mesure rien.

Le modèle DINOv2 décrit dans [`../../model-efficiency/VISION.md`](../../model-efficiency/VISION.md)
(`arcface-vits14-v1`, ViT-S/14 + `Linear(384→384)`, 546 classes, 41,8 Mo fp16)
existe comme checkpoint sur MinIO et **n'a jamais atteint l'APK**.

État de la donnée (`ml/state/eurio.replica.db`, 2026-08-19) :

```sql
SELECT resolution_status, training_eligible, COUNT(*)
  FROM image_assets GROUP BY 1,2 ORDER BY 3 DESC;
-- needs_review|0|6927   manual|1|1910   rejected|0|3006   needs_review|1|22 …
SELECT COUNT(DISTINCT eurio_id) FROM image_assets WHERE training_eligible=1;  -- 194
SELECT COUNT(*) FROM coins;                                                    -- 689
```

**1 945 crops validés sur 194 classes.** 17 dans l'APK. 546+ visés.

### 2.2 La banque gelée existe déjà — mais elle ne sert que la review

`build_anchors_2eur_all` (`ml/training/foundation/anchors.py:571`) fait déjà,
aujourd'hui, exactement l'architecture décrite au §1 :

- backbone gelé (`SUGGESTIONS_ENCODER_VERSION = dinov2-vitl14`), jamais
  entraîné ;
- par classe : le canonique Numista **plus** jusqu'à N vrais crops validés,
  choisis pour la diversité d'apparence par *farthest-point sampling* avec
  plancher de validité ;
- overrides humains `manual_pin` / `manual_exclude` honorés ;
- traçabilité prévue dans `dino_class_references`.

Autrement dit : **la voie B n'est pas à inventer, elle est à brancher côté
scan.** Ce qui manque n'est pas le concept, c'est le pont vers l'APK.

Deux réserves étaient documentées dans [`../banque-dino/CONSTAT.md`](../banque-dino/CONSTAT.md).
**Les deux ont bougé le 2026-08-19 (soir)** — l'état antérieur est conservé
ci-dessous parce que le raisonnement garde sa valeur :

- ~~**130 pièces sur 658 n'ont aucune ancre**~~ — mesure de la matinée,
  **périmée le soir même**. Au build du 2026-08-19T00:28, 664 classes ont leur
  canonique et **7 seulement** n'en avaient pas ; les 7 ont été rapatriées par
  `referential.fetch_review_images --ids …` (`n_no_canonical` : 7 → 0). Le
  mécanisme décrit reste vrai : `_resolve_obverse_path` (`anchors.py:280`) exige
  le fichier sur disque, et une classe sans canonique est éliminée entièrement
  même avec quarante crops validés (`anchors.py:514`).
  **Le trou réel n'est plus le canonique, ce sont les exemplaires** : 125
  classes en portent, 182 pourraient en porter — et la cause de l'écart est
  trouvée (un `--db` codé en dur, cf. [`FINDINGS.md`](FINDINGS.md) §2.1).
- ~~**`dino_class_references` est vide dans les 8 bases locales et au
  canonique**~~ — **faux depuis le `--push` de la nuit du 18 au 19** :
  `SELECT COUNT(*) FROM dino_class_references` → **1250** (664 `canonical` +
  586 `fps`), `dino_anchor_builds` → **1**. Le bug est corrigé :
  `build_dino_anchors.py:65-130` porte désormais un `preflight_db_traceability()`
  qui **sonde réellement l'écriture** avant les quatre minutes d'encodage, et le
  chemin nominal sous Direction A est `--push` → `POST /ingest/dino-references`.
  La cause d'origine reste à connaître (`BEGIN IMMEDIATE` réussit sur une
  connexion read-only ; l'échec ne tombe qu'à la première vraie écriture).

### 2.3 Le fine-tuning n'a jamais gagné une mesure dans ce repo

Journal de [`../../model-efficiency/VISION.md`](../../model-efficiency/VISION.md),
2026-06-12 :

| Set | Frozen zero-shot | Fine-tuné `arcface-vits14-v1` |
|---|---|---|
| Gold BE, 94 listings, ancres canonical-only (**H4**) | vitl14 : **62,8 %** top-1 / 80,9 % hit@5 | **28,7 %** / 35,1 % |
| Held-out wild, 77 crops, classes riches en wild (**H1**) | vitl14 : **72,7 %** | **71,4 %** |

Au mieux le fine-tuné égalise, au pire il perd 34 points. Ce qu'il achète
réellement, c'est la **taille** : vits14 fine-tuné ≈ vitl14 gelé, soit 21 M
params au lieu de 300 M. C'est une distillation implicite, pas un gain de
qualité — et si c'est ça qu'on veut, il existe des moyens plus directs de
l'obtenir (les variantes DINOv3 sont déjà distillées d'un ViT-7B).

Et la phrase qui fonde tout le chantier, tirée de H1 : *« ce sont les refs wild
par classe qui font le modèle »*. Pas le volume d'entraînement. **Les
références.**

### 2.4 La comparaison d'encodeurs existe, sur 478 crops

C'est la page dont tu te souviens — `dino-suggestions/phase2-encoder-bench.md`,
juin 2026, banque `2eur_all`, 478 crops labellisés :

| Modèle | dim | global@1 | global@5 | pays@1 | pays@5 | ms/img |
|---|---:|---:|---:|---:|---:|---:|
| dinov2_vits14 | 384 | 55,1 % | 73,3 % | 74,9 % | 92,2 % | 28 |
| dinov2_vitl14 | 1024 | **77,2 %** | 87,9 % | **89,1 %** | 95,0 % | 116 |

Le jeu étiqueté a quadruplé depuis : **1 955 crops** avec vérité terrain.

> **Rejoué le 2026-08-20** sur 1958 crops et une banque à 1533 ancres :
> vitl14 **77,2 % → 91,6 %**, vits14 **55,1 % → 85,9 %**. ⚠️ **Ne pas lire ce
> delta comme un gain de banque** : le jeu d'évaluation *et* la banque ont
> changé en même temps (478 → 1958 crops, canonical-only → 182 classes à
> exemplaires). Deux variables, une mesure : l'attribution est impossible. C'est
> l'**étape 3** (courbe refs/classe) qui isolera le terme banque. Détail :
> [`BENCH-ENCODEURS.md`](BENCH-ENCODEURS.md) et H1/H4 de
> [`VISION.md`](../../model-efficiency/VISION.md).

Et le harnais qui a produit ce tableau, `ml/scripts/bench_encoder_dino.py`,
accepte déjà n'importe quel backbone `timm`. Vérifié aujourd'hui sur cette
machine :

```
$ ml/.venv/bin/python -c "import timm; print(timm.__version__,
    len(timm.list_models('*dinov3*', pretrained=True)))"
1.0.27 18
```

Les 18 variantes DINOv3 sont accessibles, poids compris, dont
`vit_small_patch16_dinov3.lvd1689m` et `convnext_tiny.dinov3_lvd1689m`.
**DINOv3 est testable sans écrire une ligne de modèle.**

---

## 3. La décision : deux voies, un seul juge

### D1 · La voie A (cohorte → bake → entraînement → promotion) continue

**Décidé** : rien n'est retiré, rien n'est déprécié, rien n'est gelé. Les
skills `eurio-cohort`, `eurio-run-local`, `eurio-promote` restent la
procédure en vigueur, et `prod/current` reste alimenté par elle.

**Pourquoi** : c'est la seule chaîne qui va aujourd'hui bout en bout jusqu'à un
APK qui reconnaît quelque chose (parcourue pour la première fois le
2026-08-16). Une voie qui marche mal bat une voie qui n'existe pas encore. Et
la voie B a besoin de la voie A pour une raison précise — cf. D4.

**Écarté** : « on arrête ArcFace, DINO gelé suffit ». Les chiffres du §2.3 sont
mesurés sur des sets étroits (77 et 94 listings) et sur la tâche **review**,
pas sur la tâche **scan**. On ne remplace pas une chaîne livrée sur cette base.

### D2 · La voie B est ouverte comme chantier de mesure, pas de livraison

**Décidé** : la voie B produit d'abord des **chiffres**, ensuite seulement un
artefact. Son livrable des étapes 1-3 est une décision documentée, pas un APK.

**Écarté** : brancher tout de suite une banque vitl14 dans l'APK pour voir. Le
vitl14 fait 116 ms/img sur desktop (§2.4) — la question de sa viabilité
on-device n'est pas ouverte, elle est fermée par la négative. La voie B doit
d'abord trouver *quel* encodeur, et ça n'est pas celui de la review.

### D3 · Les deux voies partagent la review, et rien d'autre

**Décidé** : la review (`training_eligible=1`) alimente les deux. Un crop
validé part en dataset d'entraînement pour A **et** devient candidat-ancre
pour B, sans double geste humain.

C'est déjà le cas dans le code : `_candidate_crops_for_class`
(`anchors.py:544`) filtre sur `training_eligible = 1 AND storage_status =
'present'` — la même condition que `iteration_augmentations.py:252`. Le
travail de review est **déjà** partagé ; personne ne l'avait remarqué.

**Écarté** : deux files de review, deux notions de validé. On paierait deux
fois le seul coût humain irréductible du projet.

### D4 · Le juge unique est le corpus de scan, et il est vide

**Décidé** : ce qui départage A et B n'est ni le val d'entraînement, ni les
crops eBay — c'est **le corpus de vraies captures device**.

Cette distinction est le piège central du chantier, alors elle est écrite noir
sur blanc :

| | Tâche **review** | Tâche **scan** |
|---|---|---|
| Entrée | photo **cadrée par un vendeur qui veut montrer la pièce** : statique, pièce entière, choisie parmi plusieurs (souvent floue, de loin, avec du reflet — la netteté n'est PAS le critère) | frame caméra **choisie par personne** : prise au vol dans le flux, en main, de biais, reflets |
| Vérité terrain dispo | **1 955 crops** (`review_queue.decided_eurio_id`) | 317 snaps `eval_real_norm`, ~17 classes |
| Sert à décider | l'auto-acceptation en review | **ce qui part dans l'APK** |

Les 1 955 crops labellisés mesurent la review. Ils ne disent **rien** de
garanti sur le scan. Et le corpus de scan, dont l'outillage a été livré (spec
`../scan-quality/corpus-spec.md`, store `ml/store/scan_corpus.py`, import et
replay scorecard/McNemar en commits `bd4888b` / `0a11294`), est aujourd'hui un
fichier de **0 octet** :

```
$ ls -la ml/state/scan_corpus.db
.rw-r--r--  0  19 Aug 00:53  ml/state/scan_corpus.db
```

**L'infrastructure existe, le corpus n'existe pas.** C'est le vrai blocage du
projet, et c'est aussi pourquoi la voie A garde sa valeur : c'est elle qui
produit les cohortes-test dont les captures alimentent ce corpus.

### ~~D5 · Une classe entre en banque avec **deux exemplaires ou zéro** — jamais un~~ — ❌ ANNULÉE

> Décidée le **2026-08-20** après la courbe de l'étape 3, **annulée le même jour
> au soir** après la mesure par classe. Le texte d'origine est conservé
> ci-dessous — c'est une croyance renversée par la mesure, elle vaut d'être
> lisible. Ce qui est en vigueur est écrit au bloc « **D5 est annulée** » en fin
> de section : `min_exemplars = 1`, plancher **inactif**, mécanisme conservé.

**Décidé** : le builder applique un **plancher** `min_exemplars` (défaut **2**).
Une classe qui ne peut pas l'atteindre garde son **canonique seul** ; elle
n'entre pas en banque avec un exemplaire unique.

**Pourquoi 2, et pas 3** : la courbe held-out donne **N=0 : 53,1 %** contre
**N=1 : 50,1 %** — le premier exemplaire *dégrade* — puis **N=2 : 54,6 %**, déjà
au-dessus du canonique seul. Un plancher à 3 renverrait les 27 classes à deux
exemplaires vers un régime moins bon qu'où elles sont.

**Où vit la valeur** : en base, table `dino_thresholds`, scopée par couple
(banque, encodeur) — migration **0011**. Ligne absente ⇒ le défaut du code, et
la provenance est **dite** (journal du build + `dino_anchor_builds.note`,
`min_exemplars=2 (source=code|db)`). ⚠️ Elle se **lit** sur la base pointée par
`--db`, donc la réplique sous Direction A, alors qu'elle s'**écrit** au
canonique : une valeur posée par le PO n'atteint le build qu'après un pull
(défaut S7, [`FINDINGS.md`](FINDINGS.md) §8.12).

**Cas limite tranché** : une classe **sans canonique** garde son unique
exemplaire — la rejeter la rendrait invisible (recall 0 garanti) au lieu de
seulement dégradée. Zéro classe dans ce cas aujourd'hui ; la règle est écrite
pour le jour où il s'en présentera une.

⚠️ **Ce que ce plancher ne prouve pas.** Le mécanisme invoqué — le FPS retient
d'abord le crop le plus diversifiant, donc le plus atypique, qui agit seul en
faux attracteur — reste **inféré, non prouvé par classe**. Le plancher corrige
un effet mesuré, pas une cause démontrée. Et **l'effet du prochain rebuild ne se
prédit pas** depuis un compte de pool : ce qui décide est la sortie du FPS, donc
l'encodage (défaut S5). Le chiffre qui fera foi est celui que le build écrira
dans sa note.

#### 🔴 D5 a été appliquée, mesurée — et elle DÉGRADE (2026-08-20, soir)

Le build `365dcab2a253` du `2026-08-20T14:27:56+00:00` a posé le plancher sur
les vraies données. Sa note : `min_exemplars=2 (source=code); 68 classes
ramenées au canonique seul; 0 sans canonique gardées sous le plancher`. La
banque passe de **1533 ancres / 182 classes à exemplaires** à **1495 / 124**.
P3 a été refait contre elle (12 454 prédictions, 0 périmée).

| held-out, N=10 (= la banque servie) | avant | après | delta |
|---|---:|---:|---:|
| `dinov2_vits14` | 75,5 % | **74,1 %** | **−1,4** |
| `dinov2_vitl14` | 85,7 % | **84,8 %** | **−0,9** |

Contrôle qui valide la comparaison : à **N=0** les deux banques sont identiques
(671 canoniques) et rendent le même score à 0,1 pt près (53,1 → 53,2 ;
76,1 → 76,2).

**La faute de raisonnement, nommée** : la courbe mesure N=1 à 50,1 % contre N=0
à 53,1 %, mais ce point signifie *« toutes les classes plafonnées à 1 »*, **pas**
*« 68 classes en ont 1, les autres sont pleines »*. **On a extrapolé d'un
agrégat à une règle par classe.** C'est le vice, et il n'est pas dans la mesure.

**Ce que ce delta seul permettait de dire** : ni annuler, ni confirmer. Les
réserves interdisaient les deux — la banque a changé autrement que par le
plancher (FPS rejoué sur un pool qui avait bougé, 10 classes ont gagné des
exemplaires, crops fuités 858 → 779), et à **N=2 la nouvelle banque est
meilleure** (55,9 % contre 54,6 %) avec moins de lignes. Le geste qui tranchait
était **une mesure par classe**, pas un basculement de drapeau.

#### ❌ D5 est ANNULÉE — la mesure par classe a été faite (2026-08-20, soir)

Le geste réclamé au paragraphe précédent a été posé, **sans rebuild**, en
restreignant la courbe (`bench_refs_curve.py` a reçu `--bank-classes`,
`--gold-classes`, `--rank-order`, et une comparaison appariée par palier —
McNemar exact via `shared/stats/paired.py`).

**Premier résultat, et il conditionne tout le reste** : la population que D5
visait ne peut **pas** être évaluée. Les classes sans exemplaire mais à pool
éligible non vide totalisent **77 crops** dans le gold, dont **61 sont
exactement le crop qui deviendrait leur ancre** — il reste **16 crops held-out
pour ~70 classes**. Une classe à un seul crop éligible met ce crop en banque et
n'a plus rien sur quoi être notée.

**Deuxième résultat, sur le proxy le plus proche** — les 57 classes riches
plafonnées à 1, le reste de la banque intact, 1073 crops :

| | N=0 | N=1 | N=2 |
|---|---:|---:|---:|
| `dinov2_vitl14` | 67,6 % | **69,1 %** (p=0,048) | 72,0 % (p=3,9e-07) |
| `dinov2_vits14` | 41,6 % | **45,5 %** (p=4,5e-10) | 52,4 % (p=1,2e-25) |

**Un exemplaire unique améliore sa classe.** La prémisse de D5 est fausse dans
le sens où elle était affirmée.

**Troisième résultat : le creux à N=1 n'est pas un effet du nombre, mais de
l'ORDRE du FPS.** Rejoué sur la banque courante, il n'est même pas significatif
en `vits14` (53,2 → 52,1 %, **p=0,279**) ; il l'est en `vitl14` (76,2 → 73,8 %,
p=0,0056). Mais à **nombre d'ancres strictement identique** (795 lignes, un
exemplaire par classe), `--rank-order last` — garder le rang le *moins*
diversifiant — rend **77,8 %** au lieu de 73,8 %, soit **au-dessus** du canonique
seul. Le mécanisme « le rang 1 du FPS est un faux attracteur parce qu'il est
atypique », jusqu'ici inféré, est **mesuré**.

**Ce qui est décidé** : `min_exemplars` revient à **1** — plancher **inactif** —
pour les deux couples, dans `ml/shared/dino_threshold_defaults.py`. Le mécanisme
reste entier (résolution en base, clamp, WARNING fractionnaire, note de build
qui dit ACTIF/INACTIF) et couvert par 14 tests : **reposer 2 se fait en une
ligne dans `dino_thresholds`**, sans toucher au code. La migration **0011**
garde donc tout son sens.

⚠️ **Trois réserves à porter avec cette annulation.**
1. La mesure décisive est un **proxy**. L'argument qu'il est *conservateur* — le
   rang 1 d'une classe riche est choisi dans un pool de dix, donc plus atypique
   que l'unique crop d'une classe pauvre — est un raisonnement sur le code du
   FPS, pas une mesure.
2. `--rank-order last` **ne correspond à aucun build possible** : c'est une
   sonde. Elle prouve que le creux dépend de la sélection ; elle ne dit pas
   qu'un builder amorçant au médoïde rendrait 77,8 %. Cette étape n'est pas
   faite, et c'est le vrai levier (geste 5 de la note d'état).
3. Tout ceci est la tâche **review** (photos de vendeurs eBay). Le corpus de
   scan est vide.

⚠️ **Décalage à connaître avant tout rebuild** : la banque **servie** porte
encore le plancher (68 classes au canonique seul, colonne « 1 » vide) ; le code
ne l'applique plus. Le prochain rebuild **changera la forme de la banque**, et
le garde **P1 ne le signalera pas** — il compte les classes à ≥ 2 exemplaires,
compte que ce retour laisse invariant. Le découplage est délibéré ; l'inversion
sera donc silencieuse.

### D6 · Le goulot du chantier n'est plus le tri, c'est l'**approvisionnement**

> Décidé le **2026-08-20**, après l'allocateur de scrape.

**Constaté, pas supposé.** *(Chiffres du 2026-08-20 matin, avant le plancher.
Depuis le rebuild de 14:27, c'est **547 classes au canonique seul dont 331 sans
aucun crop en file ouverte** — mesuré à 17:14 UTC. Le constat ne s'est pas
adouci.)* Sur les 489 classes au canonique seul, **~305 n'ont
aucun crop en file ouverte** : pour elles, valider mieux ne change rien — il n'y
a rien à valider. Et sur les 357 classes à zéro exemplaire *et* zéro candidat,
**350 appartiennent à un groupe de découverte jamais interrogé sur eBay** ; sept
seulement ont vu leur groupe cherché sans rien récolter. Le catalogue vide n'est
pas un problème de marché, c'est un problème de **couverture**.

**Décidé** : l'allocation du quota eBay (5000 appels/jour) devient un geste
**mesuré et ordonné**, pas une impulsion. La maille n'est pas la classe mais le
**groupe de découverte** (671 classes → 416 groupes, ~380 à déficit) : une
décision sert plusieurs classes pour un coût constant. Outil :
`go-task ml:ebay:allocate` (dry-run par défaut), spec
[`ALLOCATEUR-SCRAPE.md`](ALLOCATEUR-SCRAPE.md).

**L'ordre de grandeur qui cadre l'année** : amener les 671 classes à 8
exemplaires coûte **~47 800 appels, soit ~10 jours de quota** — un jour plein
traite 20 % du déficit. Le problème n'est pas d'arbitrer entre deux classes,
c'est d'**ordonner dix jours**.

**Ce que ça ne résout pas** : le rendement d'un groupe varie d'un facteur 20 (de
7 à 149 exemplaires gagnés selon le run), et **la review reste un goulot plus
étroit que le quota** — 6 800 items attendent déjà en file. Scraper plus sans
reviewer plus ne remplit pas la banque. L'allocateur soustrait donc ce qui
attend déjà en review avant de payer un groupe.

---

## 4. Le plan — quatre étapes

> Chaque étape a un critère de sortie chiffré. Aucune ne commence avant que la
> précédente l'ait atteint. L'étape 4 est **conditionnelle**.

### Étape 1 · Remplir le corpus de scan

**But** : disposer d'un jeu figé de vraies captures device sur lequel deux
modèles se comparent honnêtement. Sans lui, tout le reste est de l'opinion.

**Ce qui existe** : le store, le schéma (`capture_id` = sha256 des octets
bruts, `eurio_id`, `condition` dans un vocabulaire ouvert incluant `glare` et
`inhand`), le versioning append-only (`corpus_version()`), l'import depuis les
bundles cohort-test, le replay avec scorecard et McNemar apparié.

**Ce qu'il faut faire** : capturer. C'est du travail de saisie, pas de code.
Via le SNAP cohort-test, qui archive déjà les frames.

> **2026-08-19 — le plan est livré, les photos non.**
> [`PROTOCOLE-CAPTURE.md`](PROTOCOLE-CAPTURE.md) + `plan-capture-scan.csv` :
> 80 classes possédées × 5 conditions = 400 cellules / 985 captures / 11
> sessions, régénérables par `go-task ml:scan-corpus:prescribe`. Le critère de
> sortie ci-dessous est dépassé avec marge (985/80/5). 🔴 Piège bloquant :
> `build_cohort_bundle.py` échantillonne **silencieusement** à 3 pièces au-delà
> de 30 — sans `NO_SAMPLE=1`, la campagne photographierait 3 classes sur 80.

**Critère de sortie** : ≥ 500 captures, ≥ 50 classes distinctes, chaque classe
vue sous ≥ 3 conditions, dont `glare` et `inhand` représentées. Corpus figé et
versionné.

**Écarté** : se contenter des 317 snaps `eval_real_norm`. Ils couvrent ~17
classes, exactement celles où le modèle actuel est bon — le biais de sélection
y est maximal.

**Ce que ça n'inclut pas** : aucune décision de modèle. C'est une étape de
donnée.

---

### Étape 2 · Comparer les encodeurs gelés, sur nos deux tâches — 🟢 **faite pour la review** (2026-08-20), 🟠 en attente pour le scan

> ## Conclusion de l'étape 2, volet review — écrite le 2026-08-20
>
> Run `20260820T011143Z`, gold figé `0ecbb1d70e3c`, **1958 crops, 0 crop non
> encodé**, banque `2eur_all` à 1533 ancres. Rapport complet :
> [`BENCH-ENCODEURS.md`](BENCH-ENCODEURS.md).
>
> | Modèle | M params | dim | global@1 | global@5 | pays@1 | ms/img |
> |---|---:|---:|---:|---:|---:|---:|
> | `dinov2_vitl14` *(sert la review)* | 304,4 | 1024 | **91,6 %** | 97,9 % | **97,4 %** | 122 |
> | `dinov2_vits14` | 22,1 | 384 | **85,9 %** | 97,2 % | 96,0 % | **16** |
> | `timm:convnext_tiny.dinov3_lvd1689m` | 27,8 | 768 | 81,5 % | 91,8 % | 90,4 % | 16 |
> | `timm:vit_small_patch16_dinov3.lvd1689m` | 21,6 | 384 | **78,7 %** | 91,7 % | 89,9 % | 22 |
>
> McNemar apparié contre `dinov2_vitl14` : vits14 `b=163 c=50 p=3,6e-15` ;
> dinov3 vits16 `b=286 c=32 p=3,8e-52` ; dinov3 convnext-t `b=237 c=39
> p=9,0e-36`.
>
> **🔴 DINOv3 est réfuté sur notre tâche.** À taille égale (21,6 M vs 22,1 M) il
> fait **7,2 points de moins** que DINOv2 ViT-S/14. Le §« Écarté » ci-dessous
> avait raison de refuser de décider sur les benchmarks publics : le signe est
> **inversé**, pas seulement atténué. Hypothèse **H12** de
> [`VISION.md`](../../model-efficiency/VISION.md), marquée réfutée.
>
> **Décision d'encodeur, motivée** :
> - **la review garde `dinov2_vitl14`** — 91,6 %, et les 122 ms/img sont payés
>   côté serveur, pas dans la main de l'utilisateur ;
> - **le candidat léger à instruire est `dinov2_vits14`**, pas un DINOv3 :
>   85,9 % pour 16 ms/img et 22,1 M params. Il perd 5,7 pts contre vitl14 pour
>   **7,6× moins de latence CPU** et 14× moins de paramètres ;
> - **aucun DINOv3 n'est retenu** à ce stade, ni pour la review ni comme
>   candidat APK par défaut — cela **annule** la préférence exprimée au §4a et à
>   [ADR-008](../../adr/008-deux-voies-backbone-gele-et-arcface.md), qui reposait
>   sur les seules latences.
>
> **Trois réserves, non négociables** — détaillées dans
> [`BENCH-ENCODEURS.md`](BENCH-ENCODEURS.md) :
> 1. **c'est la tâche review, pas la tâche scan** (corpus : 0 capture
>    versionnée, 2 264 images device non protégées — cf.
>    [`DURABILITE-CORPUS.md`](../scan-quality/DURABILITE-CORPUS.md)) — le
>    critère de sortie « 4 encodeurs × **2 jeux** » n'est donc **pas** atteint ;
>    la seconde colonne manque et manquera tant que P5 n'est pas fait ;
> 2. les bloqueurs imprimés dans le corps généré ont été lus sur une réplique
>    **périmée** ; sur la réplique fraîche, `dinov2-vitl14` rend **0 bloqueur** ;
> 3. la banque a été **sélectionnée par FPS dans l'espace de `dinov2-vitl14`** —
>    un DINOv3 avec sa propre banque n'a pas été mesuré (**H13**), et le rebuild
>    d'une banque candidate reste **interdit** tant que **Q6** est ouvert.
>
> **Ce qui reste à faire pour clore l'étape 2** : rejouer les quatre bras sur le
> corpus de scan, une fois P5 rempli. Si le classement diverge entre les deux
> jeux, c'est l'information la plus précieuse du chantier.

**But** : savoir lequel de DINOv2 vits14 / vitl14, DINOv3 ViT-S/16, DINOv3
ConvNeXt-Tiny sert le mieux, **à backbone gelé**, sans rien entraîner.

**Ce qui existe** : `bench_encoder_dino.py` fait 90 % du travail — ré-encode la
banque **et** les crops étiquetés avec chaque modèle, mesure recall@1/@5 global
et bande pays avec la logique de prod, n'écrit rien. Les 18 DINOv3 sont
accessibles par `timm:<model>` (vérifié §2.4).

**Ce qu'il faut écrire** — les quatre manques listés dans
[`PROTOCOLE-BENCH.md`](../banque-dino/PROTOCOLE-BENCH.md). ✅ **Les quatre sont
comblés depuis le 2026-08-19**, ainsi que les deux blocages structurels **et le
câblage** : `bench_encoder_dino.py` ne rejoue plus sa requête de sélection (elle
est supprimée), lit le gold figé, et pousse run + prédictions par
`POST /ingest/encoder-bench`. Ce qui reste n'est plus du code manquant mais de la
**dette nommée** — registre daté défaut par défaut :
[`FINDINGS.md`](FINDINGS.md) §7 et §8. Deux points bloquent encore un chiffre
publiable : **D1** (le bloqueur P1 ne filtre pas l'encodeur) et **N1** (les crops
non encodés sont invisibles). Et le câblage est prouvé, **pas les chiffres** :
aucun run réel n'a tourné.

1. un **set figé** (le banc reconstruit son jeu par SQL sur une table vivante :
   deux runs à deux semaines d'écart ne sont pas comparables) ;
2. un **test apparié** — `mcnemar_exact` existe dans `replay_corpus.py`, à
   extraire ;
3. un **balayage de seuils par encodeur** : chaque encodeur a sa propre échelle
   de spread, comparer à seuils gelés mesure « qui gagne avec les seuils de
   l'autre » ;
4. une table `encoder_bench_runs` + `encoder_bench_predictions`.

Plus deux blocages structurels à lever avant tout A/B : `anchor_path(kind)`
(`anchors.py:130`) ne met pas l'encodeur dans le nom du `.npz` — deux encodeurs
**s'écrasent** ; et `_get_bank`
(`ml/sources/_base/steps/auto_validate.py:130`) rend invisible une banque dont l'encodeur ne correspond pas au mapping.

**L'ajout propre à ce chantier** : faire tourner le banc sur **les deux jeux**
— les 1 955 crops review *et* le corpus de scan de l'étape 1. Deux colonnes de
résultats. Si le classement diverge entre les deux, c'est l'information la plus
précieuse que ce chantier produira, et il faut qu'elle soit visible.

**Critère de sortie** : un tableau à 4 encodeurs × 2 jeux, avec p-value de
McNemar contre le champion courant (vitl14), le spread atteignant 97 % de
précision par encodeur, et le ms/img. Décision d'encodeur écrite et motivée.

**Écarté** : décider sur les benchmarks publics. DINOv3 annonce +10,8 pts sur
Met et +7,6 sur AmsterTime en recherche d'instance (arXiv 2508.10104), et
ViT-S/16 mAP 0,406 contre 0,327 pour DINOv2 ViT-S/14. Met — œuvres de musée,
peu de références par classe, discrimination par détail fin — ressemble
beaucoup à notre problème. **Ça reste une raison de tester, pas une preuve.**
Distinguer deux faces nationales de 2 € est du quasi-duplicata fin ; seuls nos
crops tranchent.

> ✅ **Vérifié le 2026-08-20, et c'est le point à retenir de tout ce doc.** Nos
> crops ont tranché **contre** le benchmark public : `vit_small_patch16_dinov3`
> rend **78,7 %** contre **85,9 %** pour `dinov2_vits14`, alors que le public
> annonçait +24 % relatif en faveur du premier. Le prix de la prudence a été
> **un run de banc** ; le prix de la croyance aurait été un export TFLite, un
> rebuild de banque et un APK. Cette ligne « Écarté » a payé — la garder.

**La licence : levée le 2026-08-19.** Redistribution **permise**, y compris
commerciale, sous trois conditions (§1.b.i) : distribuer sous le même accord,
joindre une copie de l'accord, et **afficher « Built with DINOv3 »**. La
quantification TFLite ne lave pas la licence (le §1.b.i vise « any derivative
works thereof »). ⚠️ La clause de branding figure sur `ai.meta.com` et **pas**
dans le `LICENSE.md` de GitHub — on se conforme à la plus stricte.

🔴 **Correction** : les variantes « EUPE » ne sont **pas** des variantes de
DINOv3. C'est une famille séparée (Meta Reality Labs + FAIR) sous FAIR
Noncommercial Research License. Les vraies variantes sont `lvd1689m` et
`sat493m`, **toutes deux sous la même licence DINOv3**. Détail :
[`FINDINGS.md`](FINDINGS.md) §3 et [ADR-008](../../adr/008-deux-voies-backbone-gele-et-arcface.md).

---

### Étape 3 · Mesurer la courbe qui pilote l'année — 🟢 **faite pour la review** (2026-08-20), 🟠 en attente pour le scan

> **Résultat, en trois lignes.** Rapport complet et toutes les tables :
> [`COURBE-REFERENCES.md`](COURBE-REFERENCES.md). **Ce que la courbe a changé
> dans le plan**, décidé le 2026-08-20 : le plancher `min_exemplars` (**D5**,
> depuis **annulé** le soir même) et l'allocateur de scrape (**D6**) ci-dessus. L'étape 3 est **faite pour la
> review** ; l'étape 4 approche, et ce qui la retarde n'est plus une mesure
> manquante mais **l'approvisionnement en crops**.
>
> 1. **Viser 8 crops validés par classe, ne jamais s'arrêter à 1.** En
>    `dinov2_vits14` held-out, N=8 rend **73,9 %** top-1 / 94,3 % top-5 contre
>    53,1 % / 75,5 % au canonique seul. Le rendement passe de ~2,5 pt/réf sur le
>    segment 3 → 8 à ~0,8 au-delà : « 8 » est un **arbitrage coût/bénéfice**, pas
>    un plateau mesuré (voir l'encadré ci-dessous).
> 2. **La première référence FAIT BAISSER la précision** : −3,0 pts en vits14
>    (53,1 → 50,1), −3,6 en vitl14 (76,1 → 72,5), sur les deux populations. En
>    encodeur de production il faut **N=5** pour repasser au-dessus du canonique
>    seul (N=3 rend exactement le chiffre de N=0 : 76,09 % dans les deux cas).
> 3. **La forme de la courbe ne dépend pas de l'encodeur** — creux, remontée,
>    écrasement du rendement au même endroit, décalage de niveau constant. Donc
>    **le budget de review se décide avant le choix d'encodeur**, qui reste
>    ouvert.
>
> **Corollaire opérationnel — le budget, mesuré.** Un crop validé donne une
> référence à **96-97 %** (le plancher `floor_sim=0.45` ne coupe presque rien).
> Sur les 671 classes de banque, dont **489 (73 %) sont aujourd'hui à zéro
> exemplaire** :
>
> | Cible | crops à valider | repère |
> |---|---:|---|
> | N = 3 | **1 622** | ≈ tout ce qui a été reviewé depuis le début |
> | N = 5 | **2 805** | |
> | **N = 8** | **4 622** | **2,4×** les 1 958 crops décidés à ce jour |
> | N = 10 | 5 848 | |
>
> Priorité qui découle de la courbe : (1) sortir les 489 classes du régime
> « canonique seul » en les amenant à 3 — le seul palier qui évite la régression
> de N=1 ; (2) monter l'ensemble de 3 à 8 ; (3) le reste ensuite.
>
> ⚠️ **Deux réserves, à ne pas perdre.** (a) **Ce sont les chiffres de la tâche
> REVIEW** — photos cadrées par un vendeur qui veut montrer la pièce (souvent
> floues ou de loin, mais statiques, entières, **choisies**). La courbe du
> **scan** (frame caméra en main, choisie par personne) n'est **pas mesurée** :
> 0 capture versionnée, 2 264 images device non protégées.
> (b) **Il n'y a pas de plateau mesuré** : le « coude à N=8 » de la première
> rédaction est un artefact du maillage des paliers — au maillage fin 4..10 le
> même détecteur ne trouve plus de coude, et l'analyse appariée montre que
> 8 → 10 rapporte encore **+1,55 pt** (34 gagnés / 17 perdus, McNemar `z=2,38`,
> `p≈0,017`). « Ne pas dépasser 10 » n'est appuyé par aucune mesure ; au-delà de
> 10 rien n'a été mesuré du tout (plafond `exemplars_per_class` du build).
>
> **Comment ça a été mesuré sans rebâtir la banque** : les rangs FPS de
> `dino_class_references` s'apparient exactement aux lignes du `.npz` servi
> (862/862, 0 écart dans chaque sens ; `selected_sim` monotone croissant avec le
> rang, 680 paires, 0 violation) — donc un préfixe par rang équivaut à un build
> `exemplars_per_class=N`, et on sous-échantillonne la matrice **en mémoire**.
> Outil : `ml/scripts/bench_refs_curve.py` (`go-task ml:refs-curve:run`).
> Harnais validé : en population fuitée à N=10 il reproduit le banc officiel au
> dixième de point.

**But** : répondre à « combien de références wild par classe faut-il ? ». C'est
le chiffre qui dimensionne le budget de review, donc la trajectoire du projet.

**Comment** : avec l'encodeur retenu à l'étape 2, gelé, rejouer le corpus de
scan en faisant varier le nombre de références par classe dans la banque :
1, 3, 5, 10, 20, 30. Le sélecteur existe déjà (`exemplars_per_class`,
`farthest_point_select` dans `anchors.py`).

**Critère de sortie** : une courbe précision/couverture par palier, et le
**seuil de rendement décroissant** identifié. Plus le corollaire opérationnel :
combien de crops à valider pour amener une classe pauvre au niveau utile.

**Pourquoi c'est ici et pas ailleurs** : H1 est confirmée mais sur une seule
itération et des classes déjà riches en wild. La courbe est ce qui la
transforme en règle de conduite. Et c'est cette étape, pas l'étape 2, qui dira
si la voie B tient sa promesse — parce que si la courbe est plate, aucun
encodeur ne sauvera la banque.

**Écarté** : mesurer ça sur les crops eBay. Le nombre de références utiles pour
matcher une photo de vendeur n'est pas le même que pour matcher une frame en
main sous reflet.

> ⚠️ **Cet « écarté » a été enfreint, sciemment, et il faut le lire comme tel.**
> La mesure du 2026-08-20 est faite **sur les crops eBay**, parce que le corpus
> de scan est vide et que le choix était entre un chiffre imparfait maintenant
> et aucun chiffre avant des semaines. Ce qu'on en tire — l'ordre de grandeur du
> budget, la régression à N=1, l'indépendance à l'encodeur — dimensionne la
> **review**, ce qui est légitime. Ce qu'on n'en tire pas : un critère de
> promouvabilité pour le scan. **L'étape 3 reste à rejouer sur le corpus de
> scan** dès qu'il existe ; c'est le même script, la même courbe, une autre
> population.

---

### Étape 4 · Descendre on-device — et seulement là, la tête de projection

**But** : un APK qui reconnaît les classes couvertes par la banque, sans
entraînement dans la boucle d'ajout.

**Trois sous-chantiers, dans cet ordre** :

**4a — Export du backbone.** ~~ConvNeXt-Tiny d'abord, ViT-S/16 ensuite.~~
~~Ordre inversé le 2026-08-19 : ViT-S/16 (DINOv3) d'abord.~~
**Les deux candidats DINOv3 sont écartés le 2026-08-20 : c'est `dinov2_vits14`
qu'on exporte.**

> **Pourquoi le raisonnement précédent tombe, alors qu'il était juste.** Les
> deux ordres successifs — « ConvNeXt d'abord » (les ops ViT passent mal NNAPI),
> puis « ViT-S/16 d'abord » (292,8 ms contre 24,5 ms en CPU bs1) — étaient des
> arbitrages **de latence entre deux DINOv3**. Ils supposaient sans le dire que
> la **qualité** de DINOv3 était acquise, sur la foi des benchmarks publics.
> Le banc du 2026-08-20 tue cette prémisse : à 21,6 M params, DINOv3 ViT-S/16
> fait **78,7 %** top-1 contre **85,9 %** pour DINOv2 ViT-S/14 à 22,1 M. On ne
> choisissait pas le bon vainqueur parce qu'on ne comparait pas les bons
> concurrents.
>
> | Candidat APK | top-1 review | M params | dim | ms/img **au banc** | CPU bs1 Mac, 19/08 |
> |---|---:|---:|---:|---:|---:|
> | **`dinov2_vits14`** ✅ | **85,9 %** | 22,1 | 384 | 16 | non mesuré |
> | DINOv3 ViT-S/16 ❌ | 78,7 % | 21,6 | 384 | 22 | 24,5 ms |
> | DINOv3 ConvNeXt-T ❌ | 81,5 % | 27,8 | 768 | 16 | **292,8 ms** |
>
> ⚠️ **Les deux colonnes de temps ne se comparent pas** : le `ms/img` du banc
> est un débit d'encodage en lot sur la machine du run, pas une latence CPU
> batch 1 — ConvNeXt-T y sort à 16 ms alors qu'il met 292,8 ms en CPU bs1. Seule
> la colonne de droite parle du régime du scan Android, et elle-même n'est
> qu'un proxy (H11 : PyTorch/Mac ≠ TFLite/NNAPI). **`dinov2_vits14` n'a pas été
> mesuré en CPU bs1** — à faire avant de figer 4a.
>
> Bénéfice de bord : `dinov2_vits14` est sous **Apache 2.0** (⚠️ à reconfirmer
> sur la carte du modèle avant le Play Store), donc les trois obligations DINOv3
> (redistribution sous le même accord, copie de l'accord, « Built with DINOv3 »)
> **tombent** — cf. §Conséquences d'[ADR-008](../../adr/008-deux-voies-backbone-gele-et-arcface.md).
> Le travail de licence du 2026-08-19 n'est pas perdu : il reste valable le jour
> où un DINOv3 reviendrait, avec sa propre banque (H13).
>
> ⚠️ **Ce qui n'est PAS tranché** : le classement est mesuré sur la tâche
> **review**. Il ne devient une décision d'APK qu'après le corpus de scan (D4).
> Et ConvNeXt-T garde le droit d'être rebenché en TFLite avant d'être écarté
> pour de bon — mais il devrait désormais rattraper **4,4 points de qualité**,
> pas seulement une latence.

Le raisonnement de latence entre DINOv3, conservé pour mémoire :

L'argument initial reste valable en théorie — les ops ViT (attention, layernorm
dynamique) passent mal les délégués GPU/NNAPI de LiteRT, alors qu'un ConvNeXt
s'exporte et se quantifie sans surprise. Mais une mesure le contredit sur le
régime qui compte. Mac, torch 2.9.1, 8 threads, **CPU batch 1** — le régime du
scan Android :

| | CPU bs1 | MPS bs1 |
|---|---:|---:|
| dinov3 ViT-S/16 (21,6 M) | **24,5 ms** | 15,0 ms |
| dinov3 ConvNeXt-T (27,8 M) | **292,8 ms** | **9,5 ms** |

Le 292,8 ms est reproduit machine libre (292,6 ms, 286,0 en `channels_last`).
⚠️ **estimation** pour le transfert : ces mesures sont PyTorch/Mac, pas
TFLite/Android — le noyau NNAPI n'a rien à voir. ConvNeXt garde donc le droit
d'être rebenché en TFLite avant d'être écarté, et il reste **le meilleur
candidat pour bâtir la banque côté Mac** (le plus rapide en MPS). ~~Mais le
candidat APK par défaut est désormais le ViT-S/16.~~ *(caduc le 2026-08-20 : le
candidat par défaut est `dinov2_vits14`, cf. l'encadré ci-dessus.)*
`export_tflite.py` et `spike_vits14_litert.py` existent pour trancher.

Budget APK, calculé :

| | poids int8 | banque 546 classes × 8 refs, fp16 |
|---|---:|---:|
| **DINOv2 ViT-S/14 (22,1 M, dim 384)** — retenu 2026-08-20 | ~22,1 Mo | **3,2 Mo** (`546 × 8 × 384 × 2 o` = 3,35 Mo) |
| DINOv3 ViT-S/16 (21,6 M, dim 384) | ~21,6 Mo | **3,2 Mo** |
| DINOv3 ConvNeXt-Tiny (27,8 M, dim 768) | ~27,8 Mo | **6,4 Mo** |
| _(référence)_ DINOv2 ViT-L/14 (dim 1024) | — | 8,5 Mo |

À comparer à l'existant : 4,4 Mo d'embedder + 10 Mo de détecteur + ~25 Mo
d'OpenCV. Le net est de l'ordre de **+20 Mo**. C'est un coût, pas un obstacle.

**4b — Format de banque multi-exemplaires.** L'APK lit aujourd'hui
`coin_embeddings.json` : **23 entrées, un centroïde de 256 dim par classe**
(vérifié). Passer à N références par classe est un changement de format —
binaire fp16 plutôt que JSON — et `EmbeddingMatcher.kt` doit agréger plusieurs
vecteurs par classe (max des cosinus, pas moyenne : c'est tout l'intérêt de la
diversité d'apparence sélectionnée par FPS).

**4c — La tête de projection, si et seulement si.** Elle ne se déclenche que
si l'étape 3 montre un plafond que les références seules ne franchissent pas.
Elle s'entraîne sur les vecteurs **déjà encodés** (donc minutes CPU, cf. §1),
et elle se livre comme un second petit fichier appliqué après le backbone —
lequel reste gelé et générique.

> **Ce que la courbe du 2026-08-20 dit de cette condition — et ce qu'elle ne
> dit pas.** La condition de déclenchement est « un plafond que les références
> seules ne franchissent pas ». **Aucun plafond n'a été observé** : jusqu'à
> N=10, chaque palier rapporte encore, et le dernier segment mesuré (8 → 10)
> gagne +1,55 pt de façon significative. **4c reste donc non déclenchée, mais
> pour une raison faible** : on n'a pas mesuré au-delà de 10 (plafond
> `exemplars_per_class` du build), donc on n'a pas cherché le plafond, on ne
> l'a simplement pas rencontré.
>
> **Ce que la courbe éclaire en revanche, et qui vise 4c directement** : à
> **nombre de références égal**, l'écart entre le petit encodeur et celui de
> production ne se referme pas. À N=10 held-out, `vits14` rend 75,5 % top-1
> contre 85,7 % pour `vitl14` — **10,2 points**, contre 5,7 points seulement en
> régime fuité, donc l'écart réel est **plus grand** que ne le laissait croire le
> banc. Les références rachètent beaucoup (73,9 % à N=8 pour `vits14`, contre
> 72,5 % pour `vitl14` à N=1), mais elles **ne rachètent pas tout**. C'est
> exactement le trou qu'une tête de projection entraînée sur les vecteurs déjà
> encodés est censée combler, et c'est aujourd'hui le meilleur argument en sa
> faveur — **pas une décision** : le juge reste le corpus de scan (D4).
>
> **Un fait de la courbe qui change 4b, lui, tout de suite** : la première
> référence FAIT BAISSER la précision (−3,0 pts en `vits14`, −3,6 en `vitl14`).
> L'agrégation embarquée doit donc être testée sur ce cas — une classe à une
> seule référence wild est aujourd'hui **pire** que la même classe au canonique
> seul. Tant que ce n'est pas compris, la règle de peuplement de la banque APK
> est : zéro exemplaire, ou trois et plus. Jamais un.

**Critère de sortie** : sur le corpus de scan, la voie B égale ou dépasse la
voie A. C'est là que D4 se tranche.

---

## 5. Ce que ça coûte, et ce que ça ne résout pas

**Ce que la voie B ne résout pas** : le besoin de **références wild par
classe**. Aucun encodeur ne le supprime. Le travail de review reste le travail.
Ce que la voie B change, c'est que ce travail devient **immédiatement**
rentable au lieu de rentable-au-prochain-réentraînement.

**Trois choses qui manquent encore, quelle que soit la voie** :

- **La rotation.** `augmentations/recipes.py` la traite en augmentation ; les
  features DINO ne sont pas équivariantes en rotation et une pièce est
  photographiée à angle arbitraire. Alternatives moins coûteuses :
  canonicalisation (déroulé log-polaire, alignement sur l'axe du millésime) ou
  TTA à 4-8 rotations avec max des similarités. Non chiffré ici.
- **L'abstention.** Avec 546 classes proches, la métrique utile n'est pas le
  top-1 mais la précision à couverture donnée. Le palier `spread ≥ 0,10` →
  97,1 % mesuré en review ([`../banque-dino/CONSTAT.md`](../banque-dino/CONSTAT.md))
  est le patron à transposer au scan. Et hit@5 à 87,9 % dit qu'un carrousel
  « c'est laquelle ? » résout la plupart des cas **sans réseau**.
- **Le canal texte.** Le theme-matcher texte fait 69,7 % d'auto-attribution à
  94,5 % de précision (2026-06-12) — meilleur que toute notre vision. Un OCR
  on-device sur le crop normalisé donnerait un canal indépendant à fusionner
  (pays, millésime, légende). Hors périmètre de ce doc, mais c'est la suite
  naturelle de l'étape 4.

**Ce qui rendrait ce doc caduc** : si l'étape 2 montre que tous les encodeurs
gelés plafonnent bas sur le corpus de scan pendant que la voie A monte, la
voie B se ferme et on l'écrit ici. C'est le résultat que le chantier doit
pouvoir produire — et il faudra alors une ADR qui supersède
[ADR-008](../../adr/008-deux-voies-backbone-gele-et-arcface.md), pas une
réécriture.

**Le coût administratif de la voie B, chiffré depuis le 2026-08-19** : si
l'encodeur retenu est un DINOv3, l'APK doit embarquer le texte de la licence et
afficher « Built with DINOv3 ». Deux mentions, à payer avant le Play Store, et
un avis juridique souhaitable sur l'écart entre les deux versions publiées de
la licence.

---

## 6. Ce qui reste ouvert

- **Le mode de fusion des N références par classe** — max des cosinus, moyenne
  des top-k, ou vote. ⚠️ **Toujours ouvert après l'étape 3** : la courbe a été
  mesurée avec la fusion en vigueur (`top_k_match`, importé du banc), elle n'a
  pas comparé les modes. Le creux à N=1 est précisément le genre d'effet qu'un
  autre mode de fusion pourrait absorber — c'est la première expérience à
  faire.
- **Le creux à N=1 est expliqué, pas démontré.** L'hypothèse : le rang 1 du FPS
  est le crop le plus atypique, donc un faux attracteur tant qu'aucun frère ne
  délimite le nuage de sa classe. La sonde qui trancherait est cheap (compter
  les top-1 dont la ligne gagnante est une ligne `fps` de rang 1 alors que la
  vérité est ailleurs) et n'a pas été faite. Si elle tient, elle suggère de
  prendre un exemplaire **médian** plutôt que le rang 1 quand une classe n'en a
  qu'un.
- **Le sort de `2eur_commemo`.** Le verdict d'auto-validation lit encore la
  seule banque sans pièces courantes ; D1 de `banque-dino` le laisse là en
  attendant sa recalibration. Un changement d'encodeur à l'étape 2 est
  l'occasion de payer les deux migrations en un geste — c'est déjà écrit dans
  `PROTOCOLE-BENCH.md`, et ça reste vrai.
- ~~**Les 130 classes sans ancre.**~~ **Réglé le 2026-08-19** : le chiffre était
  périmé (7 classes sans canonique, pas 130), et les 7 ont été rapatriées par
  `referential.fetch_review_images --ids …` — 7 appels API, `n_no_canonical`
  7 → 0. Le prérequis silencieux reste vrai en mécanisme (`anchors.py:514`).
  **Ce qui reste ouvert à sa place** : les **57 classes** dont les exemplaires
  n'arrivent pas en banque, cause trouvée (`--db` codé en dur), correctif écrit,
  rebuild **non lancé** — cf. [`PREREQUIS.md`](PREREQUIS.md) §P1.
- **La convergence des deux voies.** Si la voie B gagne, que devient la chaîne
  cohorte/bake ? Elle garde au moins un rôle — produire les cohortes-test qui
  alimentent le corpus de scan. Le reste se décidera avec les chiffres en main.
