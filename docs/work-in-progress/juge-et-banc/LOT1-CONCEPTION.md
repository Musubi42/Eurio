# Lot 1 — conception exécutable de la séparation train / val / judge

> **Phase de CONCEPTION, 2026-08-25. Aucun code modifié, aucune migration
> appliquée, rien de commité.** Ce document est l'entrée d'implémentation du
> chantier posé par [`PROBLEME.md`](./PROBLEME.md). Tout chiffre porte sa
> commande ; tout ce qui est estimé porte un ⚠️.
>
> Mesures faites sur `ml/state/eurio.replica.db` (mtime 2026-08-25 01:31, Mac),
> en lecture seule (`sqlite3 -readonly`). Aucune écriture n'a été tentée : le
> devShell pose `EURIO_DB_READONLY=1` (Direction A) et ce document ne le
> contourne pas.

---

## 0. Ce que la mesure a changé par rapport à l'énoncé

Trois résultats non prévus par `PROBLEME.md`, dont deux sont plus graves que le
défaut qu'il décrit. Ils sont en tête parce qu'ils déplacent la priorité.

### 0.a 🔴 Le juge se note contre des prototypes fabriqués AVEC ses propres photos

`PROBLEME.md` décrit une fuite de **sélection de checkpoint**. Il y en a une
seconde, en aval, et elle est totale.

Le benchmark (`evaluate_real_photos.py`) ne compare pas des images à un modèle :
il compare l'embedding d'une photo device aux **centroïdes** du fichier
`embeddings_v1.json`. Ces centroïdes sont produits par
`ml/training/compute_embeddings.py`, dont la stratégie par défaut est écrite
noir sur blanc :

```
ml/training/compute_embeddings.py:88    source = getattr(args, "centroid_source", "auto")
ml/training/compute_embeddings.py:107-109
    if source in ("auto", "val_mean"):
        _split_means("val")
```

et `ml/training/pipeline.py:336-354` (`_compute_embeddings`) **ne passe jamais
`--centroid-source`** → la valeur est `auto` → le centroïde d'une classe est la
**moyenne des embeddings de son split `val`**, c'est-à-dire — puisque
`_override_val_with_eval_real` a remplacé `val/` par les photos device — la
moyenne des photos device de cette classe.

Le benchmark note ensuite **ces mêmes photos** contre ces centroïdes.

Avec 6 photos par classe sur le Mac (`ls ml/datasets/eval_real_norm | wc -l` →
19 dossiers, `find … -type f | wc -l` → 114), **chaque photo de test pèse ~1/6
du centroïde contre lequel elle est notée.** Ce n'est plus un biais de
sélection, c'est une fuite d'étiquette directe.

⚠️ **L'ampleur de la surestimation n'est pas mesurée** — elle ne peut pas l'être
sans le jeu tenu à l'écart que ce chantier construit. C'est le Q6 de
`PROBLEME.md`, et ce constat en augmente l'enjeu attendu.

### 0.b ⛔ Le garde anti-fuite existe, il est appelé, et il garde le mauvais dossier

`evaluate_real_photos.py:12-13` promet : *« Strict hold-out: the photos consumed
here MUST NOT appear in any training set — this is asserted upstream (see
`train_embedder.py::_assert_no_real_photos`) »*.

Or ce garde ne connaît **qu'un seul chemin** :

```
ml/training/train_embedder.py:53    REAL_PHOTOS_DIR = (ML_DIR / "data" / "real_photos").resolve()
ml/training/train_embedder.py:56    def _assert_no_real_photos(path_str, *, role) -> None:
ml/training/train_embedder.py:1124-1125   appelé sur args.dataset (role="train") et args.val_dataset (role="val")
ml/training/prepare_dataset.py:477-480    appelé sur raw_dir et output_dir
```

`ml/data/real_photos/` est le répertoire **legacy** du bench manuel. Le juge
réel est `ml/datasets/eval_real_norm/`, qui n'est mentionné nulle part dans le
garde. Le garde est donc structurellement incapable de voir la fuite : c'est le
motif « un garde posé, testé, et jamais sur le chemin réel » du catalogue
`eurio-verify`. Les deux tests qui l'exercent (`ml/tests/test_benchmark.py:125`,
`:129`) fabriquent des chemins sous `real_photos/` — ils passent, et ne prouvent
rien sur le chemin emprunté.

**Conséquence de conception : le lot qui sort le device de `val` doit AUSSI
élargir ce garde**, sinon la régression revient sans bruit.

### 0.c ✅ La prémisse du brief est vraie, et vérifiée

> *« les photos device sont des FICHIERS, pas des lignes d'`image_assets` ;
> une colonne en base ne les couvre pas »*

Vérifié, et le chiffre est net :

```bash
sqlite3 -readonly ml/state/eurio.replica.db "
SELECT COALESCE(si.source,'(null)') src, COUNT(*)
  FROM image_assets ia LEFT JOIN source_images si ON si.id=ia.source_image_id
 WHERE ia.training_eligible=1 GROUP BY 1 ORDER BY 2 DESC;"
# ebay|2968
# mock|1
```

