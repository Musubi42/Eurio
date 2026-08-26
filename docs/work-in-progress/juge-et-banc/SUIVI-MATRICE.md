# Suivi — la matrice d'encodeurs, étape par étape

> **Le document de pilotage de ce chantier.** Ouvert le **2026-08-26** à la
> demande du PO. Il dit où on en est, ce qui est décidé, ce qui reste, et sur
> quelle machine. Le *pourquoi* est dans [`MATRICE.md`](./MATRICE.md), le
> *défaut d'origine* dans [`PROBLEME.md`](./PROBLEME.md).
>
> Mets-le à jour à chaque étape franchie. Un suivi qui ment est pire que pas de
> suivi.

## L'objectif, en une phrase

Départager **ArcFace** et **DINO** sur la même tâche, le même jeu d'évaluation
et le même ensemble de classes — pour savoir lequel part dans l'APK.

## Les décisions prises, et qu'on ne rouvre pas

| # | Décision | Date |
|---|---|---|
| D1 | **Le jeu d'évaluation vient des crops eBay.** 5 par classe, prélevés du pool d'enrichissement, **exclus de l'entraînement** | 2026-08-26 |
| D2 | **60 classes**, pas 68 — les 8 autres tombent sous le plancher `MIN_REAL=10` après prélèvement (mesuré, cf. §Quotas) | 2026-08-26 |
| D3 | **La banque DINO servie (`2eur_all`) n'est PAS touchée.** La matrice travaille sur une **sous-banque** restreinte aux 60 classes | 2026-08-26 |
| D4 | **~8 bras** dans la matrice, pas 18. DINOv2 + DINOv3 + ArcFace, avec `dinov2_vitl14` comme plafond de référence | 2026-08-26 |
| D5 | Le critère de prélèvement des images d'éval est **indépendant des deux modèles jugés** (géométrique), jamais la distance DINO à la canonique | 2026-08-26 |
| D6 | L'entraînement ArcFace se fait **sur le PC** (1080 Ti), pas sur le Mac | 2026-08-26 |
| D7 | Le critère géométrique de D5 est **`tilt_deg`**, pas `quality_score` : après backfill il couvre **99,9 %** du pool éligible contre 65,4 % — aucune imputation, donc aucune règle qui choisirait en fait l'imputation | 2026-08-26 |
| D8 | Le marquage vit dans **`image_assets.eval_corpus` (TEXTE)**, pas dans `training_eligible=0` : `training_eligible` porte le verdict de la REVIEW, `eval_corpus` porte un RÔLE. Les confondre ferait disparaître les 300 crops des compteurs de review | 2026-08-26 |
| D9 | **Le rangement suit le rôle.** Les crops d'éval partent dans un bucket dédié `eval-corpus`, sous le préfixe de clé `eval/<corpus>/`. Décidée après réouverture — la première réponse était un argument de COÛT déguisé en argument de PRINCIPE | 2026-08-26 |

### ✅ D9 tranchée — bucket dédié **et** préfixe de clé, appliqué le 2026-08-26

Réponse initiale : « la clé S3 est immuable, c'est la ligne qui porte le rôle,
un déplacement d'objets serait décoratif ». **Objection du PO, et elle porte :**
un crop qui passe en évaluation **n'est plus le même objet fonctionnellement**.
Il sort du pool d'entraînement. Que le stockage n'en sache rien signifie que la
séparation ne tient que par un `WHERE` — et qu'un oubli de prédicat la fait
fuir en silence.

**L'incohérence est de notre côté** : quelques heures plus tôt, on a choisi de
mettre le corpus de jugement dans une **base isolée** (`scan_corpus.db`)
exactement pour cette raison — *« l'entraînement ne la lit pas, donc il ne PEUT
pas la prendre, même par bug »*. Le même raisonnement vaut pour les octets. On
l'a appliqué à la base et refusé au stockage, sans justifier la différence.

Ce qui était **vrai** dans la réponse initiale relève du coût, pas du principe :

- `storage_path` est une clé S3 qui sert de jointure partout, et le bucket est
  **dérivé de la source** (`bucket_for_asset`), pas du rôle ;
- déplacer 300 objets impose de réécrire 300 `storage_path`, de rendre
  `bucket_for_asset` conscient du rôle, et d'invalider le cache local
  correspondant.

C'est un **lot**, pas une ligne — mais c'est la bonne cible. ⚠️ À noter : le
fichier ne « disparaît » pas de MinIO, il change de rôle ; ce que le PO demande
est que le **rangement** reflète ce rôle, comme la base le fait désormais.

**Tranché : option (a), et les DEUX marques — pas l'une ou l'autre.**

| Marque | Ce qu'elle apporte |
|---|---|
| bucket `eval-corpus` | la garantie **physique** : un process qui ne connaît que `enrichment-crops` ne peut plus atteindre l'octet, quel que soit son SQL |
| préfixe `eval/<corpus>/` dans la clé | rend le bucket **dérivable de la clé seule** (`bucket_for_key`) — sinon il faudrait faire descendre `eval_corpus` dans chaque requête qui alimente une vignette, et un oubli donnerait une image cassée sans un mot |

⚠️ **Le préfixe ferme un trou que le bucket seul laissait ouvert.** À clé
INCHANGÉE, le cache local `~/.cache/eurio/enrichment-crops/<clé>` reste un
**HIT** : l'entraînement aurait lu le crop d'éval malgré le déplacement. La clé
change → le cache d'entraînement ne peut plus le trouver.

