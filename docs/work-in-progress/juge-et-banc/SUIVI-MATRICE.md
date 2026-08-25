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
| D9 | **« Propager côté MinIO » n'a pas de sens technique** : la clé S3 est immuable et sert de jointure partout ; c'est la LIGNE qui porte le rôle. Un tag d'objet reste possible pour l'œil humain, mais rien du pipeline ne le lit — il serait décoratif | 2026-08-26 |

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
| **2** | Prélever 5 crops d'éval × 60 classes, les marquer, les exclure de l'entraînement, propager MinIO + API | Mac | 🟡 **prêt, PAS appliqué** — règle écrite et testée, plan à **60 classes / 300 crops**, migration `0014` + route `/ingest/eval-corpus` + les 2 prédicats écrits et **mutés**. ⛔ Attend le PO : **la colonne au canonique D'ABORD** (cf. [`ETAPE1-2.md`](./ETAPE1-2.md) §Ce qui attend le PO) |
| **3** | **Entraîner ArcFace sur les 60 classes** | **PC** | 🔜 le PO — bloqué par l'application de l'étape 2 |
| **4** | Sous-banque DINO restreinte aux 60 classes | Mac | 🔜 |
| **5** | La matrice — ~8 bras sur les mêmes 300 frames | Mac | 🔜 |

⚠️ **L'étape 2 n'est pas « faite » tant que `0014` n'est pas au canonique.** Le
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
- **`encoder_bench_runs`** manque deux colonnes pour porter la matrice :
  `quantization` et `eval_corpus` (cf. [`MATRICE.md`](./MATRICE.md) §4).
- **`provisional`** est gardé à l'écriture mais son prédicat croit quatre champs
  déclarés par l'appelant — à fermer avant qu'une page ne fonde un choix
  d'encodeur dessus.

## Journal

| Date | Ce qui s'est passé |
|---|---|
| 2026-08-26 | Document ouvert. D1..D6 posées. Quotas mesurés : 5/classe × 60 classes = 300 frames. |
| 2026-08-26 | **Étape 1 jouée.** `EURIO_CACHE_MAX_GB=0` pour la passe — tranché sur mesure : le cache (15 Go) est **sous** son plafond (20 Go), l'éviction n'aurait rien évincé, et son `rglob` coûtait 1,35 s × 1 579 téléchargements ≈ **35 min** pour ~7,4 min de CPU utile. `{"updated": 17658, "skipped": 20, "missing": 0}`. |
| 2026-08-26 | **Étape 2 préparée, non appliquée.** Règle de sélection déterministe (quantiles de la moitié la plus inclinée, `tilt_deg` desc + `id` en bris d'égalité, **aucun aléatoire donc aucune graine**), ancres `2eur_all` exclues (751 écartées). Plan : **60 classes × 5 = 300**, tilt moyen **16,43°** contre 12,75° pour le pool restant. Migration `0014` (`image_assets.eval_corpus`), route `POST /ingest/eval-corpus`, prédicat dans les DEUX collectes. Préflight **`ready=True` avant ET après**, `n_ebay` 2 208 → 1 908 (−300 exactement), aucune classe ne tombe. |
| 2026-08-26 | **Trois mutations jouées, trois tests rouges** (ArcFace, ancres DINO, `_ensure_column` pre-bootstrap) ; sur le **vrai** point d'entrée, la mutation ArcFace fait remonter `n_ebay` à 2 208 — le hold-out fuit. Suite complète : **2373 passed, exit=0** (2358 + 15 neufs). |
| 2026-08-26 | ⚠️ **Deux pièges rencontrés, à ne pas re-payer.** (a) `_ensure_column` posé **après** `executescript` est trop tard : `schema.sql` crée l'index PARTIEL sur la colonne et échoue en `no such column` avant le rattrapage — il va en **pre-bootstrap**. (b) **`:8042` ré-écrase la réplique toutes les 120 s** (`client/replica.py::start_autopull`) : un `ALTER` posé à la main dessus disparaît en moins de deux minutes, **sans un mot**. |