**2968 des 2969 crops `training_eligible=1` viennent de `source='ebay'`** ; le
969e est un `mock` de test. `source_images.source` ne connaît que quatre valeurs
(`ebay` 20845, `bce` 475, `jo` 71, `mock` 5) — **il n'existe aucune source
`device`**. Les 114 photos de `eval_real_norm/` n'ont pas de ligne en base.

**Donc : deux mécanismes, obligatoirement.** Un marqueur en base pour les crops
eBay ; un changement de **code** (pas de schéma) pour sortir le corpus device du
split `val`. Toute conception qui unifie les deux est fausse.

---

## 1. Inventaire des lecteurs et des écrivains

### 1.a Les deux lecteurs qui décident du train (le point d'appui de D3)

| Voie | Fonction | Fichier:ligne | Prédicat exact |
|---|---|---|---|
| **ArcFace** | `_ebay_training_sources` | `ml/training/iteration_augmentations.py:225` (SQL `:246-257`) | `si.source='ebay'` ∧ `a.eurio_id=?` ∧ **`a.training_eligible=1`** ∧ `a.storage_status='present'` ∧ `(a.face IS NULL OR a.face!='reverse')` |
| **DINO** | `_candidate_crops_for_class` | `ml/training/foundation/anchors.py:824` (SQL `:833-846`) | `eurio_id IN (membres)` ∧ `face='obverse'` ∧ `(denom IS NULL OR denom!='not_2eur')` ∧ `resolution_status IN ('manual','auto_name','auto_phash')` ∧ **`training_eligible=1`** ∧ `storage_status='present'` ∧ `LIMIT 40` |

⚠️ **Correction à apporter au D3 de l'ADR-008 tel que `PROBLEME.md` le cite.**
Les deux voies ne filtrent **pas** sur « la même condition » : elles partagent
**une condition nécessaire commune**, `training_eligible = 1`, et divergent sur
tout le reste. Mesuré :

```bash
sqlite3 -readonly ml/state/eurio.replica.db "
WITH p AS (SELECT ia.id,
  (ia.training_eligible=1 AND ia.storage_status='present' AND si.source='ebay'
   AND (ia.face IS NULL OR ia.face!='reverse')) a,
  (ia.training_eligible=1 AND ia.storage_status='present' AND ia.face='obverse'
   AND (ia.denom IS NULL OR ia.denom!='not_2eur')
   AND ia.resolution_status IN ('manual','auto_name','auto_phash')) d
  FROM image_assets ia LEFT JOIN source_images si ON si.id=ia.source_image_id)
SELECT SUM(a AND d), SUM(a AND NOT d), SUM(d AND NOT a) FROM p;"
# 2888|79|1
```

**79 crops sont dans le pool ArcFace sans être dans le pool DINO**, 1 l'inverse.
Le pool DINO est en outre **borné à 40 par classe**
(`anchors.py:783 MAX_CANDIDATES_PER_CLASS = 40`).

✅ **La conclusion de `PROBLEME.md` tient quand même, et c'est ce qui compte :**
puisque `training_eligible = 1` est une condition **nécessaire** des deux côtés,
un marqueur qui s'ajoute en conjonction à ce prédicat exclut des deux pipelines
à la fois. Mais il doit être **posé explicitement dans les deux requêtes** — il
n'y a pas de point unique en amont qu'on pourrait modifier une seule fois.

### 1.b Les lecteurs dérivés de `real_training_sources`

`real_training_sources` (`ml/training/iteration_augmentations.py:326`) enveloppe
`_ebay_training_sources` + l'avers Numista FS + les réfs BCE/JO. Ses appelants :

| Appelant | Fichier:ligne | Rôle |
|---|---|---|
| Le bake | `ml/training/iteration_augmentations.py:445` | génère les augmentations d'une itération |
| **Le préflight** | `ml/training/foundation/preflight.py:179` (import `:38`) | calcule le *seed* par classe, bloque le run sous `MIN_REAL` |
| Cockpit / galerie | `ml/serving/lab_routes.py:988,998` | affiche les sources réelles d'un coin |
| Route augmentations | `ml/serving/augmentation_routes.py:99,102` | prévisualisation |

⚠️ **Conséquence non triviale : préflight et bake partagent la même collecte
*exprès*** (docstring `preflight.py:19-24`). Un prélèvement qui retire des crops
du pool **fait donc automatiquement baisser le seed vu par le préflight** —
c'est ce qui rend calculable la contrainte du §4 de `PROBLEME.md`, et c'est
aussi ce qui la rend dangereuse si on l'oublie.

### 1.c Le corpus device — les lecteurs, tous par le système de fichiers

| Fichier:ligne | Ce qu'il fait |
|---|---|
| `ml/training/prepare_dataset.py:242` | appelle `_override_val_with_eval_real` en **mode lab** (`skip_train_split`) et **sort** |
| `ml/training/prepare_dataset.py:309` | l'appelle aussi en mode legacy (après le split studio) |
| `ml/training/prepare_dataset.py:312-372` | corps de `_override_val_with_eval_real` : `rmtree` de `val/<class>` puis copie de `eval_real_norm/<eurio_id>/*` ; **`SystemExit` si une classe n'a pas de dossier device** en `class_kind='eurio_id'` |
| `ml/serving/iteration_runner.py:1096` | passe `--real-photos ml/datasets/eval_real_norm` à `evaluate_real_photos.py` — **le juge** |
| `ml/training/compute_embeddings.py:65,107-109` | s'en sert comme **source des centroïdes** (cf. §0.a) |
| `ml/vision/sync_eval_real.py:51` | l'**écrivain** : peuple l'arbre depuis un `debug_pull` |
| `ml/scripts/remap_bench_golden_set.py:83` | renomme les dossiers `eurio_id` → étiquettes de classe |
| `ml/vision/eval_real_snaps.py:41` | outil de diagnostic de similarité, hors pipeline |

