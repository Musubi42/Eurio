# ADR-008 — Deux voies vers le modèle embarqué : backbone gelé + banque de vecteurs, à côté d'ArcFace

**Date :** 2026-08-19
**Statut :** 🟡 Proposée — la voie B est ouverte comme chantier de **mesure**.
Le départage entre les deux voies n'est pas rendu : il attend le corpus de scan.

## Contexte

Ajouter une classe reconnue par l'APK coûte aujourd'hui un **réentraînement** :
cohorte → bake → entraînement GPU → promotion. C'est la voie A, et c'est la
seule qui aille bout en bout jusqu'à un APK qui reconnaît quelque chose
(parcourue pour la première fois le 2026-08-16).

Trois faits mesurés rendent cette voie insuffisante à elle seule.

**1. Ce que l'APK embarque n'a rien à voir avec ce que la doc décrit.**
`shared/model-assets.json` (épinglé 2026-08-15) + `model_meta.json` :
`{"mode":"arcface","backbone":"mobilenet_v3_small","num_classes":17,
"embedding_dim":256}`, **4,43 Mo**. Dix-sept classes. Le `arcface-vits14-v1`
décrit dans [`../model-efficiency/VISION.md`](../model-efficiency/VISION.md)
(546 classes, 41,8 Mo fp16) existe comme checkpoint sur MinIO et **n'a jamais
atteint l'APK**. Pendant ce temps, la review a produit **1958 crops décidés sur
194 classes** (`review_queue.status='done' AND decided_eurio_id IS NOT NULL`,
joints aux assets à `storage_path` non nul, réplique du 2026-08-19).

**2. Le fine-tuning n'a jamais gagné une mesure dans ce repo.** Journal de
VISION.md, 2026-06-12 :

| Set | Frozen zero-shot | Fine-tuné `arcface-vits14-v1` |
|---|---|---|
| Gold BE, 94 listings, ancres canonical-only (**H4**) | vitl14 : **62,8 %** top-1 / 80,9 % hit@5 | **28,7 %** / 35,1 % |
| Held-out wild, 77 crops, classes riches en wild (**H1**) | vitl14 : **72,7 %** | **71,4 %** |

Au mieux il égalise, au pire il perd 34 points. Ce qu'il achète est la
**taille** (21 M params au lieu de 300 M) — une distillation implicite, pas un
gain de qualité. Et la phrase qui fonde tout : *« ce sont les refs wild par
classe qui font le modèle »* (H1). Pas le volume d'entraînement. **Les
références.**

**3. L'architecture de la voie B existe déjà et tourne en production interne.**
`build_anchors_2eur_all` (`ml/training/foundation/anchors.py:571`) fait
exactement ce qui est décrit ci-dessous — backbone gelé `dinov2-vitl14`, N
références par classe choisies par *farthest-point sampling*, overrides humains
— et sert la review depuis des semaines. Vérifié le 2026-08-19 : la banque
`2eur_all` porte **1250 références** (664 `canonical` + 586 `fps`), dim 1024
(`SELECT method, COUNT(*) FROM dino_class_references GROUP BY 1` sur
`ml/state/eurio.replica.db`). Ce qui manque n'est pas le concept, c'est le pont
vers l'APK.

## Décision

**Ouvrir la voie B — backbone gelé + banque de vecteurs — en parallèle de la
voie A, comme chantier de mesure, sans rien retirer de la chaîne existante.**

La voie B est trois objets séparés :

1. un **backbone gelé** (DINOv2, DINOv3, ConvNeXt…), fonction image → vecteur,
   jamais entraîné sur nos pièces ;
2. une **banque** de couples `(classe, vecteur)`. Reconnaître = encoder le crop
   caméra et comparer par cosinus. **Ajouter une classe = ajouter des lignes** ;
3. une **tête de projection** optionnelle (`Linear(1024→256)`, ~0,26 M params),
   entraînée sur des vecteurs **déjà calculés** — minutes CPU, pas 7 h de GPU.
   Elle ne contient pas la liste des classes : même avec elle, ajouter une
   classe reste gratuit.

Quatre décisions dérivées, détaillées dans
[`../work-in-progress/scan-sans-retrain/DECISION.md`](../work-in-progress/scan-sans-retrain/DECISION.md) :

- **D1** — la voie A continue, rien n'est déprécié. Une voie qui marche mal bat
  une voie qui n'existe pas encore.
