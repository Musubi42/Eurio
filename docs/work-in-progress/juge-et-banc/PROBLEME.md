# Le juge et l'entraînement partagent des photos — et personne ne l'avait vu

> **Problème posé le 2026-08-25, rien d'implémenté.** Ce document établit le
> défaut, mesure ce qu'il touche, et pose la cible. Il ne décide pas de la
> mise en œuvre. Toutes les mesures sont sur `ml/state/eurio.replica.db`
> (répliquée le 2026-08-24 23:29) et portent leur requête.
>
> 🔴 **Le fait en une ligne** : le corpus device sert de **split de validation**
> à l'entraînement *et* de **juge** au benchmark. Le modèle choisit son meilleur
> checkpoint en regardant les photos sur lesquelles il sera noté.
>
> 🔴🔴 **AGGRAVÉ le 2026-08-25, vérifié au code — c'est pire que ce que ce
> document décrivait.** Ce n'est pas seulement la sélection de checkpoint : **les
> centroïdes contre lesquels les photos device sont notées sont fabriqués à
> partir de ces mêmes photos.** `compute_embeddings.py:88` lit
> `centroid_source` avec le défaut `"auto"`, et `"auto"` déclenche
> `_split_means("val")` (`:107-109`) ; or `ml/training/pipeline.py:336-352`
> construit sa commande **sans jamais passer `--centroid-source`**. Comme `val/`
> a été remplacé par `eval_real_norm/`, le prototype d'une classe **est la
> moyenne de ses photos de test**. À 6 photos par classe, chaque photo pèse ~1/6
> du prototype qui la juge. Ce n'est plus un biais de sélection, c'est une
> **fuite d'étiquette directe**, et elle rend le `r@1 = 92,4 %` non
> interprétable — pas « optimiste de x points », **non interprétable**.
> Le §1bis détaille la vérification.

## 1. La chaîne du défaut

Trois maillons, tous corrects pris isolément, faux mis bout à bout.

**a. Le corpus device devient le split de validation.**
`ml/training/prepare_dataset.py:242` appelle `_override_val_with_eval_real()`,
qui remplace `val/` par les snaps de `ml/datasets/eval_real_norm/<class_id>/`.
L'intention est écrite dans le docstring et elle est bonne :

> *« Device snaps run through `normalize_device` so their distribution aligns
> with on-device inference — the only val set whose metric correlates with
> deployed behavior. »*

**b. Le même corpus sert de juge.** `benchmark_runs` note le checkpoint sur
`ml/datasets/eval_real_norm/` — c'est le chemin qu'on lit dans
`top_confusions_json` de chaque run.

**c. Donc la sélection de modèle se fait sur le jeu de test.** Le meilleur
checkpoint est retenu d'après une métrique calculée sur les photos qui
serviront ensuite à annoncer sa performance.

### Ce que ça coûte

| Conséquence | Portée |
|---|---|
| **Le `r@1 = 92,4 %` du run du 2026-08-16 est optimiste** | de combien, **personne ne le sait** — ce n'est pas mesuré, et ça ne peut pas l'être sans un jeu tenu à l'écart |
| **La comparaison ArcFace ↔ DINO est biaisée en faveur d'ArcFace** | ArcFace choisit son checkpoint en regardant le juge ; DINO n'entraîne rien, il n'a aucun équivalent de cet avantage |

⚠️ **C'est la deuxième conséquence qui motive ce chantier.** Le biais absolu
serait supportable un temps ; un biais qui fausse un **départage entre deux
voies** ne l'est pas, parce que c'est exactement la décision qu'on s'apprête à
prendre ([ADR-008](../../adr/008-deux-voies-backbone-gele-et-arcface.md), D4 :
« le juge unique est le corpus de scan »).

### La requête qui le montre

```bash
grep -n "_override_val_with_eval_real" ml/training/prepare_dataset.py
# 242:        _override_val_with_eval_real(
# 313:def _override_val_with_eval_real(
```

```bash
sqlite3 -readonly ml/state/eurio.replica.db \
  "SELECT id, num_photos, num_coins, r_at_1 FROM benchmark_runs
    WHERE status='completed' ORDER BY started_at DESC LIMIT 1;"
```

## 1bis. La fuite de centroïdes, et le garde qui protège un dossier inexistant

Trouvé pendant le lot 1, **vérifié au code le 2026-08-25**. Deux constats liés.

### La fuite

```bash
sed -n '88p;107,109p' ml/training/compute_embeddings.py
#   source = getattr(args, "centroid_source", "auto")
#   if source in ("auto", "val_mean"):
#       _split_means("val")
sed -n '336,352p' ml/training/pipeline.py | grep -c "centroid-source"   # → 0
```