Aucun de ces chemins ne passe par SQLite. **Confirmation opérationnelle du §0.c.**

### 1.d Les écrivains de `training_eligible` (là où un défaut de rôle devra se poser)

| Fichier:ligne | Geste |
|---|---|
| `ml/store/decisions.py:219` | décision de review « accepté » → `training_eligible = 1` |
| `ml/store/decisions.py:226` | décision « refusé » → `= 0` |
| `ml/store/crops.py:50` | exclusion manuelle d'un crop du train → `= 0` |
| `ml/store/gate.py:52` | gate `not_2eur` / rejet → `resolution_status='rejected', training_eligible=0` |
| `ml/serving/bench_routes.py:1338-1341` | reflag « needs review » (réversible) |
| `ml/serving/lab_routes.py:2512` | `set_asset_training_eligible` — bascule depuis le front |

⚠️ **Tout crop qui devient `training_eligible=1` après le prélèvement naîtra donc
en rôle par défaut.** C'est voulu (§3.d) mais ça veut dire qu'un prélèvement
figé ne suit pas l'enrichissement — le nœud de **Q3**.

### 1.e Le préflight

`ml/training/foundation/preflight.py` — seed par classe = Numista FS + crops
eBay `training_eligible=1` + réfs BCE/JO ; plancher `MIN_REAL = 10`
(`ml/store/funnel_constants.py:39`), `M_PER_CLASS = 4` (`:51`),
`TRAINING_TARGET = 100` (`:45`). Il ne connaît pas le corpus device et n'a rien
à en connaître.

---

## 2. Le DDL — marquer le rôle des crops eBay

### 2.a Le fait de schéma qui contredit le brief (à lire avant d'écrire la migration)

Le brief énonce : *« toute migration doit être recopiée à l'identique dans
`ml/state/schema.sql` ET déclarée dans le `MIROIR_ATTENDU` de
`ml/tests/test_schema_mirror.py` »*. **C'est vrai pour une migration qui CRÉE une
table ; c'est faux — et le test l'interdit activement — pour une migration qui
fait un `ALTER TABLE … ADD COLUMN` nu.**

Preuve dans le test lui-même (`ml/tests/test_schema_mirror.py:145-157`) : la
migration `0013_dino_prediction_perimee_par_recadrage.sql`, qui est exactement un
`ALTER TABLE image_asset_dino_predictions ADD COLUMN stale_since TEXT`, est
**dans la liste des exclusions**, pas dans `MIROIR_ATTENDU` — parce qu'une
migration `ALTER` nue est **inapplicable sur une base vide**, ce que la
comparaison de miroir exige. Même raison pour 0003/0004/0005/0007.

Le contrat réel a donc **trois branches**, et `test_schema_mirror.py:125`
(`test_toute_migration_neuve_est_declaree_ou_exclue_sciemment`) force à trancher
laquelle :

| Forme de la migration | `schema.sql` | `store/connection.py` | `test_schema_mirror.py` |
|---|---|---|---|
| `CREATE TABLE` / index sur table neuve | miroir **identique** | — | `MIROIR_ATTENDU` |
| `ALTER … ADD COLUMN` nu | colonne **dans le `CREATE TABLE`** | `_ensure_column` obligatoire | **liste `exclues`**, avec motif écrit |

Le `_ensure_column` n'est pas optionnel : c'est lui qui rattrape les bases
locales **antérieures**, et sans lui un index partiel de `schema.sql` échoue en
`no such column` avant que quoi que ce soit d'autre tourne (motif écrit en clair
dans le test, `:152-156`).