- **D2** — la voie B produit d'abord des chiffres, ensuite un artefact.
- **D3** — les deux voies partagent la review (`training_eligible=1`) et rien
  d'autre. C'est **déjà** le cas dans le code : `_candidate_crops_for_class`
  (`anchors.py:544`) filtre sur la même condition que
  `iteration_augmentations.py:252`. Personne ne l'avait remarqué.
- **D4** — **le juge unique est le corpus de scan**, et il est vide
  (`ml/state/scan_corpus.db` : 0 octet).

### Ce que chaque voie coûte

| | Voie A — fine-tune ArcFace | Voie B — backbone gelé + banque |
|---|---|---|
| Ce qui apprend | le backbone entier, 21,7 M params | rien (ou une matrice de 0,26 M) |
| Entrée de l'entraînement | des **images** (décodage, augmentation) | des **vecteurs déjà calculés** |
| Matériel | GPU — la 1080 Ti, Xid 79 compris | CPU du Mac |
| Durée d'un cycle | ~7 h mesurées (log run v2, 35 min/epoch) | ~6 min d'encodage (312 s au dernier build) |
| Ajouter une classe | réentraînement complet | **N lignes dans la banque** |
| Taille APK | 4,43 Mo aujourd'hui | 21,6 Mo int8 (ViT-S/16) + ~3,2 Mo de banque |
| Promotion | destructive — elle **remplace**, elle n'accumule pas | additive |

### Ce qui les départagera

**Le corpus de scan, et rien d'autre.** La distinction est le piège central du
chantier :

| | Tâche **review** | Tâche **scan** |
|---|---|---|
| Entrée | photo **cadrée par un vendeur qui veut montrer la pièce** : statique, pièce entière, choisie parmi plusieurs (souvent floue, de loin, avec du reflet — la netteté n'est PAS le critère) | frame caméra **choisie par personne** : prise au vol dans le flux, en main, de biais, reflets |
| Vérité terrain | **1958 crops** figés le 2026-08-19 (`gold_version=0ecbb1d70e3c`) | 317 snaps `eval_real_norm`, ~17 classes |
| Sert à décider | l'auto-acceptation en review | **ce qui part dans l'APK** |

Les 1958 crops labellisés mesurent la review. Ils ne disent **rien** de garanti
sur le scan. Le plan de capture est livré (80 classes, 400 cellules, 985
captures, 11 sessions — `plan-capture-scan.csv`) ; les photos ne le sont pas.

## Alternatives considérées

| Option | Verdict |
|---|---|
| Arrêter ArcFace, DINO gelé suffit | ❌ Les chiffres de H1/H4 sont mesurés sur 77 et 94 listings, et sur la tâche **review**, pas **scan**. On ne remplace pas une chaîne livrée sur cette base |
| Rester sur ArcFace seul | ❌ Chaque classe ajoutée coûte 7 h de GPU sur une machine tombée du bus PCIe (Xid 79) pendant l'epoch 12. 17 classes dans l'APK, 546+ visées, 194 classes déjà validées en review qui n'y arrivent pas |
| Brancher tout de suite une banque vitl14 dans l'APK | ❌ **217,9 ms/img en CPU batch 1** mesurés sur Mac (304 M params). La question de sa viabilité on-device n'est pas ouverte, elle est fermée par la négative |
| Décider l'encodeur sur les benchmarks publics | ❌ DINOv3 annonce +10,8 pts sur Met et ViT-S/16 mAP 0,406 vs 0,327 (arXiv 2508.10104). Met ressemble à notre problème (peu de références, discrimination par détail fin) — **raison de tester, pas preuve**. Distinguer deux faces nationales de 2 € est du quasi-duplicata fin ; seuls nos crops tranchent |
| **Deux voies, un seul juge** | ✅ Le coût marginal est une banque déjà bâtie et un banc à câbler. Le risque est borné : si la voie B plafonne sur le corpus de scan, on l'écrit et on la ferme |

## Conséquences

### Sur la licence — DINOv3 n'est plus Apache 2.0

Si l'encodeur retenu est un DINOv3 (ce que les latences du 2026-08-19 rendent
probable pour le ViT-S/16), **l'APK hérite de trois obligations** issues du
§1.b.i de la licence DINOv3 :