La chaîne complète : `pipeline` n'exprime jamais son intention → défaut `auto`
→ moyenne du split `val` → `val` = `eval_real_norm/` = **le juge**. Le
prototype de chaque classe est la moyenne des photos qui la testent.

### Le garde qui ne garde rien

`evaluate_real_photos.py:13` promet un « strict hold-out » assuré par
`_assert_no_real_photos`. Ce garde ne connaît qu'un seul chemin :

```bash
grep -n "REAL_PHOTOS_DIR = " ml/training/train_embedder.py
#   REAL_PHOTOS_DIR = (ML_DIR / "data" / "real_photos").resolve()
test -d ml/data/real_photos && echo existe || echo "N'EXISTE PAS"   # → N'EXISTE PAS
```

**Il protège un répertoire legacy qui n'existe plus**, tandis que le juge réel
(`ml/datasets/eval_real_norm/`, 114 fichiers) ne figure nulle part dans sa
définition. Et les deux tests qui l'exercent (`tests/test_benchmark.py:125` et
`:129`) fabriquent leurs chemins **sous `real_photos/`** : ils passent, et ils
ne prouvent rien.

C'est le motif exact du catalogue `eurio-verify` — un garde posé sur le chemin
qu'on avait en tête, jamais sur celui qui est réellement emprunté (cf. skill
`eurio-banque` §5b, « le garde qui ne garde pas », sept instances en deux jours).

## 2. Le second défaut, celui qui n'existe pas encore

La piste « fabriquer un juge à partir des crops eBay d'enrichissement, pour ne
plus dépendre de séances photo » est bonne et elle est retenue (§4). Mais
telle qu'elle se formule spontanément — *« prendre les N crops les plus
éloignés de la canonique en espace DINO, donc les plus dégradés »* — elle
crée **deux fuites**, et il faut les nommer avant d'écrire une ligne.

**Fuite de banque.** « Le plus loin de la canonique » est **le critère du
farthest-point sampling**, c'est-à-dire très exactement la règle qui a choisi
les ancres. Sélectionner comme ça, c'est sélectionner les ancres. Précédent
mesuré : sur le gold de review, **779 crops sur 1958 sont des lignes de la
banque** — les noter contre elle mesure une similarité de 1,0 avec eux-mêmes
(cf. skill `eurio-banque` §3).

**Fuite d'entraînement.** Ces crops portent `training_eligible = 1` : ils sont
**dans le jeu d'entraînement d'ArcFace**. Même problème, autre voie.

**Circularité du critère.** Choisir le juge avec DINO puis s'en servir pour
juger DINO n'est pas neutre : on lui construit un examen fait de ses propres
cas durs, et on impose ce choix à ArcFace qui n'a pas voix au chapitre. Le
critère de sélection doit être indépendant des deux modèles jugés, ou
appliqué symétriquement.

⚠️ **Et une limite de fond qui ne se corrige pas** : une photo eBay dégradée
reste une photo **choisie**. Floue, de biais, avec du reflet — mais un vendeur
l'a sélectionnée parmi plusieurs pour montrer sa pièce. Une frame de scan n'est
choisie par personne. Le juge eBay sera donc un **proxy**, jamais un substitut
au corpus device. Les deux se gardent séparés et nommés séparément ; les
fusionner rendrait tout écart inexplicable.

## 3. La cible — trois rôles disjoints

Chaque image porte **un** rôle, et un seul :

| Rôle | Sert à | Peut-elle influencer les poids ? |
|---|---|---|
| **train** | apprendre | oui, c'est son travail |
| **val** | choisir le checkpoint, régler les seuils | indirectement — donc jamais juge |
| **judge** | annoncer la performance | **non, jamais, sous aucune forme** |

État actuel contre cible :

| Population | Aujourd'hui | Cible |
|---|---|---|
| crops eBay (`training_eligible=1`) | **train** | **train**, moins un prélèvement |
| photos device (`eval_real_norm`) | **val + judge** ⛔ | **judge** seul |
| prélèvement eBay (nouveau) | n'existe pas | **val**, puis un second prélèvement en **judge-proxy** |

### Le point d'appui qui rend ça faisable

Les deux voies filtrent déjà sur **la même condition** : `training_eligible = 1`
— `real_training_sources` (`ml/training/iteration_augmentations.py:252`) pour
ArcFace, `_candidate_crops_for_class` (`ml/training/foundation/anchors.py:544`)
pour les ancres DINO. C'est le D3 de l'ADR-008, et il a été remarqué après coup.