Prochain numéro libre : **`0014`** (`ls ml/serving/migrations/` s'arrête à 0013).

### 2.b Option A — colonne `corpus_role` sur `image_assets` ✅ recommandée

C'est le candidat naturel de Q1 : la table que les deux pipelines filtrent déjà,
donc **un seul JOIN de moins à ne pas oublier**.

**`ml/serving/migrations/0014_corpus_role.sql`**

```sql
-- 0014 — le rôle d'un crop dans le protocole d'évaluation (chantier juge-et-banc).
--
-- Contexte : jusqu'ici un crop `training_eligible=1` était, sans autre nuance,
-- une source de train pour ArcFace (iteration_augmentations._ebay_training_sources)
-- ET un candidat exemplaire pour la banque DINO (foundation/anchors.
-- _candidate_crops_for_class). Les deux voies partagent `training_eligible = 1`
-- comme condition NÉCESSAIRE : c'est le seul endroit où un marqueur unique
-- exclut des deux à la fois.
--
-- `corpus_role` ne remplace pas `training_eligible` — il le RAFFINE.
--   training_eligible = 0  → le crop ne sert à rien, quel que soit son rôle.
--   training_eligible = 1  → le rôle dit à QUOI il sert :
--     'train' : apprendre / servir d'exemplaire d'ancre (défaut = l'existant)
--     'val'   : régler un seuil, choisir un checkpoint — jamais juger
--     'judge' : annoncer une performance — n'influence JAMAIS de poids,
--               ni directement (train), ni indirectement (val, ancres,
--               centroïdes, seuils)
--
-- Défaut 'train' : toutes les lignes existantes gardent EXACTEMENT le
-- comportement d'aujourd'hui. La migration est donc un no-op sémantique tant
-- que rien n'écrit 'val'/'judge' — c'est ce qui la rend déployable seule.

ALTER TABLE image_assets
  ADD COLUMN corpus_role TEXT NOT NULL DEFAULT 'train'
             CHECK (corpus_role IN ('train','val','judge'));

-- Index partiel : la question posée est « lesquels sont hors-train ? », soit
-- quelques centaines de lignes sur ~18 700. Un index plein coûterait pour une
-- réponse qui tient dans un mouchoir. (Même raisonnement que 0013.)
CREATE INDEX IF NOT EXISTS idx_image_assets_corpus_role
  ON image_assets(corpus_role)
  WHERE corpus_role != 'train';
```

✅ **Vérifié que SQLite accepte ce DDL** (`ADD COLUMN` avec `NOT NULL DEFAULT`
constant **et** `CHECK`), sur une base jetable du scratchpad :

```bash
sqlite3 t.db "
CREATE TABLE image_assets(id TEXT PRIMARY KEY, training_eligible INTEGER NOT NULL DEFAULT 0);
ALTER TABLE image_assets ADD COLUMN corpus_role TEXT NOT NULL DEFAULT 'train'
  CHECK (corpus_role IN ('train','val','judge'));
INSERT INTO image_assets(id) VALUES('a'); SELECT id, corpus_role FROM image_assets;"
# a|train
sqlite3 t.db "INSERT INTO image_assets(id,corpus_role) VALUES('b','bogus');"
# Error: stepping, CHECK constraint failed: corpus_role IN ('train','val','judge') (19)
```

Le miroir, dans l'ordre :

1. **`ml/state/schema.sql`** — insérer la colonne dans le `CREATE TABLE IF NOT
   EXISTS image_assets` (bloc `:394-…`), juste après `training_eligible`
   (`:425`) / `quality_reason` (`:426`), avec le même commentaire ; et ajouter
   l'index partiel à la suite des autres index de la table.
2. **`ml/store/connection.py`** — ajouter au tuple `_ensure_column` d'`image_assets`
   (`:584-592`) :
   ```python
   ("corpus_role",
    "TEXT NOT NULL DEFAULT 'train' CHECK (corpus_role IN ('train','val','judge'))"),
   ```
3. **`ml/tests/test_schema_mirror.py`** — ajouter
   `"0014_corpus_role.sql"` à la liste **`exclues`** de
   `test_toute_migration_neuve_est_declaree_ou_exclue_sciemment` (`:129-158`),
   **pas** à `MIROIR_ATTENDU`, avec le motif : *ALTER nu, inapplicable sur base
   vide ; la propriété tenue autrement — colonne + index dans `schema.sql`,
   rattrapage par `_ensure_column`, et `test_corpus_role` prouve que les deux
   lecteurs la respectent.*

**Ce que l'option A ne porte pas :** ni la version du prélèvement, ni le critère,
ni la graine, ni la date. C'est-à-dire **rien de ce que Q3 demande**. Voir 2.d.

### 2.c Option B — table dédiée `corpus_assignments`

```sql
CREATE TABLE IF NOT EXISTS corpus_assignments (
  asset_id          TEXT NOT NULL REFERENCES image_assets(id) ON DELETE CASCADE,
  sampling_version  TEXT NOT NULL,
  role              TEXT NOT NULL CHECK (role IN ('val','judge')),
  criterion         TEXT NOT NULL,
  seed              INTEGER,
  assigned_at       TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (asset_id, sampling_version)
);
CREATE INDEX IF NOT EXISTS idx_corpus_assignments_version
  ON corpus_assignments(sampling_version, role);
```

| | Option A (colonne) | Option B (table) |
|---|---|---|
| Miroir | 3 gestes, liste `exclues` | 2 gestes, `MIROIR_ATTENDU` (précédent 0006/0008/0009) |
| Versionnement du prélèvement (Q3) | ❌ absent | ✅ natif (`sampling_version`) |
| Traçabilité critère + graine (Q2) | ❌ absente | ✅ native |
| Coût côté lecteurs | `AND corpus_role='train'` | `AND NOT EXISTS (SELECT 1 FROM corpus_assignments …)` + le choix de la version courante |
| Risque d'oubli d'un lecteur | identique (silencieux des deux côtés) | **plus grand** : un JOIN s'oublie plus facilement qu'un prédicat |

⚠️ **Recommandation : A d'abord, B en complément si Q3 est tranchée « figé +
versionné ».** Les deux se composent bien — `corpus_role` reste la **projection
dénormalisée de la version active**, celle que lisent les deux requêtes chaudes,
et `corpus_assignments` en est le journal. Un test de cohérence les tient
alignés. **Décider seul de faire A+B tout de suite serait décider Q3 : ne pas le
faire.**

### 2.d Q1 formellement

`PROBLEME.md` liste Q1 (*« où marquer le rôle ? »*) comme non tranchée. Ce
document en produit le **dossier technique complet et le DDL vérifié**, pas la
décision. La ratification appartient au PO ; le lot 2 ne démarre pas avant.

---

## 3. La sortie du corpus device du split `val` — changement de code, pas de schéma

### 3.a Le geste minimal

Aujourd'hui, en mode lab (`--skip-train-split`), `prepare_dataset.py` **ne fait
que ça** : écrire le manifeste, appeler `_override_val_with_eval_real`, sortir
(`:236-243`). Retirer l'appel laisse donc `val/` **vide** en mode lab.

Le geste propre n'est pas de supprimer la fonction (elle reste utile en mode
legacy et pour un diagnostic), mais de la **conditionner explicitement** :