**Ce qui a été écrit** (suite : 2392 passed) :

- `shared/storage/__init__.py` — `eval-corpus` dans `Bucket`, `EVAL_KEY_PREFIX`,
  `is_eval_key` / `eval_storage_key` / `corpus_of_eval_key` / `bucket_for_key`,
  `bucket_for_asset(source, storage_key=None)` où le **rôle l'emporte sur la
  source** ;
- **`assert_role_matches_bucket`**, appelé par `local_path`, `cache_path_for` et
  `signed_url`. C'est lui qui rend une fuite *bruyante* : sans lui, une collecte
  d'entraînement ayant perdu son prédicat `eval_corpus IS NULL` irait chercher
  `enrichment-crops/eval/…`, prendrait un 404, et `local_path` déclencherait
  `cascade.mark_missing_in_storage()` — le crop d'éval serait marqué
  `missing_in_storage` alors qu'il est parfaitement là. **La fuite aurait
  « réparé » la base à l'envers.** Le garde lève AVANT le réseau et AVANT la
  cascade ;
- `store/eval_corpus.py` + `POST /ingest/eval-corpus` acceptent `storage_path` :
  rôle et rangement atterrissent dans la **même transaction** ;
- `ml/scripts/move_eval_corpus_objects.py` — **copier → vérifier → écrire la
  base → supprimer la source**, dans cet ordre et pas un autre. Idempotent ;
- les couches d'**affichage** dérivent leur bucket (galerie, review, arbitrage,
  ami, recadrage, suppression) — un crop d'éval garde son `training_eligible` et
  reste donc dans les compteurs et les planches de review (D8) ;
- les collectes d'**entraînement** gardent `"enrichment-crops"` **en dur**, et
  c'est délibéré. Un test le verrouille dans ce sens : si quelqu'un les
  « corrige » en les faisant dériver leur bucket, la garantie de D9 tombe sans
  qu'aucun autre test ne rougisse ;
- `scripts/cascade_sync.py` connaît `eval-corpus` — sans quoi l'audit
  chercherait les clés `eval/…` dans `enrichment-crops`, ne les trouverait pas,
  et les marquerait `missing_in_storage`.

**Vérifié après application, sur les trois surfaces** (2026-08-26) :

| Quoi | Mesure |
|---|---|
| base | `300` marqués, `300` avec `storage_path LIKE 'eval/%'`, `300` encore `present` |
| MinIO | `eval-corpus` : **300 objets** ; le bucket n'existait pas avant |
| préflight | `n_ebay = 1996`, 0 block, 0 warn (process neuf) |
| affichage, de bout en bout | URL présignée → `HTTP 200 · 81 205 octets` · `PNG image data, 224 × 224` — **exactement la taille de l'objet source avant déplacement** |
| **mutation sur le VRAI point d'entrée** | prédicat `eval_corpus IS NULL` retiré de `_ebay_training_sources` sur disque → `ValueError: clé d'éval servie depuis le mauvais bucket : enrichment-crops/eval/…`. **La fuite est bruyante**, et elle lève avant tout accès réseau. Fichier restauré, `git status` vide |

⚠️ **Deux pièges rencontrés pendant l'application, à ne pas re-payer :**

1. **La clé MinIO du Mac ne peut pas créer de bucket** (`AccessDenied` sur
   `CreateBucket`) — elle est scopée par `eurio-app-policy`. Le bucket se crée
   **côté VPS, en ciblé** (`docker exec eurio-minio mc mb …`), jamais en
   relançant `bootstrap.sh` (qui ferait un `docker compose up` sur le conteneur
   qui porte `eurio-api`, `eurio-review` et le miroir de backup). Et la policy
   doit gagner `eval-corpus` **avant** la passe, sinon elle refuse tout.
2. **Pendant le remplacement de la policy, les 300 `head_object` ont pris un
   403** — et le script a annoncé « source absente de MinIO ». Un message qui
   ment est pire qu'une erreur : il désignait les octets comme coupables au lieu
   du droit d'accès. Corrigé : `_tete` sépare le 404 (absent) de tout le reste
   (`TeteRefusee`), et un refus **arrête la passe** au lieu de conclure 300 fois
   de suite. Rien n'avait été écrit ni supprimé — l'ordre copier → vérifier →
   écrire → supprimer a tenu.

### Le recadrage d'un crop d'éval — tranché le 2026-08-26 : **on ne bloque rien**

Le constat technique est exact : `apply_manual_crop` réécrit les pixels **sous
la même clé** (`serving/crop_edit.py:357-367`) — même `asset_id`, même clé, seuls
les octets changent. Recadrer un des 300 crops d'éval modifie donc le jeu noté
sans que rien ne le dise.

**Le PO a refusé le blocage, et son argument porte** : ce qu'on construit est une
banque qui GROSSIT — plus de crops, plus de classes enrichies, c'est
l'objectif même du projet. Deux modèles entraînés à deux mois d'écart ne sont
donc **pas** comparables, par construction, et vouloir le rendre possible
reviendrait à figer l'enrichissement. Trois crops recadrés sur des milliers ne
changent pas un verdict ; si c'était le cas, le problème serait ailleurs.

**Ce qui reste vrai, et qui est plus étroit** : la matrice n'est pas une
comparaison longitudinale, c'est un A/B **simultané** — ArcFace et DINO notés à
quelques jours d'écart sur les mêmes 300 frames. C'est le seul endroit où
l'identité des images compte, et ça dure le temps de la matrice. On le sait, on
n'en fait pas une règle, et aucun code ne l'impose.

### Sur D5 — pourquoi pas « les plus éloignées de la canonique selon DINO »

L'intention du PO est juste : il veut des images d'éval qui **ressemblent à ce
qu'un utilisateur photographierait**, donc dégradées. L'instrument, lui, est
circulaire, et il l'est dans les deux sens :

- « le plus loin de la canonique » **est le critère du farthest-point sampling**,
  donc on sélectionnerait préférentiellement des crops qui **sont déjà des
  ancres** — 46,8 % du pool éligible en est une (1391/2969). DINO les
  reconnaîtrait à similarité 1,0 : biais **en sa faveur** ;
- et si on exclut les ancres pour l'éviter, on obtient **les cas durs de DINO
  choisis par DINO**, imposés à ArcFace qui n'a pas voix au chapitre : biais
  **contre lui**.

La sortie garde l'intention et change d'instrument : la dégradation visée est
**géométrique** (de biais, mal cadré, partiel), et elle se mesure sans aucun
modèle appris — `tilt_deg`, `axis_ratio` (ellipse ajustée sur les bords),
`quality_score` (cadrage). C'est ce que l'étape 1 rend disponible.

## Les quotas — mesuré le 2026-08-26

```sql
-- crops eBay validés par classe, maille COALESCE(design_group_id, eurio_id)
select coalesce(co.design_group_id, co.eurio_id),
       sum(case when ia.training_eligible=1 and s.source='ebay' then 1 else 0 end)
  from coins co
  left join image_assets ia on ia.eurio_id = co.eurio_id
  left join source_images s on s.id = ia.source_image_id
 group by 1;