- ne redistribuer que sous les termes de ce même accord ;
- **joindre une copie de l'accord** — un écran « Licences open source » ;
- **afficher « Built with DINOv3 »** de façon proéminente (page À propos suffit
  d'après le texte).

⚠️ **Les deux copies publiées de la licence diffèrent** : la clause de branding
figure sur `ai.meta.com` (version faisant autorité, vers laquelle pointent
toutes les cartes Hugging Face) et **pas** dans le `LICENSE.md` de GitHub
(`grep -c 'Built with'` → 0). Conduite retenue : se conformer à la plus stricte.
Le §8 laisse Meta modifier l'accord avec effet immédiat.

Un **dérivé** est couvert par les mêmes obligations : le §1.b.i vise « DINO
Materials, **and any derivative works thereof** », et la définition inclut
nommément « trained model weights ». **La quantification TFLite/int8 ne lave pas
la licence.** ⚠️ estimation : la banque de vecteurs relève des « outputs and
results » (§3) et nous appartient probablement librement — seul le backbone
porte la licence.

Ce qu'on perd exactement en quittant Apache 2.0 : la liberté de sous-licencier,
la stabilité du contrat, la clause brevets d'Apache §3, et l'obligation de
branding. Ce qu'on ne perd pas : le commercial, la modification, la
redistribution, la propriété de ses dérivés. **Le coût est administratif, pas
stratégique** — mais il doit être payé avant le Play Store, et il mérite un avis
juridique (je ne suis pas juriste).

Atténuation peu coûteuse du risque §8, ⚠️ estimation : archiver dans le repo la
version datée de la licence sous laquelle les poids ont été téléchargés, avec la
date et le hash des fichiers.

### Sur l'architecture

- **La review devient le seul coût humain, et il est déjà partagé.** Un crop
  validé part en dataset pour A **et** devient candidat-ancre pour B, sans
  double geste. Ce que la voie B change, c'est que ce travail devient
  **immédiatement** rentable au lieu de rentable-au-prochain-réentraînement.
- **Le format de banque de l'APK doit changer.** Il lit aujourd'hui
  `coin_embeddings.json` : 23 entrées, un centroïde de 256 dim par classe.
  Passer à N références par classe est un changement de format (binaire fp16
  plutôt que JSON) et `EmbeddingMatcher.kt` doit agréger **par max des cosinus,
  pas par moyenne** — c'est tout l'intérêt de la diversité sélectionnée par FPS.
- **La banque doit être scopée par encodeur, sinon le banc écrase la
  production.** Fait le 2026-08-19 (`anchor_path(kind, encoder_version)`), **y
  compris pour le bras baseline depuis la passe du soir** : la déduction
  « encodeur de production ⇒ on réécrit la banque servie » est supprimée
  (`save_anchors(…, write_legacy=False)` par défaut, `--no-serve` côté CLI), et
  les deux fichiers sont séparés **par le rôle** — banque servie ↔ artefact de
  banc — avec écriture atomique. `dinov2-vitl14` reste à la fois l'encodeur servi
  et un bras du banc, mais l'encodeur ne décide plus de l'intention (D10/D11 de
  `FINDINGS.md` §8.3). ⚠️ Reste ouvert : le cache mémoire de `_get_bank` met les
  deux rôles sur la même clé — dans un même processus, un appel scopé peut faire
  servir à la review la banque du dernier run de banc (N4, §8.5).
  ⚠️ **Le « fait le 2026-08-19 » ne valait que pour le `.npz`** — mesuré depuis.
  La **table** `dino_class_references` n'était, elle, pas scopée : sa clé
  primaire ignorait `encoder_version`, donc bâtir la banque d'un candidat
  écrasait les références de la production en base (défaut **M1**, reproduit :
  `prod=200 cand=0` → `prod=0 cand=200`). **Fermé le 2026-08-20** — l'encodeur
  est entré dans la clé primaire, migration **0010**, et le writer refuse une
  table à l'ancienne clé ; il reste à appliquer 0010 au canonique (redémarrage
  `eurio-api`). ⚠️ **Et le scoping n'est acquis que côté écriture** : aucun
  **lecteur** de cette table ne nomme `encoder_version` (défaut **Q6**,
  `FINDINGS.md` §8.10) — la route admin rend deux canoniques pour une classe et
  le plan de capture P5 déplace 9 classes de strate dès qu'une seconde banque
  existe. **Tant que Q6 est ouvert, le premier build de banque d'un candidat
  reste interdit** : c'est une précondition de la voie B, pas un détail.