- un drapeau `--val-source {device,ebay,none}` sur `prepare_dataset.py`,
  **obligatoire** en mode lab (pas de défaut implicite : c'est exactement
  l'ambiguïté qui a produit le défaut) ;
- `iteration_runner` / `pipeline` passent la valeur retenue par le PO en Q4 ;
- `_override_val_with_eval_real` n'est appelée que pour `device`, et elle
  **journalise en WARNING** que le run est alors non comparable au juge.

### 3.b Le garde qui doit être élargi dans le MÊME lot

Sans ça, la régression revient sans bruit (§0.b) :

- `REAL_PHOTOS_DIR` (`train_embedder.py:53`) devient un **ensemble** :
  `{ml/data/real_photos, ml/datasets/eval_real_norm}` ;
- `_assert_no_real_photos` refuse si le chemin est **sous l'un des deux**, et le
  message nomme lequel ;
- ⚠️ **et ce n'est pas suffisant** : le garde compare des *chemins de dataset*,
  or la fuite passe par une **copie de fichiers** dans `val/`. Le garde doit
  donc aussi être posé **au bon endroit** — un contrôle de contenu
  (`val/` contient-il des fichiers dont le nom porte la marque device ?), ou
  mieux, la sortie du device de `val` rendue **structurelle** en mode lab. Le
  choix est un point d'implémentation du lot 4, pas une question PO.

### 3.c Le troisième point de fuite : les centroïdes (§0.a)

`compute_embeddings.py` en `source="auto"` prend `val` s'il existe, sinon
ArcFace-W. **Si `val` devient vide, le fallback ArcFace-W s'active tout seul** —
c'est déjà écrit (`:114-129`). Le comportement est donc *défini* sans rien
toucher, mais il n'est **pas neutre** : le commentaire `:66-79` explique
longuement pourquoi le val-mean a été préféré à W (W « pointe là où les
embeddings *étaient* » quand la loss ArcFace tombe à 0 ; diagnostic mesuré :
R@1 95,83 % par KNN sur val contre 50 % déployé via W sur les mêmes images).

⚠️ **Sortir le device de `val` retire donc, en cascade, la stratégie de
centroïdes qui avait été adoptée sur mesure.** Ce n'est pas un effet de bord
acceptable en silence : c'est la moitié cachée de Q4.

### 3.d Q4 — les options, et ce que chacune coûte ⚠️ NON TRANCHÉE, PO

`PROBLEME.md` Q4 : *« que devient le split `val` d'ArcFace une fois le device
retiré ? »*. État du code aujourd'hui, qui rend la question **moins ouverte
qu'elle n'en a l'air** :

```
ml/training/train_embedder.py:992-995
    save_now = (
        val_loader is not None and val_metrics["recall@1"] >= best_recall
    ) or (val_loader is None and epoch == args.epochs)
```

**Le « dernier epoch sans val » est déjà implémenté et déjà commenté** (*« When
val is empty, save on the final epoch — loss alone is too noisy a selector »*).
L'option 1 ci-dessous coûte donc zéro ligne dans `train_embedder`.

| Option | Sélection de checkpoint | Centroïdes | Ce que ça coûte |
|---|---|---|---|
| **1. Pas de val** | dernier epoch (déjà codé) | ArcFace-W (fallback déjà codé) | Perte de toute sélection : un run qui sur-apprend n'est plus rattrapé. Et on hérite du défaut W décrit en `compute_embeddings.py:66-79`, celui-là même qui avait motivé le val-mean |
| **2. val = prélèvement eBay** | R@1 sur crops eBay | val-mean sur crops eBay | Ré-arme la sélection, mais **sur une distribution qui n'est pas celle du déploiement** — l'argument exact du code actuel. Et coûte des crops au train (cf. plancher, §4) |
| **3. val = device, judge = eBay** | inchangée | inchangés | Ne corrige **rien** du biais de départage ArcFace ↔ DINO : ArcFace continue de sélectionner sur des photos device, DINO n'a toujours pas d'équivalent. ⛔ Contredit la cible du §3 de `PROBLEME.md` |
| **4. val = device, split en deux** | R@1 sur une moitié device | val-mean sur cette moitié | Garde la distribution de déploiement, coupe la fuite. **Mais** : 114 photos / 19 classes sur le Mac = **6 par classe** → 3/3. ⚠️ Un juge à 3 photos/classe n'a probablement aucun pouvoir statistique — non mesuré |
| **5. Reporter** | statu quo | statu quo | Livrer d'abord le juge-proxy eBay (lots 2-3), mesurer Q6, décider ensuite avec un chiffre |

⚠️ **Aucune de ces options n'est recommandée ici.** Q4 appartient au PO. Ce que
la mesure ajoute au dossier :

- l'option 1 est **gratuite en code** et non gratuite en qualité ;
- l'option 4 est arithmétiquement contrainte par un corpus device dont on ne
  sait même pas où vit la version complète (`PROBLEME.md` §6 : le run du
  2026-08-16 annonce 317 photos / 16 pièces, le Mac en porte 114 / 19 dossiers) ;
- **quelle que soit l'option, §0.a doit être réglé** : le
  `--centroid-source` doit devenir **explicite** dans `pipeline.py`, jamais
  laissé à `auto`. Un défaut implicite qui bascule de `val_mean` à `arcface_W`
  selon qu'un répertoire est vide, c'est le motif « valeur par défaut plausible »
  du catalogue `eurio-verify`.

### 3.e Ce que je NE tranche pas

**Q2** (critère de sélection du juge-proxy), **Q3** (figé ou rejouable), **Q4**
(sort du split val), **Q5** (un juge par tâche) restent au PO. Ce que la mesure
apporte pour **Q2**, en revanche, est décisif et n'était pas au dossier :

```bash
# combien de crops training_eligible sont DÉJÀ des ancres de la banque servie ?
sqlite3 -readonly ml/state/eurio.replica.db "
SELECT COUNT(*) FROM image_assets ia
 WHERE ia.training_eligible=1
   AND ia.id IN (SELECT asset_id FROM dino_class_references
                  WHERE asset_id IS NOT NULL AND anchors_kind='2eur_all');"
# 1391
sqlite3 -readonly ml/state/eurio.replica.db "SELECT COUNT(*) FROM image_assets WHERE training_eligible=1;"
# 2969
```

🔴 **1391 / 2969 = 46,8 % du pool éligible est déjà une ancre de la banque
`2eur_all` servie.** Un tirage **aléatoire** dans ce pool — la piste « neutre »
de Q2 — a donc près d'une chance sur deux de prélever une ligne de la banque,
c'est-à-dire de mesurer une similarité de 1,0 avec elle-même (fuite de banque,
`eurio-banque` §3). **Le tirage aléatoire n'est pas neutre ici : il doit au
minimum exclure `dino_class_references.asset_id`.** Ce n'est pas trancher Q2,
c'est en retirer une option qui paraissait sûre.