```

| quota éval / classe | classes qui tiennent | crops d'éval | classes perdues |
|---:|---:|---:|---:|
| 3 | 60 | 180 | 8 |
| **5** ✅ | **60** | **300** | **8** |
| 8 | 54 | 432 | 14 |
| 10 | 51 | 510 | 17 |

**5 ne coûte rien de plus que 3** : les 8 classes perdues sont celles à 10-12
crops, qui tombent déjà sous le plancher avec un quota de 3. Et **300 frames**
est la cible que `exp-01 §9` réclamait pour que le McNemar ait de la puissance
(150-300) — cible jamais atteinte jusqu'ici.

Répartition des 68 classes riches : 8 à `10-14`, 9 à `15-19`, 23 à `20-29`,
28 à `30+`.

## Les étapes

| # | Étape | Machine | État |
|---|---|---|---|
| **1** | Backfill `quality_score` + tilt sur le parc | Mac | ✅ **fait** 2026-08-26 — `{"updated": 17658, "skipped": 20, "missing": 0}`, couverture `quality` 5,6 % → **61,6 %**, `tilt` → **99,5 %**. Détail : [`ETAPE1-2.md`](./ETAPE1-2.md) |
| **2** | Prélever 5 crops d'éval × 60 classes, les marquer, les exclure de l'entraînement, propager MinIO + API | Mac | ✅ **fait** 2026-08-26 — plan régénéré (**60 classes / 300 crops**), `select_eval_holdout --apply` → `{"updated": 300, "skipped": 0, "conflict": 0, "missing": 0}`. Préflight recalculé : `n_ebay` **2296 → 1996** (−300 exactement), `ready=true`, 0 block, 0 warn. Rangement MinIO (D9) propagé. Plan appliqué : [`eval-holdout-plan.json`](./eval-holdout-plan.json) |
| **2bis** | Composer la cohorte des 60 (bloqueur `REVUE-ETAPE3` §B4) | Mac | ✅ **fait** 2026-08-26 — `matrice-60c` = **`2e51f2b3d633`**, clonée de `rich10-68c` moins les 8 classes sans hold-out. Préflight : **60 classes, `ready=true`, 0 block, 0 warn, `n_ebay = 1908`**. Classe la plus pauvre : 12 crops. **Encore `draft`** — créer l'itération la gèlera irréversiblement |
| **3** | **Entraîner ArcFace sur les 60 classes** | **PC** | ✅ **calibration jouée et rapatriée** 2026-08-26 — `b55b61b59632`, `status=completed`, 3 epochs en **9 min 28 s**, 13 988 samples bakés. Artefacts sur le Mac. Reste : le run complet à 40 epochs (≈ 2 h 06, **mesuré** et non plus extrapolé) |
| **4** | Sous-banque DINO restreinte aux 60 classes | Mac | 🔜 |
| **5** | La matrice — les 4 bras sur les mêmes 260 frames | Mac | 🟡 **4 bras mesurés** 2026-08-26, cf. §Les chiffres. ⚠️ Le bras ArcFace est un run de **calibration à 3 epochs**, non convergé : la comparaison qui compte attend les 40 epochs |

✅ **`0014` est au canonique depuis le 2026-08-26.** Ce qui suit reste vrai comme RÈGLE : Le
prédicat `eval_corpus IS NULL` est en place dans les deux collectes ; sur une base
qui n'a pas la colonne il lève `no such column`, et sous un job détaché ça donne
**HTTP 200 + silence**. L'ordre de déploiement n'est pas négociable.

### Étape 1 — pourquoi elle passait devant, et ce qu'elle a rendu — ✅ 2026-08-26

Sans elle, aucun critère de sélection neutre n'était disponible : `tilt_deg`
n'était fiable que sur **11,1 %** du pool éligible et `quality_score` renseigné
sur **8,8 %**. **Mesuré après la passe** (`sqlite3 "file:ml/state/eurio.replica.db?mode=ro"`,
cf. [`ETAPE1-2.md`](./ETAPE1-2.md) §Couverture) :

| | avant | **après** |
|---|---:|---:|
| `quality_score` sur le parc (18 730) | 5,6 % | **61,6 %** |
| `quality_score` sur le pool éligible (2 968) | 8,8 % | **65,4 %** |
| `tilt_deg` sur le pool éligible | 21,5 % | **99,9 %** |
| **examinés** (`quality_pipeline_version`) | 5,6 % | **100 %** |

C'est cet écart qui fonde **D7** : le critère de D5 est `tilt_deg`, pas
`quality_score`.

✅ **Le coût d'éviction a été tranché : `EURIO_CACHE_MAX_GB=0` le temps de la
passe**, et le choix est démontré nul en effet — le cache tenait 15 Go sous un
plafond de 20, l'éviction n'aurait rien évincé. Re-mesuré ici : **1,35 s par
passage** (62 583 fichiers, 3 tirs), × **1 579** raws à télécharger (85,8 % de
hit) ≈ **35 min** de balayage pur pour ~7,4 min de CPU utile. Le correctif de
fond n'est **pas** fait — cf. §Reste-à-faire.

⚠️ **La limite de méthode, à ne jamais taire** : `quality_score` mesure le
**cadrage**, pas la qualité. L'oracle Otsu plafonne (~35 % resteront `NULL` =
*non mesuré*, jamais *mauvais*) et il est **aveugle au mauvais objet** — un crop
pris sur une capsule ou un bout de tissu est scoré « ok ».

### Étape 2 — ce que « exclu de l'entraînement » veut dire exactement

Le marquage doit être honoré par **les deux** voies, et il n'y a **pas de point
unique en amont** : les deux requêtes divergent (intersection 2888, ArcFace seul
79, DINO seul 1). Le prédicat s'écrit donc dans les deux :

- `ml/training/iteration_augmentations.py` — `_ebay_training_sources` : `AND a.eval_corpus IS NULL` ✅ posé ;
- `ml/training/foundation/anchors.py` — `_candidate_crops_for_class` : `AND eval_corpus IS NULL` ✅ posé.

Chacun a **son** test et **sa** mutation (`ml/tests/test_eval_holdout.py`) : un
correctif d'une seule voie passerait au vert sur l'autre. Sur le **vrai** point
d'entrée, retirer le prédicat ArcFace fait remonter le `n_ebay` du préflight de
1 908 à **2 208** — le hold-out fuit, et rien ne le dirait.

⚠️ **`real_training_sources` est partagé par le bake ET le préflight**
(`preflight.py:179`). Retirer des crops fait donc baisser le seed que le
préflight contrôle — c'est voulu, et c'est pourquoi le quota se raisonne sur
**ce qui reste**, jamais sur ce qu'on prend.

### Étape 3 — ce que le PO lancera sur le PC

Préparée ici, jouée là-bas. La revue de préparation dira si elle est prête.

## Les chiffres — LES 4 BRAS, 2026-08-26

Rapport brut : [`matrice-dino.md`](./matrice-dino.md). Jeu `9bc08e19b83c`
(260 frames, 52 classes, règle v2), banque `matrice60` (1 813 ancres).
Appariement vérifié : 52 classes toutes présentes, 0 distracteur, 0 crop non
encodé. **Les quatre bras encodent la MÊME banque et les MÊMES frames** — même
espace de labels, McNemar apparié.

| Modèle | M params | dim | **r@1** | r@5 | pays@1 | ms/img |
|---|---:|---:|---:|---:|---:|---:|
| **ArcFace** `b55b61b59632` | **1,1** | 256 | **76,5 %** | 93,8 % | 83,8 % | **4** |
| `dinov2_vits14` | 22,1 | 384 | 94,2 % | 99,2 % | 88,1 % | 13 |
| `dinov2_vitb14` | 86,6 | 768 | 96,9 % | 99,6 % | **89,2 %** | 31 |
| `dinov2_vitl14` | 304,4 | 1024 | **98,1 %** | 99,6 % | 88,5 % | 101 |

McNemar apparié, référence **ArcFace** :

| bras | gagne | perd | p |
|---|---:|---:|---:|
| `vits14` | 50 | 4 | 3,8 × 10⁻¹¹ |
| `vitb14` | 57 | 4 | 4,9 × 10⁻¹³ |
| `vitl14` | 59 | 3 | **1,7 × 10⁻¹⁴** |

### 🔴 CE CHIFFRE NE DIT PAS QUE DINO BAT ARCFACE

**L'ArcFace mesuré est un run de CALIBRATION à 3 epochs, pas un modèle
entraîné.** Sa perte valait encore **5,42 et descendait** (9,93 → 6,22 → 5,42)
quand le run s'est arrêté. Il n'a pas convergé, et il n'a jamais prétendu le
faire : son but était de valider la plomberie avant les 40 epochs.

Comparer un modèle à 3 epochs à trois encodeurs pré-entraînés sur des millions
d'images et en tirer « DINO gagne » serait malhonnête. **La comparaison qui
compte attend le run à 40 epochs** (≈ 2 h 06, mesuré).

### Ce qui EST acquis, et qui ne bougera pas

* **la chaîne de mesure fonctionne de bout en bout** : 4 bras, une banque, un
  jeu, un espace de labels commun, un McNemar apparié. C'était l'objet du
  chantier, et c'est fait ;
* **le coût d'ArcFace est écrasant en sa faveur** : 1,1 M de paramètres et
  **4 ms/image**, contre 304 M et 101 ms pour `vitl14` — **25× plus rapide,
  276× plus petit**. Cet écart-là ne dépend pas de l'entraînement. Si le run à
  40 epochs le rapproche des DINO, la question du choix devient sérieuse ;
* **`r@5 = 93,8 %` à 3 epochs** alors que `r@1` n'est qu'à 76,5 % : la bonne
  réponse est presque toujours dans les cinq. C'est la signature d'un modèle
  qui a appris à séparer grossièrement et pas encore à trancher — exactement ce
  qu'on attend à mi-entraînement.

### Le protocole, et ce qu'il coûte

ArcFace entre dans le banc **comme un encodeur** : on lui fait encoder la même
banque d'ancres que les autres, et **ses 60 centroïdes entraînés ne servent
pas**. Deux conséquences :

* c'est une mesure de **représentation**, pas du système qui shippe — en
  production ArcFace compare à ses centroïdes, pas au plus proche voisin d'une
  banque ;
* mais l'espace de labels devient **identique pour les quatre bras**, donc la
  comparaison est appariée. Sans ça, ArcFace aurait affronté ses 60 centroïdes
  là où DINO n'a que 52 classes, et on aurait mesuré la taille des espaces de
  recherche.

⚠️ **Une asymétrie réelle, qui n'est pas un défaut** : ArcFace a été ENTRAÎNÉ
sur les crops qui composent la banque ; DINO n'a rien vu. Les requêtes sont
inconnues des deux. L'avantage d'ArcFace sur les références est donc réel — et
il perd quand même, ce qui confirme qu'il est sous-entraîné plutôt que
désavantagé.

## Le run ArcFace de calibration — joué, rapatrié, 2026-08-26

`b55b61b59632` sur la cohorte gelée `matrice-60c`. `status=completed`,
`error` vide, **15:29:11Z → 15:38:39Z = 9 min 28 s** pour 3 epochs.

| | |
|---|---|
| samples bakés | **13 988** (l'extrapolation disait ≈ 16 000, soit −13 %) |
| coût réel des 40 epochs | **≈ 2 h 06**, mesuré par règle de trois sur ce run (l'estimation de `REVUE-ETAPE3 §P9` disait 2 h 21) |
| backbone | `mobilenet_v3_small`, mode `arcface`, `embedding_dim = 256` |
| centroïdes | **60 classes** |
| perte | 9,93 → 6,22 → **5,42** — elle descend, elle n'a pas convergé (3 epochs) |
| `recall@1` du log | **0,0 à chaque epoch** — attendu : `val_source=none`, il n'y a pas de jeu de validation à mesurer. Ce n'est pas un échec |

**Rapatriement — par MinIO, jamais par git.** Les artefacts sont archivés à
`model-artifacts/lab/iterations/b55b61b59632/a167e6a42bdf/artifacts.tar.gz`
(8 228 384 octets). `sha256` identique des deux côtés :
`a167e6a42bdf5fc9b2efe1cc33caca36a5e33df5be3911434d591e10541bdabe`. Extraits
dans `ml/lab/iterations/b55b61b59632/` (9,3 Mo, gitignoré) : `best_model.pth`,
`embeddings_v1.json`, `coin_embeddings.json`, `eurio_embedder_v1.tflite`,
`model_meta.json`, `per_class_metrics.json`, `training_log.json`,
`class_manifest.json`.

### 🔴 L'obstacle suivant, et il est immédiat : 60 contre 52

Le modèle porte **60 centroïdes** — la cohorte gelée. Le corpus d'éval v2 n'a
plus que **52 classes** (le garde vendeur en a coûté 8). Noter ArcFace tel quel
lui donnerait **8 distracteurs de plus** que DINO, dont la banque est à 52 :
on mesurerait la taille des espaces de recherche, pas les encodeurs.

Il faut restreindre les centroïdes aux 52 classes du manifeste avant de noter.
Précédent dans le dépôt : `_filter_embeddings`
(`ml/scripts/build_cohort_bundle.py:163-176`). C'est la même opération que la
sous-banque DINO, de l'autre côté.

⚠️ Et il restera à **charger ArcFace dans le banc** : `_load_model` de
`bench_encoder_dino` ne connaît que `timm:` et les noms `torch.hub` DINOv2.

## Le corpus d'évaluation lui-même — chantier ouvert le 2026-08-26

Document : [`CORPUS-EVAL-EBAY.md`](./CORPUS-EVAL-EBAY.md). Ouvert à la demande du
PO (« utiliser des crops eBay comme jeu d'éval »), il constate d'abord que
**c'est déjà fait** (D1, les 300 sont eBay à 100 %), puis mesure trois choses
que la matrice doit connaître :

- 🔴 **contamination par vendeur, +5,0 pts, `p ≈ 0,002`** — 40,7 % des crops
  d'éval partagent leur `seller_id` avec une ancre de leur classe.
  `phase-4-subcenter-evalbench.md:40` l'exigeait depuis des mois
  (« split par lot/seller, pas par photo individuelle ») ; `select_eval_holdout`
  ne le fait pas ;
- 🔴 **la règle D5/D7 n'a pas sélectionné du dur** — le jeu « le plus incliné »
  est 3,7 pts plus FACILE que ce qu'il a laissé (94,9 % contre 91,2 % à
  contamination contrôlée). Le tilt ne classe rien à l'intérieur du jeu non plus ;
- 🔴 **aucun signal géométrique ne prédit la difficulté**, et le seul qui
  s'en approche est **inversé** : `quality_score` HAUT = le plus dur (87,8 %
  contre 93,1 %). Aucun mécanisme n'est proposé — ce serait une histoire.

⚠️ **Rien de tout ça ne bloque le bras ArcFace.** Les défauts du jeu sont les
mêmes pour les deux modèles et le McNemar est apparié : il reste utilisable
pour les départager *entre eux*. Ce document sert à savoir ce que le chiffre
vaudra, pas à retarder sa production.

## Reste-à-faire hors étapes

- **Persister `inputs_digest` sur l'itération** (~3 lignes). Il existe déjà
  — recette + graine + cible + liste ordonnée des sources — mais il vit dans le
  `_manifest.json` du bake et ne quitte jamais le disque. Sans lui, on ne saura
  pas plus tard **avec quoi** un modèle a été entraîné.
  ⚠️ Le pool grossit : **5 051 samples le 2026-08-16, 6 594 le 2026-08-25**
  (+30,5 %) pour la même cohorte. Deux runs à deux semaines d'écart ne bakent
  pas la même chose, et rien ne le dit.
- **La couche de textures est inerte** — la recette `test-3` déclare 3 couches,
  en applique 2 (`ml/training/data/overlays/` n'existe pas). Générer les
  textures change le bake, donc rend tout run ultérieur non comparable aux
  précédents. Décision de calendrier, pas technique.
- **`_evict_if_needed` rglob avant CHAQUE téléchargement** (`shared/storage/local_cache.py:250`)
  sans mémoriser la taille totale : 1,35 s × 62 583 fichiers, payé même quand le cache
  est très en dessous de son plafond (donc pour rien). Contourné à la main en étape 1
  (`EURIO_CACHE_MAX_GB=0`) ; **non corrigé**. Toute passe massive future repaiera la taxe.
- ⚠️ **`:8042` sert un `training-readiness` PÉRIMÉ quand il a été lancé avant
  l'écriture.** Mesuré le 2026-08-26 : après le marquage des 300 crops, le
  serveur en place répondait encore `n_ebay=2296` tandis qu'un process neuf
  lisant *le même fichier* rendait 1996. `Store._connection()` garde une
  connexion `mode=ro` **thread-local** ouverte pour la vie du process ; les
  pages réécrites par `sqlite3_rsync` ne lui parviennent pas. Rien ne le dit —
  la réponse est bien formée et plausible.
  **Contournement immédiat** : recalculer dans un process neuf, ou redémarrer
  `:8042`. **Correctif de fond non fait.** Ne jamais conclure d'un
  `training-readiness` lu sur un serveur plus vieux que la dernière écriture.
- **`encoder_bench_runs`** manque deux colonnes pour porter la matrice :
  `quantization` et `eval_corpus` (cf. [`MATRICE.md`](./MATRICE.md) §4).
- **Le prélèvement d'éval devrait exclure les quasi-doublons** : un crop dont
  le `source_image_id` porte aussi une ancre de sa classe est presque la même
  image. Mesuré le 2026-08-26 : 36/300 (12 %), tous justes sous `vitb14`,
  +0,5 pt d'inflation. Un prédicat de plus dans `select_eval_holdout`.
- **`provisional`** est gardé à l'écriture mais son prédicat croit quatre champs
  déclarés par l'appelant — à fermer avant qu'une page ne fonde un choix
  d'encodeur dessus.

## ✅ L'autopull de la réplique ne menace PAS un entraînement long

Question du PO : *« toutes les deux minutes il y a un pull ; si mon entraînement
dure plusieurs heures, est-ce qu'il va écraser les images qu'on a pull ? »*

**Non.** Vérifié au code le 2026-08-26 :

- `client/replica.py` ne contient **aucune** référence à `cache`, `datasets`,
  `augmentations` ou `enrichment-crops` :
  `grep -cE "cache|datasets|augmentations|enrichment-crops" ml/client/replica.py`
  → **0** ;
- l'autopull rafraîchit **uniquement** `state/eurio.replica.db`, par
  **`sqlite3_rsync` incrémental** (~3 s toutes les 2 min), sous verrou
  (`_REPLICA_LOCK`) — pas un remplacement de fichier en vrac ;
- les **images** vivent ailleurs et ne sont jamais touchées : le cache
  read-through `~/.cache/eurio/<bucket>/<clé>` et le bake
  `ml/datasets/<numista_id>/augmentations/<iteration_id>/sample_NNN.jpg`, qui
  sont de vrais fichiers.

**Interrupteur si tu veux la déterminisme absolu pendant un run :**
`EURIO_REPLICA_AUTOPULL=0` (ou ne pas lancer l'API sur la machine qui entraîne
— c'est `serving/server.py:291` qui démarre le thread, et il est no-op si le
transport rsync n'est pas provisionné).

⚠️ **Ce qui reste vrai, et qui est un autre sujet** : la réplique étant
rafraîchie, le **pool de sources** peut bouger entre deux lectures. Le bake lit
ses sources **une fois**, au début — donc un run est cohérent avec lui-même.
Mais deux runs à deux semaines d'écart ne bakent pas la même chose (5 051 →
6 594 samples, +30,5 %), et rien ne le dit. C'est ce que `inputs_digest`
persisté fermerait (cf. §Reste-à-faire).

## Deux lots que le plan ne contenait pas — trouvés par la revue adversariale

Ils s'intercalent **avant** l'étape 5, et sans eux la matrice ne peut pas être
calculée. Ce ne sont pas des réglages.

| Lot | Ce qui manque | Preuve |
|---|---|---|
| **A — noter des crops eBay** | `replay_corpus` ne lit qu'une table, `scan_corpus` (`replay_corpus.py:662`). 7 points à changer, dont la double identité `truth_eurio_id`/`class_id` du gold, `by_condition` qui dégénère, et `normalize_device_path` ≠ `normalize_listing_path` | `REVUE-ETAPE3.md` §B2 |
| **B — un adaptateur DINO** | `load_embedder` n'accepte que `.pth/.pt/.tflite` ; la banque est un `.npz` (2 062 ancres, 671 classes, dim 1024). Restreindre la banque à 60 classes est **nécessaire mais insuffisant** | `REVUE-ETAPE3.md` §B3 |

### ✅ La faille du garde d'espace de labels est fermée — 2026-08-26

Le constat était : `assert_same_label_space` ne se déclenche que si
`--baseline` est passé. Deux runs notés séparément puis comparés à la main
passaient sans un mot — **le garde se contournait en ne l'appelant pas.**

Ce n'est pas un oubli qu'on corrige par de la discipline : une comparaison à la
main **n'a pas** de garde, quelle que soit la bonne volonté de celui qui la
fait. Tant que le chemin gardé n'existait pas, le contourner n'était même pas
une négligence — c'était le seul geste disponible. La fermeture a donc deux
moitiés, et il faut les deux :

1. **l'empreinte entre dans l'artefact.** Chaque scorecard porte désormais
   `label_space.mesh_digest` (16 hex de SHA-256 de la maille triée), plus
   `n_mesh_classes` et `mesh_basis`. ⚠️ Un **compte** n'aurait rien dit : deux
   candidats à 60 classes **chacun** peuvent porter deux ensembles de 60
   classes différents, et un compte les déclarerait comparables. L'écart est
   maintenant lisible dans le fichier, six mois plus tard, sans rien relancer ;
2. **`--compare RUN_A RUN_B`** croise deux runs déjà notés en passant par
   `assert_comparable_runs` — aucune inférence, aucun modèle chargé, et le
   McNemar apparié est calculé depuis les deux `predictions.jsonl`. Le résultat
   est gravé dans `comparison.json` par l'**opération**, pas par la CLI : une
   comparaison faite depuis un notebook laisse le même artefact.

`assert_comparable_runs` refuse sur **quatre** motifs, et le quatrième est le
moins évident : une scorecard **sans empreinte** (notée avant ce lot) n'est pas
« probablement compatible », elle est **non vérifiable** — sans ce refus, la
seule scorecard qu'on ne peut pas contrôler serait la seule à passer. Les trois
autres : espace de labels, `corpus_version`, et le bloc `filter` (dont
`include_rejected`, LE réglage qui change le jeu noté).

Verrouillé par 7 tests dans `tests/test_replay_corpus_iteration.py`.

## Journal

| Date | Ce qui s'est passé |
|---|---|
| 2026-08-26 | Document ouvert. D1..D6 posées. Quotas mesurés : 5/classe × 60 classes = 300 frames. |
| 2026-08-26 | Étape 1 **faite** (backfill, `missing=0`, tilt 21,5 % → 99,9 %). Étape 2 **préparée**, non appliquée. |
| 2026-08-26 | Migration `0014` **appliquée au canonique**, `/ingest/eval-corpus` servie, réplique à jour. Suite : 2373 passed. |
| 2026-08-26 | **D9 réouverte** : le PO conteste le refus de propager côté MinIO, et il a raison — l'argument était un coût déguisé en principe. |
| 2026-08-26 | Autopull vérifié **inoffensif** pour un entraînement long (il ne touche que la base, jamais les images). |
| 2026-08-26 | Deux lots ajoutés au plan (noter des crops eBay ; adaptateur DINO), trouvés par la revue adversariale. |
| 2026-08-26 | **Étape 1 jouée.** `EURIO_CACHE_MAX_GB=0` pour la passe — tranché sur mesure : le cache (15 Go) est **sous** son plafond (20 Go), l'éviction n'aurait rien évincé, et son `rglob` coûtait 1,35 s × 1 579 téléchargements ≈ **35 min** pour ~7,4 min de CPU utile. `{"updated": 17658, "skipped": 20, "missing": 0}`. |
| 2026-08-26 | **Étape 2 préparée, non appliquée.** Règle de sélection déterministe (quantiles de la moitié la plus inclinée, `tilt_deg` desc + `id` en bris d'égalité, **aucun aléatoire donc aucune graine**), ancres `2eur_all` exclues (751 écartées). Plan : **60 classes × 5 = 300**, tilt moyen **16,43°** contre 12,75° pour le pool restant. Migration `0014` (`image_assets.eval_corpus`), route `POST /ingest/eval-corpus`, prédicat dans les DEUX collectes. Préflight **`ready=True` avant ET après**, `n_ebay` 2 208 → 1 908 (−300 exactement), aucune classe ne tombe. |
| 2026-08-26 | **Trois mutations jouées, trois tests rouges** (ArcFace, ancres DINO, `_ensure_column` pre-bootstrap) ; sur le **vrai** point d'entrée, la mutation ArcFace fait remonter `n_ebay` à 2 208 — le hold-out fuit. Suite complète : **2373 passed, exit=0** (2358 + 15 neufs). |
| 2026-08-26 | **Étape 2 APPLIQUÉE.** `{"updated": 300, "skipped": 0, "conflict": 0, "missing": 0}`. Préflight recalculé dans un process neuf : `n_ebay` 2296 → 1996 (−300 exactement), `ready=true`. |
| 2026-08-26 | **D9 tranchée et appliquée** : bucket `eval-corpus` + préfixe de clé `eval/<corpus>/`, `assert_role_matches_bucket` en garde, affichage dérivé / entraînement volontairement aveugle. Suite : 2392 passed. |
| 2026-08-26 | **Faille du garde d'espace de labels fermée** : empreinte `mesh_digest` dans chaque scorecard + `--compare A B` qui passe par le garde. |
| 2026-08-26 | ⚠️ **Panne muette trouvée en vérifiant l'étape 2** : l'API `:8042` déjà lancée répondait encore `n_ebay=2296` sur `training-readiness` alors que le fichier réplique qu'elle lit disait 1996. Sa connexion read-only thread-local ne voit pas les pages neuves écrites par `sqlite3_rsync`. **Un `training-readiness` lu sur un serveur lancé avant une écriture ment.** Cf. §Reste-à-faire. |
| 2026-08-26 | **3 bras DINO, mesure v1** (300 frames, règle tilt, banque FPS 893) : 94,0 / 96,3 / 95,3 %. **Aucun écart significatif.** Jeu contaminé à 40,7 % au vendeur. |
| 2026-08-26 | **Règle v2 + banque complète, remesure** : jeu `9bc08e19b83c` (260 frames, 52 classes, 5 au hasard, garde vendeur symétrique), banque 1 813 ancres. vits14 94,2 %, vitb14 96,9 %, **vitl14 98,1 %** — et **`vitl14` bat `vits14`, p = 0,031**. Classement monotone en taille, alors que la v1 inversait vitl14/vitb14. ⚠️ Deux changements simultanés : l'écart avec la v1 n'est PAS attribuable. |
| 2026-08-26 | **Les 4 bras mesurés.** ArcFace (3 epochs) 76,5 % · vits14 94,2 % · vitb14 96,9 % · vitl14 98,1 %. Les trois DINO battent ArcFace à `p < 10⁻¹⁰` — **mais ArcFace n'a pas convergé** (perte 5,42 et descendante). Ce qui est acquis : la chaîne de mesure marche, et ArcFace est 25× plus rapide / 276× plus petit que `vitl14`. |
| 2026-08-26 | **Run ArcFace rapatrié du PC par MinIO**, sha256 identique des deux côtés. 3 epochs en 9 min 28 s sur 13 988 samples → les 40 epochs coûteront ≈ 2 h 06. |
| 2026-08-26 | **La libération du corpus d'éval existe** (`--release`). Il était une porte à sens unique : un crop entré ne pouvait plus revenir au train, donc changer de règle était impossible sans le perdre. 300 ramenés, 0 échec. |
| 2026-08-26 | **Itération de calibration `b55b61b59632` créée** — 3 epochs, `val_source=none`, `centroid_source=train_mean`, graine `20260826`, recette `test-3`, `variant_count=100`. Les cinq clés **relues sur la ligne**. La cohorte `matrice-60c` est **gelée** (`2026-08-26T01:36:48Z`). Le run court valide la plomberie (bake, MinIO, boucle, embeddings, TFLite) — **pas** la notation sur les 300 frames, qui attend le **lot A**. |
| 2026-08-26 | **Cohorte `matrice-60c` (`2e51f2b3d633`) composée** : 60 classes, `ready=true`, 0 block, 0 warn, `n_ebay=1908`. Encore `draft`. |
| 2026-08-26 | **Les 300 crops d'éval tirés de MinIO et décodés : 300/300, tous 224×224** (62-104 Ko). Le chemin de lecture d'évaluation fonctionne. ⏱️ 374 s, soit ~1,25 s/fichier — la taxe `_evict_if_needed` du reste-à-faire, mesurée une fois de plus. |
| 2026-08-26 | **Recadrage d'un crop d'éval : on ne bloque pas** (décision PO). La banque grossit par construction ; figer pour comparer serait contraire au projet. |
| 2026-08-26 | ⚠️ **`:8042` tournait encore l'ANCIEN code** après le déplacement des octets → `500` sur `training-readiness`, car l'ancien `_ebay_training_sources` cherchait `enrichment-crops/eval/…` sans le garde. **Aucun dégât** : la cascade `mark_missing_in_storage` n'a pas pu écrire (base du Mac en lecture seule sous le flip), 300 assets toujours `present`. Après redémarrage : `n_ebay=1996`. |
| 2026-08-26 | ⚠️ **Deux pièges rencontrés, à ne pas re-payer.** (a) `_ensure_column` posé **après** `executescript` est trop tard : `schema.sql` crée l'index PARTIEL sur la colonne et échoue en `no such column` avant le rattrapage — il va en **pre-bootstrap**. (b) **`:8042` ré-écrase la réplique toutes les 120 s** (`client/replica.py::start_autopull`) : un `ALTER` posé à la main dessus disparaît en moins de deux minutes, **sans un mot**. |
