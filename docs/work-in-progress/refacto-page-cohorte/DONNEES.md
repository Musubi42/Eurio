# Le flot de données — ce qui entre, ce qui sort, où c'est rangé

> État constaté le 2026-08-18. But de ce fichier : s'assurer qu'aucune donnée
> traitée ne disparaît, et que le rangement est rationnel avant de refaire les écrans.

## Les cinq transformations

Chaque étape prend un artefact et en produit un autre. Le nom de l'artefact est
ce qui doit apparaître à l'écran — pas le nom de la table.

### 1 · Classe ← référentiel

**Entre** : le référentiel des pièces (Numista, BCE, JO).
**Sort** : une classe = un dessin + la liste des pièces qui le partagent.
**Clé** : `design_group_id` si la pièce appartient à une ère (standards),
sinon `eurio_id` (commémoratives).

⚠️ **Piège mesuré** : la vue sourcing regroupe les millésimes d'une ère sur une
seule ligne. Sur `giga-40-vague1`, **7 pièces n'y apparaissent pas** (les « 2ᵉ
carte » : DE 2008, FR 2007, IT 2008, AT 2008, ES 2007, BE 2007 et 2009). Elles
**sont bien rattachées à leur classe** et seront entraînées — c'est un défaut
d'affichage, pas de données. Mais tel quel, on croit avoir perdu des pièces.

### 2 · Matière ← eBay

**Entre** : une classe qui manque de photos.
**Sort** : des annonces retenues, puis des images téléchargées.
**Origine** : eBay Browse API.

⚠️ **La découverte se fait par PAYS entier, jamais par pièce.** Viser une pièce
néerlandaise ramène tout le 2 € néerlandais. C'est un gain (les sœurs sont
nourries au passage) mais l'écran doit le dire, sinon les compteurs paraissent
incohérents.

⚠️ **Fuite mesurée** : sur cette cohorte, **56 crops sont partis sur 37 pièces
sœurs hors cohorte** (ex. 4 crops du Bleuet de France atterris sur sa version
*colorée*). Ces photos existent et n'entraîneront rien. À traiter : soit on élargit
la classe, soit on les récupère, soit on l'assume — mais on l'affiche.

### 3 · Crops ← détection

**Entre** : les images téléchargées.
**Sort** : des crops candidats.
**Comment** : détection (YOLO + Hough + census) puis **filtre anti-fragment**
(probe DINO, seuil τ=0.55) qui écarte les fragments, capsules, emballages.

⚠️ **Piège coûteux, corrigé le 2026-08-18** : sur les bimétal, la détection
accroche le motif central, le crop sort trop serré, le filtre le jette → la photo
repart en « zéro crop ». Une **passe de secours** existe (`vision/score_recover.py`,
activée par `EURIO_CENSUS_RECOVER=1`) ; le bouton de recrop de la page ne la
posait pas. Mesuré à seuil identique : `fr-2010-degaulle` **0 → 144 crops** sur
193 photos ; `cy-2008` 0→46/60 ; `de-2009-saarland` 0→46/60.

**Réservoir restant** : **4 486 images téléchargées n'ont jamais donné de crop**
sur cette cohorte. La passe de secours n'a été exploitée que sur 11 pièces.

### 4 · Photos validées ← décision

**Entre** : des crops candidats.
**Sort** : les photos qui entrent à l'entraînement.
**Comment**, par ordre de préférence :

1. **auto-résolu** (phash, DINO) — sans intervention
2. **single** — une photo, un verdict
3. **lot** — une planche à plusieurs pièces
4. **rejetés à récupérer** — recours quand le reste est à sec

Une photo compte si elle est **retenue ET face avers**. Un crop passé en *revers*
est accepté puis **écarté du bake en silence** (1 seul cas sur cette cohorte,
mais le piège est réel).

⚠️ **33 crops sont bloqués hors file** : ni tranchés, ni visibles en review.
Invisibles = jamais traités. À faire ressortir.

### 5 · Modèle ← entraînement

**Entre** : les photos validées de toutes les classes de la cohorte.
**Sort** : une itération (modèle + artefacts) et sa mesure.
**Étapes** : bake (augmentation vers la cible) → ArcFace → benchmark.

Le bake tire aussi les **sœurs de même dessin hors cohorte** — voulu, mais à
afficher : sur un run passé, 27 pièces demandées → 61 bakées.

## Où c'est rangé

| Donnée | Stockage | Autorité |
|---|---|---|
| Référentiel, classes, crops, décisions de review, cohortes, itérations | `eurio.db` (SQLite WAL) sur le **VPS** | ✅ **le canonique** |
| Images (brutes, crops, artefacts de modèle) | MinIO (`eurio-s3.musubi.dev`) | ✅ canonique |
| Réplique de lecture | `eurio.replica.db` sur Mac / PC | copie, **jusqu'à 120 s de retard** |
| État opérationnel local (jobs, progression) | `eurio.local.db` sur la machine | local, jamais poussé |
| Calcul (bake, entraînement, artefacts) | disque de la machine qui calcule | local, ne voyage pas |
| Projection prod | Supabase | lecture seule, pour l'app |

**Règle** : Mac et PC **lisent une réplique** et **écrivent au canonique** par HTTP.
Le calcul reste local à la machine qui calcule.

⚠️ **Conséquence UX mesurée** : un compteur lu sur la réplique locale accuse
jusqu'à **2 minutes** de retard sur les décisions de review — qui, elles, partent
directement au canonique. C'est ce qui donne l'impression d'une barre figée.
Le compteur d'une classe doit se lire **au canonique**
(`GET /lab/cohorts/{id}/training-crops`, mesuré : 68 Ko compressés, 0,29 s ;
écart avec le préflight local sur les 40 classes : **0**).

## Ce qu'il faut vérifier avant de refaire les écrans

1. **Aucune donnée traitée ne disparaît.** Les 33 crops hors file et les 56 crops
   partis sur des sœurs sont deux fuites connues. Y en a-t-il d'autres ?
2. **Un seul endroit dit la vérité par notion.** Aujourd'hui « combien de photos
   validées » se lit à trois endroits qui ne donnent pas toujours le même chiffre.
3. **Les seuils sortent du code** (cf. `SEUILS.md`).
4. **Les tables abandonnées et colonnes jamais alimentées** — un inventaire existe
   déjà (`docs/architecture/dette-de-stockage.md`). À reprendre ici avant de
   figer le nouveau schéma.