Et pour la piste « critère de qualité indépendant » de Q2 :

```bash
sqlite3 -readonly ml/state/eurio.replica.db "
SELECT COUNT(*) te, SUM(quality_score IS NOT NULL) qs,
       SUM(tilt_deg IS NOT NULL) tilt, SUM(axis_ratio IS NOT NULL) ar
  FROM image_assets WHERE training_eligible=1;"
# 2969|262|637|637
```

⚠️ **`quality_score` n'est renseigné que sur 262 / 2969 crops (8,8 %) ;
`tilt_deg` / `axis_ratio` sur 637 (21,5 %).** Stratifier sur ces colonnes
aujourd'hui, c'est stratifier sur un cinquième du pool — et le cinquième qui a
été mesuré n'est pas un échantillon au hasard du reste. **Cette piste de Q2
demande un backfill préalable, ou elle est indisponible.** Non mesuré : si le
backfill (`scripts/crop_tilt_backfill_db.py`) est rejouable à coût raisonnable.

---

## 4. Le plancher des 15 — reproduit, et sa contrainte réelle

Requête de `PROBLEME.md` §4, rejouée le **2026-08-25** sur la réplique du Mac :

```bash
sqlite3 -readonly ml/state/eurio.replica.db "
with pc as (
  select coalesce(c.design_group_id, c.eurio_id) cid,
         sum(case when ia.training_eligible=1 and s.source='ebay' then 1 else 0 end) n
    from coins c
    left join image_assets ia on ia.eurio_id = c.eurio_id
    left join source_images s on s.id = ia.source_image_id
   group by 1)
select 'ge15', count(*) from pc where n >= 15
union all select 'ge10', count(*) from pc where n>=10
union all select '10_14', count(*) from pc where n between 10 and 14
union all select 'ge1',  count(*) from pc where n>=1;"
# ge15|60      ge10|68      10_14|8      ge1|250
```

✅ Reproduit à l'identique (60 / 8). `MIN_REAL = 10` confirmé
(`ml/store/funnel_constants.py:39`).

**La contrainte à encoder, telle qu'elle doit s'écrire :** le prélèvement d'une
classe est autorisé **si et seulement si** `n_restant_apres_prelevement >=
MIN_REAL`, pas si `n_avant >= 15`. Avec `MIN_REAL = 10` et un prélèvement de 5,
les deux formulations coïncident numériquement aujourd'hui — mais elles
divergent dès que l'un des trois chiffres bouge, et **c'est la seconde qui est
juste**. Encoder « 15 » en dur reproduirait le défaut que ce chantier corrige :
un chiffre sans sa raison.