**Conséquence directe : un seul marqueur, posé au bon endroit, exclut des deux
pipelines à la fois.** C'est ce qui fait de ce chantier une affaire de quelques
lots et non d'une refonte.

## 3bis. 🟡 DÉCIDÉ ET DIFFÉRÉ — le juge-proxy eBay se fera, plus tard

> Décision du PO, **2026-08-25**. Ce n'est pas une question ouverte : c'est un
> engagement daté, sorti du périmètre d'une session pour ne pas la faire
> échouer. À reprendre dès que les lots de la séparation tournent.

**Le raisonnement du PO, dans ses termes** : ne pas avoir de jeu de validation
est un vrai problème pour l'entraînement. Le juge-proxy eBay le résoudra. Mais
d'abord on valide que la séparation **fonctionne** ; ensuite seulement on
construit la stratégie complète.

Donc, dans l'ordre :

| Quand | Ce qu'on fait | Statut |
|---|---|---|
| **Cette session** | `val/` vide, **on garde le dernier epoch**. Pas de sélection de checkpoint. Le but est de prouver le mécanisme, pas d'obtenir une performance | ✅ retenu |
| **Une fois tous les lots joués et vérifiés** | Prélever des crops eBay pour constituer le **jeu d'évaluation**, et **ces images n'entrent PAS dans le jeu d'entraînement** | 🟡 engagé, non planifié |

⚠️ **La contrainte à ne jamais relâcher**, et c'est tout l'objet de ce
document : une image prélevée pour le juge **sort** de l'entraînement. Pas
« sort de préférence », pas « sort si on y pense » — sort, et le code doit
rendre l'inverse impossible. Les deux requêtes qui devront porter le prédicat
sont `ml/training/iteration_augmentations.py:246-257` (ArcFace) et
`ml/training/foundation/anchors.py:833-846` (ancres DINO) : elles divergent
(intersection 2888, ArcFace seul 79, DINO seul 1), **il n'existe pas de point
unique en amont**, donc le marqueur s'écrit dans les deux.

⚠️ Et le piège de dimensionnement, mesuré : `real_training_sources` est partagé
par le bake **et** le préflight (`preflight.py:179`). Retirer des crops du pool
fait mécaniquement baisser le seed que le préflight contrôle. Le plancher se
raisonne donc sur **ce qui reste après prélèvement**, jamais sur ce qu'on prend
(cf. §4).

Les questions qui restent à trancher pour l'exécuter sont **Q2** (critère de
sélection non circulaire — rappel : **46,8 % du pool éligible est déjà une
ancre DINO**, donc le tirage aléatoire n'est pas neutre) et **Q3** (prélèvement
figé ou rejouable).

## 4. La règle de prélèvement — le plancher des 15

Proposition du PO, **2026-08-25** : *« il me faut un minimum de 15 photos
d'enrichissement pour une classe avant d'avoir le droit d'en prélever pour le
juge »*, puis en prélever ~5.

⚠️ **15 et 5 sont arbitraires et assumés comme tels.** Ils ne sortent d'aucune
mesure. Ce qui suit dit seulement ce qu'ils **coûtent**, pas s'ils sont bons.

```sql
-- classes par nombre de crops eBay validés (maille COALESCE(design_group_id, eurio_id))
with pc as (
  select coalesce(c.design_group_id, c.eurio_id) cid,
         sum(case when ia.training_eligible=1 and s.source='ebay' then 1 else 0 end) n
    from coins c
    left join image_assets ia on ia.eurio_id = c.eurio_id
    left join source_images s on s.id = ia.source_image_id
   group by 1)
select count(*) from pc where n >= 15;
```

Mesuré le **2026-08-25** :

| | |
|---|---|
| classes à ≥ 15 crops eBay validés | **60** |
| dont dans la cohorte `rich10-68c` | **60** (toutes) |
| classes de la cohorte entre 10 et 14 — **sous le plancher** | **8** |
| crops prélevables à 5/classe | **300** |

Lecture : le plancher de 15 laisse **8 classes de la cohorte sans juge-proxy**.
Ce n'est pas un blocage — elles gardent le juge device si elles y figurent —
mais c'est le prix du chiffre, et il faut le dire plutôt que le découvrir.

⚠️ **Le plancher doit se raisonner sur ce qui RESTE, pas sur ce qu'on prend.**
Une classe à 15 crops qui en cède 5 tombe à 10 pour l'entraînement — c'est
exactement le seuil `MIN_REAL` du préflight (`ml/store/funnel_constants.py`).
À 5 près, le prélèvement **rendrait une classe non entraînable**. C'est la
première contrainte à encoder, et elle explique peut-être le choix de 15 mieux
que l'intuition qui l'a produit.

## 5. Ce qui reste ouvert

