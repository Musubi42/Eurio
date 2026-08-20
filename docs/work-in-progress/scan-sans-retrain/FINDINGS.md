# Findings — session du 2026-08-19

> Ce qui a été **mesuré** ce jour-là, classé par sujet. Chaque chiffre porte sa
> requête ou sa commande ; chaque affirmation porte son statut
> (**mesure** / **estimation** / **hypothèse**).
>
> Base lue : `ml/state/eurio.replica.db` (réplique read-only du canonique),
> sauf mention explicite. Rien n'a été commité, rien n'a été déployé.
>
> **Mis à jour le 2026-08-20 (après la courbe)** — la banque a été rebâtie
> (§P1 est 🟢), **P3 a abouti** (12 454 prédictions, 23:20:42 → 23:48:36, soit
> neuf heures *après* le build de 14:36:14 UTC ; `calibration_blockers(…,
> 'dinov2-vitl14')` rend `[]` sur la réplique du 2026-08-20 03:22 — le « 12454
> périmées » venait d'une comparaison de **chaînes** entre deux formats de date,
> cf. `PREREQUIS.md` §P3), la **courbe de l'étape 3 est mesurée**
> ([`COURBE-REFERENCES.md`](COURBE-REFERENCES.md), cinq défauts neufs en
> [§8.11](#811-défauts-neufs-trouvés-en-vérifiant-la-courbe--références-par-classe-)),
> et deux passes de
> correction de plus ont tourné. Bilan du jour : **M1 fermé et vérifié**
> (l'encodeur entre dans la clé primaire, migration 0010), **M2 partiellement**
> — le câblage tient, le prédicat non — et **douze défauts neufs**
> ([§8.10](#810-défauts-neufs-trouvés-en-vérifiant-la-fermeture-de-m1-et-m2)),
> dont trois sont une face de plus du même motif. Voir
> [§8](#8-registre-de-dette--d1d16-n1n6-m1m11-q1q12-avec-leur-état), les deux
> notes de motif [§8.7](#87-le-motif--le-chemin-de-base-codé-en-dur) et
> [§8.9](#89-le-motif--le-garde-branché-sur-le-chemin-quon-avait-en-tête), et
> [`GESTE-P3.md`](GESTE-P3.md).
>
> Décision-cadre : [`DECISION.md`](DECISION.md) · Prérequis :
> [`PREREQUIS.md`](PREREQUIS.md) · Chantier frère :
> [`../banque-dino/CONSTAT.md`](../banque-dino/CONSTAT.md).

---

## Sommaire

1. [Ce qui renverse une croyance antérieure](#1-ce-qui-renverse-une-croyance-antérieure)
2. [La banque : cause trouvée, canoniques rapatriés (P1/P2)](#2-la-banque--cause-trouvée-canoniques-rapatriés-p1p2)
3. [Licence et poids DINOv3 (P7)](#3-licence-et-poids-dinov3-p7)
4. [Latences mesurées — la surprise ConvNeXt](#4-latences-mesurées--la-surprise-convnext)
5. [Le plan de capture du corpus de scan (P5)](#5-le-plan-de-capture-du-corpus-de-scan-p5)
6. [Schéma et synchronisation VPS ↔ local](#6-schéma-et-synchronisation-vps--local)
7. [Le banc multi-encodeurs : ce qui est livré (P4/P6)](#7-le-banc-multi-encodeurs--ce-qui-est-livré-p4p6)
8. [Registre de dette — D1..D16, N1..N6, M1..M11, Q1..Q12, avec leur état](#8-registre-de-dette--d1d16-n1n6-m1m11-q1q12-avec-leur-état)
   · [8.7 Le motif : le chemin de base codé en dur](#87-le-motif--le-chemin-de-base-codé-en-dur)
   · [8.9 Le motif : le garde branché sur le chemin qu'on avait en tête](#89-le-motif--le-garde-branché-sur-le-chemin-quon-avait-en-tête)
   · [8.11 Défauts neufs, trouvés en vérifiant la courbe](#811-défauts-neufs-trouvés-en-vérifiant-la-courbe--références-par-classe-)
9. [Ce qui reste bloqué, et par quoi](#9-ce-qui-reste-bloqué-et-par-quoi)
10. [La passe de correction — ce que les lots revendiquent](#10-la-passe-de-correction--les-16-défauts-ce-qui-a-été-fait)

---

## 1. Ce qui renverse une croyance antérieure

Cinq renversements, du plus structurant au plus local. Le détail et les preuves
sont dans les sections suivantes.

| # | On croyait | On sait maintenant | Où |
|---|---|---|---|
| R1 | « Six causes éliminées, **je n'ai donc pas la cause** » des 57 classes manquantes (PREREQUIS §P1) | La cause est **unique et suffisante** : `build_dino_anchors.py` codait son `--db` par défaut en dur sur `ml/state/eurio.db` (périmée) au lieu d'honorer `EURIO_DB_PATH`. La banque servie a été bâtie sur une base à 6205 `image_assets` au lieu de 12454. | [§2](#2-la-banque--cause-trouvée-canoniques-rapatriés-p1p2) |
| R2 | « `dino_class_references` est **vide** dans les 8 bases locales et au canonique » (CONSTAT.md) | Faux depuis le `--push` de la nuit : **1250 lignes** (664 `canonical` + 586 `fps`) et **1 ligne** dans `dino_anchor_builds`. Le bug `BEGIN IMMEDIATE` est corrigé, remplacé par un préflight d'écriture réel. | [§2](#2-la-banque--cause-trouvée-canoniques-rapatriés-p1p2), [§6](#6-schéma-et-synchronisation-vps--local) |
| R3 | « **130 pièces sur 658** n'ont aucune ancre » (CONSTAT.md) | Périmé. Au build du 2026-08-19T00:28 : **664 classes ont leur canonique**, 7 seulement n'en avaient pas — et ces 7 ont été rapatriées le jour même (`n_no_canonical` : 7 → 0). Le trou restant n'est plus le canonique, ce sont les **exemplaires** (125 classes sur 182 possibles). | [§2](#2-la-banque--cause-trouvée-canoniques-rapatriés-p1p2) |
| R4 | « Les variantes **EUPE** de DINOv3 sont non commerciales » (PREREQUIS §P7, DECISION §Étape 2) | EUPE n'est **pas** une variante de DINOv3 : c'est une famille séparée (Meta Reality Labs + FAIR), sous FAIR Noncommercial Research License. Les vraies variantes DINOv3 sont `lvd1689m` et `sat493m`, **toutes deux sous la même licence DINOv3**, commercialement identiques. | [§3](#3-licence-et-poids-dinov3-p7) |
| R5 | « ConvNeXt-Tiny s'exporte et se quantifie sans surprise, à tester en premier » (DECISION §4a) | Mesuré sur Mac : ConvNeXt-Tiny est **le plus rapide en MPS (9,5 ms)** et **le plus lent en CPU batch 1 (292,8 ms)** — 12× le ViT-S/16 à taille comparable. Or le scan Android est un CPU batch 1. ⚠️ Mesures PyTorch/Mac, pas TFLite/Android : signal fort, pas verdict. | [§4](#4-latences-mesurées--la-surprise-convnext) |

Et un renversement de méthode, moins spectaculaire mais aussi cher :

> **R6 — la suite de tests `ml/` était rouge depuis des semaines pour une raison
> que personne n'avait tracée.** Quatre agents ont successivement conclu « pas de
> mon fait ». La cause est un `sys.modules.pop('serving.crop_edit')` dans
> `tests/test_coin_assets_lean.py::restore_module`, qui fabrique un **second**
> objet module : le `monkeypatch.setattr` d'un autre test ne portait plus sur la
> fonction réellement appelée. Corrigé (restauration de l'objet d'origine au lieu
> d'un ré-import). Suite : **1690 passed, 0 failed**, deux exécutions, avec et
> sans `-p no:randomly`. Un échec redevient donc un signal. **mesure**

---

## 2. La banque : cause trouvée, canoniques rapatriés (P1/P2)

### 2.1 La cause des 57 classes manquantes — un `--db` codé en dur

**mesure.** `ml/scripts/build_dino_anchors.py` définissait :

```python
DB_PATH = ML_DIR / "state" / "eurio.db"     # ← avant
```

sans passer par `store.resolve_db_path()`, alors que ~70 autres entrypoints du
repo le font :

```bash
grep -rn resolve_db_path ml --include=*.py | wc -l   # 70 fichiers
sed -n 91p ml/tasks.yml
# {{.VENV}}/python -m scripts.build_dino_anchors -v {{.CLI_ARGS}}   → pas de --db
```

La tâche `go-task` ne passe jamais `--db` : le défaut fautif s'applique donc
toujours. Résultat : la banque servie a été bâtie sur `ml/state/eurio.db`, une
base de travail périmée.

**L'écart entre les deux bases, mesuré :**

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

Les 22 crops de `de-2006-2eur-state-of-schleswig-holstein` (l'exemple de
PREREQUIS §P1) n'existent **pas du tout** comme lignes dans `eurio.db` :
`SELECT id FROM image_assets WHERE id IN (<les 22 ids de la réplique>)` → 0
lignes sur 22. Ce n'est ni un filtre, ni un seuil, ni le FPS, ni une collision
de `class_id` : les crops sont invisibles parce qu'ils ne sont **pas dans la
base lue**.

**Preuve que la cause est suffisante** — rejouer la sélection du builder
(`_class_specs_2eur_all` + `_candidate_crops_for_class`, pur SQL, sans encoder)
sur chaque base :

| Base lue | Classes avec ≥1 candidat | Candidats |
|---|---:|---:|
| `state/eurio.replica.db` | 182 | 1662 |
| `state/eurio.work-dino.db` | 182 | 1659 |
| **`state/eurio.db`** | **125** | **1100** |

Et l'ensemble des 125 classes obtenues sur `eurio.db` est **strictement égal** à
l'ensemble des 125 classes à exemplaires de la banque servie ; les 586
`asset_id` de la banque sont tous inclus dans les 1100 candidats de cette base.
Sortie du script de confirmation :

```
eurio.db classes == fps_classes ?  True
seulement eurio.db: []      seulement banque: []
bank_assets ⊆ candidats(eurio.db) ?  True  586 1100
```

**Correctif appliqué** (non commité) :

```python
DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.db")
```

plus un commentaire daté et un test de non-régression
`tests/test_build_dino_anchors_cli.py::test_db_path_defaut_honore_eurio_db_path`.

> **Ce qui reste vrai des six fausses pistes** : elles étaient toutes
> correctement écartées. La sixième — « le build aurait tourné sur une autre
> base » — avait été rejetée sur un raisonnement **faux** : « la réplique porte
> à la fois les crops et les références ». Elle porte les références parce
> qu'elles y sont poussées par HTTP (`/ingest/dino-references`), ce qui ne dit
> rien de la base **lue** au moment du build. Leçon transposable : la présence
> d'un résultat dans une base ne prouve pas que le calcul y a lu ses entrées.

### 2.2 Les 7 classes sans canonique sont rapatriées

**mesure.** Aucun mécanisme existant ne pouvait les rapatrier :

- absentes de `ml/datasets/coin_catalog.json` → `import_numista --retry-images`,
  qui rejoue des URLs cachées sans appel API, est un **no-op** pour elles
  (`in_catalog = False` pour les 7) ;
- absentes de `ml/datasets/numista_review_queue.json` (11 items, intersection
  vide).

Le mécanisme adéquat est `referential/fetch_review_images.py` (KeyManager +
`get_type_details` + `download_image`), qui n'écrit **que** le filesystem
(`ml/datasets/<nid>/*.jpg` + le cache d'URLs `coin_catalog.json`) — donc sûr
sous le flip Direction A. Un drapeau `--ids` lui a été ajouté plutôt que de
polluer la file de review.

```bash
cd ml && .venv/bin/python -m referential.fetch_review_images \
  --ids 375327,576180,194605,581307,581165,578765,576181
# Done: 7 downloaded, 0 failed
```

7 avers + 7 revers téléchargés, images réelles (de 55 ko / 642 px pour 576181 à
899 ko / 2540 px pour 578765). Coût : **7 appels** `get_type_details` sur un
quota de 8 clés × 2000.

Vérification : `_class_specs_2eur_all(replica, DATASETS_DIR)` → `specs: 671,
sans canonique: 0`. **`n_no_canonical` passe de 7 à 0.**

⚠️ **Effet de bord de données à connaître** : `ml/datasets/coin_catalog.json` est
modifié dans l'arbre (+7 entrées) et 14 images sont sur le disque (dossier
gitignoré). Les chiffres de référence « 664 classes / 7 sans canonique » ne sont
donc plus reproductibles à l'identique sur cette machine — c'est l'état d'après
qui fait foi. Sauvegarde du catalogue avant modification en scratchpad.

### 2.3 Ce que le prochain rebuild devrait donner

⚠️ **estimation.** Avec le `--db` corrigé : de **125 → ~182 classes** à
exemplaires, soit ~+57 classes et jusqu'à ~+560 lignes d'exemplaires (1662
candidats, budget `DEFAULT_EXEMPLARS_PER_CLASS = 10`, `anchors.py:204`), plus 7
canoniques supplémentaires → banque autour de **671 canoniques + ~1050
exemplaires**.

Le compte exact dépend du plancher `floor_sim = 0.45` (`anchors.py:200`)
appliqué **après** encodage, non simulé ici (aucun encodage lancé).

Commande en attente du go du PO :

```bash
cd ml && .venv/bin/python -m scripts.build_dino_anchors --kind 2eur_all --force -v --push
```

> 🚫 **Non lancée.** La review sert la banque actuelle, et ce rebuild périme les
> 12454 prédictions — il déclenche donc P3.

---

## 3. Licence et poids DINOv3 (P7)

### 3.1 Le verdict : redistribuable, sous deux obligations

**mesure.** La licence DINOv3 autorise explicitement la redistribution des poids
et de leurs dérivés dans une application commerciale. §1.a : licence
« non-exclusive, worldwide, non-transferable and royalty-free » pour « use,
reproduce, distribute, copy, create derivative works of, and make
modifications ». Aucune clause ne restreint l'usage commercial, ni le nombre
d'utilisateurs, ni la taille de l'entreprise (pas d'équivalent au seuil des
700 M d'utilisateurs de Llama).

Conditions du §1.b.i, exactement :

- **(A)** ne distribuer que sous les termes de ce même accord ;
- **(B)** « provide a copy of this Agreement with any such DINO Materials » ;
- **(C)** « prominently display "Built with DINOv3" on a related website, user
  interface, blogpost, about page, or product documentation ».

```bash
curl -sfL https://raw.githubusercontent.com/facebookresearch/dinov3/main/LICENSE.md
# 7503 octets, récupéré le 2026-08-19
curl -sfL -A "Mozilla/5.0" https://ai.meta.com/resources/models-and-libraries/dinov3-license/
```

### 3.2 ⚠️ Les deux copies publiées de la licence DIFFÈRENT

**mesure.** Le `LICENSE.md` de GitHub (en-tête « Last Updated: August 19, 2025 »)
ne porte au §1.b.i que « you shall provide a copy of this Agreement ». La page
`ai.meta.com` (en-tête « August 14, 2025 »), celle vers laquelle pointent
**toutes** les cartes de modèle Hugging Face, ajoute l'obligation « prominently
display "Built with DINOv3" ».

```bash
curl -sfL .../main/LICENSE.md | grep -c 'Built with'        # 0
# page Meta : re.finditer('Built with', t) → offset 2682     # 1 occurrence
curl -sfL "https://api.github.com/repos/facebookresearch/dinov3/commits?path=LICENSE.md&per_page=10"
# 2 commits seulement : 11c58638 (2025-08-14) et ffb4bb89 (2025-08-19)
```

**Conduite retenue** : se conformer à la version **la plus stricte** (Meta), donc
afficher « Built with DINOv3 ». Le §8 dit que Meta peut modifier l'accord et que
« All such changes will be effective immediately » — la version live hébergée par
Meta prime sur une copie figée dans un dépôt. Coût de la conformité : une ligne
de texte. Coût de la non-conformité : une violation de licence sur une app Play
Store.

> **Hypothèse juridique, non tranchée** : je ne suis pas juriste. Ce point mérite
> un avis si l'app est monétisée.

### 3.3 Les dérivés, la quantification, la banque

**mesure.** Un modèle dérivé porte les **mêmes** obligations : le §1.b.i vise
« DINO Materials, and any derivative works thereof », et « DINO Materials »
inclut nommément « trained model weights ». Donc poids fine-tunés, distillés,
quantifiés TFLite/int8, ou passés par une tête de projection puis
re-sérialisés — tous restent sous licence DINOv3. Le §5.a précise qu'on est
propriétaire de ses dérivés, mais la propriété n'annule pas l'obligation de
distribution.

⚠️ **estimation** : la **banque de vecteurs** relève des « outputs and results »,
que le §3 mentionne sans en revendiquer la propriété ni en restreindre l'usage.
Elle nous appartient donc probablement librement ; seul le backbone porte la
licence. À confirmer par un juriste si ça devient structurant.

**hypothèse** — la clause §1.b.iv (« will not involve or encourage others to
reverse engineer, decompile or discover the underlying components ») frotte
littéralement avec la conversion TFLite. Interprétation retenue : elle vise le
reverse engineering au sens PI (retrouver la recette d'entraînement, les
données), pas l'export d'un modèle que le §1.a autorise explicitement à modifier
et dont le code est open source — sinon le §1.a serait vidé de sens. Risque jugé
faible, second point à faire relire.

**mesure** — **aucune Acceptable Use Policy** n'est attachée à DINOv3
(contrairement à Llama) : recherche « Acceptable Use » → 0 occurrence dans les
deux documents. Les seules restrictions vivent au §1.b : conformité aux lois et
au RGPD (iii), pas de reverse engineering (iv), Trade Controls / ITAR /
militaire / nucléaire (v). Rien ne gêne une app de collection de pièces.

### 3.4 Ce que DINOv2 → DINOv3 fait perdre, exactement

**mesure.** DINOv2 est Apache-2.0 (`curl -sfL
https://api.github.com/repos/facebookresearch/dinov2` → `spdx_id: Apache-2.0`).

On **perd** : (1) la liberté de sous-licencier — DINOv3 impose son accord en
cascade sur tout dérivé ; (2) la stabilité du contrat — §8, modification
unilatérale à effet immédiat ; (3) la clause brevets explicite d'Apache 2.0 §3 ;
(4) l'obligation de branding.

On **ne perd pas** : le droit commercial, le droit de modifier, le droit de
redistribuer, la propriété de ses dérivés.

⚠️ **estimation** — atténuation peu coûteuse du risque §8 : archiver dans le repo
la version datée de la licence sous laquelle les poids ont été téléchargés, avec
la date et le hash des fichiers.

### 3.5 Les poids se téléchargent sans gate

**mesure.** `timm` ne tape pas les dépôts `facebook/*` (qui exigent « agree to
share your contact information ») mais ses propres miroirs `timm/*` :

```python
timm.get_pretrained_cfg('vit_small_patch16_dinov3.lvd1689m').hf_hub_id
# 'timm/vit_small_patch16_dinov3.lvd1689m'
```

| Modèle | Téléchargement | Params | Sortie | Entrée |
|---|---:|---:|---:|---|
| `vit_small_patch16_dinov3.lvd1689m` | 91,2 Mo en 11,3 s | 21,59 M | (1, 384) | **256×256** bicubic |
| `convnext_tiny.dinov3_lvd1689m` | 115,4 Mo en 13,2 s | 27,82 M | (1, 768) | 224×224 bicubic |

Normalisation ImageNet pour les deux (`mean=[0.485,0.456,0.406]`,
`std=[0.229,0.224,0.225]`). Vérifié sur un vrai crop de pièce
(`debug_pull/.../bright_textured_p1_crop.jpg`) : sorties `(1,384)` norme 6,238 et
`(1,768)` norme 45,928.

⚠️ **Attention** : la résolution du ViT-S/16 résolue par `timm` est **256**, pas
les 224 annoncés par la carte `facebook/*`. Rien à écrire côté code :
`ml/scripts/bench_encoder_dino.py:109-114` gère déjà `timm:<name>` et applique
`create_transform(**resolve_model_data_config(model))` — la résolution et la
normalisation sont donc prises automatiquement, sans risque de les coder en dur
de travers.

**Budget de poids**, à comparer aux 4,43 Mo de l'ArcFace MobileNetV3 de l'APK :

| | fp32 | fp16 | int8 |
|---|---:|---:|---:|
| ViT-S/16 | 86,3 Mo | 43,2 Mo | 21,6 Mo |
| ConvNeXt-T | 111,3 Mo | 55,6 Mo | 27,8 Mo |

**Recommandation** : accepter le gate `facebook/*` **une fois**, délibérément et
de manière tracée. Le préambule lie « by using or distributing any portion or
element of the DINO Materials », pas seulement par le clic « I Accept » : on est
déjà lié, autant que l'acceptation soit datée et attribuable.

---

## 4. Latences mesurées — la surprise ConvNeXt

**mesure.** Mac, torch 2.9.1, 8 threads, 10 itérations après 3 de chauffe
(script `p7_latency.py` en scratchpad) :

| Encodeur | Params | CPU bs1 | CPU bs32 | MPS bs1 | MPS bs32 |
|---|---:|---:|---:|---:|---:|
| dinov3 **ViT-S/16** | 21,6 M | **24,5 ms** | 19,19 ms/img | 15,0 ms | 12,93 ms/img |
| dinov3 **ConvNeXt-T** | 27,8 M | **292,8 ms** | 49,13 ms/img | **9,5 ms** | **7,38 ms/img** |
| dinov2 ViT-S/14 | 21,7 M | 20,4 ms | 18,53 ms/img | 10,0 ms | 8,56 ms/img |
| dinov2 **ViT-L/14** *(sert la review)* | 304,37 M | 217,9 ms | 166,25 ms/img | 93,2 ms | 93,1 ms/img |

Le 292,8 ms **n'est pas un artefact de chauffe** : re-mesuré isolément machine
libre, 20 itérations après 5 de chauffe → **292,6 ms**, et 286,0 ms en
`memory_format=channels_last`.

**Trois lectures :**

1. ⚠️ **Ces mesures sont sur Mac (PyTorch CPU/MPS), pas sur Android.** Elles ne
   prédisent pas la latence dans l'APK : le portage passe par TFLite/NNAPI dont
   le noyau ConvNeXt n'a rien à voir avec celui de PyTorch CPU.
2. Mais le signal est fort et ne s'ignore pas : le scan Android est un **CPU en
   batch 1**, exactement le régime où ConvNeXt s'effondre ici (12× le ViT-S/16 à
   taille comparable). **Le ViT-S/16 DINOv3 devient le candidat par défaut pour
   l'APK**, et ConvNeXt-Tiny doit être benché en TFLite avant d'être pris au
   sérieux côté embarqué. Cela **renverse l'ordre** proposé par
   [`DECISION.md`](DECISION.md) §Étape 4a (« ConvNeXt-Tiny d'abord »).
3. ConvNeXt-Tiny reste **le meilleur candidat côté Mac/serveur** pour bâtir la
   banque : le plus rapide des quatre en MPS.

**Corollaire sur la review** : le ViT-L/14 qui la sert coûte 9× le ViT-S/16 en
CPU bs1 pour 14× les params. S'il perd peu en qualité au bench, le remplacer
accélérerait la review d'un ordre de grandeur.

---

## 5. Le plan de capture du corpus de scan (P5)

Livrables : [`PROTOCOLE-CAPTURE.md`](PROTOCOLE-CAPTURE.md) (à lire téléphone en
main), [`plan-capture-scan.csv`](plan-capture-scan.csv) (plan humain) et
[`plan-capture-scan.cohorte.csv`](plan-capture-scan.cohorte.csv) (format
resolver). Régénérables par `go-task ml:scan-corpus:prescribe`.

**Composition mesurée** : 80 classes possédées × 5 conditions = **400 cellules /
985 captures / 11 sessions**.

| Strate | Classes | Cellules | Captures | Part |
|---|---:|---:|---:|---:|
| riche (≥9 exemplaires) | 22 | 110 | 220 | 22,3 % |
| moyenne (1-8) | 21 | 105 | 210 | 21,3 % |
| **canonique seul** | **30** | **150** | **450** | **45,7 %** |
| hors banque | 7 | 35 | 105 | 10,7 % |

### 5.1 Les 7 classes « hors banque » ne sont pas aveugles

**mesure.** Chacune a exactement **un** frère de son `design_group` présent dans
la banque, donc chacune est scorable en maille `eq` (la maille de vérité du
replay, corpus-spec §8) :

```sql
WITH owned AS (SELECT eurio_id, design_group_id FROM coins WHERE personal_owned=1),
     bank  AS (SELECT DISTINCT class_id FROM dino_class_references
                WHERE anchors_kind='2eur_all')
SELECT o.eurio_id,
       (SELECT COUNT(*) FROM coins c JOIN bank b ON b.class_id=c.eurio_id
         WHERE c.design_group_id=o.design_group_id)
  FROM owned o WHERE o.eurio_id NOT IN (SELECT class_id FROM bank);
-- 7 lignes, valeur 1 partout
```

Les exclure aurait coûté 7 pièces déjà en main pour zéro gain → **80 classes au
plan, pas 73**. Le quota 15/15/20 de PREREQUIS §P5 reste reproductible :
`go-task ml:scan-corpus:prescribe -- --classes-par-strate riche=15,moyenne=15,canonique=20,hors_banque=0`.

### 5.2 Le piège qui ferait perdre la campagne entière, en silence

**mesure.** `ml/scripts/build_cohort_bundle.py:65` `SAMPLE_COIN_THRESHOLD = 30` et
`:195` `sampled = not no_sample and len(eurio_ids) >= SAMPLE_COIN_THRESHOLD`.
Avec 80 pièces et sans `--no-sample` / `NO_SAMPLE=1`, l'app photographierait
**3 classes sur 80**, et rien ne le dirait à l'écran : seul `sampled: true` dans
le manifest le signale. Pire, `cohort-test:bundle:prod`
(`app-android/Taskfile.yml:349-371`) n'expose **ni** `PRESCRIBE_COHORT` **ni**
`NO_SAMPLE` : ce chemin est inutilisable pour la campagne.

Le protocole impose donc `cohort-test:install … PRESCRIBE_COHORT=<id>
NO_SAMPLE=1` et un contrôle **bloquant** avant la première photo :
`sampled=False`, 400 tests, 80 classes dans `live_tests_manifest.json`.

### 5.3 Le « CSV de prescription » n'existe pas comme point d'entrée

**mesure.** L'app cohort-test lit `live_tests_manifest.json`, produit par
`build_cohort_bundle` depuis une **cohorte en base** (`--prescribe-cohort`,
`build_cohort_bundle.py:479-498`). Le seul CSV du repo
(`eurio_id;numista_id;display_name`,
`class_resolver.coin_refs_from_cohort_csv:227`) sert au **training**, et son
unique appelant est `ml/training/prepare_dataset.py:498`.

D'où deux fichiers en sortie du générateur, et une chaîne exacte dans le
protocole §1. Créer la cohorte est une **écriture** : elle part au canonique via
`POST /lab/cohorts`, jamais en SQLite direct (Direction A, skill
`eurio-data-writes`).

### 5.4 Pourquoi la strate pauvre est sur-représentée

**mesure.** 45,7 % des captures pour 37,5 % des classes (3 captures/cellule contre
2). Trois raisons : c'est le régime de 81 % du catalogue ; le taux y est proche de
50-60 %, donc de variance binomiale maximale (H4 : 62,8 % canonical-only vs
72,7 % wild-rich) ; et la strate ne peut pas s'élargir (30 classes pauvres
physiquement possédées), donc le seul levier est la profondeur. IC95 ≈ **±4,6
pts** à 450 captures, contre ±6,5 en traitement uniforme.

### 5.5 Invariants anti-corrélation, vérifiés sur le CSV produit

**mesure**, via `csv.DictReader` sur le fichier généré et le test rejouable
`ml/tests/test_build_scan_prescription.py::test_invariants_du_plan` :

- distribution du nombre de sessions par classe = `Counter({2: 80})` ;
- fonds distincts par classe : min 4, max 4 ;
- chaque session contient les 4 strates au prorata (~98 captures) ;
- cellules d'une même passe contiguës (pièce ressortie 2 fois, pas 5).

Le fond ne peut donc pas devenir un indice de la classe, et « le jour où j'ai
shooté les pauvres » ne peut pas se confondre avec la strate.

### 5.6 Le générateur n'écrit rien

**mesure.** Connexion en `sqlite3.connect("file:…?mode=ro", uri=True)` ; aucun
`INSERT/UPDATE/CREATE` (`grep -nE "INSERT|UPDATE|DELETE|CREATE|writing\(|Store\("`
→ 0) ; mtime de la réplique inchangé après une dizaine d'exécutions ; test
`test_le_script_ne_touche_pas_la_base` compare les octets avant/après. 35 tests
verts via `go-task ml:scan-corpus:test`.

⚠️ **estimation** : un corpus **partiel** est déjà exploitable — après 3 sessions
(96+96+96 = 288 captures, 4 strates représentées), un premier replay peut
attraper une erreur de protocole tant qu'elle est réparable. Le critère de sortie
P5 (≥500 captures, ≥50 classes, ≥3 conditions, glare+inhand) est dépassé avec
marge à 985/80/5.

---

## 6. Schéma et synchronisation VPS ↔ local

### 6.1 Trois mécanismes de migration, un seul ledger

**mesure.** Un changement de schéma vit par trois chemins :

1. `ml/state/schema.sql` — 73 `CREATE TABLE`, rejoué par `executescript` à
   **chaque ouverture** de Store inscriptible (`ml/store/connection.py:304`) ;
2. ~45 `_ensure_column` (ALTER gardés par `PRAGMA table_info`) dans le même
   `_bootstrap` ;
3. `ml/serving/migrations/*.sql` + `_schema_migrations`, appliqués par
   `db_migrate.run_migrations()`.

`grep -rn "_schema_migrations" ml/` → **un seul appelant** :
`ml/serving/server_serve.py:70`, c'est-à-dire l'app du conteneur canonique VPS
(`infra/eurio-api/Dockerfile:52`). L'API lourde locale `:8042`
(`serving/server.py`) ne l'appelle jamais, et `Store._bootstrap` est un **no-op
complet** en read_only (`connection.py:139-145`).

**Conséquence** : une nouvelle table n'apparaît **pas** automatiquement au
canonique — il faut `git pull` sur `/opt/eurio` + `docker compose up -d --build`
de `infra/eurio-api`. Côté Mac/PC sous flip Direction A, aucun des trois
mécanismes ne tourne : la réplique reçoit son schéma par `sqlite3_rsync`.

### 6.2 La convention en vigueur est le DOUBLE-ÉCRIT

**mesure.** L'en-tête de 0007 et 0008 le dit en toutes lettres : « Miroir DDL
canonique : ml/state/schema.sql ». Et c'est le miroir qui rattrape les bases
locales, **pas** le ledger :

```bash
sqlite3 "file:ml/state/eurio.db?mode=ro" \
  "select filename from _schema_migrations order by filename"   # s'arrête à 0005
sqlite3 "file:ml/state/eurio.db?mode=ro" \
  "select count(*) from sqlite_master where name='dino_thresholds'"  # 1
```

### 6.3 Aucune dérive de déploiement aujourd'hui

**mesure.** `ml/state/eurio.replica.db` et `ml/state/eurio.db` : **86 tables
identiques, colonne pour colonne** (comparaison `PRAGMA table_info` sur les 86 →
aucun diff). VPS `/opt/eurio` et local sur le **même commit 97d1791**, avec les
**8 mêmes migrations** appliquées de part et d'autre, 86 tables au canonique
(`docker exec eurio-api …`).

### 6.4 La dérive réelle : `schema.sql` est en retard de ~30 colonnes

**mesure.** Rejouer `schema.sql` dans une base `:memory:` et differ contre la
réplique → **18 tables en écart**, ~30 colonnes qui n'existent que via
`_ensure_column` : `coins.personal_owned / series_id / lent_to_me`,
`source_images` (14 colonnes : `download_status`, `crop_status`, `marketplace`,
`detections_json`…), `review_queue.kind`, `training_runs.aug_recipe_id`,
`experiment_iterations.augmentations_seed`, `benchmark_runs.per_condition_json`,
`image_state_events.op_id/machine/hlc`. Le repo l'admet lui-même
(`ml/state/schema.sql:966`).

> **`schema.sql` n'est PAS le schéma réel** — c'est le schéma d'une base fraîche
> **avant** les ALTER de `connection.py`. Pour raisonner sur les colonnes
> disponibles, lire `PRAGMA table_info` sur la réplique.

### 6.5 Les migrations ne sont pas auto-suffisantes

**mesure.** `server_serve.py` appelle `run_migrations` **avant** d'ouvrir le Store
inscriptible (lignes 70 puis 78), donc avant le bootstrap `schema.sql`. Or,
rejouées dans l'ordre sur une base neuve : 0001 OK, 0002 OK, **0003 FAIL → « no
such table: source_images »**. Et 0004 rejouée après `schema.sql` → « duplicate
column name: run_id ».

**Conséquence** : reconstruire le canonique à partir de zéro par ce chemin ne
marche pas — il faut restaurer un `eurio.db` existant. Latent, mais à connaître.
Corollaire appliqué : **0009 est écrite en `CREATE TABLE IF NOT EXISTS` pur**,
sans ALTER nu.

### 6.6 Le bug `BEGIN IMMEDIATE` est corrigé, et vérifié en données

**mesure.** `ml/scripts/build_dino_anchors.py:65-130` porte désormais
`preflight_db_traceability()`, qui **sonde réellement l'écriture** (CREATE + DROP
dans `store._writing()`) **avant** les ~4 min d'encodage, et lève
`ReadOnlyTraceabilityError` avec ses trois sorties. Le chemin nominal sous
Direction A est `--push` → `client.ingest.push_dino_references` → `POST
/ingest/dino-references` (route présente dans l'OpenAPI de production).

En données : `dino_class_references` = **1250**, `dino_anchor_builds` = **1**.
→ [R2 du §1](#1-ce-qui-renverse-une-croyance-antérieure).

### 6.7 Où mettre les résultats du banc — au canonique

**mesure.** Trois raisons, toutes vérifiées :

- **(a) le besoin produit l'exige** — `PROTOCOLE-BENCH.md` §« La page admin »
  demande une page en lecture seule sur `encoder_bench_runs`, or le front hébergé
  n'a pas accès au ML local (`hasLocalMlApi=false`, mixed-content interdit) : une
  table locale serait invisible depuis `eurio-admin.musubi.dev` ;
- **(b) le volume ne s'y oppose pas** — `image_asset_dino_predictions` pèse
  ~19,7 Mo pour 20 234 lignes (~975 o/ligne, dominé par `top_k_json`), dans un
  canonique de 173 Mo. Un balayage du banc = 1958 crops × 4 encodeurs = 7832
  lignes ; en ne gardant que ce dont McNemar a besoin (~120 o/ligne), **< 1 Mo**.
  L'argument « trop volumineux » ne tient pas — à condition de **ne pas** y
  sérialiser le `top_k` complet ;
- **(c) le précédent existe** — `dino_thresholds` est déjà au canonique et déjà
  servi (`/lab/dino-thresholds` dans l'OpenAPI de prod), et la promotion d'un
  seuil écrit justement dedans. Une décision et sa preuve doivent vivre au même
  endroit.

**Ce qui reste local** : le calcul et ses artefacts lourds — embeddings, `.npz`
par encodeur, images encodées. Le patron est `ml/store/scan_corpus.py` (store
dédié, `_SCHEMA` inline, fichier gitignoré, override `EURIO_SCAN_CORPUS_DB`).
Ligne de partage : *ce qui coûte cher à recalculer et ne concerne qu'une machine
reste local ; ce qui fonde une décision partagée va au canonique.*

### 6.8 Les bases `eurio.work*.db` sont périmées au SCHÉMA

**mesure.** `work.db` et `work-exercice1.db` (81 tables) n'ont ni
`dino_thresholds`, ni `dino_threshold_changes`, ni `dino_anchor_builds`, ni
`training_thresholds*` ; `work-dino.db` (83 tables) manque les trois tables dino
récentes. **Ne jamais développer ni tester le banc contre elles.** Refaire un
snapshot frais avec `sqlite3 ml/state/eurio.replica.db "VACUUM INTO
'ml/state/eurio.work-bench.db'"` — jamais `cp` (piège WAL).

---

## 7. Le banc multi-encodeurs : ce qui est livré (P4/P6)

Tout est dans l'arbre de travail, **non commité**.

### 7.1 P6-1/P6-2 — la banque est scopée par encodeur

**mesure.** `anchor_path(kind, encoder_version)` produit un `.npz` par couple, et
`save_anchors` double-écrit le legacy **uniquement** quand la banque porte
l'encodeur de production du kind. Trois fichiers coexistent sur un tmpdir, et
`load_anchors` rend la bonne banque pour chacun (dim 1024 vs 384).

La review n'est **pas** rendue aveugle : les 4 banques legacy se chargent à
l'identique, mtimes de `ml/state/*.npz` inchangés.

```
2eur_all      → (1250, 1024, 'dinov2-vitl14')
2eur_commemo  → ( 508,  384, 'dinov2-vits14')
2eur_standard → (  38,  384, 'dinov2-vits14')
reverse_2eur  → (  34, 1024, 'dinov2-vitl14')
```

Les 4 sites de cache-hit internes aux builders passent désormais l'encodeur
demandé (`anchors.py:562, 609, 732, 926`) — sinon bâtir `2eur_all` en DINOv3
aurait « hit » sur la banque vitl14 et renvoyé une banque du **mauvais espace**
sans rien signaler. Écart assumé avec la spec, qui ne le demandait pas.

### 7.2 P4 — le gold de review est figé et versionné

**mesure.** `ml/review/bench_gold.py` (stdlib-only), CLI `ml/scripts/bench_gold.py`
(build/show/diff), manifeste committable
`ml/state/validation_gold/encoder_bench_gold.jsonl` (855 ko, 1958 lignes) +
sidecar `.meta.json`. **`gold_version = 0ecbb1d70e3c`** (`9b15176b3309`
jusqu'au correctif D2/D6 du §10 : la version hache désormais
`asset_id|truth_eurio_id|class_id`, et `truth_country` a remplacé
`target_country`).

Les trois comptes de la spec sont retrouvés à l'unité près :

```sql
SELECT COUNT(*) FROM review_queue rq
  JOIN image_assets a  ON a.id = rq.image_asset_id
  JOIN source_images s ON s.id = a.source_image_id
 WHERE rq.status='done' AND rq.decided_eurio_id IS NOT NULL
   AND a.storage_path IS NOT NULL;                      -- 1958
--   + AND a.training_eligible=1                        -- 1911
-- COUNT(DISTINCT rq.decided_eurio_id)                  --  194
```

**Le piège `class_id` est réel et coûteux** : les 194 `eurio_id` se replient sur
188 `class_id` de banque, et **8 classes / 105 crops (5,4 %)** ont un `class_id`
différent de leur `eurio_id` (`at-2008` → `at-2002` porte 82 crops à lui seul).
Un gold naïf aurait **plafonné le recall à 94,6 %** sur tous les encodeurs, sans
rien signaler.

`training_eligible` est conservé comme **colonne**, pas comme filtre : les 47
crops non éligibles ont été tranchés par un humain — le drapeau dit « ne pas
l'entraîner » (flou, cadrage), pas « on ne sait pas ce que c'est ». Or le banc
mesure un encodeur **gelé en zero-shot** : il n'entraîne rien. Et
`COUNT(DISTINCT decided_eurio_id)` vaut 194 avec **et** sans le filtre.

Le manifeste ne contient **aucune prédiction** → le gold est indépendant de P3 et
peut être figé aujourd'hui. Test dédié
(`test_aucune_prediction_dans_le_manifeste`).

### 7.3 P6-3/P6-4/P6-5 — stats, seuils, store

**mesure.**

- `mcnemar_exact` est **déplacé, pas dupliqué**, dans `ml/shared/stats/paired.py` ;
  `scripts/replay_corpus.py` le ré-exporte. Vérifié identique à la version de HEAD
  sur les 3600 couples (b,c) de 0..59 : **0 divergence**.
- Le balayage précision/couverture (`shared/stats/sweep.py`) dérive ses seuils de
  la plage de scores **observée**, jamais [0,1] en dur.
- `shared/stats/calibration.py` : `propose_threshold()` **lève**
  `CalibrationBlocked` tant qu'un bloqueur est passé, et ne rend un chiffre que
  marqué `provisional=True` avec sa bannière « ⚠ CALIBRATION PROVISOIRE ».
- Le paquet `shared.stats` reste **stdlib pur** : `import shared.stats`
  n'introduit ni torch, ni cv2, ni numpy, ni timm, ni scipy (test par
  sous-processus). C'est la propriété qui évite le skip silencieux du routeur sur
  l'image lean du VPS.
- Migration `0009_encoder_bench.sql` + miroir dans `ml/state/schema.sql` (DDL
  structurellement identique, vérifié en rejouant les deux fichiers dans deux
  bases `:memory:`), store `ml/store/encoder_bench.py`, `POST
  /ingest/encoder-bench`, `GET /lab/encoder-bench/runs[/{id}]`, routeur monté sur
  `server_serve.py`.

**Les deux bloqueurs sont mesurables en SQL, pas supposés** :

```sql
-- P3 : toutes les prédictions sont antérieures au build courant
SELECT COUNT(*) FROM image_asset_dino_predictions p
  JOIN (SELECT MAX(built_at) m FROM dino_anchor_builds
         WHERE anchors_kind='2eur_all' AND encoder_version='dinov2-vitl14') b
 WHERE p.anchors_kind='2eur_all' AND p.encoder_version='dinov2-vitl14'
   AND p.computed_at < b.m;                                    -- 12454 / 12454

-- P1 : classes avec exemplaires réels
SELECT COUNT(DISTINCT class_id) FROM dino_class_references
 WHERE anchors_kind='2eur_all' AND method='fps';               -- 125  (seuil : 180)
```

### 7.4 Le double-écrit est verrouillé par un test

**mesure.** `ml/tests/test_schema_mirror.py` (5 tests) compare, pour
0006/0008/0009, le DDL de chaque objet de la migration à celui de `schema.sql`
(normalisation commentaires/blancs), et force toute migration future à être soit
déclarée miroir, soit exclue sciemment. Non tautologique : supprimer
`mcnemar_c INTEGER,` du miroir → FAILED ; renommer une table → FAILED.

Le miroir **fonctionne sur les deux chemins**, mesuré : `db_migrate` applique
0009 sur une copie VACUUM de la réplique (ledger 0001..0009), et un `Store(…,
read_only=False)` sur une copie de `eurio.work.db` (base sans ledger à jour) crée
les deux tables par le seul bootstrap `schema.sql`.

### 7.5 `build_id` : NON ajoutée, décision assumée

**mesure.** Aucun code livré ne la lit : `calibration_blockers()` mesure P3 par
`computed_at < MAX(built_at)`. L'ajouter aujourd'hui serait une colonne morte, et
0009 s'interdit tout ALTER nu (§6.5). Le jour où on veut le verdict par jointure
plutôt que par date, ce sera une **migration 0010** dédiée : ALTER + miroir
`schema.sql` + `_ensure_column`, les trois, comme 0004 l'a fait pour `run_id`.

---

## 8. Registre de dette — D1..D16, N1..N6, M1..M11, Q1..Q17, S1..S13, avec leur état

Trois revues adversariales ont tourné sur le lot P4/P6 le 2026-08-19 : elles y
ont trouvé **16 défauts** sur un lot dont la suite passait **1690 tests au
vert**. Une passe de correction (quatre lots parallèles + intégration) a suivi,
puis **deux vérifications adversariales** de cette passe (→ N1..N6). Une
**seconde passe de correction** a tourné dans la nuit du 19 au 20 (trois lots +
intégration), suivie à son tour de **deux vérifications adversariales** (→
M1..M11). Une **troisième passe** a fermé M1 et M2 le 2026-08-20 (deux lots +
intégration) ; **deux vérifications adversariales de plus** ont tourné sur cette
fermeture le soir même (→ Q1..Q12, §8.10). La vérification de la courbe
« références par classe » a rendu Q13..Q17 (§8.11). Enfin, une **quatrième
passe** a livré le plancher `min_exemplars`, l'allocateur de scrape eBay et la
skill `eurio-banque` le 2026-08-20 ; **deux vérifications adversariales** de ces
trois lots ont rendu S1..S12 (§8.12), dont cinq fermées dans la foulée.

Ce §8 est un **registre**, pas un état des lieux instantané :

- **aucune ligne n'est supprimée** — la valeur du registre est qu'on puisse
  relire *pourquoi* un défaut a existé, et par quelle reproduction ;
- **les colonnes Preuve / Effet décrivent l'état AU MOMENT DU CONSTAT**, pas le
  code d'aujourd'hui. Elles sont la reproduction historique ;
- la colonne **État** porte **une ligne datée par passe**. La plus récente
  (**2026-08-20, soir**) prime ; les précédentes restent lisibles. Ce qu'elle
  dit prime sur le §10, qui rapporte les statuts *revendiqués* par les lots.

**Légende** — ✅ corrigé, et le correctif vérifié par un tiers · ⚠️ **partiellement
corrigé**, le reste ouvert est nommé dans la cellule · ⏭ requalifié (pas de
correctif, raison écrite) · 🔍 enquête ouverte · 🔴 ouvert.

⚠️ **Ne te fie pas au compte de ce bandeau, il vieillit à chaque passe.**
Le compte recompté ligne à ligne, sa requête, et la **table de tri par gravité
et par déclencheur** sont au **[§8.0](#80-table-de-tri--ce-quil-faut-corriger-avant-le-prochain-geste)**
juste en dessous. C'est par là qu'on entre dans ce registre ; ce qui suit le
§8.0 est l'archive.

**Compte au 2026-08-20 (soir, après la vérification du plancher, de
l'allocateur et de la skill `eurio-banque`), sur 62 lignes : 22 ✅ · 3 ⚠️ ·
6 ⏭ · 1 🔍 · 30 🔴** (63 lignes et 31 🔴 depuis l'ajout de **S13**, cf. §8.0)**.** La passe d'intégration a ajouté **douze lignes** —
S1..S12, §8.12 — dont **cinq sont fermées dans la même passe** (S1, S2, S4, S8,
S10) parce qu'elles tenaient en une ligne de code ou en une correction de
chiffre. Là encore, **aucune n'a été trouvée par un test** : la suite passait
`1878 passed, 0 failed` dans les deux ordres avant comme après.
(Compte précédent, le même jour après la vérification de la courbe « références
par classe », sur 50 lignes : 17 ✅ · 3 ⚠️ · 3 ⏭ · 1 🔍 · 26 🔴.)
(Compte précédent, le même jour au soir, après la vérification de la fermeture
de M1/M2, sur 45 lignes : 17 ✅ · 3 ⚠️ · 3 ⏭ · 1 🔍 · 21 🔴. La vérification de
la courbe a ajouté **cinq lignes** — Q13..Q17, §8.11 — toutes 🔴, dont **aucune
n'a été trouvée par un test** : la suite passait `1843 passed, 0 failed` dans
les deux ordres.)
(Compte revendiqué par la passe de correction, avant sa vérification, sur 33
lignes : 18 ✅ · 2 ⚠️ · 3 ⏭ · 1 🔍 · 9 🔴. La vérification a fait passer **M2**
de ✅ à ⚠️ et ajouté **12 lignes**, toutes 🔴.)
(Compte au matin, avant la fermeture de M1 et M2 : 16 ✅ · 11 🔴.)
(Rappel du compte précédent, 2026-08-19 nuit, sur 22 lignes : 10 ✅ · 5 ⚠️ ·
1 ⏭ · 1 🔍 · 5 🔴.)

**Ce qui a bougé** : les deux défauts qui bloquaient le premier run réel du banc
— **D1** (volet P1) et **N1** — sont fermés et vérifiés, ainsi que N2, N6, D5,
D8 et D16. **Ce qui s'est ouvert** : la seconde vérification a rendu **11
défauts neufs** (§8.8), dont deux graves de la même famille que D1 — *le garde
est juste, il est branché ailleurs que là où la chose arrive* (M1, M2) — et deux
sur le chemin exact du backfill P3 (M7, M8).

**Aucun des 11 ne bloque le lancement de P3** : le backfill lit `image_assets`
et écrit `image_asset_dino_predictions` ; il ne touche ni
`dino_class_references` (M1), ni la route du banc (M2). Mesuré et argumenté dans
[`GESTE-P3.md`](GESTE-P3.md). **M1 est en revanche à fermer avant le premier
build de banque d'un encodeur candidat** — c'est le geste suivant du chantier,
et il détruirait la banque de production.

**Ce qui a bougé le 2026-08-20 au soir** : **M1 est fermé et vérifié par deux
tiers** — l'encodeur est entré dans la clé primaire (migration **0010**), le
writer refuse une table à l'ancienne clé, et la migration a été rejouée par le
vrai runner sur copie `/tmp` de la réplique (1250 lignes avant, 1250 après,
contenu **byte-identique**, `sha256` des 11 colonnes triées inchangé), puis à
1536 lignes construites, NULL compris. **M2 est requalifié ⚠️** : l'invariant
est bien descendu dans la porte d'écriture (`record_run`) et il tient, mais le
**prédicat** qu'il évalue laisse passer quatre payloads mensongers (Q1..Q4), et
le test d'inventaire censé voir le chemin de demain est aveugle à un nom de
table interpolé (Q5). **Et le correctif M1 arme lui-même une instance de plus du
motif** : en rendant la coexistence de deux encodeurs possible, il rend faux
tous les **lecteurs** de `dino_class_references`, qui n'ont jamais été scopés
(Q6, Q8). Douze lignes neuves, toutes 🔴 : §8.10.

### 8.0 Table de tri — ce qu'il faut corriger AVANT le prochain geste

> **Lis ce §8.0, pas les 63 lignes.** Le registre détaillé (§8.1 et suivants) est
> une archive : il dit *pourquoi* un défaut a existé et *par quelle
> reproduction*. Cette table-ci dit **ce qui te concerne aujourd'hui**, trié par
> le seul axe qui décide : **qu'est-ce que ça peut casser ?**

#### Le compte réel, recompté ligne à ligne

Recompté le **2026-08-20 (soir)** en lisant, pour chaque ligne du registre, la
**dernière** entrée datée de sa colonne État — pas le bandeau. Requête :

```bash
cd docs/work-in-progress/scan-sans-retrain && python3 - <<'EOF'
import re, collections
lines = open('FINDINGS.md').read().split('\n')
c = collections.Counter()
debut = next(i for i, l in enumerate(lines) if l.startswith('### 8.1 '))  # sauter ce §8.0
for l in lines[debut:]:
    m = re.match(r'\| \*\*([A-Z]\d+)\*\* \|', l)
    if not m: continue
    seg = l.split(' | ')[-1].split('<br><br>')[-1]          # la dernière passe datée
    for s in ('✅','⚠️','⏭','🔍','🔴'):
        if s in seg[:200]: c[s] += 1; break
print(sum(c.values()), dict(c))
EOF
# 63 {'✅': 22, '⚠️': 3, '⏭': 6, '🔍': 1, '🔴': 31}
```

**Non fermées : 35 lignes** (31 🔴 + 3 ⚠️ + 1 🔍). Les 6 ⏭ sont des
requalifications assumées, pas de la dette en attente. Le chiffre « 21 ouvertes »
qui circulait datait de la vérification de la fermeture de M1/M2, **avant**
Q13..Q17 et S1..S13.

#### L'échelle de gravité

Trois niveaux, et un seul critère : **ce que ça produit quand ça se déclenche.**

| | Sens |
|---|---|
| 🩸 | **détruit, ou coûte de l'argent réel** — données, calcul, quota eBay, analyse humaine écrasée. Irréversible ou payant. |
| 📉 | **fabrique un chiffre faux** — un nombre qu'on publierait, un verdict qu'on croirait, une banque servie qu'on croirait juste. |
| 🔧 | **gêne** — coûte du temps, ment dans une doc ou un test, mais ne sort aucun chiffre. |

⚠️ La colonne **Coût** est une **estimation** partout où la cellule État du
registre ne nomme pas déjà le geste exact (« une ligne : … »). Là où elle le
nomme, le coût est repris tel quel.

#### A. À corriger avant le prochain geste — 5 lignes

Ce sont les seules dont le déclencheur est **le geste suivant du chantier**
(redémarrer `eurio-api` pour appliquer 0009/0010/0011, puis bâtir la banque d'un
encodeur candidat).

| # | Grav. | Ce que ça fait | Déclencheur | Coût |
|---|:--:|---|---|---|
| **M4** | 🩸 | `build_dino_anchors.py:57` replie sur `state/eurio.db` (**6205** assets) au lieu de la réplique (**12454**). C'est la rechute de la cause racine du chantier, **sur le script qui l'a produite**. | Le prochain `ml:dino-anchors:build` lancé **hors devShell**. | 2 lignes (`build_dino_anchors.py`, `bench_gold.py`) + les ajouter à `CORRIGES`. |
| **Q6** | 📉 | Les trois lecteurs de `dino_class_references` n'ont **aucun prédicat d'encodeur**. Juste par accident tant qu'un seul encodeur existe ; faux à la seconde où 0010 en autorise deux. Prescription de scan, badge de review, coin-detail. | **Le premier build de banque d'un encodeur candidat** — le geste que le §9 dit de faire juste après le redémarrage du VPS. | Moyen ⚠️ : 3 lecteurs + 2 appelants + la trace de l'encodeur dans `DinoReferenceEntry`. |
| **Q8** | 📉 | Depuis 0010, un `manual_exclude` (`encoder_version=''`) ne remplace plus la ligne `fps` du même crop : deux lignes, et l'affichage dépend d'un `ORDER BY` absent. **Frappe la prod d'aujourd'hui, à un seul encodeur.** | Le déploiement de 0010 au canonique + le premier override humain. | Décision de contrat, pas retouche (cf. la cellule État). |
| **Q10** | 🔧 | Le garde de clé n'est appelé qu'**après** les ~4 min d'encodage, et par HTTP son message (« applique 0010 ») n'atteint jamais l'appelant. | Tout `build_dino_anchors` **tant que 0010 n'est pas déployé** — c'est-à-dire la fenêtre ouverte en ce moment. | Petit : appeler `_exige_encodeur_dans_la_cle` dans `preflight_db_traceability` + `HTTPException` dans la route. |
| **D1** | 📉 | Volet P1 corrigé, mais son reste ouvert était « la table ne peut pas porter deux encodeurs — voir M1 ». **M1 est fermé (0010) : il ne reste que le déploiement.** | Le redémarrage de `eurio-api`. | Zéro code — c'est un déploiement (`eurio-vps-deploy`). |

#### B. Fausse un chiffre qu'on publie — 9 lignes

Aucune n'est déclenchée par un geste précis : elles se déclenchent **quand on
lit un nombre**. Donc à chaque rapport.

| # | Grav. | Ce que ça fait | Déclencheur | Coût |
|---|:--:|---|---|---|
| **S13** | 📉 | Le plancher `min_exemplars=2` a été posé sur une **extrapolation** du point N=1 de la courbe, et le re-bench le contredit (**−1,4 pt** vits14, **−0,9** vitl14 en held-out). **Le plancher a été retiré le 2026-08-20 au soir** après mesure par classe ; la ligne reste ouverte pour l'**erreur de raisonnement** et pour le décalage banque-servie / code. Voir §8.12. | Déjà déclenché. Se re-déclenche à chaque lecture de la courbe comme prédiction. | Fait pour le drapeau ; reste à documenter le motif et à surveiller le prochain rebuild (P1 ne dira pas que la forme de la banque a changé). |
| **S6** | 📉 | La courbe ne connaît pas `min_exemplars` : son N=1 décrit une banque que le builder **ne peut plus construire**. Or la courbe est l'unique preuve qui justifiait le plancher — c'est le mécanisme de S13. | Toute lecture de `ml:refs-curve:run` comme prédiction de la banque de demain. | Décision de méthode (déjà dite dans la skill et le `desc:`). |
| **Q14** | 📉 | `diminishing_returns()` déclare un coude sous le plancher de bruit (1 pt = 11 crops sur 1100) : **il fabrique un fait**. Même famille que S13, un jour plus tôt. | La prochaine lecture du verdict de la courbe. | Petit : seuil au-dessus du bruit, ou muet quand l'écart apparié n'est pas significatif. |
| **Q15** | 📉 | Le banc note le gold **entier**, fuite comprise (858/1958 crops sont des ancres) : niveau absolu optimiste, et `encoder_bench_runs` n'a pas de `n_leaked`. | Toute calibration de seuil d'auto-acceptation à partir du banc. | Petit (tracer `n_leaked`) ou moyen (bande held-out). |
| **Q16** | 📉 | Symétrique : le held-out **n'est pas** un plancher prudent (le FPS retient les crops les plus durs, on les exclut). Les deux biais jouent en sens contraire. | Idem — dès qu'on cite un niveau absolu. | Une population tierce (échantillon aléatoire du pool avant construction). |
| **Q13** | 📉 | Gold et banque tirent leur vérité de **deux colonnes différentes** (`review_queue.decided_eurio_id` ↔ `image_assets.eurio_id`) : 5 ancres portent une classe que la review contredit. | Le prochain build, ou la prochaine lecture du recall par classe. | Enquête d'abord : quel journal de requalification fait foi. |
| **D2** | 📉 | `gold_version` est **déclaré, jamais vérifié** : `load_meta` relit le sidecar tel quel, pas de `verify` au CLI. Deux runs du même `gold_version` peuvent avoir été notés contre des vérités différentes. | Une re-décision humaine, ou une édition à la main du `.jsonl`. | Petit ⚠️ : un `verify` au CLI + l'appeler dans `load_meta`. |
| **M8** | 📉 | Le backfill P3 sort en **code 0** avec des milliers d'erreurs ; `go-task` déclare « réussi ». | Chaque `ml:dino-predictions:backfill`. | **Une ligne** : `return 1 if result.n_errors else 0`. |
| **S7** | 📉 | Le plancher se **lit** sur la réplique (Direction A) et s'**écrit** au canonique : une valeur posée par le PO n'atteint le build qu'après un pull, sans garde de fraîcheur. | Poser un seuil au canonique, puis bâtir sans pull. | Petit ⚠️ : une garde de fraîcheur, ou l'accepter et s'en tenir à `dino_anchor_builds.note`. |

#### C. Détruit ou coûte de l'argent — 4 lignes

| # | Grav. | Ce que ça fait | Déclencheur | Coût |
|---|:--:|---|---|---|
| **S3** | 🩸 | Le préflight quota d'eBay est aveugle **d'un facteur ~130** : il moyenne sur `source_runs.n_calls`, un compteur démontré faux. **Un garde branché sur un compteur faux est un garde absent** — et le quota, c'est de l'argent. | La prochaine vague de scrape eBay. | Moyen ⚠️ (le correctif vit dans `serving/sources_routes.py`, sur le chemin du scrape). Contourné par S4, pas fermé. |
| **M7** | 🩸 | Sous `--push`, tout le travail `face`/`denom` du backfill (~3000 faces, ~6000 dénominations) est écrit dans un `mkdtemp` qui **disparaît avec le calcul**. | Chaque `ml:dino-predictions:backfill --push` — le chemin nominal. | Moyen : brancher l'export, ou un `/ingest/*` dédié. |
| **Q17** | 🩸 | `--out` fait un `write_text()` du rapport **entier** : un rerun pointé sur `BENCH-ENCODEURS.md` **détruit** son analyse humaine, en silence, code 0. | Le prochain run du banc pointé sur un fichier suivi. | Petit : préserver ce qui précède le séparateur « CORPS GÉNÉRÉ ». |
| **N5** | 🩸 | `shared/storage/cascade.py` ouvre en lecture-**écriture** hors du flip `EURIO_DB_READONLY`, et avale l'exception. Exposition **nulle aujourd'hui** (0 crop manquant en cache), mais la mitigation affirmée par les lots est fausse. | Un 404 MinIO pendant un banc ou un backfill. | Petit : passer par `store.connection`. |

#### D. Parkable — 11 lignes, à probabilité quasi nulle aujourd'hui

**Ces défauts sont réels. Leur probabilité ne l'est pas.** Six d'entre eux
(M2, Q1, Q3, Q4, Q5, Q9) décrivent des **payloads forgés** contre
`POST /ingest/encoder-bench` : le seul appelant de cette route est le PO, depuis
une machine, avec un jeton `ingest:write` qu'il détient déjà. Un attaquant qui
peut forger le payload peut aussi écrire la table directement. **Ne les traite
pas au même poids que M1** — qui, lui, écrasait réellement des lignes.

Ils cessent d'être parkables **le jour où la route est exposée à un tiers** :
un second opérateur, un CI qui pousse des runs, un jeton partagé. Ce jour-là,
relire ce bloc en entier.

| # | Grav. | Pourquoi parkable | Ce qui le réveille |
|---|:--:|---|---|
| **M2** | 📉 | La route ne consulte aucun garde ; `provisional`, `gold_sample_n`, `n_paired` sont recopiés du corps HTTP. | Un second appelant de `/ingest/encoder-bench`. |
| **Q1** | 📉 | L'état sûr (« gold entier ») est encodé par une **absence** : omettre `gold_sample_n` désarme le bloqueur. | Idem — mais **note que c'est le motif §8.9 dans sa forme la plus pure** ; à citer, pas à oublier. |
| **Q3** | 📉 | Un run peut être sa propre baseline, et `paired_overlap` **certifie** le montage. | Idem. **Une ligne** dans `record_run` : `baseline_run_id != run_id`. |
| **Q4** | 📉 | Un run démoté par le serveur est promu par un second POST (`INSERT OR REPLACE` sans relire). ⚠️ Le moins parkable des six : **un re-push honnête suffit**, sans intention. | Un rerun du banc après correction d'un champ. |
| **Q5** | 🔧 | L'inventaire AST des chemins d'écriture est aveugle à un nom de table interpolé. | L'ajout d'un cinquième chemin d'écriture. |
| **Q9** | 🔧 | Le même jeton écrit ce que le verdict mesure : « le payload n'est pas cru » est plus fort que ce que l'archi garantit. | Une séparation de scopes, le jour où elle est promise à un tiers. |
| **Q2** | 📉 | ⚠️ **Sorti du parkable** en réalité : atteignable **sans rien forger** (un `baseline_run_id` fautif + `predictions: []`), et il produit une p-valeur contre un bras qui n'existe pas. | Une faute de frappe dans un `--baseline`. Geste minimal : vérifier l'existence dans `record_run`. |
| **N4** | 📉 | Le cache `_get_bank` met la banque servie et l'artefact de banc sur la **même clé** — mais le banc est un CLI, pas le processus de review. | Le jour où le banc tourne dans le même processus que la review. **Une ligne** : le rôle dans la clé de cache. |
| **N3** | 🔧 | Flaky à 1/6, **non reproduit** en 9 exécutions complètes depuis. | Le prochain rouge sans cause : ne pas le mettre sur le compte du bruit avant d'avoir relu cette ligne. |
| **Q11** | 🔧 | Une branche morte-née dans 0010, commentée à tort « base neuve ». | Une ligne de commentaire. |
| **Q12** | 🔧 | `encoder_version` NULLABLE sur une base locale antérieure. Inoffensif tant que le garde du writer tient — mais c'est lui qui rend **Q10** concret. | Un build local sur une base d'avant 0007. |

#### E. Gêne pure, sans déclencheur identifié — 6 lignes

Un défaut sans déclencheur est probablement parkable. Ceux-ci ne réveillent
rien tout seuls ; ils coûtent une session à celui qui tombe dessus.

| # | Grav. | Ce que ça fait | Coût |
|---|:--:|---|---|
| **M3** | 🔧 | La docstring de `resolve_db_path`, **présentée comme LA règle du repo**, est fausse pour sa moitié « lecteur ». Une règle de repo fausse est pire qu'une absence de règle. | Petit : soit `read_only=True` dans les entrypoints de lecture, soit corriger la docstring. |
| **M5** | 🔧 | La fixture `_seed_etat_du_jour` intervertit `anchors_kind` et `encoder_version` et insère en **positionnel** — sur la paire de colonnes dont dépend tout le correctif D1. Aucun effet aujourd'hui ; piège de recopie. | Petit. |
| **M6** | 🔧 | Un test qui **ne peut pas échouer** (l'autouse `_no_ambient_flip` vide la variable qu'il assert). Il gonfle le compte sans rien garder. | Une ligne. |
| **M9** | 🔧 | Le journal `face`/`denom` annonce le lot **soumis**, jamais `cur.rowcount` — et il **aggrave M7** en donnant à croire que le travail aboutit. | Une ligne. |
| **S11** | 📉 | `resolve()` ne revalide jamais ce qu'elle lit en base : un `spread_auto_accept_min = 0,9` posé hors `set_threshold` **gèlerait l'auto-acceptation** en silence. | Une ligne + un journal — jamais corriger en douce. |
| **Q7** | 🔧 | `set_reference_override` / `clear_reference_override` écrivent `dino_class_references` **sans** passer par le garde de clé, et aucun inventaire ne le verrait. Jumeau de Q8. | Petit, à faire avec Q8. |

#### Ce que la table dit, en une phrase

**Avant de redémarrer `eurio-api` et de bâtir la banque d'un encodeur
candidat : M4, Q6, Q8, Q10.** Avant de publier un chiffre : le bloc B. Avant de
lancer un scrape : S3. Le reste attend, et le bloc D attend **jusqu'à ce que la
route sorte de la machine du PO**.

---

### 8.1 Pannes muettes — à traiter avant de publier un chiffre

| # | Défaut | Preuve | Effet | État — 19/08 (nuit) puis 20/08 (matin) |
|---|---|---|---|---|
| **D1** | `calibration_blockers()` **n'émet pas P3** pour un encodeur **candidat** : sans ligne dans `dino_anchor_builds` pour son couple, `last_build` est NULL et tout le bloc est sauté (`store/encoder_bench.py:250-254`). Idem si la table est absente (`eurio.work.db` : 9034 prédictions, 0 bloqueur). | `calibration_blockers(…, encoder_version='timm:vit_small_patch16_dinov3.lvd1689m')` → **1 seul bloqueur (P1)** ; base `:memory:` vide → `[]` | Le jour où P1 passe, un run DINOv3 sortira `provisional=0` sans qu'aucune prédiction n'ait été recalculée. **Le garde s'auto-désarme précisément sur les runs qu'il devait couvrir.** À corriger **avant** que P3 serve de critère de promouvabilité. | ⚠️ **partiel.** **P3 est corrigé et re-vérifié** : `_p3_blockers` (`store/encoder_bench.py:308-371`) distingue 4 états ; la repro ci-contre ne reproduit plus (`eurio.db` → 2 bloqueurs, `eurio.work.db` → `P3: fraicheur non mesurable … table(s) absente(s)` + P1, en `mode=ro`). **Reste ouvert : P1 ne regarde pas l'encodeur.** `_p1_blockers` (`:373-397`) ne reçoit pas `encoder_version` et compte `SELECT COUNT(DISTINCT class_id) … WHERE anchors_kind=? AND method='fps'` — sans prédicat d'encodeur, alors que la table **est** scopée (`UNIQUE(anchors_kind, encoder_version, class_id)`, et `store/dino_references.py:102` scope son DELETE sur le couple). Mesuré par les deux vérificateurs, indépendamment : le candidat DINOv3 a **0** référence en base et P1 se tait dès que le seuil est franchi par les lignes `dinov2-vitl14` ; réciproquement, 60 classes `fps` arrivant pour un candidat font passer P1 de « 125 classes, bloqué » à `[]` **pour l'encodeur de production**, dont la couverture n'a pas bougé. Aucun test ne peut l'attraper : la fixture `_seed_etat_du_jour` (`tests/test_encoder_bench_store.py:250`) déclare `dino_class_references` à **3 colonnes** au lieu de 11. C'est la maladie D1 déplacée de P3 vers P1. <br><br>**20/08 (matin) — ⚠️ toujours partiel, mais le reste ouvert a changé de nature.** Le volet P1 est **corrigé** : `calibration_blockers` passe `encoder_version` jusqu'à `_p1_blockers`, dont la requête est désormais `WHERE anchors_kind = ? AND encoder_version = ? AND method = 'fps'` (`store/encoder_bench.py`, prédicat **strict** — les lignes legacy `encoder_version IS NULL` ne sont créditées à personne ; aucune n'existe : `sqlite3 ml/state/eurio.replica.db "SELECT anchors_kind, COALESCE(encoder_version,'<NULL>'), method, COUNT(*), COUNT(DISTINCT class_id) FROM dino_class_references GROUP BY 1,2,3;"` → `2eur_all\|dinov2-vitl14\|canonical\|664\|664` et `…\|fps\|586\|125`). La fixture qui rendait le défaut inexprimable est réparée : `_seed_etat_du_jour` applique le DDL réel à **11 colonnes** (`tests/test_encoder_bench_store.py`). Tests : `test_p1_ne_valide_pas_un_candidat_avec_la_couverture_de_la_prod`, `test_p1_ne_debloque_pas_la_prod_avec_les_exemplaires_du_candidat`, `test_p1_ignore_les_lignes_sans_encodeur` — mutation « prédicat d'encodeur retiré » ⇒ **3 rouges**, revert ⇒ `29 passed`, reproduit par les deux vérifications. **Reste ouvert : la prémisse de stockage sur laquelle ce garde repose est fausse — voir M1.** La docstring du correctif affirme que la table est scopée `UNIQUE(anchors_kind, encoder_version, class_id)` ; cet index est **partiel** (`WHERE asset_id IS NULL`, `state/schema.sql:576-578`) et la PK réelle est `(anchors_kind, class_id, eurio_id, asset_id)` (`:565`), sans l'encodeur. Le garde compte donc juste dans une table qui ne peut pas porter deux encodeurs. |
| **D2** | `gold_version` ne hache **que les asset_id** (`bench_gold.py:199-207`). Une re-décision humaine — le cas que `diff_gold` désigne comme « celui qui doit alerter » — laisse la version identique. `diff_gold` ne compare pas non plus les `class_id`. | Gold committé, `truth_eurio_id` du 1er crop remplacé → `9b15176b3309` **avant et après** | Deux runs estampillés du même `gold_version` peuvent avoir été notés contre des vérités différentes. La garantie P4 ne couvre pas la mutation la plus insidieuse. Correctif : hacher `asset_id\|truth_eurio_id\|class_id`. | ⚠️ **partiel.** Le hash est corrigé (`gold_version(rows: Sequence[GoldCrop])`, `asset_id\|truth_eurio_id\|class_id` trié, sha256[:12]) et le gold régénéré `9b15176b3309` → `0ecbb1d70e3c`. **Reste ouvert : la version est déclarée, jamais vérifiée.** `load_meta` (`review/bench_gold.py:391-393`) relit le sidecar tel quel ; aucun chemin ne fait `gold_version(load_gold(p)) == load_meta(p)['gold_version']`, et le CLI n'a pas de `verify`. Sonde exécutée : une ligne du `.jsonl` éditée à la main → runs estampillés `deadbeef1234` alors que le contenu hache `1cb756ca4a63`. Le gold committé est sain aujourd'hui (sidecar = recalcul = `0ecbb1d70e3c` sur 1958 lignes) : trou latent, pas corruption. <br><br>**20/08 (matin) — ⚠️ inchangé.** Aucun lot de la seconde passe ne l'a porté ; `load_meta` ne vérifie toujours pas le hash, le CLI n'a toujours pas de `verify`. Le gold committé reste sain (sidecar = recalcul = `0ecbb1d70e3c`). |
| **D3** | `_get_bank` **ne journalise plus rien** quand la banque legacy est périmée : `load_anchors(kind, encoder)` avale le mismatch (`anchors.py:290`) avant le `logger.error` conservé. | Banque legacy en `dinov2-vits14` seule sur un tmpdir → `_get_bank('2eur_all')` = `None`, `logs ERROR: []` | Le jour d'une bascule d'encodeur — le geste même qui a motivé le garde — la review devient aveugle **sans un mot dans les logs**. C'est passé de bruyant à muet. | ✅ **corrigé.** `load_anchors` journalise en ERROR le refus inter-encodeurs ; `_get_bank` relit la **banque servie**, ce qui rend son garde de nouveau atteignable. Mutation `logger.error → debug` → 3 tests rougissent. ⚠️ Voir **N4** : le cache mémoire de `_get_bank` peut rouvrir ce trou dans un même processus. <br><br>**20/08 (matin) — ✅ inchangé** ; la réserve N4 (cache `_get_bank`) l'est aussi, cf. §8.5. |
| **D4** | Le **blocage P3 n'est visible dans aucun chemin exécutable** : `scripts/bench_encoder_dino.py` n'importe ni `store.encoder_bench`, ni `shared.stats.calibration`, ni le gold figé. L'avertissement ⚠️ vit dans le `desc:` de la tâche, que `go-task` n'affiche pas à l'exécution. | `grep -n 'encoder_bench\|bench_gold\|calibration\|provisional' ml/scripts/bench_encoder_dino.py` → rien | Un opérateur obtient des chiffres nus, sans bannière, et rien ne l'empêche de les recopier dans `dino_thresholds`. Le garde existe et n'est branché sur rien. | ✅ **corrigé.** Le même `grep` rend **27** lignes. Bannière `⚠ CALIBRATION PROVISOIRE` en tête ET en pied sur stderr, recopiée en tête et en pied du rapport `--out` ; `propose_threshold` lève tant qu'un bloqueur tient ; `provisional` en base suit les bloqueurs **mesurés**, jamais l'option CLI (mutations `provisional=0` forcé / bannière de pied retirée → 1 test rouge chacune). Bannière réelle produite en lecture seule sur la réplique : 2 encodeurs × 2 bloqueurs. |
| **D5** | Le **banc a sa propre définition du jeu d'évaluation** : `bench_encoder_dino.py:57-70` (`_load_labeled`) rejoue sa requête SQL au lieu de lire le gold figé, et n'écrit rien dans `encoder_bench_runs`. | Comparaison avec `review/bench_gold.py:SELECTION_SQL` | Deux définitions concurrentes du gold coexistent. C'est **la seule contradiction inter-modules** trouvée, et le prochain chantier. | ⚠️ **corrigé sur le fond, un piège de données subsiste.** `_load_labeled` et sa requête `review_queue` sont supprimés ; le banc lit le gold figé et pousse par `POST /ingest/encoder-bench`. Contradiction close, mesurée : `grep -rn gold_version --include='*.py' ml \| grep -v tests/` ne rend plus qu'**une** source et ses consommateurs. **Reste ouvert** : `encoder_bench_predictions.truth_eurio_id` porte en réalité le `class_id` (`bench_encoder_dino.py:295`, décision argumentée dans la docstring de `score_crops`) — mais **ni `state/schema.sql:706` ni `serving/migrations/0009:86` ne le disent**, alors que les colonnes voisines sont commentées. Ampleur : **105 crops sur 1958 (5,4 %)** ne joindront pas `coins.eurio_id`. La table est vide partout : un renommage en `truth_class_id` est encore possible, sinon un commentaire dans les **deux** fichiers (le test de miroir les compare colonne par colonne). <br><br>**20/08 (matin) — ✅ le reste ouvert est fermé : la colonne a été RENOMMÉE.** `truth_eurio_id` → **`truth_class_id`** dans `state/schema.sql`, `serving/migrations/0009_encoder_bench.sql`, `store.encoder_bench.EncoderBenchPrediction`, `serving.ingest_routes.EncoderBenchPredictionPayload` et le site d'écriture de `scripts/bench_encoder_dino.py`, avec un commentaire de 6 lignes dans les **deux** fichiers SQL (ce que la colonne porte, l'ampleur — 105 crops sur 1958 qui ne joignent pas `coins.eurio_id` —, et l'ancien nom daté). Renommage gratuit, mesuré : table vide partout (`0 preds / 0 runs` dans `state/eurio.db`, table inexistante au canonique) et **aucun consommateur hors `ml/`** (`grep -rn "truth_eurio_id\|encoder_bench" admin/packages/studio-local/src` → rien). Test : `tests/test_schema_mirror.py` compare colonne par colonne — mutation « `schema.sql` seul remis sur l'ancien nom » ⇒ rouge, revert ⇒ `5 passed`. **Non renommés, et c'est voulu** : `review.bench_gold.GoldCrop.truth_eurio_id` et `review.validation.replay.ground_truth_eurio_id` portent de vrais `eurio_id`. |

### 8.2 Défauts qui fausseraient un chiffre publié

| # | Défaut | Preuve | Effet | État — 19/08 (nuit) puis 20/08 (matin) |
|---|---|---|---|---|
| **D6** | `bench_gold.py` remplit `target_country` avec `source_images.target_eurio_id[:2]` — la pièce que le **scrape visait** — et non `decided_eurio_id[:2]`, la vérité. | Sur les 1958 crops : **33 pays faux** (be→de ×5, es→de ×2, cy→gr, fr→de…) et **209 nuls** (10,7 %) — requête `SELECT COUNT(*), SUM(lower(substr(s.target_eurio_id,1,2))<>lower(substr(rq.decided_eurio_id,1,2))), SUM(s.target_eurio_id IS NULL) …` → `1958\|33\|209` | Les colonnes `country_recall1/5` de `encoder_bench_runs` seront mesurées contre un label faux. Or **la bande pays est le critère de départage** entre deux encodeurs proches : 1,7 % de bruit d'étiquetage est du même ordre que l'écart cherché. La vérité est disponible gratuitement sur la même ligne. | ✅ **corrigé**, et recompté par un tiers : le champ s'appelle `truth_country`, non nullable, extrait de `decided_eurio_id` ; **242 lignes corrigées sur 1958 (12,4 %)** = 33 faux + 209 nuls ; sur le gold régénéré, **0 nul et 0 incohérent** avec `truth_eurio_id` ; rebuild byte-identique (`cmp`). ⚠️ **Dette de couverture** : son unique garde de non-silence — la `ValueError` levée quand `decided_eurio_id` n'a pas de préfixe ISO2 (`review/bench_gold.py:156-193`) — **n'est exercé par aucun test** : mutation `raise …` → `return ""` ⇒ `23 passed`. La donnée d'aujourd'hui ne le déclenche pas (`NOT GLOB '[a-z][a-z]-*'` → 0 ligne), donc c'est un test manquant, pas une panne. |
| **D7** | ⚠️ **estimation** — `threshold_for_precision` choisit le seuil le plus bas atteignant 97 % parmi 101 candidats, **sur le même échantillon qui mesure cette précision**, avec `min_covered=30`. Aucune borne de confiance, aucun jeu tenu à l'écart. | Simulation (scores sans pouvoir prédictif, n=1958, 200 tirages, seed fixée) : précision vraie 0,90 → 21/200 tirages retiennent un seuil « ≥97 % » ; 0,95 → **104/200** ; 0,96 → 152/200 | Ce chiffre alimente `dino_thresholds.spread_auto_accept_min`, donc l'auto-acceptation. Un seuil choisi sur 37 crops par la meilleure de 101 coupes est optimiste de plusieurs points. Correctifs : borne de Wilson, `min_covered` bien plus haut, ou split calibration/validation. Le taux vient d'une **simulation**, pas des vrais spreads (impossible tant que P3 n'est pas lancé). | ⏭ **requalifié, ouvert et assumé.** Aucun lot ne l'a porté, et il n'a pas été improvisé : c'est une question de **méthode statistique** qui change la sémantique de `shared/stats/sweep.py:threshold_for_precision`, pas un défaut de câblage ; un paramètre `confidence` que personne ne passerait serait un paramètre mort (§7.5). Ce qui neutralise le risque aujourd'hui est **mesuré, pas supposé** : depuis D4 aucun seuil ne sort tant qu'un bloqueur tient, et sur la vraie réplique les deux encodeurs en portent 2 chacun. D7 redevient le dernier garde manquant **le jour où P1 et P3 passent**. |
| **D8** | `calibration_blockers()` bloque **à vie** un run sur le gold **entier** : le bloqueur « echantillon » est ajouté dès que `gold_sample_n is not None`, sans le comparer à `gold_n_crops`. | `calibration_blockers(…, gold_sample_n=1958, gold_n_crops=1958, min_useful_classes=0)` *(le paramètre s'appelait `min_classes_with_exemplars` au moment de la mesure ; renommé le 2026-08-20 au soir avec le passage du garde P1 à la couverture utile)* → `['echantillon: run sur 1958 crops sur les 1958 du gold']` | Le seul contournement est de **mentir** sur la trace (`gold_sample_n=None`) pour débloquer le chiffre — l'inverse de l'intention du garde. Correctif : `and gold_n_crops is not None and gold_sample_n < gold_n_crops`. | ⚠️ **partiel.** Le cas nominal est corrigé (gold entier ⇒ plus de bloqueur ; total inconnu ⇒ toujours bloquant, écart assumé avec la lettre du correctif suggéré pour ne pas créer de porte de sortie par omission). **Reste ouvert : le garde est asymétrique.** `store/encoder_bench.py:293-306` teste `gold_sample_n < gold_n_crops` ; un run déclarant **99999** crops sur un gold de **1958** rend `[]`, donc `provisional=0` sur une trace manifestement fausse (désynchronisation `--gold` ↔ sidecar, ou payload forgé par un appelant tiers de `POST /ingest/encoder-bench`). Correctif minimal cohérent avec la doctrine du lot : `!=` au lieu de `<`. <br><br>**20/08 (matin) — ✅ côté store.** `gold_sample_n < gold_n_crops` devient `!=` (`store/encoder_bench.py`, commenté : un run déclarant plus de crops que le gold n'en contient est une trace incohérente, pas un run « plus que complet »). Test `test_echantillon_plus_grand_que_le_gold_est_incoherent` (99999 sur 1958) — mutation « `!=` remis à `<` » ⇒ rouge, revert ⇒ vert ; reproduit par les deux vérifications. Matrice ré-exercée sur le point d'entrée réel : `<` bloque, `=` passe, `>` bloque, `0` bloque. **⚠️ Mais la menace que le correctif se donne pour cible — « payload forgé par un appelant tiers de `POST /ingest/encoder-bench` », c'est le commentaire du correctif lui-même — passe par un chemin où aucun garde n'est appelé : voir M2.** |
| **D9** | `POST /ingest/encoder-bench` déclare `predictions: list[...] = []`, et `record_predictions` fait un `DELETE … WHERE run_id=?` **inconditionnel avant** de tester `if not rows`. | `record_run(r1)+record_predictions(r1,[a,b])` → 2 lignes ; puis `record_run(r1)` seul → `load_correctness` = `{}`, réponse **200** `{"n_predictions": 0}` | Ré-envoyer un run pour corriger sa `note` ou son `mcnemar_p` **efface ses prédictions par crop** — c'est-à-dire exactement ce pour quoi la table existe (« rejouer un apparié sans ré-encoder »). Correctif : rendre `predictions` obligatoire, ou ne purger que si la liste est fournie. | ✅ **corrigé, en deux temps.** Store : `record_predictions(…, purge_empty=False)` — une liste vide ne purge plus. Puis, trouvé **pendant l'intégration** : la réponse mentait encore (`n_predictions: 0` indistinguable de « rien touché »), corrigé par `predictions_replaced` + docstring. Mutations : purge inconditionnelle → 2 tests rouges ; champ retiré → 3 tests rouges. |

### 8.3 Défauts mineurs, mais du genre qui coûte une session

| # | Défaut | Preuve | État — 19/08 (nuit) puis 20/08 (matin) |
|---|---|---|---|
| **D10** | **P6-1 n'est PAS levé pour l'arm baseline.** `save_anchors` double-écrit le legacy dès que la banque porte l'encodeur de production — or `dinov2-vitl14` est **à la fois** l'encodeur servi et le bras baseline du banc. Un rebuild vitl14 sur une sélection différente écrase encore la banque servie, **et** son propre fichier scopé. | Sur tmpdir : `save_anchors(1250 ancres)` puis `save_anchors(3 ancres)` → `load_anchors('2eur_all')` = 3 **et** `load_anchors('2eur_all','dinov2-vitl14')` = 3. `write_legacy=False` existe, aucun appelant ne le passe. Atténuation : `bench_encoder_dino.py` n'appelle jamais `save_anchors` — trou ouvert, pas encore emprunté. | ✅ **corrigé.** La déduction « encodeur de production ⇒ écrire le legacy » est supprimée : `save_anchors(…, write_legacy=False)` par défaut, l'intention traverse les 4 builders, seul le CLI la passe (`--no-serve` pour ne pas servir). Mutation « déduction restaurée » → 7 tests rouges, dont la repro ci-contre (`3 == 9`). Le rebuild de production du PO est **inchangé**. ⚠️ Voir **N4**. |
| **D11** | **Le double-écrit crée deux fichiers divergeables, et un seul lecteur sur dix lit le scopé.** `_get_bank` (la review) lit le chemin scopé ; les **9 autres appelants** de `load_anchors` lisent le legacy. L'écriture des deux `.npz` (`anchors.py:238-242`) n'est ni atomique ni transactionnelle. | Reproduit : legacy à 9 ancres / scopé à 4 → les deux lecteurs rendent des banques différentes, aucun log, aucune exception. Le garde « banque stale » ne voit rien : les deux metas annoncent le même encodeur. | ✅ **corrigé.** Séparation par le **rôle** (banque servie ↔ artefact de banc), argumentée avec ses deux options écartées dans `anchors.py:138-196` ; écriture **atomique** (tmp + `os.replace`) ; `bank_id` partagé par les deux fichiers d'un même save. Le « 1 lecteur sur 10 » est mesuré clos : sur les 4 kinds réels, `_get_bank` et `load_anchors(kind)` rendent la même banque. Mutation « écriture non atomique » → la banque servie ressort tronquée, test rouge. ⚠️ Voir **N4**. |
| **D12** | `scripts/build_scan_prescription.py:54` code `DEFAULT_DB = ML_DIR/'state'/'eurio.replica.db'` **en dur** — le motif exact corrigé le même jour dans `build_dino_anchors.py` et `bench_gold.py`. Et `_strate_of` classe en `hors_banque` sans lire `n_siblings_in_bank`, alors que la docstring définit la strate par la présence d'un frère. | `go-task ml:scan-corpus:prescribe` ignore `EURIO_DB_PATH` → échoue sur une machine sans réplique, ou lit silencieusement une autre base. ⚠️ **estimation** pour le second point : les 7 pièces concernées ont toutes `sib=1` aujourd'hui, le défaut ne se manifeste pas encore. | ✅ **corrigé, et l'estimation est confirmée par la mesure.** `default_db()` via `store.resolve_db_path`, résolu **à l'appel** ; `_strate_of` lit `n_siblings_in_bank` → 5e strate `orpheline`, hors plan par défaut mais **nommée, comptée et réintégrable** (`--classes-par-strate orpheline=all`), pas filtrée en SQL. Run réel en lecture seule : 80 classes / 400 cellules / 985 captures / 11 sessions, **0 orpheline** — plan rigoureusement identique. Correctif = no-op sur la donnée du jour, garde pour la suivante. <br><br>**20/08 (matin) — ✅ inchangé, et son repli est devenu la convention du repo** (`eurio.replica.db`, cf. §8.7 et INT-1). |
| **D13** | `build_dino_anchors.py:228` imprime toujours le **chemin legacy en dur**, et l'aide `--db` (`:168`) annonce un défaut qui n'existe plus. | Pour une banque bâtie avec un encodeur non-production, la ligne « Path: » désigne un fichier que ce run n'a **pas** écrit — et qui est la banque servie. | ✅ **corrigé.** `written_paths()` rend une ligne par fichier, chacune **vérifiée sur disque** par `bank_id` (repli `built_at`+`count`) ; l'aide `--db` annonce la valeur réellement résolue et nomme `EURIO_DB_PATH`. Le run réel sur cache hit a révélé un mensonge résiduel de la première version du correctif (« Path: » désignant un artefact absent), corrigé et couvert. Réserve mineure : §8.6. |
| **D14** | `list_runs` / `get_run` / `load_correctness` exigent implicitement `conn.row_factory = sqlite3.Row` sans le documenter ni le poser. Le module expose pourtant `ensure_schema(conn)` pour « les bases locales et les tests ». | Sur `sqlite3.connect(':memory:')` nue : `TypeError: tuple indices must be integers…`. Contraste : `review/bench_gold.build_gold` pose **et restaure** `row_factory` lui-même. | ✅ **corrigé.** Contextmanager `_row_access(conn)` qui pose `sqlite3.Row` **et restaure** le `row_factory` de l'appelant (même patron que `review/bench_gold.py`). Mutation « restauration retirée » → 2 tests rouges. |
| **D15** | `GET /lab/encoder-bench/runs/{id}` avale une erreur de désérialisation de `sweep_json` (`except (TypeError, ValueError): sweep = None`) **sans aucun log** — aucun `logger` n'est instancié dans le module. | Une courbe corrompue devient indistinguable d'un run sans balayage, côté page admin comme côté logs. | ✅ **corrigé.** ERROR journalisé avec le `run_id`, **et** `sweep_error` dans la réponse (nul quand tout va bien) ; contre-épreuve : un sweep absent n'est pas signalé comme une erreur. Mutation « clé renommée » → 2 tests rouges. Import lean préservé (`logging` est stdlib). Réserve mineure : §8.6. |
| **D16** | `paired_compare` sur deux runs aux clés **disjointes** rend `n_paired=0, delta_acc=0.0, p_value=1.0` — soit « aucune différence significative » entre deux encodeurs qui n'ont partagé aucun crop. | `common = sorted(set(a) & set(b))` puis `mcnemar_exact(0,0)` → 1.0. Le champ `n_paired` est exposé, donc lisible — mais le `1.0` stocké dans `encoder_bench_runs.mcnemar_p` ne porte aucun marqueur. | ⚠️ **partiel.** Le cas **disjoint** est corrigé : `acc_a`/`acc_b`/`delta_acc`/`p_value` valent `None`, `comparable` est `False` (`shared/stats/paired.py:93-104`). **Reste ouvert : le recouvrement PARTIEL**, bien plus probable que le disjoint total (deux `--limit` différents, deux états de cache, ou l'un des runs amputé par N1). Sonde : 1 crop commun sur 501 → `mcnemar_p=1.0, b=0, c=0`, ligne **indiscernable** d'une égalité mesurée sur les 1958 crops. Et le champ qui la trahirait n'est persisté **nulle part** : `grep -n n_paired serving/migrations/0009_encoder_bench.sql state/schema.sql store/encoder_bench.py scripts/bench_encoder_dino.py` → **0 occurrence**. Correctif = persister `n_paired` — ce qui est le **seul** point où la conclusion « schéma : rien à changer » (§10.2) ne tient pas. <br><br>**20/08 (matin) — ✅ les trois volets sont fermés.** (1) **Mesure** : `paired_overlap(conn, run_id, baseline_run_id)` compte les crops communs en SQL, sans ré-encoder (`store/encoder_bench.py:281`). (2) **Garde** : `_paired_blockers` bloque un run qui déclare un `baseline_run_id` sans `n_paired`, et un `n_paired != périmètre du run`. (3) **Persistance** : la colonne `n_paired INTEGER` est posée dans `serving/migrations/0009_encoder_bench.sql` **et** son miroir `state/schema.sql`, à la suite de `mcnemar_c` — **amendement en place plutôt qu'un 0010**, parce que 0009 n'a jamais été appliquée (`sqlite3 "file:ml/state/eurio.replica.db?mode=ro" "SELECT COUNT(*) FROM encoder_bench_predictions"` → `no such table` ; `0 preds / 0 runs` en local). Et surtout (4) **le garde est armé sur le chemin réel** — il ne l'était nulle part, défaut trouvé pendant l'intégration : le calcul apparié est remonté **avant** la seconde mesure des bloqueurs dans `bench_encoder_dino.main()`, qui passe maintenant `baseline_run_id=` / `n_paired=` à `calibration_blockers`, et `build_run` trace `n_paired`. Tests : `test_paired_overlap_compte_les_crops_communs`, `test_recouvrement_partiel_bloque`, `test_baseline_sans_n_paired_bloque`, `test_n_paired_fait_l_aller_retour_en_base`, `test_record_run_leve_si_la_colonne_manque`, `test_le_recouvrement_apparie_est_trace_dans_le_run`, `test_un_recouvrement_partiel_bloque_le_candidat` — **deux mutations distinctes** prouvent que les deux moitiés du câblage comptent (`n_paired=None` dans `build_run` ⇒ 2 rouges ; `paired_by_model` retiré du 2ᵉ `_measure` ⇒ 1 rouge, c'est-à-dire exactement l'état d'avant l'armement). Réserves : le message du bloqueur dit « **seulement** N crops communs » même quand `n_paired > périmètre` (§8.6), et le garde n'est pas appelé côté canonique (M2). |

### 8.4 Ce qui a été contre-vérifié et tient

**mesure**, indépendamment des rapports d'agents :

- `mcnemar_exact` extrait = version de HEAD, **0 divergence** (3600 couples au
  constat ; re-vérifié après la passe de correction sur les 1600 couples
  `b,c ∈ [0,40[` → `ecarts vs HEAD: []`) ;
- la review n'est pas aveugle : les 4 banques `.npz` se chargent inchangées,
  **mtime epoch + taille + md5 identiques** au début et à la fin de la passe de
  correction (`foundation_anchors_2eur_all.npz` : `1787099301 6631794
  c08338be2796da6f55027d7204e476a9`), aucun `.npz` neuf créé ;
- le gold se rebâtit **byte-identique** (`gold_version=9b15176b3309` à la
  date de ce constat ; `0ecbb1d70e3c` depuis le correctif D2/D6 — la
  propriété tient, c'est le hash qui a bougé), et son sidecar recalculé depuis
  la réplique redonne exactement le hash du sidecar committé ;
- les tests neufs ne sont pas tautologiques : **18 mutations** posées puis
  revertées sur les gardes de la passe de correction, **17 rougissent le test
  attendu**. La 18e (`M9`) est celle qui a révélé la dette de couverture de D6 ;
- suite complète : **1690 passed, 0 failed** au constat ; **1754 passed** après
  les quatre lots + intégration (+64 tests). ⚠️ Ce compte n'est pas une
  propriété stable — voir **N3** ;
- cohérence inter-modules : une seule définition de `mcnemar_exact` /
  `paired_compare` / `precision_coverage_curve` / `propose_threshold` ; noms de
  tables alignés migration ↔ store ↔ routes ; comparaison programmatique
  DDL ↔ dataclass ↔ payload Pydantic → écart vide (sauf `run_id`, passé à part) ;
  scopes d'auth alignés sur le précédent (`lab:read` en lecture, `ingest:write`
  en ingest) ;
- import lean vérifié jusqu'au bout de la chaîne montée : `shared.stats` +
  `store.encoder_bench` + `serving.encoder_bench_routes` en sous-processus →
  aucun de `numpy/torch/cv2/timm/scipy`.

**Ajout du 2026-08-20**, après la seconde passe :

- suite complète : **1797 passed** (+43), **neuf** exécutions consécutives sans
  échec — six à l'intégration, trois en vérification, en ordre aléatoire et en
  `-p no:randomly`. ⚠️ Toujours pas une propriété stable (**N3**) ;
- tâche du chantier : `go-task ml:encoder-bench:test` → **197 passed** (la liste
  a été élargie, `test_db_path_defaults_cli.py` y est entré : la convention de
  repli n'était gardée que par la suite complète) ;
- **neuf mutations posées puis revertées** sur les gardes de la seconde passe,
  **neuf rougissent le test attendu** ; la dixième est **M6**, un test dont le
  corps est du code mort ;
- la banque servie n'a pas bougé de la passe : `md5` des deux `.npz`
  `e0a5fedd413e1a86e755a2f393c6278c`, mtime `2026-08-19 16:36:14`, relevés
  identiques à l'ouverture et à la clôture des quatre agents ;
- ⚠️ **Piège de méthode, coûteux, à retenir** : entre deux mutations, purger
  `__pycache__` (`find . -path ./.venv -prune -o -name __pycache__ -print | xargs rm -rf`).
  Un `cp` de restauration suivi d'un pytest dans la même seconde laisse un
  `.pyc` périmé : on mesure alors la version *précédente* du code. Un bisect a
  rendu « chacune des 4 mutations fait passer le test », ce qui était impossible.

### 8.5 Défauts NEUFS, trouvés en vérifiant la PREMIÈRE passe de correction

Deux vérifications adversariales ont tourné **sur les correctifs**. Elles ont
confirmé dix corrections et trouvé six problèmes que personne n'avait listés —
dont trois **introduits par le câblage lui-même**. Chacun est reproduit par une
exécution, pas par une lecture.

| # | Défaut | Preuve | Effet | État |
|---|---|---|---|---|
| **N1** | **Les crops que l'encodeur n'a pas pu encoder disparaissent en silence.** `score_crops` compte `n_not_encoded` (crops présents sur disque mais écartés par `encode_paths` : JPEG tronqué, EXIF cassé, OOM) — `bench_encoder_dino.py:254, 260, 309`. **Aucun appelant ne le lit** : `grep -rn n_not_encoded --include='*.py'` → la définition et deux fixtures de test, rien d'autre. Il n'est ni imprimé, ni dans le rapport, ni dans `EncoderBenchRun`, ni pris en compte par le bloqueur « echantillon », qui se calcule (`:560`) sur les crops **soumis**. | Sonde : `_bench_model` doublé rendant `n_not_encoded=1500` avec `n_in_scope=2`, gold de 3 crops tous en cache → `gold_sample_n=None`, `provisional_reason` sans mention d'échantillon, `"1500"` absent de stdout **et** de stderr. | Un cache MinIO partiel ou une série d'images corrompues produit un **recall publiable et faux**, annoncé « gold entier ». C'est le motif exact du catalogue `eurio-verify`. Le chemin voisin (crops **absents du cache**) est, lui, compté, imprimé et rend `gold_sample_n` non nul : c'est un oubli d'un seul des deux chemins de perte. | 🔴 **ouvert.** À fermer **avant** le premier run réel, avec D1. <br><br>**20/08 (matin) — ✅ corrigé et vérifié.** `n_not_encoded` est, **par modèle** : imprimé sur stderr (`!! <modèle> : N crops présents en cache mais NON ENCODÉS`), porté dans le rapport `.md` (colonne « non encodés » + section `## Crops soumis mais NON encodés`), et surtout **retiré de la couverture du gold** — `gold_sample_n = max(len(crops) - n_not_encoded, 0)` au lieu de `None`, ce qui déclenche le bloqueur « echantillon » et `provisional=1`. Les deux chemins de perte (absent du cache / illisible à l'encodage) sont alignés. Conséquence de câblage assumée : les bloqueurs sont mesurés **deux fois** (avant le bench pour la bannière de tête, après pour la bannière de pied, le rapport et la trace). Tests : `test_les_crops_non_encodes_sont_comptes_imprimes_et_bloquent` et son garde-fou anti-sur-blocage `test_le_gold_entier_reste_le_gold_entier_sans_perte` — mutation `sample_by_model = None` ⇒ 2 rouges. Cas extrême re-exercé : `gold_sample_n=0` sur 1958 ⇒ bloqueur, pas de recall publié ; pas de division par zéro (`_ratio(n, d)` rend `None` si `d` est nul). |
| **N2** | **Un encodeur qui explose sort en code 0 et le rapport ne le dit pas.** `bench_encoder_dino.py:599` imprime `!! {m} failed:` sur stderr ; `:737` fait `return 1 if failed else 0` où `failed` ne compte **que** les échecs de push. La bannière, calculée avant le bench sur `args.models`, continue de nommer l'encodeur. | Sonde : 2 modèles, le premier lève `RuntimeError('CUDA out of memory')` → `RC = 0`, **une seule ligne** dans la table du rapport, une seule dans la traçabilité, et la bannière cite quand même le modèle tombé. | Un banc de nuit sur 4 encodeurs dont 3 tombent rend `exit=0` et un rapport à une ligne. Le `.md` archivé donne à croire que les 4 ont été évalués ; un `go-task` en CI ou un `&&` enchaîné n'apprend rien. Le message d'échec ne vit que sur stderr — le flux que `--out` ne capture pas, la faille même que `test_la_banniere_survit_a_la_redirection_du_rapport` ferme pour la bannière. | 🔴 **ouvert.** Peu coûteux : compter les modèles tombés dans `failed` et les inscrire dans le rapport. <br><br>**20/08 (matin) — ✅ corrigé et vérifié.** Un encodeur qui lève est retenu dans `failures` : recopié **dans le rapport** (`## Encodeurs TOMBÉS`) et **dans la bannière de pied** — donc dans le `.md` archivé, que stderr n'atteint pas —, retiré de la table des résultats, et `failed = len(failures) + échecs de push` fait sortir le banc en **code 1**. La bannière de pied est recalculée sur les seuls modèles réellement benchés (`[r["model"] for r in results]`) : un banc amputé ne peut plus se déclarer « ✔ CALIBRATION PROMOUVABLE ». Tests : `test_un_encodeur_tombe_sort_en_erreur_et_le_rapport_le_dit`, `test_la_banniere_finale_ne_credite_pas_l_encodeur_tombe` — mutation `failed = 0` ⇒ rouge, revert ⇒ `27 passed`. ⚠️ **Angle mort consigné, non mesuré** : si le modèle désigné par `--baseline` est celui qui tombe, la comparaison appariée disparaît sans un mot (§8.6). |
| **N3** | **La suite est instable — et c'est le test qui tient D8 qui vacille.** `test_encoder_bench_store.py::test_calibration_blockers_gold_entier_nest_pas_un_echantillon` a échoué **1 fois sur 6** exécutions complètes en ordre fixe (`-p no:randomly`), sur un arbre inchangé. | `1 failed, 1753 passed in 73.70s` (exécution 1) puis `1754 passed` (exécutions 2 à 6). Isolé : `1 passed in 0.35s`. Intra-fichier sur 40 graines `pytest-randomly` : **0 échec / 40**. → interaction **inter-fichiers**, pas d'ordre intra-fichier ni de graine. | R6 (« un échec redevient un signal ») est entamé : une suite qui rougit sans raison retrouvée rend le prochain échec réel indistinguable du bruit. C'est le mécanisme même qui avait laissé la suite rouge pendant des semaines. **Le compte « 1754 passed » n'est donc pas une propriété acquise.** | 🔍 **enquête ouverte.** Piste non explorée, ⚠️ estimation : les 4 fichiers qui manipulent `sys.modules` (`test_threshold_calibration.py`, `test_ingest_encoder_bench.py`, `test_lab_read_routes.py`, `test_coin_assets_lean.py`) — la famille de cause de R6. Méthode la moins chère : `pytest tests --lf` immédiatement après un échec, puis déselection par moitiés. <br><br>**20/08 (matin) — 🔍 toujours ouvert, et toujours non reproduit.** Neuf exécutions complètes supplémentaires (six à l'intégration, trois en vérification), **`1797 passed` à chaque fois**, en ordre aléatoire et en `-p no:randomly`. À 1 échec sur 6, la probabilité de neuf passes vertes si le défaut tenait encore est `(5/6)^9 ≈ 19 %` : c'est faible, **ce n'est pas une preuve d'extinction**. Hypothèse ⚠️ non démontrée : la réécriture de la fixture `_seed_etat_du_jour` (correctif D1) l'aurait éteinte. Ce qui est vérifiable aujourd'hui : plus aucune dépendance temporelle dans le chemin testé (`grep -n "now()\|utcnow\|datetime" store/encoder_bench.py` → rien ; les six sites de la fixture posent `computed_at='2026-09-01T00:00:00+00:00'` en dur) et une connexion `:memory:` neuve par test. **Le compte `1797 passed` n'est pas davantage une propriété acquise que ne l'était `1754`.** |
| **N4** | **Le cache de `_get_bank` remet les deux rôles sur la même clé.** `sources/_base/steps/auto_validate.py:133-181` calcule `expected = encoder_version or encoder_version_for_kind(kind)` puis met en cache sous `key = (kind, expected)`. Les deux rôles que D11 sépare volontairement en deux **fichiers** partagent donc le même créneau de cache dès que l'encodeur explicite est celui de production. | Exécuté dans un `STATE_DIR` temporaire : banque servie à 9 ancres, artefact de banc à 3. **A.** review seule → `_get_bank(kind) = 9`. **B.** un `_get_bank(kind, prod)` d'abord → `3`, puis `_get_bank(kind) = 3`. | Dans un même processus, un appel scopé fait servir à la review la banque du **bras baseline du banc** — le symptôme D10 reconstitué par le cache, et le garde D3 reste muet puisque l'encodeur correspond. | 🔴 **ouvert, latent.** Aucun appelant de production ne passe d'encodeur aujourd'hui (les 7 appels de `_get_bank(` sont tous sans encodeur). Correctif : mettre le **rôle** dans la clé (`None` conservé tel quel). `test_get_bank_cache_par_couple` ne l'attrape pas : il n'exerce que deux encodeurs **différents**. <br><br>**20/08 (matin) — 🔴 inchangé.** Aucun lot ne l'a porté. Vérifié : `sources/_base/steps/auto_validate.py:153-156` fait toujours `expected = encoder_version or encoder_version_for_kind(anchors_kind)` puis `key = (anchors_kind, expected)`. |
| **N5** | **Le flip Direction A ne couvre pas `shared/storage/cascade.py`.** `_db_path()` lit `EURIO_DB_PATH` et `_connect()` fait `sqlite3.connect(str(db))` en **lecture-écriture**, sans passer par `store.connection` — donc sans `EURIO_DB_READONLY` (`store/connection.py:23`). En prime, `mark_missing_in_storage` avale toute exception en WARNING. | Exécuté sur une **copie** de la réplique, `EURIO_DB_READONLY=1` : `avant: [('present',)] → mark_missing_in_storage -> 1 → apres: [('missing_in_storage',)]`. | **Contredit une affirmation des rapports de lot** (« sous Direction A cette écriture échouerait ») : elle n'échouerait pas. Le nouveau chemin `bench_encoder_dino → resolve_local_paths → local_path` expose les 1958 crops du gold à cette écriture sur 404 MinIO. Exposition **nulle aujourd'hui** : les 1958 crops sont dans le cache local (comptés fichier par fichier, 0 manquant), et le défaut est **préexistant** (HEAD appelait déjà `local_path`) — ce qui est neuf, c'est la mitigation affirmée à tort. | 🔴 **ouvert.** Deux issues : faire passer `cascade` par `store` (donc par le flip), ou retirer l'affirmation rassurante et écrire ce qui se passe réellement. <br><br>**20/08 (matin) — 🔴 inchangé.** Vérifié : `shared/storage/cascade.py:62-66` fait toujours `sqlite3.connect(str(db))` en lecture-écriture, sans passer par `store.connection`, donc hors du flip `EURIO_DB_READONLY`. |
| **N6** | **Deux points d'entrée, deux replis de base divergents.** `bench_encoder_dino.py:107` fait `resolve_db_path(ML_DIR/'state'/'eurio.db')` — la base **périmée** (6205 assets) — quand `EURIO_DB_PATH` est absent (le cas « shell hors direnv »), alors que le correctif D12 a choisi `eurio.replica.db` comme repli pour `build_scan_prescription`. | Lecture des deux sources ; conséquence mesurée : sur `eurio.db`, `calibration_blockers` rend **2 bloqueurs** (grâce au correctif D1/P3), donc le banc bloque au lieu de mentir. | Bénin aujourd'hui, mais c'est exactement la famille de la cause racine R1 (`--db` codé en dur) et de la mémoire « shell hors direnv ». L'incohérence de repli mérite d'être tranchée une fois pour toutes. | 🔴 **ouvert, bénin.** <br><br>**20/08 (matin) — ✅ corrigé, et l'incohérence de repli est tranchée pour le repo.** `DB_PATH = resolve_db_path(ML_DIR/'state'/'eurio.db')` (constante résolue à l'import) devient `def default_db(): return resolve_db_path(ML_DIR / "state" / "eurio.replica.db")`, **résolue à l'appel**. La convention retenue — le repli est **toujours** `eurio.replica.db` — est écrite dans la docstring de `store.resolve_db_path` (+31 lignes) et appliquée aux 10 scripts du lot C ; elle est motivée et détaillée en **§8.7**. Test : `test_le_repli_de_base_est_la_replique_pas_la_base_de_travail`, plus le garde AST `test_tous_les_scripts_corriges_replient_sur_la_replique` — mutation « `mine_coin_aliases` remis sur `eurio.db` » ⇒ rouge. Câblage exercé sur le vrai point d'entrée : `env -u EURIO_DB_PATH ./.venv/bin/python -m scripts.bench_encoder_dino --help` annonce `…/ml/state/eurio.replica.db`. ⚠️ **La justification écrite de cette convention est en partie fausse (M3) et elle n'est pas appliquée partout (M4)** — le comportement de `bench_encoder_dino`, lui, est correct : il ouvre `sqlite3.connect(f"file:{db}?mode=ro", uri=True)`, jamais un `Store`. |

### 8.6 Consigné, non retenu comme défaut

- `GET /lab/encoder-bench/runs/{id}` type `sweep: list \| None` sans vérifier que
  le JSON désérialisé **est** une liste : un `sweep_json` valant la chaîne
  `"null"` rendrait `sweep=None, sweep_error=None` — le silence que D15 ferme
  ailleurs. Le banc ne produit pas ce cas.
- `written_paths` imprime « Servie: `<chemin>` » sur un cache hit où la banque
  servie n'a pas été réécrite. La ligne n'est pas fausse (le fichier **contient**
  bien la banque rendue), mais dans une liste de « chemins écrits » elle se lit
  comme une écriture.
- Le message du bloqueur **P1** propose `scripts.build_dino_anchors --kind
  2eur_all --force --push`, qui sous le devShell (`EURIO_DB_READONLY=1`) refuse
  de démarrer pour `2eur_all`. Bruyamment — donc acceptable — mais le message
  gagnerait à le dire.
- **Préexistant, hors périmètre** : la suite complète **modifie**
  `ml/state/eurio.db` (md5 `2d290f36…` → `6383cfc6…` en une exécution). Bissecté :
  `tests/test_coins_routes.py:27-43` ouvre la vraie base avant de rebinder sur un
  tmp. Le fichier n'a pas été touché par cette session (`git log -1` → `4cc1590`) :
  ce n'est pas une régression du lot, mais une suite de tests qui écrit sur une
  vraie base mérite sa propre correction. **20/08 : le mécanisme est identifié
  et confirmé** — voir **M11**.

Ajouts du 2026-08-20 :

- **Le message du bloqueur apparié n'a pas le mot juste dans un cas.** Quand
  `n_paired > périmètre du run`, `_paired_blockers` dit « **seulement** 1958
  crops communs … sur les 501 du run ». Le verdict est bon (la trace est
  incohérente, elle doit bloquer), le mot est faux et envoie chercher un run
  amputé. C'est le pendant exact de ce que D8 a corrigé côté échantillon en
  passant `<` à `!=`, sans que le message correspondant ait suivi.
- **Si le modèle `--baseline` est celui qui tombe, la comparaison appariée
  disparaît sans un mot.** `baseline_spec not in correctness` ⇒ tous les runs
  reçoivent `(None, None)`. Le banc sort tout de même en code 1 grâce à N2,
  donc l'opérateur est averti *de quelque chose* — mais pas de ça.
  ⚠️ **non mesuré** (aucun bench réel n'a été lancé).
- **`bench_encoder_dino._measure` trace le `bank_build_id` de l'encodeur de
  PRODUCTION pour tous les runs**, y compris un candidat DINOv3
  (`_bank_build_id(conn, BENCH_KIND, base.encoder_version)`). C'est peut-être
  voulu — la sélection des images d'ancres vient bien de ce build — mais ni le
  commentaire de la colonne (`-- dino_anchor_builds.build_id, si connu`) ni la
  docstring ne tranchent. Un lecteur qui joindrait `encoder_bench_runs.bank_build_id`
  à `dino_anchor_builds` attribuerait un build `dinov2-vitl14` à un run `dinov3`.
  ⚠️ **non instruit.**

---

### 8.7 Le motif : le chemin de base codé en dur

> Ce §8.7 n'est pas un défaut de plus. C'est la **forme** que trois défauts
> distincts ont prise le même jour, dans trois fichiers écrits par trois
> personnes différentes. Écrit ici pour que la quatrième occurrence soit
> reconnue en trente secondes au lieu d'une session.

#### Le symptôme

Un entrypoint Python déclare sa base par un littéral :

```python
DB_PATH = ML_DIR / "state" / "eurio.db"          # le défaut
DB_PATH = resolve_db_path(ML_DIR / "state" / "eurio.replica.db")   # la forme correcte
```

Il ignore donc `EURIO_DB_PATH`, la variable que le devShell pose sur la base
réellement en service. Trois occurrences trouvées le 2026-08-19, plus neuf
scripts frères audités dans la foulée :

| Occurrence | Forme | Ce que ça a coûté |
|---|---|---|
| `scripts/build_dino_anchors.py` | `DB_PATH` littéral, `ml/tasks.yml` lance sans `--db` | **La cause racine du jour** : la banque servie bâtie pendant des semaines sur 6205 assets au lieu de 12454 → 125 classes à exemplaires au lieu de 182 (§2.1) |
| `scripts/bench_encoder_dino.py` | `resolve_db_path(…/eurio.db)` — le resolver est là, mais le **repli** est la base périmée | N6 : bénin ce jour-là (le garde P3 bloquait), mais deux points d'entrée du même chantier avec deux replis divergents |
| `scripts/backfill_dino_predictions.py` | `DB_PATH` littéral | C1 : le geste P3 lui-même, celui qui recalcule 12454 prédictions |
| `scripts/backfill_coin_source_status.py` et 8 autres | `DB_PATH` littéral ; **plus une variante** : `Store(resolve_db_path(args.db))`, qui écrase la valeur passée en `--db` puisque le resolver rend `EURIO_DB_PATH` **quel que soit son argument** — le drapeau est un leurre | C2..C10 |

#### Pourquoi il est invisible

**Une base périmée répond normalement.** Elle ne lève pas, elle ne journalise
rien, elle rend des lignes bien formées — simplement moins nombreuses. Le
script imprime « 1100 candidats », « 0 erreurs », et **c'est vrai** : il a
correctement traité tout ce qu'il a vu. Rien dans la sortie ne dit ce qu'il n'a
pas vu.

Trois amplificateurs, tous mesurés :

1. **`Store()` sur un chemin inexistant crée le fichier et bootstrappe le
   schéma.** Reproduit :
   ```
   $ EURIO_DB_READONLY= ./.venv/bin/python -c "
   from store import Store; from pathlib import Path
   p = Path('/tmp/dbdemo/inexistante.db'); s = Store(p, read_only=False)
   print('fichier créé ?', p.exists())
   print('image_assets =', s._connection().execute('SELECT COUNT(*) FROM image_assets').fetchone()[0])"
   fichier créé ? True
   image_assets = 0
   ```
   Sur le VPS, où `ml/state/eurio.db` n'existe pas, chacun des dix scripts
   annonçait donc « 0 candidats, 0 erreurs » sur une base vide qu'il venait de
   créer. C'est le catalogue `eurio-verify` mot pour mot : *une valeur par
   défaut plausible là où il aurait fallu une erreur*.
2. **Sous Direction A, la présence d'un résultat en base ne prouve pas que le
   calcul y a lu ses entrées.** C'est ce qui a fait écarter la bonne hypothèse
   pendant six tours : la réplique portait les 1250 références, donc « le build
   a lu la réplique » — faux, elles y arrivent par `POST /ingest/dino-references`
   (§P1, « ce que j'avais éliminé comme cause »).
3. **Le défaut ne se manifeste pas sur la commande nominale.** Requalification
   C11 : dans le devShell, `sync_enabled()` est vrai, donc `--push` est actif
   par défaut et `backfill_dino_predictions` pull une réplique scratch neuve —
   `args.db` n'est **jamais ouvert**. Le piège est armé par `--no-push`, ou sur
   une machine sans `EURIO_API_URL`. Un test qui aurait lancé la commande
   nominale aurait conclu « tout va bien ».

#### La convention retenue (2026-08-20)

Les six premiers points ont été posés à la clôture de M1/M2 ; les trois derniers
sont ce que la vérification du soir a coûté. **Deux d'entre eux (7 et 8) ne sont
pas encore appliqués** — ils décrivent la parade, pas l'état du code : Q1..Q6
sont ouverts.

**`resolve_db_path(<ML_DIR>/"state"/"eurio.replica.db")`, résolu à l'appel, et
le repli est TOUJOURS la réplique.** Écrite dans la docstring de
`store.resolve_db_path` (`ml/store/__init__.py`).

Le discriminant **n'est pas** « lecteur ou écrivain » — c'est l'axe sur lequel
les deux lots de correction se sont opposés, et il ne tranche pas. C'est
**bruit ou silence**, et il se vérifie en une ligne (`store/connection.py:86`) :

```python
if not read_only and self._db_path.name == "eurio.replica.db":
    raise RuntimeError("Refus d'ouvrir la réplique eurio.replica.db en écriture : "
                       "poser EURIO_DB_READONLY=1 …")
```

| Repli | Lecteur hors devShell | Écrivain hors devShell |
|---|---|---|
| `eurio.db` | lit 6205 assets au lieu de 12454, **sans un mot** | sur le VPS : base vide **créée**, « 0 candidats, 0 erreurs » |
| **`eurio.replica.db`** | lit le vrai corpus si l'ouverture est explicitement `read_only` ; **échoue bruyamment** sinon (cf. M3) | `RuntimeError` nommant la marche à suivre |

Les deux issues du repli retenu sont donc des **messages**. Un repli
inscriptible achète la commodité au prix du silence, et dans ce repo le silence
est le mode de panne dominant. Corollaire écrit dans la même docstring :
**`resolve_db_path` n'a sa place que sur le DÉFAUT** ; `Store(resolve_db_path(args.db))`
est interdit, il transforme le drapeau `--db` en leurre.

⚠️ **La convention n'est pas encore la réalité du repo** : ~39 entrypoints
portent encore un littéral (C12) et 55 sites passent par `resolve_db_path` avec
l'autre repli — dont `scripts/build_dino_anchors.py:57` et
`scripts/bench_gold.py:46`, c'est-à-dire le script de la cause racine et un
fichier neuf de ce chantier (**M4**).

#### Comment on l'attrape la prochaine fois

1. **Un garde AST, pas une relecture.** `tests/test_db_path_defaults_cli.py`
   parcourt l'AST des scripts d'une liste et refuse un littéral comme défaut de
   `--db`, ainsi que tout `resolve_db_path(args.*)`. AST plutôt qu'`import`
   parce que `backfill_denom` / `backfill_face` tirent torch+DINO à l'import
   (~40 s chacun). ⚠️ Sa faiblesse est nommée en M4 : il ne garde que la liste
   qu'on lui donne.
2. **Exécuter le point d'entrée, pas le prédicat.** `import m; print(m.DB_PATH)`
   et `--help` prouvent la constante, jamais le câblage. La vérification qui
   compte est celle qui **ouvre** la base :
   ```
   $ env -u EURIO_DB_PATH -u EURIO_DB_READONLY ./.venv/bin/python -m scripts.<x> --help
   $ EURIO_DB_PATH=/tmp/ailleurs.db ./.venv/bin/python -m scripts.<x> --help
   ```
   C'est cette distinction qui a rendu M3 visible alors que 27 tests verts
   affirmaient le contraire.
3. **Un témoin de volume dans la sortie du script.** Un backfill qui imprime
   « N candidate assets in scope » donne à l'opérateur le seul chiffre qui
   distingue une base saine d'une base périmée (12454 vs 6205). C'est ce qui a
   été mis dans le `desc:` de `ml:dino-predictions:backfill` et dans
   [`GESTE-P3.md`](GESTE-P3.md). **Un script qui ne dit pas combien il a vu ne
   peut pas être vérifié.**

---

### 8.8 Défauts NEUFS, trouvés en vérifiant la SECONDE passe de correction

Deux vérifications adversariales ont tourné sur les correctifs de la nuit du 19
au 20. Elles ont confirmé les corrections de D1(P1), D5, D8, D16, N1, N2, N6 —
**neuf mutations posées, neuf rougeurs**, revert réel à chaque fois — et rendu
onze problèmes que personne n'avait listés. Chacun est reproduit par une
exécution.

**La lentille qui a payé** : « le garde garde-t-il *là où la chose arrive* ? ».
D1 avait été diagnostiqué comme *un garde qui ne se déclenche pas dans le cas
qu'il devait couvrir*. M1 et M2 montrent une forme plus stable de la même
maladie : **le garde est juste, et il est branché ailleurs que là où la chose
arrive.** Une campagne de mutation ne peut pas les voir — elle prouve qu'un test
*couvre* le code écrit, jamais que ce code soit *appelé* sur le chemin réel.

| # | Défaut | Preuve | Effet | État au 20/08 (matin) |
|---|---|---|---|---|
| **M1** | **La table sur laquelle le garde P1 compte ne peut pas porter deux encodeurs.** Le correctif D1/P1 scope son `COUNT` sur `encoder_version` et le justifie, dans sa docstring, par « la table est scopée `UNIQUE(anchors_kind, encoder_version, class_id)` ». **Faux pour les lignes `fps`** : cet index est **partiel** (`… WHERE asset_id IS NULL`, `state/schema.sql:576-578`, donc canoniques seulement) et la PK réelle est `PRIMARY KEY (anchors_kind, class_id, eurio_id, asset_id)` (`:565`), **sans l'encodeur**. Or `store/dino_references.py:107` écrit en `INSERT OR REPLACE`. | Sonde sur le **DDL réel** extrait de `state/schema.sql` (pas la fixture), via le vrai writer `replace_auto_references`, 200 classes à un exemplaire `fps`, les deux encodeurs piochant les mêmes `asset_id` — le cas nominal, c'est le même pool de crops validés : `apres build PROD : prod=200 cand=0` puis `apres build CAND : prod=0 cand=200`, `total lignes fps : 200`. | **Bâtir la banque d'un encodeur candidat DÉTRUIT les références de la production.** Le jour du premier build DINOv3, les 182 classes à exemplaires de `dinov2-vitl14` tombent à 0, P1 se met à bloquer la **production**, et la traçabilité du build `23c637d93b43` — objet du commit `ddc8ed9 « la banque redevient traçable »` — disparaît sans un mot. Le `.npz` servi, lui, ne bouge pas : muet côté scan, visible seulement en base. **Pourquoi aucun test ne l'attrape** : la fixture `_ajoute_refs_fps` fabrique un `asset_id` par encodeur (`f"asset-{encoder_version}-{i}"`), donc le scénario multi-encodeur n'est exprimable dans les tests que sous une forme que le monde réel ne produit pas. | ✅ **corrigé le 2026-08-20**, issue (a) — l'encodeur entre dans l'**identité** de la ligne. Trois gestes : `state/schema.sql` porte `encoder_version TEXT NOT NULL DEFAULT ''` et `PRIMARY KEY (anchors_kind, encoder_version, class_id, eurio_id, asset_id)` ; la migration **0010** `0010_dino_refs_encoder_dans_la_cle.sql` reconstruit la table (SQLite ne sait pas changer une PK) avec vérification de compte par `CHECK (delta = 0)` ; et `store/dino_references._exige_encodeur_dans_la_cle` **refuse d'écrire** sur une table à l'ancienne clé — le garde est sur le chemin où la chose arrive, pas seulement dans la migration. Issue (c) faite aussi : les deux docstrings de `store/encoder_bench.py` (`_p1_blockers`, `calibration_blockers`) disent maintenant que le scope vient de la PK et que `idx_dino_class_refs_canonical` est **partiel aux canoniques**. Répétition sur copie `/tmp` de la réplique (`VACUUM INTO`, jamais `cp`) par le VRAI runner `serving.db_migrate.run_migrations` : **1250 lignes avant, 1250 après**, PK correcte, 4 index présents, `foreign_key_check` vide ; puis le VRAI writer rejoué sous un encodeur candidat sur les mêmes crops → la production garde ses 664 canoniques et ses 586 `fps` au lieu de tomber à 0. Tests : `tests/test_dino_refs_encoder_key.py` (7), rouge/vert prouvé par revert réel (6 failed → 7 passed). ⚠️ **Reste un geste humain** : 0010 ne prend effet au canonique qu'au **redémarrage de `eurio-api`** (§9). <br><br>✅ **confirmé le 2026-08-20 (soir) par deux vérifications indépendantes.** La migration a été rejouée par le VRAI `serving.db_migrate.run_migrations` sur copie `VACUUM INTO` de la réplique : **1250 → 1250 lignes, contenu byte-identique** (`sha256` des 11 colonnes de toutes les lignes triées, inchangé), PK correcte, 4 index, aucune table ni temp résiduelle, `foreign_key_check` vide, `integrity_check ok` ; **idempotente** (2ᵉ application : mêmes lignes, mêmes index) ; rejouée à **1536 lignes** (283 `fps` réels ajoutés + 3 lignes `encoder_version IS NULL` semées) → 1536 après, les 3 NULL repliées sur `''` — **la réserve « non vérifiable à 1533 lignes » est levée en substance**. Le refus documenté est réel ET atomique : deux canoniques NULL de la même classe → `IntegrityError`, transaction annulée, table intacte à l'ancienne forme, **0010 non enregistrée**. Le garde du writer refuse bien une table à l'ancienne clé. ⚠️ **Mais le correctif arme trois défauts neufs** : il rend la coexistence de deux encodeurs possible, or **aucun lecteur** de la table n'est scopé par encodeur (**Q6**), le pin/exclude humain ne remplace plus la ligne auto (**Q8**), et le garde arrive après les ~4 min d'encodage avec un message perdu en 500 générique par HTTP (**Q10**). Voir §8.10. |
| **M2** | **`POST /ingest/encoder-bench` n'appelle aucun garde.** `serving/ingest_routes.py` construit `EncoderBenchRun(**payload.run.model_dump())` et appelle `record_run` sans jamais passer par `calibration_blockers` : `provisional`, `provisional_reason`, `gold_sample_n`, `n_paired` sont recopiés tels quels depuis le corps HTTP. `paired_overlap` — écrite pour « vérifier un run déjà poussé, y compris un run dont le `n_paired` déclaré serait faux » — n'a **aucun appelant** (`grep -rn paired_overlap ml/scripts ml/serving ml/store ml/client` → sa définition et sa docstring). | Sonde contre la vraie route FastAPI, base `tempfile.mkdtemp()`. Payload forgé : `gold_n_crops=1958, gold_sample_n=99999, baseline_run_id='une-baseline', n_paired=1, recall1=0.99, provisional=0`. → `HTTP 200`, et en base `{'provisional': 0, 'provisional_reason': None, 'gold_sample_n': 99999, 'n_paired': 1, 'recall1': 0.99}`. Le même triplet, soumis au store : `echantillon: run sur 99999 crops sur les 1958 du gold` + `apparie: seulement 1 crops communs …`. | **Le garde a la bonne réponse et n'est pas consulté.** `provisional=0` avec `provisional_reason=NULL` est exactement la ligne que la page admin lira comme « ✔ promouvable ». Le commentaire du correctif D8 nomme pourtant sa menace : « payload forgé par un appelant tiers de `POST /ingest/encoder-bench` » — **le garde a été durci sur le seul chemin où la menace citée ne passe pas**. `tests/test_ingest_encoder_bench.py` vérifie que le *défaut* de `provisional` est 1 ; aucun test n'envoie `provisional=0` avec des chiffres incohérents. | ✅ **corrigé le 2026-08-20**, et fermé plus bas que la route. L'invariant est dans **`store.encoder_bench.record_run`** — seule écriture SQL de `encoder_bench_runs` du produit : il mesure les bloqueurs sur la connexion de **destination** dès que `provisional == 0` et lève `CalibrationNotVerified` AVANT l'INSERT. La route, elle, **corrige plutôt que refuse** (argumenté dans son docstring : sous Direction A l'appelant mesure sur une réplique en retard, un désaccord est le cas normal, et un 4xx jetterait des heures de GPU) : elle écrit les prédictions d'abord, recompte `n_paired` par `measured_overlap` → `paired_overlap` (qui n'avait aucun appelant, et qui rend `None` — pas `0` — quand la mesure est impossible), remesure les bloqueurs, force `provisional=1`, journalise (WARNING si le verdict ou `n_paired` bougent, INFO si seule la raison est rafraîchie) et renvoie `provisional`/`blockers`/`corrections`. Le banc imprime « ⚠ CORRIGÉ PAR LE CANONIQUE : … ». `recall1` survit : ce que le serveur ne sait pas refaire n'est pas jeté. Tests : `tests/test_encoder_bench_guard_family.py` (13), **quatre mutations** rouges puis vertes après revert réel. <br><br>⚠️ **requalifié le 2026-08-20 (soir) : partiellement corrigé.** Le **câblage** est confirmé — `record_run` est bien la seule porte SQL du produit (vérifié par grep, par AST, en constatant que `store/__init__.py` ne ré-exporte pas `record_run` et qu'aucun applicateur de `row_ops` n'existe dans `ml/`), il mesure sur la connexion de destination, et un encodeur candidat inconnu est correctement bloqué. **Le prédicat qu'il évalue, lui, n'a jamais été audité** : sur une base où P1 et P3 sont réellement satisfaits, la vraie route FastAPI accepte **quatre payloads distincts** qui laissent en base `provisional=0, provisional_reason=NULL` — la ligne exacte que la page admin lit « promouvable » — journal muet, `corrections: []` (**Q1** gold menti à 3 crops · **Q2** baseline inexistante · **Q3** run baseline de lui-même, que `measured_overlap` **certifie** · **Q4** re-push qui promeut 1 → 0 une ligne déjà démotée, contre ce que le docstring affirme). Et le test d'inventaire censé attraper le cinquième chemin **ne rougit pas** pour un nom de table interpolé (**Q5**, mutation exécutée : 13 passed ; témoin en SQL littéral : 2 failed). Le titre du lot — « la famille fermée par un invariant dans la porte » — est vrai **de la porte** et faux **de la famille**. Voir §8.10. |
| **M3** | **La règle de repli promet une chose que l'exécution dément.** La docstring de `store.resolve_db_path` (`ml/store/__init__.py:97-100`), présentée comme LA règle du repo, dit : « repli `eurio.replica.db` — un LECTEUR lit le vrai corpus. Un ÉCRIVAIN est refusé au constructeur. Les deux issues sont bruyantes. » La moitié « lecteur » est fausse : hors devShell, `EURIO_DB_READONLY` est absent **aussi**, donc `StoreBase.__init__` prend `read_only=False` et `store/connection.py:86` refuse la réplique **par nom**. | `env -u EURIO_DB_PATH -u EURIO_DB_READONLY … Store(m.DB_PATH)` sur `enrich_bench_images` → `RuntimeError : Refus d'ouvrir la réplique eurio.replica.db en écriture : poser EURIO_DB_READONLY=1 …`. Sites : `scripts/enrich_bench_images.py:98`, `scripts/bench_theme_match.py:97` et `:395`, `scripts/llm_coin_aliases.py:138` — tous des `Store(DB_PATH)` sans `read_only=True`. | Trois entrypoints de **lecture** plantent hors devShell au lieu de lire. Le message est bon, donc ce n'est pas un désastre — mais **ce n'est pas ce que la règle promet, et la règle est le livrable**. Le test censé la garder (`tests/test_db_path_defaults_cli.py:117-131`) compare un `Path`, n'ouvre jamais rien, et sa docstring répète l'affirmation fausse. `bench_encoder_dino` y échappe **par accident** : il fait `sqlite3.connect(f"file:{db}?mode=ro", uri=True)`, pas un `Store`. | 🔴 **ouvert.** Le choix de repli lui-même n'est pas remis en cause (§8.7). Deux issues : passer `read_only=True` dans les entrypoints de lecture (le geste est connu de leur auteur, pas de l'env), ou corriger la docstring pour dire ce qui arrive vraiment. **Une règle de repo fausse est pire qu'une absence de règle, parce qu'elle se cite.** |
| **M4** | **La « convention unique » ne couvre que les 10 scripts de sa propre liste.** Le garde `test_tous_les_scripts_corriges_replient_sur_la_replique` itère sur la constante `CORRIGES`. Deux fichiers du chantier lui échappent et divergent de la règle qu'il vient de poser : `scripts/build_dino_anchors.py:57` et `scripts/bench_gold.py:46`, tous deux sur `resolve_db_path(ML_DIR / "state" / "eurio.db")`. | `grep -n DB_PATH scripts/build_dino_anchors.py scripts/bench_gold.py` → les deux littéraux ; `git status --short` → `build_dino_anchors.py` est ` M` (modifié **dans ce diff**) et `bench_gold.py` est `??` (fichier **neuf** de ce chantier). Inventaire : `grep -rn 'resolve_db_path(' scripts review serving store training client sources referential \| grep 'eurio\.db' \| wc -l` → **55**. | `build_dino_anchors` est **le script de la cause racine du jour**. Hors devShell, la prochaine construction de banque repartira sur `state/eurio.db` — 6205 assets contre 12454 : littéralement la rechute du défaut R1 sur le script qui l'a produit. Le garde AST et la divergence coexistent, **verts**, dans le même diff. | 🔴 **ouvert.** Deux lignes à changer, priorité haute par ironie autant que par risque. Les ~39 littéraux restants (C12) sont une dette distincte, à traiter fichier par fichier — un `sed` global sur 39 entrypoints non testés serait le geste que R0 interdit. Premier de la file : `scripts/gate_standard_vision.py:44+143`, qui porte le **double défaut de C2** (`DEFAULT_DB` littéral **et** `Store(resolve_db_path(args.db or DEFAULT_DB))`, donc `--db` est un leurre). |
| **M5** | **La fixture a été réparée pour une table sur trois, et l'une des deux restantes inverse deux colonnes.** `_DDL_REFERENTIEL_DINO` déclare bien `dino_class_references` à 11 colonnes (✓, c'est le correctif D1). Mais `image_asset_dino_predictions` y est `(asset_id, anchors_kind, encoder_version, computed_at)` alors que `state/schema.sql:483-487` porte `(asset_id, encoder_version, anchors_kind, anchors_count NOT NULL, top_k_json NOT NULL, …)` — **les deux colonnes sont permutées**, et la fixture insère en **positionnel**. `dino_anchor_builds` : 4 colonnes contre 14 réelles, dont 4 `NOT NULL` absentes. | `sed -n '245,266p' tests/test_encoder_bench_store.py` vs `grep -n "CREATE TABLE IF NOT EXISTS image_asset_dino_predictions" -A 4 state/schema.sql`. | Aucun effet sur les verdicts d'aujourd'hui (`calibration_blockers` ne lit que `built_at`, `anchors_kind`, `encoder_version`, `computed_at`). Mais recopier cet `INSERT` vers du code réel intervertirait le kind et l'encodeur — **sur la paire de colonnes dont tout le correctif D1 dépend**. Et c'est le motif que D1 a payé cher : « le test mentait » a été corrigé sur une table sur trois. La fixture est son propre référentiel, donc la divergence est invisible aux tests par construction ; `tests/test_schema_mirror.py` ne couvre que `serving/migrations/*.sql` ↔ `state/schema.sql`, pas les DDL recopiés dans les fixtures. | 🔴 **ouvert, mineur.** |
| **M6** | **Un test qui ne peut pas échouer.** `tests/test_db_path_defaults_cli.py:230` `test_environnement_du_devshell_est_bien_celui_quon_croit` fait `env = os.environ.get("EURIO_DB_PATH", ""); if env: assert env.endswith(".db")`. Or `tests/conftest.py:61` porte un fixture **autouse** `_no_ambient_flip` qui fait `monkeypatch.delenv("EURIO_DB_PATH")` avant chaque test : `env` vaut **toujours** `""` sous pytest. | Mutation `assert env.endswith(".db")` → `assert False, "cette ligne est-elle atteinte ?"` : `1 passed`. Le corps est du code mort. À comparer aux 26 autres tests du même fichier, qui rougissent tous quand ils le méritent (mutation `DB_PATH` littéral ⇒ `5 failed, 22 passed`). | Il gonfle le compte de 1797 sans rien garder. C'est exactement ce que la skill `eurio-verify` interdit. | 🔴 **ouvert, mineur.** Correctif : poser explicitement `monkeypatch.setenv` avant d'asserter, capturer l'environnement au niveau module (avant l'autouse), ou le supprimer. |
| **M7** | **Sur le chemin nominal de P3 (`--push`), tout le travail `face` / `denom` que le backfill calcule est jeté en silence.** `sources/_base/steps/auto_validate.py:832,846` fait `UPDATE image_assets SET face=? / denom=? WHERE id=? AND … IS NULL` sur la réplique **scratch** pull-ée du canonique. Mais `client/runbatch.export_run` ne récolte `image_assets` que par `WHERE run_id = <run>` (or `image_assets.run_id` est celui du scrape d'origine) ou par `source_image_id IN si_ids`, où `si_ids` vient de `source_image_runs WHERE run_id = ?` — **vide pour un run de backfill DINO**. Les prédictions, elles, ont leur colonne `run_id` et leur branche dédiée (`client/runbatch.py:198-207`). | Ampleur, sur les 12454 candidats réels de P3 (via la fonction de sélection du script, `_select_assets_for_backfill`) : **`face IS NULL` = 2997**, **`denom IS NULL` = 6185**. Reproduction bout en bout sur copie `/tmp` : un asset remis à `NULL/NULL`, `--no-push --force --limit 1` → `apres backfill : obverse/2eur` en base locale, et `export_run` rend `{'source_runs': 1, 'image_asset_dino_predictions': 1}`, **`image_assets: 0`**. | Sous `--push`, la base locale est un `mkdtemp` : elle **disparaît avec le calcul**. Environ 3000 faces et 6000 dénominations recalculées et perdues à chaque passage. **Préexistant**, non introduit par les lots (`git diff` ne touche ni `auto_validate.py` ni `runbatch.py`) — mais intégralement sur le chemin que le PO va lancer, et le `desc:` de la tâche, réécrit pour dire « comment on sait que c'est complet », n'en dit pas un mot : ses quatre témoins ne couvrent que les prédictions. | 🔴 **ouvert.** Trois issues : rattacher les assets touchés au run via `source_image_runs` ; ajouter une branche `image_assets WHERE id IN (…)` à `export_run` ; ou un `/ingest/*` dédié. **À défaut, le dire** — c'est fait dans [`GESTE-P3.md`](GESTE-P3.md). |
| **M8** | **Le backfill P3 sort en code 0 même avec des milliers d'erreurs.** `scripts/backfill_dino_predictions.main()` imprime `result.n_errors` et se termine par un `return 0` **inconditionnel** (`:153` et `:166`) ; c'est son unique point de sortie. | `grep -n "return 0\|n_errors" scripts/backfill_dino_predictions.py` → `153: print(f"Errors: {result.n_errors}")`, `166: return 0`. **Préexistant** : `git diff -- ml/scripts/backfill_dino_predictions.py \| grep -c 'return 0'` → 0. | 18 minutes de calcul avec 3000 erreurs sortent en code 0 et `go-task` déclare « réussi ». C'est **exactement le défaut N2 que le même chantier vient de fermer dans le script frère** `bench_encoder_dino.py` (`failed = len(failures)` → `return 1 if failed else 0`, mutation `failed = 0` ⇒ rouge) : la doctrine a été posée puis pas appliquée au script que le PO va lancer. Aucun test n'existe pour ce point d'entrée : `tests/test_db_path_defaults_cli.py` ne teste que le chemin de base. | 🔴 **ouvert.** Une ligne : `return 1 if result.n_errors else 0` (ou un seuil explicite si un taux d'erreur non nul est acceptable pour ce geste). **Recommandé avant le lancement de P3.** |
| **M9** | **Le journal `face`/`denom` annonce la taille du lot soumis, pas le nombre de lignes changées.** `sources/_base/steps/auto_validate.py` fait `conn.executemany("UPDATE … WHERE … IS NULL")` puis journalise `len(face_writes)` / `len(denom_writes)`, jamais `cur.rowcount`. | Sur copie `/tmp`, bornes mesurées par `sqlite3 <copie> "SELECT SUM(face IS NULL)\|\|' / '\|\|SUM(denom IS NULL) FROM image_assets"` : `AVANT 2997 / 6185` → `--limit 300` → journal `face écrit sur 300 crops`, `denom écrit sur 245 crops` → `APRES 2997 / 6185`. **Zéro ligne changée.** | Témoin trompeur pour un opérateur qui suit la sortie pendant 18 minutes, et il **aggrave M7** : il donne à croire que le travail face/denom a lieu et aboutit. | 🔴 **ouvert, mineur.** Correctif : journaliser `cur.rowcount`, ou reformuler en « N crops soumis ». |
| **M10** | **La documentation d'arbitrage décrit mal le travail restant.** La §4 des remarques du lot C, reprise par l'intégration, affirme que quatre scripts écrivent des tables « **sans jumeau `/ingest`** » : `listing_text_signals`, `coin_aliases` ×2, `coin_source_status`. **Deux des quatre tables ont bel et bien un transport.** | `client/runbatch.py:37` et `:44` les listent dans `_TABLE_ORDER` ; `export_run` les récolte (`:181` `listing_text_signals … WHERE source_image_id IN (…)`, `:226` `coin_source_status … WHERE last_run_id=?`). Seul `coin_aliases` n'a rien : `grep -c coin_aliases ml/client/runbatch.py` → **0**. | Ce qui manque n'est pas le jumeau, c'est que **ces scripts ne créent pas de run** pour s'y raccrocher — une question de câblage, nettement plus petite que « route `/ingest` ou `guard_vps_only` ? ». Non reformulée, la décision d'architecture sera reposée plus large qu'elle ne l'est. | ⏭ **requalifié** — inexactitude de documentation, pas défaut de code. À reformuler dans `docs/work-in-progress/local-sync/vps-only-migrations.md` quand le sujet sera repris. |
| **M11** | **Le mécanisme par lequel la suite de tests écrit sur `ml/state/eurio.db`** (consigné en §8.6 le 19/08, cause maintenant établie). `tests/conftest.py:60-61` (`_no_ambient_flip`, autouse) retire `EURIO_DB_READONLY` **et** `EURIO_DB_PATH` ; le fixture de `tests/test_coins_routes.py` importe ensuite `serving.server` « pour absorber le bind initial » ; `serving/server.py:64` calcule alors `CANONICAL_DB = Path(os.environ.get("EURIO_DB_PATH") or (STATE_DIR / "eurio.db"))` → la base de travail réelle, ouverte **sans** `read_only`. | Bissection sur les quatre tests qui touchent la vraie base (md5 avant/après) : `test_cohort_refetch: inchangé`, `test_storage_migration: inchangé`, `test_numista_writer: inchangé`, **`test_coins_routes: *** MODIFIE state/eurio.db ***`**. Snapshot (taille+mtime+mode+md5) de `state/*.db*` sur la suite entière : **une seule** base du dépôt bouge, plus le `-shm` de la réplique (touché, contenu identique). Contenu métier intact : `SELECT COUNT(*) FROM image_assets` → **6205** avant et après. | Bootstrap de schéma + checkpoint WAL, pas de corruption. Mais c'est le mécanisme qui a fait tomber 28 tests en « attempt to write a readonly database » quand un `chmod 444` avait été posé sur `eurio.db` : **le piège qui attend le prochain agent de vérification**. Corollaire pratique : `ml/state/eurio.db` n'est **pas** un artefact à md5 stable dans ce dépôt. | ⏭ **préexistant, hors périmètre, mécanisme désormais écrit.** Correctif : borner l'import de `serving.server` sous un `EURIO_DB_PATH` tmp, ou lui donner `read_only=True`. |


### 8.9 Le motif : le garde branché sur le chemin qu'on avait en tête

> Note de motif, écrite le 2026-08-20 à la clôture de M1 et M2, **complétée le
> soir même après la vérification de cette clôture** — qui a rendu douze défauts
> de plus (§8.10) dont trois sont une nouvelle face du même motif. Même forme
> que §8.7 : un symptôme, la raison pour laquelle il est invisible, ce qui l'a
> fait passer, la convention retenue, et comment on l'attrape la prochaine fois.
>
> **À lire par quelqu'un qui n'était pas là.** Ce n'est pas le résumé d'une
> session : c'est le seul défaut de ce dépôt qui soit revenu **sept fois en deux
> jours**, chaque fois sous une forme que la précédente n'avait pas prévue, et
> chaque fois en laissant la suite de tests au vert.

#### Le symptôme

**Sept instances en deux jours.** Les quatre premières tournent autour du
**même** garde (`store.encoder_bench.calibration_blockers`) ; les trois
suivantes ont été trouvées le soir en vérifiant la fermeture des deux
précédentes — dont une **créée par le correctif lui-même** :

| # | Le garde… | …mais |
|---|---|---|
| D1 volet P3 | mesure « les prédictions sont-elles postérieures au build ? » | n'émettait rien pour un encodeur **candidat** — pas de ligne de build ⇒ tout le bloc sauté |
| D1 volet P1 | compte les classes à exemplaires | comptait **sans prédicat d'encodeur** : il validait la couverture d'un autre encodeur |
| M1 | justifie ce prédicat par « la table est scopée `UNIQUE(anchors_kind, encoder_version, class_id)` » | cet index est **partiel aux canoniques**, et la PK réelle **n'avait pas l'encodeur** : bâtir la banque d'un candidat écrasait celle de la production |
| M2 | a la bonne réponse | **n'est pas appelé** par `POST /ingest/encoder-bench`, le seul chemin par lequel un run entre en base |
| Q1..Q4 | est enfin **appelé** — l'invariant est descendu dans `record_run`, la porte d'écriture | **dit faux** : il traite `gold_n_crops`, `gold_version` et `baseline_run_id` comme des faits alors que ce sont des affirmations d'appelant. Quatre payloads le franchissent et laissent `provisional=0` en base |
| Q5 | est protégé par un test qui **énumère par AST** tous les chemins d'écriture, pour que le cinquième rougisse | ne voit que les **littéraux** : une constante de module et une f-string suffisent à passer. Le détecteur a hérité du défaut qu'il devait détecter |
| Q6, Q8 | met l'encodeur dans la **clé primaire** (0010) pour que deux banques coexistent | **rend faux tous les LECTEURS** de la table, écrits à une époque où la coexistence était impossible et qui n'ont donc jamais nommé `encoder_version` : la route admin rend deux canoniques pour une classe, le plan de capture P5 double son `n_fps` et bascule des classes de strate |

Ce n'est pas sept bugs, c'est **une faiblesse de conception** : on protège le
chemin qu'on **a en tête** (le CLI, le rebuild qu'on imagine, le scope qu'on
croit, l'écrivain qu'on connaît) et jamais celui qui est **réellement emprunté**
(la route HTTP, le writer, la clé primaire, le lecteur d'à côté). Et la maladie
se déplace à chaque correctif : on ferme le câblage, le prédicat reste faux ; on
ferme le prédicat, le détecteur est aveugle ; on ferme l'écriture, ce sont les
lectures qui deviennent fausses.

#### Pourquoi il est invisible

Une campagne de mutation ne peut pas le voir. Elle prouve qu'un test **couvre**
le code écrit ; elle ne prouve jamais que ce code soit **appelé** sur le chemin
réel. Les neuf mutations posées sur les correctifs de la nuit du 19 au 20 sont
toutes devenues rouges — et M1 comme M2 étaient là, dessous, intacts.

Les fixtures aggravent le silence. Celle du banc fabrique un `asset_id` **par
encodeur** (`f"asset-{encoder_version}-{i}"`) : le scénario nominal — deux
encodeurs qui piochent dans le **même pool de crops validés** — n'y est pas
exprimable. Le test ne pouvait pas rougir, quel que soit le soin qu'on y mette.

#### Ce qui les a fait passer — les mécanismes, pas les lignes

Chaque instance a un mécanisme nommable, et **aucun n'est une étourderie** : ce
sont cinq façons ordinaires de se tromper, qu'on refera.

1. **Une fixture est son propre référentiel.** Le DDL du décor de test avait 3
   colonnes sur les 11 réelles, et personne ne pouvait le voir : rien ne
   compare une fixture au schéma. Un test écrit contre un monde inventé mesure
   la cohérence de l'invention. *Parade : dériver le DDL du vrai
   `state/schema.sql` (`ml/tests/_schema_reel.py`), jamais le retaper.*
2. **Une contrainte d'unicité partielle citée comme totale.** L'index
   `idx_dino_class_refs_canonical` porte un `WHERE asset_id IS NULL` : il ne
   couvre que les canoniques. La docstring du garde l'invoquait comme s'il
   scopait la table entière — et le raisonnement du correctif D1/P1 s'appuyait
   dessus pour compter des lignes `fps`, qu'il ne touche pas. *Parade : citer
   une contrainte, c'est la relire, prédicat compris.*
3. **Une route qui recopie le payload.** `EncoderBenchRun(**payload.model_dump())`
   transporte un corps HTTP jusqu'à la base sans qu'aucune ligne de code n'ait
   l'air de décider quoi que ce soit. Le passe-plat est invisible parce qu'il
   n'a pas de branche à lire. *Parade : tout champ recopié depuis l'extérieur
   est une affirmation, et se marque comme telle.*
4. **Un détecteur qui reconnaît la forme déjà rencontrée.** Le test d'inventaire
   AST cherche le nom de la table dans les `ast.Constant`. Une constante de
   module plus une f-string — le patron le plus banal du dépôt — coupent la
   chaîne en morceaux dont aucun ne contient le nom. Le garde du garde a le
   défaut du garde. *Parade : préférer une observation à l'exécution (trigger
   SQLite sur la table) à une reconnaissance de texte.*
5. **Un correctif qui rend possible ce que le reste du code croit impossible.**
   Avant 0010, deux lignes du même crop ne pouvaient pas coexister — elles
   s'écrasaient, c'était précisément le défaut M1. Tous les lecteurs écrits sous
   ce régime étaient **accidentellement justes** avec un `WHERE anchors_kind = ?`
   sans encodeur. Le jour où la clé change, ils deviennent faux **sans avoir été
   touchés**, et aucun diff ne les montre. *Parade : la question du §« comment
   on l'attrape », point 4.*

#### La convention retenue (2026-08-20)

1. **L'invariant descend jusqu'à la porte.** Pas dans l'appelant, pas dans la
   route : dans la **seule fonction qui écrit**. `record_run` mesure lui-même et
   refuse. Tout cinquième chemin écrit demain hérite du garde sans que son
   auteur y pense.
2. **L'invariant se mesure sur la connexion de DESTINATION.** Un verdict calculé
   sur la réplique, en retard par construction sous Direction A, ne dit rien de
   ce qu'on est en train d'écrire au canonique.
3. **Ce que le schéma peut porter, le schéma le porte.** M1 n'est pas fermé par
   un `if` : l'encodeur est entré dans la **clé primaire** (0010). Une garantie
   dans la clé ne se contourne pas, ne s'oublie pas au prochain chemin, et
   n'attend pas qu'un test y pense. Corollaire : dans une PK, la colonne doit
   être `NOT NULL` — `NULL ≠ NULL` ne déduplique rien, on ne ferait que
   déplacer le trou.
4. **Un désaccord entre deux vérités s'imprime.** Le canonique corrige
   (`provisional 0 → 1`) plutôt que de refuser en 4xx — sinon des heures de GPU
   sont jetées pour un champ que le serveur recalcule seul — mais la correction
   est journalisée côté serveur, renvoyée dans la réponse, et **remontée par le
   banc** (`⚠ CORRIGÉ PAR LE CANONIQUE : …`). Une correction muette recrée le
   motif un cran plus haut.
5. **Le nombre de chemins est un invariant testé.**
   `tests/test_encoder_bench_guard_family.py` ::
   `test_inventaire_des_chemins_d_ecriture_d_un_run` énumère par
   **AST** tous les appelants de `record_run` et tous les littéraux SQL qui
   écrivent `encoder_bench_runs`, imports résolus (l'homonyme
   `state.sources_runs.record_run` a onze appelants sans rapport), et compare à
   une liste de trois entrées portant chacune sa raison. Un cinquième chemin le
   fait échouer — vérifié en en déposant un.
6. **La clé d'un `row_op` décrit la clé de la TABLE.** Même famille, chemin
   différent : celle de `dino_class_references` valait
   `{anchors_kind, class_id, asset_id}` — sans `eurio_id` (trou préexistant) ni
   `encoder_version`. Elle les nomme désormais tous, et le test les **lit par
   `PRAGMA table_info`** au lieu de les recopier.
7. **Un garde appelé n'est pas un garde juste — le prédicat s'audite à part.**
   Descendre l'invariant dans la porte prouve qu'il est *consulté*, jamais qu'il
   *dise vrai*. La question à poser une fois le câblage fait est : *sur quelles
   entrées ce garde rend-il `[]` alors qu'il ne devrait pas ?* Le sous-cas
   récurrent : **un champ déclaré par l'appelant que le garde traite comme un
   fait**, et pire, **l'état sûr encodé par une absence** — `gold_sample_n=None`
   veut dire « gold entier », donc omettre le champ désarme le bloqueur. Un
   sentinelle qui vaut « tout va bien » est ce qu'un payload forgé obtient
   gratuitement (Q1). *Corollaire : ce qui n'est pas mesurable bloque — le
   module l'écrit dans sa propre docstring, et ne l'applique qu'aux champs
   auxquels il a pensé.*
8. **Quand une colonne entre dans une clé primaire, tout lecteur qui ne la
   nomme pas devient faux ce jour-là.** C'est la face que 0010 a ouverte (Q6,
   Q8). Elle est **énumérable mécaniquement** — les `SELECT … FROM <table>` sans
   la colonne dans le `WHERE` — exactement comme l'inventaire AST des écrivains.
   Le geste est symétrique et il manquait : on a inventorié les écrivains, on
   n'a pas inventorié les lecteurs.
9. **Un invariant se sonde là où il s'applique, pas là où il s'écrit.** Le test
   d'inventaire par AST se fait battre par une f-string (Q5). Sonder
   l'**exécution** — un trigger SQLite qui refuse toute écriture hors de la
   fonction autorisée — ne dépend d'aucune forme syntaxique. Un détecteur qui
   lit du texte reconnaît le passé.

#### Comment on l'attrape la prochaine fois

Trois questions, dans cet ordre, chaque fois qu'on pose un garde :

1. **Qui écrit vraiment ?** Faire l'inventaire (grep + AST), pas la liste de
   mémoire. Les quatre instances tiennent dans l'écart entre les deux.
2. **Le garde est-il en aval de tous ces écrivains ?** Si non, le descendre —
   ou, mieux, le remplacer par une contrainte de schéma.
3. **La fixture peut-elle exprimer le cas nominal ?** Si le scénario du monde
   réel n'est pas représentable dans le décor du test, le test est décoratif.
   Le remède est un helper qui **dérive** le DDL du vrai `state/schema.sql`
   (`ml/tests/_schema_reel.py`), pas une fixture recopiée à la main.
4. **Ce correctif rend-il possible un état que le reste du code croit
   impossible ?** C'est la question qui manquait, et c'est celle que la
   vérification du soir a démontrée en trouvant Q6 : le correctif M1 est juste,
   vérifié, et il casse trois lecteurs qu'il n'a pas touchés. Se la poser coûte
   un `grep` ; ne pas se la poser a coûté un plan de capture P5 dont deux
   classes changent de strate sans qu'aucune donnée n'ait changé.
5. **Quelle entrée fait dire `[]` à ce garde à tort ?** Après le câblage, une
   demi-heure de payloads forgés contre le **vrai point d'entrée** (route montée
   sur `TestClient`, base `mkdtemp`). Les quatre défauts Q1..Q4 ont été trouvés
   comme ça, en une sonde, sur un garde que tout le monde croyait fermé.


### 8.10 Défauts NEUFS, trouvés en vérifiant la FERMETURE de M1 et M2

Deux vérifications adversariales ont tourné le 2026-08-20 au soir sur la
troisième passe de correction (les lots M1 et M2 + leur intégration). Elles ont
**confirmé M1 sur le fond** — migration atomique, données préservées au byte
près, refus bruyant plutôt que fusion silencieuse — et **requalifié M2 en
partiellement corrigé**. Elles ont rendu **douze défauts que personne n'avait
listés**, tous reproduits par une exécution, aucun sur simple lecture.

La suite passait **1820 passed, 0 failed** dans les deux ordres pendant ces
douze constats. Aucun n'a été trouvé par un test.

**Les lentilles qui ont payé** : (1) « le garde est appelé — mais **dit-il
vrai** ? » → Q1..Q4 ; (2) « le détecteur du chemin suivant voit-il la forme la
plus banale de ce chemin ? » → Q5 ; (3) « ce correctif rend-il possible un état
que le reste du code croit impossible ? » → Q6, Q8. La troisième est la
question qui manquait au §8.9, et c'est le correctif M1 lui-même qui la pose.

> **Numérotation.** Les deux vérifications ont numéroté leurs constats
> indépendamment ; ils sont fusionnés ici en Q1..Q12, les doublons repliés
> (Q6 réunit trois lecteurs mesurés par les deux passes, Q8 réunit le pin et
> l'exclude).

| # | Défaut | Preuve | Effet | État au 20/08 (soir) |
|---|---|---|---|---|
| **Q1** | **Le garde ne confronte jamais la taille du gold déclarée par l'appelant.** `calibration_blockers` n'évalue le bloqueur « echantillon » que `if gold_sample_n is not None` — or `None` est le **sentinelle de « gold entier »** posé par le banc (`scripts/bench_encoder_dino.py:632` : `gold_sample_n = len(crops) if len(crops) < len(gold) else None`). L'état sûr est donc encodé par une **absence**, et une absence est ce qu'un payload forgé obtient gratuitement. `gold_n_crops` n'est confronté à rien : ni au sidecar (`state/validation_gold/encoder_bench_gold.meta.json` : `gold_version=0ecbb1d70e3c`, `n_crops=1958`), ni aux autres runs du même `gold_version` déjà en base — un contrôle croisé pourtant faisable en SQL pur. | Sonde contre la VRAIE route FastAPI montée sur une base `mkdtemp` où **P1 et P3 sont satisfaits** pour `dinov2-vitl14` (200 classes `fps`, 200 prédictions postérieures au build, un build tracé) → `bloqueurs de base : []`. Payload `gold_sample_n` omis, `gold_n_crops=3`, `provisional=0` → `HTTP 200 {'provisional': 0, 'blockers': [], 'corrections': []}` et en base `{'provisional': 0, 'provisional_reason': None, 'gold_n_crops': 3}`. Le gold réel fait 1958 (`wc -l state/validation_gold/encoder_bench_gold.jsonl`). | Un run évalué sur **3 crops** ressort promouvable, sans un bloqueur, sans un mot au journal. C'est le défaut M2 dans sa forme suivante : le garde est enfin appelé, et il rend `[]`. Le module écrit pourtant son propre principe dans sa docstring — « ce qui n'est pas mesurable bloque » ; ici, **ce qui n'est pas déclaré passe**. | 🔴 **ouvert.** Deux gestes : traiter l'absence de `gold_sample_n` comme « non mesurable » (donc bloquante) plutôt que comme « gold entier », et confronter `gold_n_crops` aux autres runs du même `gold_version`. |
| **Q2** | **Rien ne vérifie que `baseline_run_id` désigne un run existant** — ni la route, ni `measured_blockers`, ni `_paired_blockers`, et `0009_encoder_bench.sql` ne pose **aucune clé étrangère** dessus. Pire, le garde s'auto-désarme sur ce cas précis : `measured_overlap` rend `None` quand l'un des deux runs n'a pas de prédictions en base (contrat volontaire, et juste par ailleurs — le `0` ambigu), et la route retombe alors sur le `n_paired` **déclaré**. Le déclaratif est cru exactement dans le cas où la baseline est fictive. | Même sonde, même base : payload `baseline_run_id='run-qui-n-existe-pas'`, `n_paired=1958`, `mcnemar_p=0.001`, `provisional=0` → `HTTP 200`, `blockers: []`, et en base `{'provisional': 0, 'provisional_reason': None, 'n_paired': 1958, 'baseline_run_id': 'run-qui-n-existe-pas'}`. | Une p-valeur de McNemar enregistrée contre un bras de comparaison **qui n'existe pas**, et rien ne le dit. C'est D16 dans sa forme la plus pure. Le trou est atteignable **sans rien forger**, par le chemin D9 documenté : la route accepte `predictions: []`. | 🔴 **ouvert.** Le geste minimal est une vérification d'existence dans `record_run` (donc dans la porte) ; la clé étrangère serait mieux, elle est à peser contre l'ordre d'arrivée des runs. |
| **Q3** | **Un run peut être sa propre baseline, et le seul champ que le serveur sait recalculer CERTIFIE le montage.** `paired_overlap` est une auto-jointure `encoder_bench_predictions a JOIN encoder_bench_predictions b USING (asset_id) WHERE a.run_id=? AND b.run_id=?` : avec `run_id == baseline_run_id`, elle rend le compte des prédictions du run lui-même. | Sonde 2, prédictions réellement poussées (donc `measured_overlap` s'exécute) : `HTTP 200 {'run_id': 'self-1', 'n_predictions': 10, 'provisional': 0, 'blockers': [], 'corrections': []}`, `measured_overlap(self-1, self-1) = 10`, en base `{'provisional': 0, 'n_paired': 10, 'baseline_run_id': 'self-1', 'mcnemar_p': 0.0001}`. | Le mécanisme que M2 a précisément câblé pour **ne plus croire l'appelant** devient la confirmation du mensonge : il mesure, trouve la valeur déclarée, ne corrige rien. Un run promouvable avec une p-valeur contre lui-même. | 🔴 **ouvert.** Une ligne dans `record_run` : `baseline_run_id != run_id`. |
| **Q4** | **Un run démoté par le serveur peut être promu par un second POST** — et cela contredit une affirmation écrite du correctif. Le docstring de la route dit : « Le sens de la correction est toujours le sûr : `0 → 1`. On ne promeut jamais un run que l'appelant disait provisoire. » Vrai à l'échelle d'**une requête**, faux à l'échelle de **la ligne** : `record_run` écrit en `INSERT OR REPLACE INTO encoder_bench_runs`, et ni la route ni le store ne lisent la ligne existante avant de la remplacer. | Deux POST sur le même `run_id` : push 1 → `provisional=1`, `provisional_reason='echantillon: run sur 200 crops sur les 1958 du gold'` ; push 2, même `run_id`, champ litigieux omis → `{'provisional': 0, 'provisional_reason': None, 'gold_sample_n': None}`. Reproduit par les deux sondes. | La démotion ne laisse **aucune trace** : il suffit de re-pousser sans le champ qui avait déclenché le bloqueur. Bilan des deux sondes : quatre lignes `provisional=0` en base, dont trois sont des mensonges. | 🔴 **ouvert.** Lire la ligne avant de la remplacer, et refuser (ou journaliser bruyamment) une transition `1 → 0`. |
| **Q5** | **Le test qui devait attraper le cinquième chemin ne rougit pas pour un nom de table interpolé.** `_inventaire_reel()` de `tests/test_encoder_bench_guard_family.py` ne cherche `_SQL_ECRITURE` que dans les nœuds `ast.Constant` de type `str`. Une constante de module + f-string — le patron le plus banal du dépôt — coupe la chaîne en morceaux dont aucun ne contient à la fois un verbe d'écriture et `encoder_bench_runs`. | **Mutation exécutée**, fichier déposé dans l'arbre de production (`ml/scripts/_sonde_bypass_q.py`) : `_TABLE = "encoder_bench_runs"` puis `conn.execute(f"UPDATE {_TABLE} SET provisional = 0 WHERE run_id = ?", …)` → `13 passed in 7.86s`. **Témoin**, même chemin en SQL littéral → `2 failed, 11 passed`. Les deux fichiers de mutation ont été supprimés. | C'est la question exacte que la mission posait au test famille, et la réponse est **non** pour la forme la plus ordinaire. Tant qu'il tient, on se croit protégé : c'est le §8.9 appliqué au test censé fermer le §8.9. | 🔴 **ouvert.** Deux issues : joindre les `ast.JoinedStr` et suivre les constantes de module (rustine, même famille), ou **sonder l'exécution** — un trigger SQLite qui refuse toute écriture hors de `record_run` ne dépend d'aucune forme syntaxique. |
| **Q6** | **AUCUN lecteur de `dino_class_references` n'est scopé par encodeur — et c'est le correctif M1 qui les rend faux.** Avant 0010, la coexistence de deux encodeurs était impossible (les lignes s'écrasaient : c'était M1), donc un `WHERE anchors_kind = ?` sans encodeur était **accidentellement juste**. Trois lecteurs mesurés : `scripts/build_scan_prescription.py:139` (`_SQL_CLASSES`, CTE `refs`) somme `n_fps` / `n_canonical` sur les deux encodeurs et `_strate_of` classe sur ces sommes ; `store/dino_references.py:212` `get_references_for_assets` construit un dict `asset_id → row` **sans `ORDER BY`** et sans prédicat d'encodeur ; `store/dino_references.py:199` `get_class_references` (UI coin-detail, via `serving/coin_assets_routes.py:467` et `:271`) rend les lignes des deux encodeurs. | Sur copie `/tmp` de la réplique **réelle** migrée, deux builds via le VRAI `replace_auto_references` sur **les mêmes crops** : `get_class_references` rend **22 lignes au lieu de 11**, `Counter({'dinov2-vitl14': 11, 'timm-…-dinov3': 11})`, **2 canoniques pour une classe** ; `get_references_for_assets` rend `{'a0': ('timm-…-dinov3', …), …}` — **la ligne de production est masquée par celle du candidat, silencieusement**. Et le VRAI CLI `python -m scripts.build_scan_prescription`, deux fois : 1 encodeur → `riche 22 / moyenne 21` (110 et 105 cellules) ; 2 encodeurs → `riche 24 / moyenne 19`. Sur les 664 classes : `Counter({'pauvre':539,'moyenne':85,'riche':40})` → `{'pauvre':539,'moyenne':76,'riche':49}`, **9 classes déplacées, `canoniques>1` passe de 0 à 664**. | **Latent aujourd'hui, armé au premier build de banque d'un encodeur candidat** — c'est-à-dire au geste que `ml/tasks.yml` et le §9 disent de faire juste après le redémarrage du VPS. Effets : la section « Références Dino » de coin-detail affiche chaque exemplaire deux fois et deux canoniques, sans dire de quel encodeur (`DinoReferenceEntry` ne porte pas `encoder_version`) ; le badge de la grille de review affiche un `rank` et un `selected_sim` d'un encodeur qui n'est **pas celui servi** ; le **plan de capture P5 est un livrable humain** (on photographie d'après lui) et `ml/tasks.yml:1096` en cite les chiffres de référence — ils bougeront sans un mot. Le script se dit « en LECTURE SEULE », ce qui est vrai et rassure à tort : il ne casse rien, il ment. | 🔴 **ouvert, priorité haute.** `get_class_references` / `get_references_for_assets` doivent prendre un `encoder_version` et leurs deux appelants le passer — **l'encodeur servi**, pas « tous » ; `build_scan_prescription` a besoin d'un `AND encoder_version = :encoder`, d'une option, et de la trace de la valeur retenue dans son récapitulatif. **À fermer avant le premier build candidat.** |
| **Q7** | **La famille a été fermée par un inventaire AST pour une table et par un `grep` de session pour l'autre.** Il n'existe aucun test d'inventaire des chemins d'écriture de `dino_class_references` (`grep -rn "_inventaire_reel" ml/tests` → seulement `test_encoder_bench_guard_family.py`), dans la session même qui découvrait que cette table avait le même problème d'identité. Corollaire concret : `set_reference_override` (`store/dino_references.py:230`) et `clear_reference_override` (`:247`) écrivent la table **sans passer par `_exige_encodeur_dans_la_cle`** — seul `replace_auto_references` l'appelle. | Inventaire à la main, faute de test : `grep -rn "dino_class_references" ml --include="*.py" \| grep -v "/tests/\|\.venv"` → verbes d'écriture aux lignes **162** (DELETE), **169** (INSERT OR REPLACE), **240** (INSERT OR REPLACE) et **253** (DELETE) de `store/dino_references.py`. Les deux derniers ne passent par aucun garde. | Le garde est, ici encore, sur le chemin qu'on avait en tête (le build) et pas sur tous ceux qui écrivent. Aucun test ne ferait échouer l'ajout d'un cinquième. | 🔴 **ouvert.** Symétrique du point 5 de la convention §8.9 : l'inventaire doit exister pour cette table aussi — en veillant à ne pas reproduire Q5. |
| **Q8** | **Un override humain ne remplace plus la ligne automatique du même crop.** `method` n'a jamais été dans la clé : tant que la PK valait `(kind, class, eurio, asset)`, l'`INSERT OR REPLACE` de `set_reference_override` **remplaçait** la ligne `fps`. Depuis 0010, l'override s'écrit avec `encoder_version = ''` (choix délibéré et bon par ailleurs : une décision d'humain vaut pour tous les encodeurs) tandis que la ligne auto garde le sien — deux clés différentes, deux lignes. | Même crop, même classe, deux copies `/tmp` de la réplique. **AVANT 0010** : après `exclude`, `[('manual_exclude', None)]`, la classe reste à **11 lignes**. **APRÈS 0010** : `[('fps', 'dinov2-vitl14'), ('manual_exclude', '')]`, la classe passe à **12**. Symétrique pour le pin : `apres build [('fps','dinov2-vitl14')]` → `apres pin [('manual_pin',''), ('fps','dinov2-vitl14')]`. | **Frappe la production d'aujourd'hui, à un seul encodeur.** L'humain bannit un crop ; la page continue de le lister comme exemplaire `fps` jusqu'au prochain build d'ancres — un job MPS de ~4 min qui ne tourne pas tous les jours. Et le badge dépend de l'ordre de retour SQL, `get_references_for_assets` n'ayant pas d'`ORDER BY` : correct par accident dans la mesure, l'autre sens observé dans la mesure Q6. Aucun test ne verrouille ce contrat — `tests/test_dino_references.py::test_pin_then_clear_override` ne pose jamais de ligne AUTO avant l'override, c'est pourquoi la suite reste verte. | 🔴 **ouvert.** Choix de contrat à trancher, pas retouche : soit `set_reference_override` supprime les lignes auto du même crop quel que soit l'encodeur, soit les lecteurs donnent priorité au `manual_*` — dans les deux cas avec un `ORDER BY` explicite. |
| **Q9** | **Le verdict de calibration est mesuré contre un état que le même jeton peut écrire.** `POST /ingest/dino-references` (`serving/ingest_routes.py:301`) écrit `dino_anchor_builds` (que lit P3) et `dino_class_references` (que compte P1) ; `POST /ingest/encoder-bench` (`:541`) est monté sur le même routeur avec la même dépendance `require_scope("ingest:write")`. « La base mesure » et « l'appelant déclare » ne sont donc pas deux sources aussi indépendantes que le docstring de `measured_blockers` le laisse croire (« Le payload n'est pas cru »). | Lecture des deux routes. ⚠️ **estimation** quant à la faisabilité complète de l'enchaînement : fabriquer 180 classes `fps` demande des `asset_id` valides (FK) et des prédictions fraîches, non monté. Le partage de jeton et de tables, lui, est lu dans le code. | Pas une rupture de frontière de confiance — le jeton du lab est censé être honnête, et sous Direction A pousser **est** le chemin normal. Mais la phrase « le payload n'est pas cru » est plus forte que ce que l'architecture garantit. | 🔴 **ouvert, sévérité faible.** À trancher plus haut : soit la docstring se modère, soit les scopes se séparent. |
| **Q10** | **Le garde M1 arrive après les ~4 minutes d'encodage, et par HTTP son message se perd.** `preflight_db_traceability` (`scripts/build_dino_anchors.py:75-140`) existe explicitement pour que ce genre d'échec tombe **avant** — sa docstring dit « seule la première vraie écriture échoue, c'est-à-dire APRÈS les ~4 minutes d'encodage » — mais elle ne sonde que l'**inscriptibilité** (`CREATE TABLE _dino_anchors_write_probe` / `DROP`), jamais la **forme de la clé**. `_exige_encodeur_dans_la_cle` n'est appelé qu'en tête de `replace_auto_references`, atteint depuis `:199`, après l'encodage. | La cible existe : `sqlite3 'file:ml/state/eurio.db?mode=ro'` → `PK ['anchors_kind','class_id','eurio_id','asset_id']`, `encoder_version notnull=0`, **0 ligne**. Et par HTTP, contre le VRAI handler `ingest_dino_references_route` sur une copie non migrée : `EXCEPTION NON-HTTP -> CleSansEncodeurError => FastAPI rendra 500 "Internal Server Error"`, « message perdu pour le client ». `CleSansEncodeurError` hérite de `RuntimeError`, pas de `HTTPException` ; le `except Exception: ROLLBACK; raise` de la route la relaie telle quelle. | Un `build_dino_anchors --db state/eurio.db` — le chemin « écrire en local » que le message du préflight recommande lui-même en 2ᵉ position — brûle 4 min puis meurt, sur une base à 0 ligne : le garde bloque là où il n'y a rien à protéger, au prix maximal. Et le remède nommé (« appliquer 0010 ») ne parvient jamais à la personne qui a lancé `--push` : il faut aller lire les logs du conteneur. C'est **la fenêtre réelle d'ici au redémarrage de `eurio-api`**, c'est-à-dire précisément le moment où le garde doit parler. | 🔴 **ouvert.** Deux gestes : appeler `_exige_encodeur_dans_la_cle` depuis `preflight_db_traceability`, et attraper `CleSansEncodeurError` dans `serving/ingest_routes.py:303-328` pour la rendre en `HTTPException` portant le message — la route voisine le fait déjà pour `ReferentialFixConflict`. |
| **Q11** | **La branche « base neuve » de 0010 est inatteignable.** Son `CREATE TABLE IF NOT EXISTS` de tête est commenté « base neuve : le runner tourne AVANT le bootstrap `schema.sql` » (§6.5) — mais le runner n'arrive jamais jusqu'à 0010 sur une base vide. | `run_migrations` sur un fichier vide → `ECHEC base neuve: OperationalError no such table: source_images`, sur **0003**, sept migrations avant 0010. | Inoffensif : le filet est mort-né, pas faux. Mais le lecteur pressé conclura qu'une base neuve est un chemin supporté. | 🔴 **ouvert, mineur.** Une ligne de commentaire à corriger dans l'en-tête de 0010. |
| **Q12** | **`store/connection.py` pose `encoder_version` NULLABLE sur une base locale antérieure**, divergent du `NOT NULL DEFAULT ''` de `schema.sql`. `_ensure_column(..., decl="TEXT")` du bloc « Migration 0007 » (`:288-300`) ne peut pas reconstruire une table : `CREATE TABLE IF NOT EXISTS` ne reconstruit rien, et les migrations ne sont rejouées que par le conteneur canonique. | Mesuré : `ml/state/eurio.db` → `encoder_version notnull=0, default=None`, PK `['anchors_kind','class_id','eurio_id','asset_id']`. Signalé comme point ouvert par l'intégration, confirmé en données par la vérification. | N'aggrave rien tant que le garde du writer tient — le résultat pratique est un refus nommé, pas un écrasement. Mais c'est lui qui rend **Q10** concret. | 🔴 **ouvert, connu et assumé.** Une reconstruction de table dans un `_bootstrap` qui tourne à **chaque** ouverture inscriptible se discute avant, pas après (R0). |

**Ce qui a été confirmé au passage, et qui tient** : `record_run` est bien la
seule porte SQL d'écriture de `encoder_bench_runs` (grep + AST + `store/__init__.py`
ne le ré-exporte pas + aucun applicateur de `row_ops` n'existe dans `ml/`) ; un
encodeur candidat inconnu est correctement bloqué par P1+P3 ; les deux gardes
P1 de `store/encoder_bench.py` (`:456`, `:663`) portent bien
`AND encoder_version = ?` — **le correctif D1/P1 tient**. C'est ce qui rend
l'oubli des autres lecteurs frappant : le prédicat a été posé là où on
regardait.

**Ordre de traitement proposé** : **Q10** d'abord (il coûte 4 min de GPU par
tentative, son message se perd, et sa fenêtre est ouverte maintenant), puis
**Q6** — latent, armé par le geste immédiatement suivant — puis **Q1..Q4**, qui
décident de ce que la page admin appellera « promouvable », puis **Q5** parce
que tant qu'il tient on se croit protégé, puis Q7, Q8, Q9, Q11, Q12.

### 8.11 Défauts NEUFS, trouvés en vérifiant la courbe « références par classe »

Une vérification adversariale a tourné le 2026-08-20 sur le livrable de
l'étape 3 (`scripts/bench_refs_curve.py`, `tests/test_refs_curve.py`,
[`COURBE-REFERENCES.md`](COURBE-REFERENCES.md)). Elle a **confirmé le harnais**
— appariement `.npz` ↔ base recompté sans réutiliser le code mesuré (1533
lignes des deux côtés, 862 asset_id appariés à 0 écart dans chaque sens,
`selected_sim` monotone sur 680 paires, 0 violation), reproduction du banc
officiel au dixième de point, **10 mutations sur 10 font rougir** les tests,
`1843 passed` dans les deux ordres — et **cassé le résultat le plus vendeur du
rapport**. Cinq lignes, toutes 🔴.

**La lentille qui a payé, et qui manquait au §8.9 comme au §8.10** : « ce
chiffre survit-il à un paramètre de présentation que je n'ai pas choisi ? ».
Ici le paramètre était le **maillage des paliers**, et le fait s'est dissous.

| # | Défaut | Preuve | Effet | État au 20/08 |
|---|---|---|---|---|
| **Q13** | **Le gold et la banque ne tirent pas leur vérité de la même colonne.** Le gold est bâti sur `review_queue.decided_eurio_id` (`selection_sql` du sidecar `state/validation_gold/encoder_bench_gold.meta.json`) ; la banque sur `image_assets.eurio_id` (`_candidate_crops_for_class`, `training/foundation/anchors.py:794-818`). | Intersection des deux : **5 asset_id divergents**. Ex. `e7d4caa900364c67aa9a53f697591087` — gold `de-2020-2eur-german-polish-reconciliation` (`decided_at` 2026-06-15, `decided_by` admin), `image_assets.eurio_id` `de-2020-2eur-brandenburg-the-bundeslander-series` (`resolution_status='manual'`), ligne `fps` rang 2 du build `23c637d93b43`. Les 4 autres : `5602672b…` / `d3af872b…` (fi-2016 von Wright vs Eino Leino), `dc16d9e7…` (fi-2017 indépendance vs fi-2009 Porvoo), `e8ef3523…` (Brandebourg). | **5 ancres de la banque portent une classe que la review contredit** — des faux attracteurs par construction, et le banc les note contre une vérité qu'elles ne partagent pas. Impact sur la courbe : négligeable (5 sur 862, tous hors held-out). Impact sur le scoring de production : non chiffré. | 🔴 **ouvert, non diagnostiqué.** On n'a pas déterminé quelle colonne fait foi, ni si `image_assets.eurio_id` a été requalifié **après** le gel du gold (sidecar `db_mtime 2026-08-19T00:22:48Z`, décisions de juin). Trancher demande le journal de requalification au canonique. |
| **Q14** | **Le seuil du détecteur de rendement décroissant est sous le plancher de bruit, et il fabrique un fait.** `diminishing_returns()` (`scripts/bench_refs_curve.py`) déclare un coude au plus petit N dont tous les segments suivants rapportent < **1 point de global@1 par référence**. Sur 1100 crops held-out, **1 point = 11 crops**. Le verdict dépend donc du maillage des paliers, pas de la courbe. | Même script, mêmes données, deux maillages : `--refs 0 1 2 3 5 8 10` → « **Rendement décroissant à N = 8** … 0.77 point … par référence ajoutée » ; `--refs 4 5 6 7 8 9 10` → `knees {'variable': None, 'constante': None}`, « **Aucun coude dans la plage mesurée** ». Gains mesurés au maillage fin : 3,72 · 4,82 · 1,00 · 1,73 · **0,18** · 1,36 pt/réf. Analyse appariée (McNemar, `vits14`, population variable) : 8→9 `net +2, z=0,50` (bruit) mais **8→10 `net +17, +1,55 pt, z=2,38, p≈0,017`** et 9→10 `z=2,54`. | La première rédaction de [`COURBE-REFERENCES.md`](COURBE-REFERENCES.md) présentait « coude à N=8, ne pas dépasser 10 » comme le résultat le plus solide du document. **Le segment qu'elle proposait d'abandonner rapporte un gain significatif.** La recommandation « viser 8 » survit comme **arbitrage coût/bénéfice** ; « ne pas dépasser 10 » ne survit pas. | 🔴 **ouvert.** Document corrigé le jour même (§3.5 et bandeau de tête). Reste au code : choisir un seuil **au-dessus** du bruit et le justifier, ou rendre le détecteur muet quand l'écart apparié n'est pas significatif. Aucun test ne peut attraper ça — le détecteur est juste, c'est son seuil qui ment. |
| **Q15** | **Le banc d'encodeurs note sur le gold entier, fuite comprise : son niveau absolu est optimiste.** `scripts/bench_encoder_dino.py` score les 1958 crops, dont **858 SONT des lignes de la banque** — une similarité de 1,0 avec soi-même. Et rien ne le trace : `encoder_bench_runs` n'a pas de colonne `n_leaked`. | Intersection `{asset_id du gold}` ∩ `{asset_id du .npz}` = **858**. Écart fuité − held-out sur global@1 à N=10 : **+10,4 pts** (`vits14` 85,9 → 75,5) et **+5,9 pts** (`vitl14` 91,6 → 85,7). Le harnais de la courbe reproduit le banc au dixième de point en régime fuité, ce qui écarte l'hypothèse d'une divergence d'implémentation. | Le **classement** n'est pas retourné (`vitl14` devance `vits14` dans les deux régimes) et le McNemar publié reste valide sur sa propre population. Mais c'est le **niveau absolu** qu'on lit pour décider si le scan est « assez bon », et **un seuil d'auto-acceptation calibré sur ce régime serait optimiste**. | 🔴 **ouvert, décision et non retouche.** Geste minimal : tracer `n_leaked` dans `encoder_bench_runs`. Geste juste : ajouter une bande held-out au banc. Rien n'a été modifié dans `bench_encoder_dino.py`. |
| **Q16** | **⚠️ Symétrique de Q15, et plus discret : la population held-out n'est pas un plancher prudent.** Le rapport opposait « fuité = gonflé » à « held-out = honnête ». Or **à N=0 la banque est canonique seule, aucune fuite n'est possible**, et l'écart subsiste — donc il ne mesure pas la fuite mais un **biais de sélection** : le FPS retient les crops les plus diversifiants, donc les plus **durs**, et ce sont eux qu'on exclut. | À N=0 : `vits14` **53,1 %** held-out (1100 crops) contre **47,7 %** sur les 1958 in-scope ; `vitl14` **76,1 %** contre **70,5 %**. Les 858 crops écartés valent `(934−584)/858 = 40,8 %` à eux seuls. | Aucune des deux populations ne donne le niveau absolu qu'on cherche, et **les deux biais jouent en sens contraire** selon le palier (la fuite l'emporte dès N=1) : on ne peut corriger ni l'une ni l'autre par un décalage constant. ⚠️ **estimation** : rien ne garantit que l'écart de 5,5 pts soit stable aux paliers supérieurs, **non mesuré** ailleurs qu'à N=0. | 🔴 **ouvert.** Document corrigé (§5.1). La lecture honnête demande une population **tierce** — des crops décidés que le FPS n'a ni retenus ni écartés pour leur atypicité, c'est-à-dire un échantillonnage aléatoire du pool de review avant construction de la banque. |
| **Q17** | **Le rapport `BENCH-ENCODEURS.md` porte un en-tête humain dans un fichier que le banc réécrit en entier.** `scripts/bench_encoder_dino.py:868` fait `Path(args.out).write_text(report + "\n", encoding="utf-8")` — il **remplace**, il n'append pas et ne préserve rien. | `grep -n 'write_text' ml/scripts/bench_encoder_dino.py` → `868: Path(args.out).write_text(report + "\n", encoding="utf-8")`. | Un rerun pointé sur `docs/work-in-progress/scan-sans-retrain/BENCH-ENCODEURS.md` **détruit** l'analyse humaine ajoutée le 2026-08-20 (le renversement DINOv3, les réserves H13). Perte silencieuse : le script sort en 0. | 🔴 **ouvert, mitigé par une convention.** Un commentaire HTML en tête du fichier dit la conduite : sortir vers `/tmp`, puis recoller le corps sous le séparateur « CORPS GÉNÉRÉ ». La garde réelle serait que le script préserve ce qui précède ce séparateur. |

**Ce qui a été confirmé au passage, et qui tient** : l'hypothèse centrale de la
courbe (le rang FPS est un ordre glouton, donc un préfixe par rang équivaut à un
build `exemplars_per_class = N`) est vraie et **mieux étayée que le rapport ne
le disait** — `selected_sim` est monotone croissant avec le rang sur les 680
paires consécutives, **0 violation**, signature exacte du glouton ; la boucle
`farthest_point_select` (`training/foundation/anchors.py:448-505`) est amorcée
par le canonique pour les 671 classes (`n_no_canonical=0`), et ce build ne
contient aucun `manual_pin`. Le scoring de la courbe n'est pas une seconde
implémentation à comparer : ce sont **les mêmes fonctions importées**
(`_load_model`, `encode_paths`, `score_crops`, `top_k_match`,
`top_k_match_country`) ; aucune ne lit `bank.encoder_version`, donc l'étiquette
`dinov2-vitl14` que `sub_bank` traîne sur une matrice ré-encodée en `vits14` est
**inerte** — piège latent, pas biais actuel. Les effectifs annoncés sont justes
(1958 in-scope, 858 fuités, 1100 held-out / 72 classes, 1055 / 52 classes), les
deux populations sont réellement distinctes dans le code (mutée, elle rougit),
et la table de budget (1 622 / 2 805 / 4 622 / 5 848) est arithmétiquement
exacte. Hygiène : `.npz` inchangé (8,5 Mo, 19 Aug 16:36), aucun droit modifié,
aucune sonde laissée sous `ml/tests/`.

**Ordre de traitement proposé** : **Q15** en premier — c'est celui qui fausse un
chiffre déjà publié et déjà cité dans trois documents — puis **Q13** (une vérité
contradictoire en base vaut mieux tranchée tôt), puis **Q17** (une seule
commande peut détruire un livrable), puis **Q14** et **Q16**, qui sont des
corrections de **méthode de lecture** et sont déjà portées par le document.



### 8.12 Défauts NEUFS, trouvés en vérifiant le plancher, l'allocateur et la skill

Deux vérifications adversariales ont tourné le 2026-08-20 sur les trois
livrables du jour — le plancher `min_exemplars` (lot A), l'allocateur de scrape
eBay (lot B), la skill `eurio-banque` (lot C). Elles ont **confirmé l'essentiel**
: la migration 0011 rejouée par le VRAI runner (`serving.db_migrate
.run_migrations`) préserve la ligne préexistante et ne laisse aucune table
résiduelle ; le CHECK conditionnel accepte `min_exemplars = 50` et refuse
toujours `spread_auto_accept_min = 7` ; le plan de l'allocateur est déterministe
(deux exécutions, `diff` vide), ses 37 représentants existent tous au
référentiel, sa commande passe bien par `go-task ml:src:ebay:run` (donc
`EURIO_CENSUS_RECOVER=1`) ; onze des treize commandes de la skill rendent
exactement ce qu'elle annonce. Aucun appel eBay émis, `.npz` toujours au 19 août
16:36.

**La lentille qui a payé ici** : « ce chiffre a-t-il une DATE, et la base
a-t-elle bougé depuis ? ». Trois des douze lignes ci-dessous ne sont pas des
bugs de code mais des **preuves périmées en six heures** — et l'une d'elles
portait la conclusion la plus citée du lot A.

**Une treizième ligne, S13, a été ajoutée le soir même** : le re-bench de la
banque effectivement construite sous le plancher a **contredit le plancher**
(−1,4 pt held-out en vits14). Elle n'est pas sortie d'une vérification
adversariale mais d'une mesure de contrôle — et elle porte l'erreur de
raisonnement la plus coûteuse du chantier, cf. §8.0 bloc B.

| # | Défaut | Preuve | Effet | État au 20/08 (soir) |
|---|---|---|---|---|
| **S1** | **Un plancher fractionnaire est accepté et désarme le garde en se déclarant réglé.** `store.dino_thresholds.set_threshold` valide `BOUNDS['min_exemplars'] = (0.0, 50.0)` sur un `float(value)` sans vérifier l'intégralité ; `anchors.py` relit `int(seuils['min_exemplars'])`. | Sur une table à la forme 0011 : `pose 1.9 → resolve 1.9 source db → int() 1` ; `pose 0.4 → resolve 0.4 → int() 0`. | **`min_exemplars = 1,9` pose un plancher effectif de 1** — exactement le régime N=1 (50,1 % held-out contre 53,1 % à N=0) que tout le lot A existe pour interdire — avec `source='db'` pour caution à l'écran de réglage. Le journal du build le dit (`min_exemplars=1 (source=db)`), mais après coup et seulement pour qui lit le log. | ✅ **corrigé le 2026-08-20 (soir).** `shared/dino_threshold_defaults.CLES_ENTIERES` nomme les clés qui sont des COMPTES ; `set_threshold` refuse une valeur non entière pour celles-là (400, message qui dit pourquoi et quoi poser) ; et `build_anchors_2eur_all` journalise en WARNING une ligne fractionnaire **déjà** en base plutôt que de la tronquer en silence. Tests : `tests/test_plancher_exemplaires.py::test_un_plancher_fractionnaire_est_refuse_a_lecriture` et `::test_une_ligne_fractionnaire_deja_en_base_ne_passe_pas_en_silence` — rouge avant (`2 failed, 11 passed`), vert après (`13 passed`). |
| **S2** | **`--dry-run` de l'allocateur n'est lu NULLE PART.** `grep -n dry_run scripts/allocate_ebay_scrape.py` ne rend que son `add_argument` (`action='store_true', default=True`) ; `main()` ne teste que `args.execute` puis `args.yes`. | `--budget 300 --dry-run --execute --yes` partait exécuter les vagues. Seule la garde `--yes` protégeait (vérifiée : `--dry-run --execute` sans `--yes` → exit 1). | **La commande la plus prudente à lire brûle le quota** — du vrai argent — en affichant qu'elle ne le brûle pas. C'est la forme la plus dangereuse d'un drapeau mort : il rassure. | ✅ **corrigé le 2026-08-20 (soir).** `--dry-run` et `--execute` sont dans un `add_mutually_exclusive_group` : argparse sort en **2** sur la paire, avant toute lecture de base. Test `test_dry_run_et_execute_ensemble_sont_refuses` (runner qui lève si appelé) — rouge avant, vert après. |
| **S3** | **Le préflight quota de `sources.cli`, présenté comme la marge de sécurité de l'allocateur, est aveugle d'un facteur ~130.** `estimate_calls_per_eurio_id` (`serving/sources_routes.py:2150`) moyenne `n_calls / targets` sur les 5 derniers runs eBay — or `source_runs.n_calls` est le compteur que le lot B a lui-même démontré faux. | `check_ebay_quota(Store(replique), n_eurio_ids=8)` → `{'ok': True, 'estimate': 8, 'remaining': 5000, 'avg_calls_per_eurio_id': 0.95, 'max_safe_batch': 4054}` pour une vague que l'allocateur budgète **1040** (8 × 130). Les `n_calls` des 5 derniers runs valent 3, 29, 1, 1, 2 ; `api_call_log` porte **740** pour le run du 2026-08-16. | Aucune vague qui dérape ne sera arrêtée par ce préflight. **Un garde branché sur un compteur faux est un garde absent** — et le document de l'allocateur le citait comme filet. | 🔴 **ouvert.** Le correctif vit dans `serving/sources_routes.py`, sur le chemin du scrape : pas touché ici (aucune mesure possible sans brûler du quota). **Contourné, pas fermé** : l'allocateur pose son propre filet sur `api_call_log` (S4), et `ALLOCATEUR-SCRAPE.md` §« Il ne dépasse pas le budget » dit désormais que le préflight ne rattrape rien. |
| **S4** | **Le budget de l'allocateur n'était calculé qu'une fois**, avant la première vague ; `execute()` enchaînait toutes les vagues sans jamais relire `api_call_log`. | `scripts/allocate_ebay_scrape.py` (avant correctif) l. 548-558 : `for wave in waves(...)`, `rc = runner(cmd)`, arrêt seulement si `rc != 0` ; `remaining_quota_today()` appelé une seule fois, l. 653. | Un plan à 5000 appels tient 5 vagues ; le coût réel peut dépasser de 25 % (le lot B annonce lui-même « 4000 ou 6000 »), et rien ne s'interposait — S3 garantissant que le préflight ne produirait pas le `rc != 0` attendu. | ✅ **corrigé le 2026-08-20 (soir).** `execute(..., quota_reader=None)` relit le compteur RÉEL avant **chaque** vague et sort en 1, sans lancer, si `restant < coût prévu × 1,3` ; le message dit quoi faire. Tests `test_le_quota_reel_est_relu_entre_deux_vagues` (10000 puis 0 → 1 seule vague partie, `rc=1`) et sa contre-épreuve — rouge avant, vert après. |
| **S5** | **La preuve chiffrée du lot A est fausse : les 64 classes à un exemplaire n'ont PAS toutes un pool éligible ≤ 1.** Le lot annonçait « pool >=2 : 0 ; <=1 : 64 » comme *mesure*, et en déduisait l'effet du prochain rebuild (182 → 118 classes à exemplaires, 1533 → 1469 lignes). | Avec les fonctions du builder elles-mêmes (`_class_specs_2eur_all` puis `_candidate_crops_for_class`), sur `state/eurio.replica.db`, **2026-08-20 13:58 UTC** : `{'<=1': 61, '>=2': 3}` — `it-2018-…ministry-of-health` (2), `it-2023-…air-force` (4), `it-2025-…jubilee-year-2025` (4). Les deux vérifications l'ont trouvé indépendamment. Cause mesurée : leurs crops supplémentaires portent `resolved_at` entre 13:38 et 13:41 UTC — **validés dans l'heure**, après la mesure du lot. | La conclusion (« ces classes repassent au canonique seul ») survit probablement ; le raisonnement qui la porte, non — et il **ne peut pas** être remplacé par un compte de pool, puisque ce qui décide est la sortie du FPS, donc l'encodage. « 182 → 118 » est une **borne**, pas un compte. | ⏭ **requalifié : preuve périmée, pas défaut de code.** Corrigé partout où il était écrit — skill `eurio-banque` §3, [`DECISION.md`](DECISION.md) et [`PREREQUIS.md`](PREREQUIS.md) disent maintenant que le seul chiffre qui fera foi est celui du prochain build (`dino_anchor_builds.note`, ligne `plancher : N classes ramenées au canonique seul`). |
| **S6** | **La courbe références/classe ne simule PLUS ce que le builder produit.** `scripts/bench_refs_curve.py:135-175` tronque la banque par rang FPS ; `grep -n min_exemplars ml/scripts/bench_refs_curve.py` → **aucune occurrence**, alors que le builder vide `picks` sous le plancher (`anchors.py:1031-1040`). | Les deux fichiers, côte à côte. | La courbe est **l'unique preuve** qui justifie le plancher. Depuis A1, son point **N=1 décrit une banque que le builder ne peut plus construire**, et son N=2 conserve à un exemplaire des classes que le vrai build ramènerait au canonique seul. Elle reste juste comme mesure du rendement d'un exemplaire de plus ; elle n'est plus une prédiction de la banque de demain. | 🔴 **ouvert, et c'est un choix.** Faire connaître `min_exemplars` à la courbe changerait la définition de ses paliers (à N=1, « aucune classe » n'est pas un palier) : le sujet est la **méthode de lecture**, pas une ligne de code. Dit dans la skill §3, dans le `desc:` de `ml:refs-curve:run`, et ici. |
| **S7** | **Le plancher se LIT sur la base pointée par `--db` — la réplique sous Direction A — alors qu'il s'ÉCRIT au canonique.** `build_anchors_2eur_all` résout via `dino_seuils.resolve(conn, …)` où `conn` vient de `Store(Path(args.db))`, et `DB_PATH = resolve_db_path(ML_DIR/'state'/'eurio.db')` → `EURIO_DB_PATH` → réplique. | `state/eurio.replica.db.sync.json` → `pulled_at_iso 2026-08-20T01:22:12+00:00`, soit **14 h de retard** à l'heure de la vérification. | Une valeur posée par le PO au canonique n'atteint le build **qu'après un pull de réplique**, sans aucune garde de fraîcheur. Atténuation réelle : le journal et `dino_anchor_builds.note` disent `source=db|code`, donc la divergence est traçable **après** coup — pas empêchée avant. | 🔴 **ouvert.** Même famille que le §8.7 (le chemin de base) : ce n'est pas un bug local mais la conséquence de Direction A. Écrit dans le `desc:` de `ml:dino-anchors:build` : **le contrôle est la note du build**, pas la commande. |
| **S8** | **Un chiffre de la skill `eurio-banque` est irreproductible, et il va dans le sens qui rassure.** §4 annonçait, entre parenthèses, « 716 / 816 crops, 98,6 % / 99,4 % en maille classe » pour la métrique `COALESCE(country_spread, spread)` — celle que le verdict de review utilise réellement. | Même recette, même effectif (716 / 816), 2026-08-20 13:58 UTC : **hors banque 716 → 91,8 %**, ancre 816 → 99,4 %. Les quatre variantes plausibles ont été essayées (`country_spread` seul, `top1_country_eurio_id`, vérité `truth_eurio_id` → 84,2 %) : **aucune ne rend 98,6 %**. Le chiffre principal du §4 (463 → 98,5 %, 821 → 97,4 %, sur `spread` global et vérité `truth_eurio_id`) se reproduit **exactement**. | 6,8 points d'écart sur la métrique du verdict, **du côté qui affaiblit D4**. Un chiffre faux dans une skill se propage à toutes les sessions futures — c'est le pire endroit du dépôt où en laisser un. | ✅ **corrigé le 2026-08-20 (soir).** Le §4 de la skill porte désormais les **quatre** combinaisons (marge × vérité) en table, chacune horodatée, et dit explicitement que la métrique du verdict est la moins bonne des quatre hors banque. |
| **S9** | **« La base n'a pas bougé, son `mtime` est inchangé » ne prouve rien en WAL** — et le lot B s'en servait comme preuve de non-écriture. | `stat` : `eurio.replica.db` à 03:22, son `-wal` à **la seconde courante** ; `SELECT MAX(resolved_at) FROM image_assets` → 7 s avant la requête ; `review_queue` : 64 items passés de `open` à `done` dans la journée, total conservé (11 858). | Toute conclusion « rien n'a été écrit » adossée au `mtime` du `.db` est sans valeur. Ici l'écrivain était la review du PO, pas les lots — mais la méthode ne permettait pas de le savoir. | ⏭ **requalifié : défaut de méthode.** Entré au catalogue de `eurio-verify` (« la base n'a pas bougé »). La preuve valable est le `-wal`, ou un `MAX(<date>)`, ou un instantané `VACUUM INTO`. |
| **S10** | **Deux affirmations fausses dans `ALLOCATEUR-SCRAPE.md`** : « aucune ligne `empty_upstream` dans toute la base » (il y en a **19**) et le mécanisme d'exclusion de FR/2015 (« ses 49 candidats couvrent tout son déficit »). | `SELECT source, state, COUNT(*) FROM coin_source_status GROUP BY 1,2` → `bce_official\|empty_upstream\|18`, `lmdlp\|empty_upstream\|1` ; aucune pour eBay. `build_group_plans` à 14:05 UTC → `FR/2015 … served=13.0, need=13, pending=49, score=0,100`, détail par classe `have=[0,0,0,1,2] need=[3,2,8,0,0]` ; le 37ᵉ retenu est à 0,131 : FR/2015 sort **par le score**. | La première inexactitude fait croire que le mécanisme `empty_upstream` n'existe nulle part, alors qu'il sert ailleurs et que seul eBay ne l'emprunte pas. La seconde donne comme illustration d'une règle un cas qui n'en relève pas — le lecteur en tirerait une intuition fausse du seuil de coupe. | ✅ **corrigé le 2026-08-20 (soir)** dans `ALLOCATEUR-SCRAPE.md`, avec la sortie complète des deux requêtes. La règle « on ne scrape pas ce qui attend en review » **mord réellement** : 49 classes déficitaires ont un besoin résiduel nul grâce à la file (`alloc.review_covered`, mesuré à 14:05 UTC). |
| **S11** | **`resolve()` ne revalide jamais ce qu'elle lit en base.** Les `BOUNDS` du code ne sont appliquées que par la voie `set_threshold` ; le CHECK SQL de 0011, lui, borne les similarités à `[0, 1]`. | Une ligne `spread_auto_accept_min = 0.9` passe le CHECK SQL (≤ 1.0) alors que `BOUNDS` s'arrête à 0.5 — et `resolve()` la sert telle quelle. | Un seuil posé par un chemin autre que `set_threshold` (SQL à la main, autre writer, import) peut servir une valeur que le code déclare absurde. Un `spread_auto_accept_min = 0,9` **gèlerait l'auto-acceptation** en silence — c'est le cas nommé dans le commentaire de `BOUNDS`. | 🔴 **ouvert.** Même famille que S1, qu'on vient de fermer côté écriture seulement. Issue cohérente avec la doctrine du §8.9 (« l'invariant descend jusqu'à la porte ») : faire revalider `resolve()` et **journaliser** une valeur hors bornes plutôt que la servir — jamais la corriger en douce. |
| **S12** | **Trois livrables publient des comptes du jour sur une base qui bouge d'heure en heure, sans horodatage à la minute.** Chaque chiffre porte bien sa requête — la discipline est respectée — mais pas son heure. | Écarts mesurés entre les lots (matin) et leur vérification (après-midi) du **même** jour : 793 → 792 exemplaires visés, 3932 → 3940 de déficit, 50 → 49 classes couvertes par la review, file 6894 → 6830 puis 6798 ouverts, répartition des 489 classes pauvres `305/78/36/26/21/23` → `306/77/38/24/21/23`. Aucun écart n'est une erreur de méthode ; tous sont de la review qui avance. | Sans l'heure, **on ne peut pas distinguer une erreur de six heures de review** — et c'est ce qui a fait perdre du temps sur S5. | ⏭ **convention posée le 2026-08-20 (soir)** : tout compte publié porte sa requête **et** son horodatage à la minute, en UTC. Appliquée dans la skill `eurio-banque` (§2, §4, §8), dans `eurio-review`, dans `ALLOCATEUR-SCRAPE.md` et dans ce §8.12. |

| **S13** | **Le plancher `min_exemplars = 2` a été posé sur une EXTRAPOLATION, et le re-bench le contredit.** La preuve invoquée était le point **N=1** de la courbe références/classe (50,1 % contre 53,1 % à N=0, vits14 held-out). Or ce point signifie « **toutes** les classes plafonnées à 1 », pas « 68 classes en ont 1 et les autres sont pleines ». On a **extrapolé d'un agrégat à une règle par classe** — et c'est exactement le trou que **S6** décrit côté outil (la courbe ne connaît pas `min_exemplars`, `grep -n min_exemplars ml/scripts/bench_refs_curve.py` → rien). | Re-bench held-out à N=10 (= la banque réellement servie), banque **avant** plancher (1533 ancres, 182 classes à exemplaires) contre **après** (1495 ancres, 124 classes à exemplaires, 68 ramenées au canonique seul) :<br><br>`dinov2_vits14` : **75,5 % → 74,1 %** (**−1,4**)<br>`dinov2_vitl14` : **85,7 % → 84,8 %** (**−0,9**)<br><br>**Contrôle qui valide la comparaison** : à N=0 les deux banques sont identiques (671 canoniques) et rendent le même score à 0,1 pt près (53,1 → 53,2 vits14 ; 76,1 → 76,2 vitl14) — les populations sont donc comparables malgré le passage de 1100 à 1179 crops held-out.<br><br>⚠️ **Réserves à porter avec le chiffre** : la banque a changé **autrement** que par le plancher (le FPS a rejoué sur un pool qui avait bougé, 10 classes ont **gagné** des exemplaires, les crops fuités sont passés de 858 à 779), et 1495 ancres offrent mécaniquement moins que 1533. Le delta n'est donc pas imputable au seul plancher.<br><br>🔍 **Curiosité non expliquée** : à **N=2** la nouvelle banque est **meilleure** (55,9 % contre 54,6 %) avec **moins** de lignes ; elle ne perd qu'à N=8 et N=10. | **Le plancher a dégradé, pas amélioré.** Il a été livré comme un correctif de la régression N=1, avec sa migration (0011), sa clé de seuil, son garde d'intégralité (S1) et sa documentation dans trois fichiers — sur une inférence que personne n'avait mesurée. Et c'est **la troisième fois en deux jours** qu'un chiffre plausible ne survit pas à sa vérification (après « coude à N=8 » → **Q14**, et « pool ≤ 1 pour les 64 classes » → **S5**) : les deux premières venaient d'un outil, **celle-ci vient de nous**. La leçon est de méthode, et elle survit au sort du plancher : **un agrégat ne se lit pas comme une règle par classe** — un point de courbe « toutes les classes à N » ne prédit pas « ces classes-ci à N, les autres pleines ». Le seul chiffre qui aurait tranché est celui qu'on a fini par mesurer : un re-bench de la banque réellement construite. | 🔴 **ouvert — l'erreur de raisonnement ; le plancher, lui, est TRANCHÉ (retiré le 2026-08-20 au soir).** Cette ligne reste : elle documente le motif, pas le sort du drapeau.<br><br>**Ce que l'issue (3) est devenue.** Elle demandait « une banque bâtie deux fois sur le même pool, plancher 0 puis 2 » — un rebuild double, 237 s + ~41 min de P3 chacun. Une expérience **moins chère et plus informative** l'a remplacée : restreindre la courbe au lieu de rebâtir. `bench_refs_curve.py` a reçu `--bank-classes` (le plafond N ne s'applique qu'à ces classes), `--gold-classes` (seuls ces crops sont notés), `--rank-order last` (sonde de mécanisme), et McNemar exact par palier. Lecture seule, zéro rebuild.<br><br>**Trois résultats.** (a) La population que le plancher visait est **inévaluable** : 77 crops dans le gold pour ces classes, dont **61 sont le crop qui deviendrait leur ancre** — il reste **16 crops held-out** pour ~70 classes. (b) Donner à 57 classes riches **exactement un** exemplaire **AMÉLIORE** leurs propres crops : `vitl14` 67,6 → **69,1 %** (p=0,048), `vits14` 41,6 → **45,5 %** (p=4,5e-10) — la prémisse est fausse dans le sens où elle était affirmée. (c) Le creux à N=1 vient de l'**ORDRE** du FPS, pas du nombre : non significatif en `vits14` (53,2 → 52,1 %, **p=0,279**), et à nombre d'ancres identique `--rank-order last` rend **77,8 %** au lieu de 73,8 % en `vitl14`.<br><br>**Décidé** : `min_exemplars` = **1** (plancher inactif) pour les deux couples ; mécanisme conservé, 14 tests, reposer 2 est une ligne dans `dino_thresholds`.<br><br>⚠️ **Ce qui reste ouvert** : la mesure décisive est un **PROXY** (classes riches plafonnées à 1), pas les classes pauvres visées — celles-ci restent inévaluables tant que le gold ne les voit pas. Et le vrai levier, **l'amorce du FPS** (médoïde au lieu du point le plus lointain), n'est **pas** implémenté : la configuration livrée est celle dont le tort est le mieux étayé, sans son correctif de mécanisme.<br><br>⚠️ **Conséquence non gardée** : la banque **servie** porte le plancher, le code ne l'applique plus. Le prochain rebuild changera sa forme (68 classes retrouvent leur exemplaire) et **P1 ne le signalera pas** — il compte les classes à ≥ 2 exemplaires, compte invariant par ce retour. Découplage délibéré (lot B), inversion silencieuse.<br><br>**S6** n'est plus un prérequis mais reste vrai : un palier N de la courbe est « toutes les classes à N ». |

**Ordre de traitement proposé pour ce qui reste ouvert** : **S3** en premier —
c'est le seul qui puisse coûter de l'argent, et son contournement (S4) vit dans
un autre fichier que le garde faux ; puis **S11** (une valeur absurde servie sans
un mot) ; puis **S7** (la fraîcheur du seuil au build) ; **S6** en dernier, parce
que c'est une décision de méthode et qu'elle est déjà dite partout où elle se
lit. ⚠️ **Cet ordre est antérieur à S13 et il est à réviser** : S13 fait de S6
un **prérequis**, pas un reliquat — tant que la courbe ne simule pas le
builder, elle continuera de servir de preuve à des règles par classe qu'elle
ne mesure pas.


---

## 9. Ce qui reste bloqué, et par quoi

| Geste | État | Débloqué par |
|---|---|---|
| Rebuild de la banque `2eur_all` avec le `--db` corrigé | 🟢 **fait le 2026-08-19 à 16:36** — 671 classes, 1533 ancres, 862 exemplaires, **182 classes à exemplaires** (contre 125), canonique-seul 489 (contre 539). Build `23c637d93b43` poussé au canonique, 237 s. | — (détail : [`PREREQUIS.md`](PREREQUIS.md) §P1) |
| P3 — backfill `--force` des 12454 prédictions | 🟢 **abouti le 2026-08-19 au soir**, constaté le 2026-08-20 : `SELECT COUNT(*), MIN(computed_at), MAX(computed_at) FROM image_asset_dino_predictions WHERE anchors_kind='2eur_all' AND encoder_version='dinov2-vitl14'` → `12454 | 2026-08-19 23:20:42 | 2026-08-19 23:48:36` (28 min), contre `MAX(built_at)='2026-08-19T14:36:14+00:00'` — les prédictions sont **postérieures de neuf heures** au build. `calibration_blockers(conn, anchors_kind='2eur_all', encoder_version='dinov2-vitl14')` → **`[]`**. 🔴 **Le « résultat non établi » du 2026-08-20 au soir était un artefact de requête** : la complétude écrite dans [`GESTE-P3.md`](GESTE-P3.md) compare `computed_at < built_at` **en chaînes**, deux formats différents (`'2026-08-19 23:48:36'` contre `'2026-08-19T14:36:14+00:00'` ; espace `0x20` < `T` `0x54`), donc toute prédiction paraît antérieure à tout build du même jour. Mesuré : `SELECT SUM(computed_at < b), SUM(datetime(computed_at) < datetime(b))` → `12454 | 0`. Le code `_p3_blockers` est corrigé (`datetime()` des deux côtés) ; **`GESTE-P3.md` ne l'est toujours pas** | — (le « 0 erreur » du run n'est pas vérifié ici, et **M8** fait sortir le backfill en code 0 même en erreur : la preuve retenue est `calibration_blockers → []`, qui se re-mesure en une commande) |
| Déploiement VPS de 0009 **et 0010** | 🚫 non fait | ⚠️ **Q6 et Q10 changent ce que ce redémarrage arme** : une fois 0010 appliquée, le premier build de banque d'un encodeur candidat rend faux tous les **lecteurs** de `dino_class_references` (§8.10 Q6 — route admin, badge de review, plan de capture P5). Fermer Q6 **avant** ce build. Geste humain : `git pull` sur `/opt/eurio` + `docker compose up -d --build` sur `infra/eurio-api` — c'est le redémarrage qui applique les migrations. **0010 doit être appliquée AVANT le premier build de banque d'un encodeur candidat** : c'est ce build qui arme le piège M1. Répétition faite sur copie `/tmp` de la réplique, les deux passent d'affilée, 1250 lignes préservées. Contrôle après redémarrage (attendu inchangé) : `SELECT encoder_version, method, COUNT(*) FROM dino_class_references GROUP BY 1,2;` → `dinov2-vitl14\|canonical\|671` et `…\|fps\|862`. En attendant, le writer **refuse** d'écrire sur une table à l'ancienne clé plutôt que d'écraser l'autre encodeur |
| Câblage du banc (D4/D5) | 🟢 **fait** (§10) | `bench_encoder_dino.py` lit le gold figé, mesure `calibration_blockers(…)`, imprime la bannière en tête ET en pied, refuse le seuil tant qu'un bloqueur tient, et pousse par `client.ingest.push_encoder_bench`. Reste à exercer un run RÉEL (GPU) |
| Campagne de capture P5 | 🟠 plan prêt, photos à faire | Deux gestes humains : créer la cohorte `scan-owned-80` via `POST /lab/cohorts` (écriture → canonique), puis builder l'APK cohortTest avec `NO_SAMPLE=1` |
| Avis juridique DINOv3 | 🟠 non bloquant pour le bench, **bloquant avant Play Store** | Trancher l'écart entre les deux versions publiées de la licence ; confirmer que §1.b.iv ne vise pas la conversion TFLite |
| Bench TFLite/NNAPI sur device | 🚫 non fait | Le verdict ViT-S/16 vs ConvNeXt-Tiny pour l'APK l'exige — les latences du §4 sont sur Mac |
| Vérification `snapArchiveDir` | 🚫 non vérifiée (pas de device) | Si l'archivage est inactif, les sessions produisent le JSONL mais **aucune frame corpus**. La requête de contrôle du protocole §3 l'attrape dès la première session |

**Rien n'est commité.** L'arbre porte les modifications et les 14 images
téléchargées (dossier `ml/datasets/` gitignoré).

---

## 10. La passe de correction — les 16 défauts, ce qui a été fait

**Session du 2026-08-19.** Quatre agents sur des périmètres disjoints, puis une
passe d'intégration (schéma, migrations, `tasks.yml`, suite complète). Rien
n'est commité ; P3 n'a pas été lancé ; la banque servie n'a pas été rebâtie.

> ⚠️ **Les statuts de ce §10 sont ceux REVENDIQUÉS par les lots de correction.**
> Deux vérifications adversariales les ont ensuite rabaissés sur cinq points —
> **D1** (P1 ne filtre pas l'encodeur), **D2** (la version du gold n'est jamais
> vérifiée), **D5** (`truth_eurio_id` porte le `class_id`, non documenté en SQL),
> **D8** (garde asymétrique), **D16** (recouvrement partiel, `n_paired` non
> persisté) — plus une dette de couverture sur **D6** et six défauts neufs
> (N1..N6). **Le registre qui fait foi est le [§8](#8-registre-de-dette--d1d16-n1n6-m1m11-avec-leur-état).** Une **seconde** passe de correction (2026-08-20) a depuis fermé D1(P1), D5, D8, D16, N1, N2 et N6, et une seconde vérification a rendu onze défauts neufs (§8.8).

### 10.1 Le relevé

| # | Statut | Ce qui a changé | Le test qui le tient |
|---|---|---|---|
| **D1** | ⚠️ | `calibration_blockers` délègue à `_p3_blockers` / `_p1_blockers` (`store/encoder_bench.py:248-397`). P3 bloque dans **4** cas au lieu d'1 : tables absentes, aucun build tracé pour le couple, build tracé mais 0 prédiction, prédictions périmées. P1 bloque aussi si `dino_class_references` est absente. Principe posé : **ce qui n'est pas mesurable bloque.** **⚠️ Reste ouvert (§8.1) : P1 ne filtre pas `encoder_version`** — le même auto-désarmement, déplacé de P3 vers P1. | `test_encoder_bench_store.py::test_calibration_blockers_encodeur_candidat_sans_build`, `…_build_trace_mais_zero_prediction`, `…_referentiel_absent_bloque_sans_exploser` |
| **D2** | ⚠️ | `gold_version(rows: Sequence[GoldCrop])` hache `asset_id\|truth_eurio_id\|class_id` trié, sha256[:12] ; une liste d'`asset_id` nus lève un `TypeError` explicite. `diff_gold` gagne `class_changed`, le CLI l'imprime. **⚠️ Reste ouvert (§8.1) : le `gold_version` est déclaré, jamais vérifié** — rien ne recalcule le hash du manifeste contre son sidecar. | `test_bench_gold.py::test_gold_version_bouge_quand_une_verite_est_re_tranchee`, `…_quand_un_class_id_change`, `…_refuse_une_liste_d_asset_ids`, `test_diff_gold_signale_un_class_id_change` |
| **D3** | ✅ | `load_anchors` journalise en ERROR le refus inter-encodeurs ; `_get_bank` relit la **banque servie**, ce qui rend son garde « banque périmée » de nouveau atteignable. | `test_anchor_bank_serving.py::test_d3_get_bank_journalise_quand_la_banque_servie_est_perimee`, `test_d3_load_anchors_journalise_le_refus_inter_encodeurs`, contre-épreuve `test_d3_pas_de_bruit_quand_tout_va_bien` |
| **D4** | ✅ | La bannière `⚠ CALIBRATION PROVISOIRE` vit dans le **chemin exécutable** : imprimée en tête ET en pied sur stderr, recopiée en tête et en pied du rapport `--out`. Le seuil ne sort pas tant qu'un bloqueur tient ; `--allow-provisional` rend le chiffre marqué. `provisional` en base suit les bloqueurs **mesurés**, jamais l'option. | `test_bench_encoder_dino.py::test_la_banniere_est_en_tete_ET_en_pied`, `…_survit_a_la_redirection_du_rapport`, `test_le_seuil_ne_sort_pas_tant_qu_un_bloqueur_tient`, `test_le_run_est_marque_provisional_meme_avec_allow` |
| **D5** | ⚠️ | `_load_labeled` et sa requête `review_queue` **supprimés**. Le banc lit le gold figé, trace son `gold_version`, et pousse run + prédictions par `POST /ingest/encoder-bench`. Une seule définition du jeu d'évaluation subsiste. **⚠️ Reste ouvert (§8.1) : `encoder_bench_predictions.truth_eurio_id` porte le `class_id`** (105 crops / 5,4 %), sans un mot dans `schema.sql` ni dans 0009. | `test_bench_encoder_dino.py::test_le_banc_ne_rejoue_plus_sa_propre_selection`, `test_le_banc_lit_le_gold_et_trace_sa_version`, `test_le_run_pousse_porte_le_gold_et_ses_predictions` |
| **D6** | ⚠️ | `target_country` → `truth_country`, **non nullable**, extrait de `decided_eurio_id`. Un `decided_eurio_id` sans préfixe ISO2 lève une `ValueError` nommant l'asset. Mesure : **242 lignes corrigées sur 1958** (33 faux, 209 nuls). Gold régénéré. **⚠️ Reste ouvert (§8.2) : la `ValueError` de non-silence n'est couverte par aucun test** (mutation `return ""` ⇒ 23 passed). | `test_bench_gold.py::test_truth_country_vient_de_la_decision_pas_de_la_cible_du_scrape`, `test_le_gold_ne_porte_plus_le_pays_du_scrape` |
| **D7** | ⏭ | **Requalifié, hors de cette passe.** C'est une question de méthode statistique (borne de Wilson, `min_covered`, split calibration/validation), pas un défaut de câblage — et son effet est aujourd'hui neutralisé par D4 : aucun seuil ne sort tant que P1/P3 bloquent. À trancher quand un seuil sera réellement promouvable. | — |
| **D8** | ⚠️ | Le bloqueur « echantillon » n'est émis que si `gold_sample_n < gold_n_crops`. Choix assumé : `gold_n_crops` **inconnu reste bloquant** — le littéral suggéré (`and gold_n_crops is not None`) aurait ouvert une porte de sortie par omission, la famille de pannes que D1 dénonce. **⚠️ Reste ouvert (§8.2) : le garde est asymétrique** — `gold_sample_n=99999` sur un gold de 1958 ne déclenche rien (`<` au lieu de `!=`). | `test_encoder_bench_store.py::test_calibration_blockers_gold_entier_nest_pas_un_echantillon`, `…_echantillon_sans_total_reste_bloquant` |
| **D9** | ✅ | `record_predictions(…, purge_empty=False)` : une liste vide ne purge plus. La route distingue les deux cas dans sa **réponse** — `predictions_replaced` — pour qu'un `n_predictions: 0` ne se lise pas « tout effacé ». | `test_encoder_bench_store.py::test_record_predictions_liste_vide_ne_purge_pas`, `test_ingest_encoder_bench.py::test_renvoyer_un_run_sans_predictions_ne_les_efface_pas`, `test_la_reponse_distingue_remplacement_et_abstention` |
| **D10** | ✅ | La déduction « la banque porte l'encodeur de production ⇒ on écrit le legacy » est **supprimée** : `dinov2-vitl14` est à la fois l'encodeur servi et le bras baseline, l'encodeur ne dit rien de l'intention. `save_anchors(…, write_legacy=False)` par défaut ; seul le CLI passe l'intention, exposée par `--no-serve`. | `test_anchor_bank_serving.py::test_d10_rebuild_baseline_n_ecrase_pas_la_banque_servie`, `test_d10_save_anchors_n_ecrit_pas_la_banque_servie_par_defaut`, `test_d10_remplacer_la_banque_servie_est_journalise` |
| **D11** | ✅ | Séparation par le **rôle**, pas par le contenu : `foundation_anchors_<kind>.npz` = la banque SERVIE (slot unique, 10 lecteurs sur 10) ; `…__<slug>.npz` = artefact de banc. Écriture **atomique** (tmp + `os.replace`), `bank_id` partagé par les deux fichiers d'un même save. Les deux options écartées (alias/lien, double-écrit vérifié) sont argumentées dans `anchors.py:138-196`. | `test_anchor_bank_serving.py::test_d11_ecriture_interrompue_laisse_la_banque_servie_intacte`, `test_d11_les_deux_fichiers_d_un_meme_save_partagent_leur_bank_id` |
| **D12** | ✅ | `DEFAULT_DB` supprimé → `default_db()` via `store.resolve_db_path`, résolu **à l'appel**. `_strate_of` lit `n_siblings_in_bank` : sans frère en banque, la classe est `orpheline` (5e strate), hors plan par défaut mais **nommée et comptée**, pas filtrée en SQL. Mesuré : 0 orpheline aujourd'hui, plan identique (80 classes / 400 cellules / 985 captures) — l'⚠️ estimation du §8.3 est confirmée. | `test_build_scan_prescription.py::test_orpheline_est_hors_du_plan_par_defaut`, `…_entre_au_plan_si_on_la_nomme`, `test_db_par_defaut_honore_eurio_db_path`, `test_aucun_chemin_de_base_code_en_dur` |
| **D13** | ✅ | Le CLI n'imprime plus de chemin en dur : `written_paths()` annonce une ligne par fichier, chacune **vérifiée sur disque** par `bank_id` (repli `built_at`+`count`). L'aide `--db` annonce la valeur réellement résolue et nomme `EURIO_DB_PATH`. | `test_anchor_bank_serving.py::test_d13_written_paths_ne_ment_pas_sur_un_cache_hit`, `test_d13_plus_aucun_chemin_de_banque_code_en_dur_dans_le_cli`, `test_d13_l_aide_db_ne_promet_plus_eurio_db` |
| **D14** | ✅ | Contextmanager `_row_access(conn)` qui pose `sqlite3.Row` **et restaure** le `row_factory` de l'appelant (patron déjà utilisé par `review/bench_gold.py`). | `test_encoder_bench_store.py::test_lectures_sur_connexion_nue_sans_row_factory`, `…_restaurent_le_row_factory_de_lappelant` |
| **D15** | ✅ | Le sweep illisible est journalisé en ERROR avec le `run_id`, **et** signalé dans la réponse (`sweep_error`, nul quand tout va bien). Une courbe corrompue n'est plus indistinguable d'un run sans balayage. | `test_ingest_encoder_bench.py::test_sweep_illisible_est_journalise_et_signale`, `test_sweep_absent_ne_signale_aucune_erreur` |
| **D16** | ⚠️ | Intersection vide ⇒ `acc_a`/`acc_b`/`delta_acc`/`p_value` valent `None` et `comparable` est `False`. Un test qui n'a pas eu lieu n'a pas de p-valeur ; `1.0` se lisait « aucune différence significative ». Le cas n_paired>0 sans discordance garde bien `p=1.0`. **⚠️ Reste ouvert (§8.3) : le recouvrement PARTIEL reste muet** (1 crop commun sur 501 ⇒ `p=1.0`), et `n_paired` n'est persisté nulle part. | `test_paired_stats.py::test_paired_compare_cles_disjointes_ne_compare_rien`, `…_intersection_non_vide_reste_comparable` |

### 10.2 Schéma et migrations : rien à changer — **sauf un point, trouvé après**

Aucun correctif n'a exigé de colonne ni de contrainte neuve. Vérifié plutôt
qu'affirmé — comparaison des trois déclarations d'une même table :

```
encoder_bench_runs         DDL↔dataclass : ∅ | payload↔dataclass : ∅ | miroir schema.sql identique : True
encoder_bench_predictions  DDL↔dataclass : ['run_id'] | payload↔dataclass : ∅ | miroir schema.sql identique : True
```

(`run_id` est passé à part à `record_predictions`, pas porté par la ligne.)

Le détail par défaut : D9 se règle **dans le store** (`purge_empty`) — rendre
`predictions` obligatoire côté payload aurait cassé les appelants sans rien
gagner, le DELETE conditionnel suffit ; D16 stocke `mcnemar_p = NULL`, colonne
déjà nullable ; D4 réutilise `provisional` / `provisional_reason` ; D5 réutilise
`gold_version` / `gold_sample_n` / `bank_build_id` ; D11 pose son `bank_id` dans
le **meta du `.npz`**, jamais en base. Ajouter une colonne que personne ne lit
serait exactement le refus argumenté au §7.5.

Seul le commentaire d'en-tête de `0009_encoder_bench.sql` a bougé : il annonçait
le miroir `schema.sql` comme « à écrire par l'agent d'intégration ». Il est
écrit, et `tests/test_schema_mirror.py` le verrouille.

> ⚠️ **La conclusion « rien à changer » tient pour 15 défauts sur 16, pas pour
> D16.** La garantie de D16 repose explicitement sur `n_paired` — « n_paired
> n'est pas décoratif », dit la docstring de `PairedResult` — or ce champ n'est
> persisté **nulle part** (`grep -n n_paired serving/migrations/0009_encoder_bench.sql
> state/schema.sql store/encoder_bench.py scripts/bench_encoder_dino.py` → 0
> occurrence). Un `mcnemar_p=1.0` mesuré sur 1 crop commun est indiscernable en
> base d'une égalité mesurée sur 1958. Le fermer demande une **migration 0010**
> (ALTER + miroir `schema.sql` + `_ensure_column`, les trois, comme 0004). Second
> point, sans migration celui-là : `encoder_bench_predictions.truth_eurio_id`
> porte le `class_id` et aucun des deux fichiers SQL ne le dit — la table est
> vide partout, un renommage en `truth_class_id` est encore gratuit (§8.1 D5).

### 10.3 Ce qui reste à faire

- **P1** (rebuild `2eur_all`) et **P3** (backfill `--force`) : toujours non
  lancés, sur go du PO. Le rebuild de production est inchangé côté opérateur —
  `go-task ml:dino-anchors:build -- --kind 2eur_all --force` sert la banque comme
  avant ; c'est `--no-serve` qui est neuf, pour un bras baseline de banc.
- **Un run réel du banc** : le câblage est prouvé (gold lu, bloqueurs mesurés sur
  la vraie réplique, bannière rendue, seuil refusé, payload assemblé), **pas les
  chiffres**. Il faut un GPU. Deux champs à relire au premier run :
  `bank_build_id` et `n_out_of_scope`.
- **D7** : la méthode de calibration du seuil, à trancher avant qu'un seuil soit
  promouvable.
- **Les cinq corrections partielles et les six défauts neufs** du
  [§8](#8-registre-de-dette--d1d16-et-n1n6-avec-leur-état). Par ordre d'urgence
  mesuré :
  1. **D1 (P1 non scopé)** et **N1 (`n_not_encoded` lu par personne)** — les deux
     seuls qui produisent un **faux vert** sur le chemin que le PO va emprunter.
     D1 se déclenchera au moment précis où le garde compte : quand le rebuild
     aura fait passer P1 pour `dinov2-vitl14` ;
  2. **N4** (le cache de `_get_bank` rouvre D3/D10/D11 dans un même processus) et
     **N5** (`cascade` écrit malgré le flip Direction A) — latents, mais tous deux
     referment une porte que cette session a voulu fermer ;
  3. **D2**, **D16** — trous structurels : une version déclarée qu'on ne vérifie
     pas, une p-valeur qu'on ne peut pas rattraper ;
  4. **D8**, **N2**, **D5** (commentaire SQL), **D6** (test du garde), **N6** —
     peu coûteux, une ligne à quelques lignes chacun ;
  5. **N3** — pas un correctif, une enquête : la suite rougit 1 fois sur 6 sans
     cause retrouvée, et c'est R6 qui s'entame.