⚠️ **Le seed du préflight n'est PAS le compte de crops eBay.** Il additionne
l'avers Numista FS + les crops eBay + les réfs BCE/JO
(`preflight.py:26-28`, `iteration_augmentations.py:326-341`). La garde doit donc
se calculer **par `real_training_sources`**, pas par la requête SQL ci-dessus,
sous peine de bloquer ou d'autoriser à côté. Non mesuré : l'écart entre les deux
comptes sur les 68 classes de `rich10-68c`.

---

## 5. Baseline de tests — mesurée AVANT toute modification

```bash
cd ml && ./.venv/bin/python -m pytest tests -q -p no:randomly
```

**`2258 passed, 40 warnings in 107.93s` — 0 échec, exit 0.**
Mac, 2026-08-25, sous devShell (`EURIO_DB_PATH=…/eurio.replica.db`,
`EURIO_DB_READONLY=1`).

⚠️ Écart à noter avec `eurio-banque` §5(a), qui cite *1878 passed* au 2026-08-20
15:39 : la suite a **grossi de 380 tests en cinq jours**. C'est la baseline
ci-dessus qui fait foi pour ce chantier, pas celle de la skill.

**Tout rouge apparu après cette ligne appartient au chantier.** Les 40 warnings
sont préexistants (`DeprecationWarning` sur `datetime.utcnow()` dans
`training/pipeline.py:501,529` et sur `EURIO_DB` déprécié dans
`shared/storage/cascade.py:63`) — ne pas les compter comme un signal.

---

## 6. Découpage en lots, avec critère de vérification observable

> Ordre imposé par une seule règle : **rien qui change un chiffre de benchmark
> avant que le juge propre existe.** Les lots 2 et 3 sont donc du schéma et de
> l'outillage inertes ; le premier changement de comportement est au lot 4.

### Lot 2 — le marqueur de rôle (schéma seul, inerte)

Migration `0014`, miroir `schema.sql`, `_ensure_column`, entrée dans la liste
`exclues` du test de miroir. **Aucun lecteur modifié.**

- ✅ `cd ml && ./.venv/bin/python -m pytest tests/test_schema_mirror.py -q` →
  `passed`, et le test `test_toute_migration_neuve_est_declaree_ou_exclue_sciemment`
  ne signale plus `0014` comme non classée.
- ✅ Base neuve née avec la colonne :
  ```bash
  cd ml && rm -f /tmp/neuve.db && EURIO_DB_PATH=/tmp/neuve.db EURIO_DB_READONLY=0 \
    ./.venv/bin/python -c "
  import sys; sys.path.insert(0,'.'); from store import Store, resolve_db_path
  s=Store(resolve_db_path('/tmp/neuve.db'))
  print([r[1] for r in s._connection().execute('PRAGMA table_info(image_assets)') if r[1]=='corpus_role'])"
  # ['corpus_role']
  ```
- ✅ Rattrapage d'une base ANTÉRIEURE : même commande sur une copie
  `VACUUM INTO` d'une base sans la colonne → la colonne apparaît (c'est
  `_ensure_column` qui est prouvé, pas `schema.sql`).
- ✅ Mutation : retirer l'entrée `_ensure_column` **doit** faire rougir le test
  de rattrapage. Sans cette passe, le lot ne prouve rien (`eurio-verify`).
- ✅ Suite complète toujours à **2258 passed**.
- ⛔ **Aucune migration appliquée au canonique dans ce lot.** Le déploiement VPS
  est un geste séparé, sous `eurio-vps-deploy`.

### Lot 3 — les deux lecteurs honorent le rôle (comportement inchangé par construction)

Ajouter `AND corpus_role = 'train'` dans les deux requêtes de §1.a.
Comme **100 % des lignes valent `'train'`**, la sortie est identique.

- ✅ Invariance mesurée avant/après sur la réplique :
  ```bash
  cd ml && ./.venv/bin/python -c "
  import sys; sys.path.insert(0,'.'); from store import Store, resolve_db_path
  from training.iteration_augmentations import real_training_sources
  s=Store(resolve_db_path('state/eurio.replica.db'))
  print(sum(real_training_sources(r[0], r[1], s).n_ebay
            for r in s._connection().execute(
              'SELECT eurio_id, numista_id FROM coins WHERE numista_id IS NOT NULL')))"
  # même total avant et après le patch — attendu 2968 ⚠️ (estimé depuis §0.c ;
  # le total réel dépend des crops absents du cache local, à relever au lot 3)
  ```
- ✅ Test neuf `tests/test_corpus_role.py` : une base en mémoire avec 3 crops
  (`train`, `val`, `judge`) → `_ebay_training_sources` en rend **1**,
  `_candidate_crops_for_class` en rend **1**.