- **Les résultats du banc vont au canonique, le calcul reste local.** Ligne de
  partage : ce qui coûte cher à recalculer et ne concerne qu'une machine reste
  local (`.npz`, embeddings) ; ce qui fonde une décision partagée va au
  canonique (`encoder_bench_runs`, migration 0009). Le volume ne s'y oppose pas :
  < 1 Mo par balayage contre 173 Mo de canonique. ⚠️ **Un run en base n'est pas
  encore une décision fiable** (constat du 2026-08-20) : la colonne
  `provisional` est bien gardée à l'écriture — l'invariant est dans
  `record_run`, la seule porte SQL — mais le **prédicat** qu'elle évalue croit
  quatre champs déclarés par l'appelant, et quatre payloads mensongers
  ressortent `provisional=0` (`FINDINGS.md` §8.10, Q1..Q4). À fermer avant que
  la page admin du banc ne fonde un choix d'encodeur.
- **La taille de l'APK monte d'environ +20 Mo net** (21,6 Mo int8 + ~3,2 Mo de
  banque, contre 4,43 Mo d'embedder actuel). C'est un coût, pas un obstacle.

### Ce que la décision ÉCARTE

- **Écarté : arrêter la voie A.** Elle reste la procédure en vigueur
  (`eurio-cohort`, `eurio-run-local`, `eurio-promote`), et `prod/current`
  continue d'être alimenté par elle. Elle garde en outre un rôle **irremplaçable
  même si la voie B gagne** : c'est elle qui produit les cohortes-test dont les
  captures alimentent le corpus de scan.
- **Écarté : deux files de review, deux notions de « validé ».** On paierait
  deux fois le seul coût humain irréductible du projet.
- **Écarté : décider avant le corpus.** Ni le val d'entraînement, ni les crops
  eBay ne tranchent la question du scan. Un bench review peut être lancé plus
  tôt — il décide **quel encodeur sert la review**, pas ce qui part dans l'APK.
- **Écarté : la tête de projection maintenant.** Elle ne se déclenche que si la
  courbe « nombre de références par classe » montre un plafond que les
  références seules ne franchissent pas. C'est l'étape 4c, conditionnelle.
- **Écarté : ConvNeXt-Tiny comme candidat APK par défaut.** L'ordre proposé
  initialement (« ConvNeXt d'abord, les ops ViT passent mal NNAPI ») est inversé
  par la mesure : 292,8 ms en CPU batch 1 contre 24,5 ms pour le ViT-S/16, sur
  Mac, reproduit. ⚠️ Mesure PyTorch/Mac, pas TFLite/Android — ConvNeXt garde donc
  le droit d'être rebenché en TFLite avant d'être écarté pour de bon. Il reste
  le meilleur candidat pour bâtir la banque côté Mac (le plus rapide en MPS).

### Ce qui rendrait cette ADR caduque

Si le corpus de scan montre que **tous** les encodeurs gelés plafonnent bas
pendant que la voie A monte, la voie B se ferme. C'est un résultat que le
chantier doit pouvoir produire — et il faudra alors une ADR-00X qui supersède
celle-ci, pas une réécriture.

## Complément daté — 2026-08-20 : DINOv3 n'est plus l'encodeur probable

> Cette section **complète** l'ADR, elle ne la réécrit pas. La décision de fond
> (deux voies, un seul juge) est **inchangée** ; ce sont deux paris chiffrés
> énoncés en cours de route qui tombent.

**Ce qui a été mesuré.** Premier run réel du banc, `20260820T011143Z`, gold figé
`0ecbb1d70e3c`, **1958 crops, 0 crop non encodé**, banque `2eur_all` à 1533
ancres — celle **d'avant le plancher**, cf. l'addendum plus bas — chaque modèle
avec sa transform recommandée. Rapport :
[`../work-in-progress/scan-sans-retrain/BENCH-ENCODEURS.md`](../work-in-progress/scan-sans-retrain/BENCH-ENCODEURS.md).

| Modèle | M params | dim | global@1 | global@5 | pays@1 | ms/img |
|---|---:|---:|---:|---:|---:|---:|
| `dinov2_vitl14` *(sert la review)* | 304,4 | 1024 | **91,6 %** | 97,9 % | **97,4 %** | 122 |
| `dinov2_vits14` | 22,1 | 384 | **85,9 %** | 97,2 % | 96,0 % | **16** |
| `timm:convnext_tiny.dinov3_lvd1689m` | 27,8 | 768 | 81,5 % | 91,8 % | 90,4 % | 16 |
| `timm:vit_small_patch16_dinov3.lvd1689m` | 21,6 | 384 | **78,7 %** | 91,7 % | 89,9 % | 22 |

McNemar apparié contre `dinov2_vitl14` : vits14 `b=163 c=50 p=3,6e-15` ; dinov3
vits16 `b=286 c=32 p=3,8e-52` ; dinov3 convnext-t `b=237 c=39 p=9,0e-36`.

### Les deux passages de l'ADR que cela corrige

1. **§Conséquences → licence.** La phrase *« Si l'encodeur retenu est un DINOv3
   (ce que les latences du 2026-08-19 rendent probable pour le ViT-S/16) »* n'est
   plus la lecture juste : à taille égale, DINOv3 ViT-S/16 fait **7,2 points de
   moins** que DINOv2 ViT-S/14. Le candidat léger devient **`dinov2_vits14`**
   (Apache 2.0), et les trois obligations DINOv3 **ne s'appliquent alors pas**.
   ⚠️ **Ne pas supprimer l'analyse de licence** : elle reste exacte et
   redeviendra opposable le jour où un DINOv3 sera rebenché avec sa propre
   banque (hypothèse **H13**).
2. **§Ce que la décision ÉCARTE → « ConvNeXt-Tiny comme candidat APK par
   défaut ».** L'écart tient toujours, mais la raison change de nature : ce
   n'est plus seulement une latence (292,8 ms CPU bs1), c'est **aussi** une
   qualité — 81,5 % contre 85,9 %. Et le remplaçant proposé alors, le DINOv3
   ViT-S/16, est écarté à son tour. **Les deux DINOv3 sortent.**

### Ce que cela CONFIRME, et qui compte plus que le classement

La ligne *« Décider l'encodeur sur les benchmarks publics → ❌ raison de tester,
pas preuve »* du tableau des alternatives **a payé**. L'argument public n'était
pas faible : +24 % relatif de mAP en recherche d'instance, +10,8 pts sur Met
(arXiv 2508.10104), sur une famille de tâches structurellement proche de la
nôtre — peu de références par classe, discrimination par détail fin. Il pointait
**dans le mauvais sens**, et seule une mesure sur nos crops l'a montré. Le coût
du doute a été un run de banc ; le coût de la croyance aurait été un export
TFLite, un rebuild de banque et un APK.

**Règle à retenir** : un benchmark public ne transfère pas *parce que* sa tâche
ressemble à la nôtre — c'est précisément quand elle lui ressemble qu'on cesse de
se méfier. Écrire le doute comme une hypothèse falsifiable et semer sa mesure
**avant** de commencer est ce qui a sauvé la décision (H12 / H13 de
[`../model-efficiency/VISION.md`](../model-efficiency/VISION.md)).

### Ce qui n'est PAS tranché, et reste exactement comme l'ADR le dit

- **D4 tient : le juge est le corpus de scan, et il n'a toujours 0 capture
  versionnée** — pour **2 264 images device non protégées**, ni sur MinIO ni
  dans la chaîne de sauvegarde
  ([`DURABILITE-CORPUS.md`](../work-in-progress/scan-quality/DURABILITE-CORPUS.md)).
  Ce bench mesure la tâche **review**. Il décide quel encodeur sert la review, il
  ne décide **pas** ce qui part dans l'APK — c'est écrit tel quel au
  §« Écarté : décider avant le corpus », et rien ici ne le change.
- **Le biais de banque n'est pas quantifié.** Le banc ré-encode les images
  d'ancre avec chaque modèle, mais leur **sélection** (farthest-point sampling)
  a été faite dans l'espace de `dinov2-vitl14`. Il joue contre les candidats.
- **Q6 reste ouvert**, donc le rebuild d'une banque candidate — le seul geste qui
  lèverait ce biais — **reste interdit**.

### Mise à jour d'un chiffre du §Contexte

Le §Contexte point 3 cite « la banque `2eur_all` porte **1250 références**
(664 `canonical` + 586 `fps`) ». Deux rebuilds ont eu lieu depuis :

| build | quand | ancres | classes | classes à exemplaires |
|---|---|---:|---:|---:|
| `23c637d93b43` | 2026-08-19 16:36 | 1533 | 671 | 182 |
| **`365dcab2a253`** (servi) | **2026-08-20 14:27** | **1495** | **671** | **124** |

`SELECT COUNT(*), COUNT(DISTINCT class_id), COUNT(DISTINCT CASE WHEN
method='fps' THEN class_id END) FROM dino_class_references WHERE
anchors_kind='2eur_all'` sur `ml/state/eurio.replica.db` → `1495 | 671 | 124`
(2026-08-20 17:13 UTC). Le second build applique le plancher `min_exemplars=2`
et a ramené **68 classes au canonique seul** (`dino_anchor_builds.note`). Les
12 454 prédictions ont été recalculées contre lui, **0 périmée**.

### 🔴 Addendum 2026-08-20 (soir) — le plancher a dégradé, il est RETIRÉ, et ce que ça change à l'ADR

Le re-bench held-out à N=10, après application du plancher :
`dinov2_vits14` **75,5 % → 74,1 %**, `dinov2_vitl14` **85,7 % → 84,8 %**.
Contrôle : à N=0 les deux banques sont identiques et rendent le même score à
0,1 pt près (53,1 → 53,2 ; 76,1 → 76,2).

**Ce que ça ne change pas** : les deux voies de cette ADR, l'ordre des étapes,
et le juge unique (D4 — le corpus de scan). Le plancher est une règle
d'alimentation de la banque, pas un choix d'architecture ; qu'il coûte 1 pt ne
remet en cause ni le backbone gelé ni la banque de vecteurs.

**Ce que ça change** : la promesse « ajouter une classe coûte des lignes de
données » se paie plus cher qu'annoncé quand ces lignes sont **rares**. La leçon
de méthode est consignée au journal des croyances de
[`../model-efficiency/VISION.md`](../model-efficiency/VISION.md) : **on a
extrapolé d'un agrégat de courbe à une règle par classe.**

**Suite du même soir : le plancher est RETIRÉ.** La mesure par classe a été faite
sans rebuild, en restreignant la courbe (`--bank-classes` / `--gold-classes` /
`--rank-order`, McNemar exact par palier). Trois résultats : (1) la population
visée est inévaluable — 16 crops held-out pour ~70 classes ; (2) donner à 57
classes riches exactement **un** exemplaire **améliore** leurs propres crops
(`vitl14` 67,6 → 69,1 %, p=0,048 ; `vits14` 41,6 → 45,5 %, p=4,5e-10) ; (3) le
creux à N=1 vient de l'**ordre** du FPS, pas du nombre — à nombre d'ancres
identique, garder le rang le moins diversifiant rend **77,8 %** au lieu de
73,8 %. Défaut revenu à `min_exemplars = 1` (inactif), mécanisme conservé et
testé. **Une classe à un seul crop validé sera donc servie** au prochain
rebuild — et c'est bien ce que la mesure recommande.

⚠️ **Deux réserves de portée ADR.** La mesure décisive est un **proxy** (classes
riches plafonnées à 1), pas les classes pauvres visées. Et le levier réel —
amorcer le FPS au médoïde — n'est **pas** implémenté : la voie B est donc livrée
dans la configuration dont le tort est le mieux étayé, sans son correctif de
mécanisme. Tout ceci est mesuré sur la tâche **review**, jamais sur le scan.

## Références

- [`../work-in-progress/scan-sans-retrain/DECISION.md`](../work-in-progress/scan-sans-retrain/DECISION.md) — la décision-cadre et ses 4 étapes
- [`../work-in-progress/scan-sans-retrain/PREREQUIS.md`](../work-in-progress/scan-sans-retrain/PREREQUIS.md) — les 7 prérequis P1..P7 et leur état
- [`../work-in-progress/scan-sans-retrain/FINDINGS.md`](../work-in-progress/scan-sans-retrain/FINDINGS.md) — les mesures du 2026-08-19, et le **registre de dette daté** (§8 : D1..D16 corrigés / partiels / ouverts, plus les défauts neufs N1..N6)
- [`../work-in-progress/banque-dino/CONSTAT.md`](../work-in-progress/banque-dino/CONSTAT.md) et [`PROTOCOLE-BENCH.md`](../work-in-progress/banque-dino/PROTOCOLE-BENCH.md)
- [`../model-efficiency/VISION.md`](../model-efficiency/VISION.md) — registre des hypothèses (H1, H4) et journal des révisions