Aucune de ces questions n'est tranchée. Elles sont listées pour être décidées,
pas pour être devinées.

| # | Question | Ce qui pèse |
|---|---|---|
| **Q1** | Où marquer le rôle ? | Une colonne `corpus_role` sur `image_assets` (`train`/`val`/`judge`) est le candidat naturel : c'est la table que les deux pipelines filtrent déjà. Coût : une migration, **plus son miroir** dans `ml/state/schema.sql` et dans le `MIROIR_ATTENDU` de `tests/test_schema_mirror.py` — sans quoi deux tests rougissent (précédent : migration 0011) |
| **Q2** | Quel critère de sélection du juge-proxy ? | Il ne doit être ni DINO ni ArcFace (§2). Pistes à départager : aléatoire à graine fixe (neutre, faible pouvoir discriminant), critère de qualité d'image indépendant (`quality_score`, `tilt_deg`, `axis_ratio` — déjà en base), ou stratification par condition de prise de vue |
| **Q3** | Le prélèvement est-il figé ou rejouable ? | Figé = comparabilité entre runs (l'argument de `gold_version`). Rejouable = suit l'enrichissement. Probablement figé + versionné, comme le gold de review |
| **Q4** | Que devient le split `val` d'ArcFace une fois le device retiré ? | Sans val, pas de sélection de checkpoint — on prend le dernier epoch. Avec un val issu d'eBay, on sélectionne sur une distribution qui **n'est pas** celle du déploiement, ce qui était précisément l'argument du code actuel. Il n'y a pas de réponse gratuite ici |
| **Q5** | Faut-il un juge par tâche ? | La tâche *review* (crops eBay) et la tâche *scan* (frames caméra) sont distinctes ([ADR-008](../../adr/008-deux-voies-backbone-gele-et-arcface.md)). Un juge unique moyennerait deux choses différentes |
| **Q6** | Combien vaut le biais actuel ? | Mesurable une fois la séparation faite : rejouer le run du 2026-08-16 contre un juge propre et lire l'écart avec 92,4 %. C'est la seule façon de savoir si ce chantier corrige un dixième de point ou dix |

## 6. Le corpus device, et le fait qu'il est fragile

Le juge de départ, c'est `ml/datasets/eval_real_norm/`. Deux choses à savoir
avant de s'appuyer dessus.

**Il n'est pas là où on croit.** Sur le Mac, le 2026-08-25 :

```bash
find ml/datasets/eval_real_norm -type f | wc -l   # 114
ls ml/datasets/eval_real_norm | wc -l             # 19 classes, 6 photos chacune
```

Or le benchmark du 2026-08-16 annonce **317 photos / 16 pièces**. L'écart n'est
pas expliqué ici : le run a eu lieu sur une machine dont le pull device était
plus fourni. **Le juge de référence n'est donc pas intégralement sur le Mac**, et
avant toute mesure il faut établir où vit la version complète.

**Il n'a aucune réplique.** Les 2 264 images device connues (114 dans
`eval_real_norm`, 2 150 dans `debug_pull`) ne sont ni sur MinIO ni en
sauvegarde — cf.
[`../scan-quality/DURABILITE-CORPUS.md`](../scan-quality/DURABILITE-CORPUS.md).
Un `git clean -xdf` ou un reset de téléphone les efface. **Toute séance de
capture qui ne pousse pas immédiatement produit de la donnée qu'on perdra.**

**Six dossiers sur 19 sont nommés par membre, pas par classe.**
`fr-1999-2eur-standard-1st-map` au lieu de `fr-2euro-standard-t1`, etc. —
`sync_eval_real.py` retombe sur l'`eurio_id` brut quand le `class_manifest.json`
manque. `prepare_dataset` sait fusionner ; **toute lecture naïve du dossier
comptera 7 classes fantômes**. C'est le piège `class_id` ≠ `eurio_id` de la
skill `eurio-banque` §2, dans une nouvelle tenue.

Recouvrement avec la cohorte `rich10-68c` (68 classes, préflight propre) :
**18 des 19 classes du corpus device y sont** ; seule `mt-2euro-standard-t1`
reste dehors.

## 7. Ce que ce document ne fait pas

- Il ne décide pas Q1..Q6.
- Il ne touche à aucun code.
- Il ne dit pas quel modèle gagne — c'est [`MATRICE.md`](./MATRICE.md).
- Il ne remplace pas [ADR-008](../../adr/008-deux-voies-backbone-gele-et-arcface.md),
  dont il exécute le D4 : *« le juge unique est le corpus de scan »*. Ce chantier
  est la condition pour que ce D4 veuille dire quelque chose.