- ✅ Mutation : retirer le prédicat de **l'une** des deux requêtes → le test
  correspondant rougit. Les deux mutations doivent être jouées séparément
  (le piège « on ferme un chemin, l'autre reste ouvert », `eurio-banque` §5(b)).
- ✅ Suite complète : **2258 + n** passed, 0 failed.

### Lot 4 — sortir le device du split `val` + élargir le garde + expliciter les centroïdes

⚠️ **Ce lot ne démarre pas avant que Q4 soit tranchée** (§3.d).

- ✅ `--val-source` obligatoire en mode lab : lancer `prepare_dataset.py
  --skip-train-split` **sans** le drapeau → `SystemExit` avec message nommant les
  trois valeurs. (Vérifier le code de sortie **sans pipe** — `eurio-verify`.)
- ✅ `--val-source none` → `ls <out>/val | wc -l` = `0`.
- ✅ `--val-source device` → warning « run non comparable au juge » dans la
  sortie, et le compte de photos device inchangé.
- ✅ Garde élargi : `_assert_no_real_photos('<repo>/ml/datasets/eval_real_norm',
  role='val')` **doit** lever ; le test le prouve, et la mutation (retirer le
  second chemin de l'ensemble) le fait rougir.
- ✅ `pipeline.py` passe désormais `--centroid-source` **explicitement** ;
  `grep -n "centroid-source" ml/training/pipeline.py` rend une ligne (un drapeau
  qui n'apparaît qu'une fois dans un fichier ne décide de rien —
  `eurio-verify`, S2).
- ✅ Sur un run lab de bout en bout, la sortie de `compute_embeddings` liste
  `arcface_W` (ou `ebay_val_mean`) pour **toutes** les classes, plus jamais
  `val_mean(n=6)` sur des photos device.

### Lot 5 — le prélèvement (⚠️ bloqué sur Q2 et Q3)

Script `scripts/prelever_juge_proxy.py`, `--dry-run` par défaut, écriture par la
voie canonique uniquement (`eurio-data-writes` : jamais `ml/state/*.db` en
direct sous flip ; un push raté = 502, pas 200).

- ✅ `--dry-run` sans `--execute` **n'écrit rien** : compte de
  `corpus_role != 'train'` inchangé avant/après.
- ✅ Garde de plancher : une classe dont le seed **après** prélèvement tomberait
  sous `MIN_REAL` est refusée nommément, et le rapport dit combien de classes
  sont dans ce cas (attendu ⚠️ ~8 sur `rich10-68c`, cf. §4).
- ✅ Aucun asset prélevé n'est dans `dino_class_references` (§3.e) : la requête
  d'intersection rend **0**.
- ✅ Rejouabilité : deux exécutions avec la même graine produisent le même
  ensemble d'`asset_id` (diff vide).

### Lot 6 — mesurer Q6

Rejouer le run du 2026-08-16 contre le juge propre et lire l'écart avec 92,4 %.
Critère : une ligne `benchmark_runs` neuve dont le `top_confusions_json` ne
pointe plus vers un chemin partagé avec `val/`, et l'écart publié.

---

## 7. Ce que je n'ai pas pu vérifier

- **Où vit la version complète du corpus device.** Le Mac en porte 114 photos /
  19 dossiers ; le benchmark du 2026-08-16 en annonce 317 / 16 pièces
  (`PROBLEME.md` §6). Je n'ai pas accès à la machine qui portait le pull complet.
  **Toute mesure de Q6 est suspendue à ce point.**
- **L'ampleur réelle du biais** (Q6) — non mesurable avant la séparation.
- **Le pouvoir statistique d'un juge à 3 photos/classe** (option 4 de Q4) — non
  mesuré, et probablement nul ⚠️.
- **Le coût d'un backfill `quality_score` / `tilt_deg`** sur les ~78 % de crops
  non mesurés (§3.e).
- **L'écart entre « seed préflight » et « compte de crops eBay »** sur les 68
  classes de `rich10-68c` (§4) — la garde de plancher doit se calculer sur le
  premier, je n'ai chiffré que le second.
- **L'état du canonique VPS.** Toutes les mesures sont sur la réplique locale du
  2026-08-25 01:31 ; la review avance en continu, donc les comptes bougeront
  (`eurio-banque` §2 : *« ces comptes sont ceux d'une minute »*).
- **Le comportement réel de `compute_embeddings` avec `val/` vide** — le
  fallback ArcFace-W est lu dans le code, pas exécuté (il demande un checkpoint).

---

## 8. En attente d'une décision du PO

| # | Question | Ce que ce document y ajoute |
|---|---|---|
| **Q1** | Où marquer le rôle ? | DDL vérifié pour la colonne (option A) et pour la table (option B) ; le contrat de miroir réel est en 3 branches, pas 2 (§2.a) |
| **Q2** | Critère du juge-proxy | 🔴 **46,8 % du pool est déjà une ancre** → le tirage aléatoire n'est pas neutre. `quality_score` couvre 8,8 % du pool → piste indisponible sans backfill |
| **Q3** | Prélèvement figé ou rejouable | Détermine A seul ou A+B ; les écrivains de `training_eligible` (§1.d) font naître tout nouveau crop en `'train'` |
| **Q4** | Sort du split `val` | 5 options chiffrées ; l'option « dernier epoch » est **déjà codée** ; la cascade sur les centroïdes (§0.a) est la moitié cachée de la question |
| **Q5** | Un juge par tâche | Non instruit ici |
| **Q6** | Combien vaut le biais | Suspendu à la localisation du corpus device complet (§7) |
