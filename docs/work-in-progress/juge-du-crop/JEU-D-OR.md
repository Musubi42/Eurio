# Le jeu d'or — 60 ellipses, et comment on les obtient

> **La requête ci-dessous a été exécutée le 2026-08-27 : elle rend exactement 60
> lignes, 15 par strate, 8 acceptés / 7 rejetés partout.**

## Deux pièges à connaître avant de lire la requête

### 1. `tilt_deg` est tronqué par le bas à 14,07°

`ml/vision/crop_detectors.py:328` pose `_TILT_TRIVIAL = 0.97`, et `:462` refuse
la confiance aux quasi-cercles :

```python
if axis_ratio >= _TILT_TRIVIAL:
    reasons.append(f"too_circular:{axis_ratio:.3f}")   # → trustworthy = False
```

Or `tilt_deg = degrees(acos(axis_ratio))`, et `acos(0,97) = 14,0699°` —
**exactement le minimum observé en base**. Donc :

> `tilt_trustworthy = 1` ⟺ `tilt_deg ≥ 14,07°`

**Chercher une pièce « de face » dans cette colonne est une contradiction
logique.** La garde elle-même est juste (ajuster une ellipse sur un quasi-cercle
rend l'angle numériquement instable) ; c'est la colonne qui est inutilisable pour
cet usage.

**Critère de remplacement : `axis_ratio ≥ 0,97`, sans passer par
`tilt_trustworthy`** — 9 422 assets, le complément exact de la population
tronquée.

### 2. Les deux tiers des rejets ne parlent pas du crop

| motif | n | parle du cadrage ? |
|---|---:|---|
| `face_reverse` | 2 636 | ❌ mauvaise face |
| `not_2eur` | 2 042 | ❌ mauvaise dénomination |
| `rejected_in_review` | 1 461 | ✅ |
| `consensus_reject` | 97 | ✅ |

**4 678 des 6 299 rejets ne portent aucune information de cadrage** et doivent
être exclus du vivier « rejeté », sans quoi le jeu d'or apprend à détecter des
revers.

## Les strates, justifiées par le parc

| strate | définition | vivier accept | vivier reject |
|---|---|---:|---:|
| **S1 facile** | 1 crop, `listing_kind='single'`, `axis_ratio ≥ 0,97` | 1 224 | 337 |
| **S2 capsule** | marqueur `proof` / `blister` / `PCGS|NGC` / `belle épreuve` | 176 | **58** |
| **S3 multi** | `n_crops_detected ≥ 2` ou `lot` ou `coffret` | 1 240 | 651 |
| **S4 oblique** | `tilt_trustworthy=1` et `tilt_deg ≥ 20°` | 271 | 274 |

⚠️ **Le mot « capsule » n'existe pas dans le parc** (3 occurrences dans les
titres). S2 se définit par le **conditionnement** — c'est lui qui produit le
reflet spéculaire et le halo de plastique.

⚠️ **Il n'existe aucune colonne d'uniformité du fond.** S1 s'en approche par
proxy ; c'est la **confirmation de strate par le PO à l'annotation** qui la rend
honnête.

## Le tirage

Clé : `substr(si.sha256 || ia.id, -8)`. **`image_assets.sha256` est NULL sur les
20 375 lignes** — inutilisable ; `source_images.sha256` est peuplé sur
21 608/23 056. Reproductible à l'octet, sans `random()`.

⚠️ **Correction du 2026-08-28 — le `sha256` n'entre pas dans la clé.** Mesuré :
`length(image_assets.id) = 32` sur les 20 375 lignes, `length(sha256) = 64` sur
les 21 608 peuplées. Les **8 derniers caractères** de la concaténation tombent
donc *entièrement* dans l'id : `substr(si.sha256 || ia.id, -8)` **est**
`substr(ia.id, -8)`.

```sql
SELECT length(id), COUNT(*) FROM image_assets GROUP BY 1;                    -- 32 | 20375
SELECT length(sha256), COUNT(*) FROM source_images WHERE sha256 IS NOT NULL
  GROUP BY 1;                                                                -- 64 | 21608
```

Ce n'est **pas un défaut** : `image_assets.id` est un uuid4, le tirage reste
uniforme, reproductible, et il désambiguïse bien les crops frères d'un même raw
— c'est la seule des deux colonnes qui le peut. Mais la phrase « la
concaténation … » laissait croire que le hachage du raw pesait sur le tirage :
il n'y pèse pas. Verrouillé par
`ml/tests/test_gold_crop_sample.py::test_la_cle_de_tirage_ne_doit_rien_au_sha256_du_raw`.

Pour un second tirage indépendant (départage d'égalité) : changer l'offset,
`substr(..., -16, 8)` — qui tombe lui aussi dans l'id (caractères 81 à 88 sur
96), donc reste une tranche indépendante de la même source d'aléa.

```sql
-- Jeu d'or crop v1 — 60 images, 4 strates × 15, 8 acceptés / 7 rejetés.
-- Base : ml/state/eurio.replica.db, ouverte en file:...?mode=ro
WITH base AS (
  SELECT
    ia.id AS asset_id, si.id AS source_image_id, si.source, si.storage_path AS raw_path,
    si.width, si.height, ia.bbox_json,
    ia.tilt_deg, ia.axis_ratio, ia.tilt_trustworthy,
    si.n_crops_detected, si.is_lot_suspected,
    CASE WHEN ia.resolution_status='manual' THEN 'accept' ELSE 'reject' END AS verdict,
    ia.quality_reason,
    MAX(COALESCE(lts.is_lot,0))         AS is_lot,
    MAX(COALESCE(lts.listing_kind,'?')) AS listing_kind,
    MAX(CASE WHEN lts.rejected_markers_json LIKE '%proof%' THEN 1 ELSE 0 END) AS mk_proof,
    MAX(CASE WHEN lower(COALESCE(si.listing_title,'')) LIKE '%blister%'
               OR lower(COALESCE(si.listing_title,'')) LIKE '%capsule%'
               OR lower(COALESCE(si.listing_title,'')) LIKE '%proof%'
               OR lower(COALESCE(si.listing_title,'')) LIKE '%belle epreuve%'
               OR lower(COALESCE(si.listing_title,'')) LIKE '%pcgs%'
               OR lower(COALESCE(si.listing_title,'')) LIKE '%ngc%'
             THEN 1 ELSE 0 END)         AS mk_capsule,
    substr(si.sha256 || ia.id, -8)      AS draw_key
  FROM image_assets ia
  JOIN source_images si              ON si.id = ia.source_image_id
  LEFT JOIN listing_text_signals lts ON lts.source_image_id = si.id
  WHERE ia.resolution_status IN ('manual','rejected')
    AND si.storage_status = 'present'
    AND si.storage_path IS NOT NULL
    AND si.sha256       IS NOT NULL
    AND ia.bbox_json    IS NOT NULL
    -- un rejet « mauvaise face / mauvaise pièce » ne dit RIEN du crop
    AND (ia.resolution_status = 'manual'
         OR COALESCE(ia.quality_reason,'') NOT IN ('face_reverse','not_2eur'))
  GROUP BY ia.id
),
strat AS (
  SELECT base.*,
    CASE
      WHEN n_crops_detected >= 2 OR is_lot = 1 OR is_lot_suspected = 1
           OR listing_kind IN ('lot','coffret')      THEN 'S3_multi'
      WHEN tilt_trustworthy = 1 AND tilt_deg >= 20.0 THEN 'S4_oblique'
      WHEN mk_capsule = 1 OR mk_proof = 1            THEN 'S2_capsule'
      -- « quasi de face » : axis_ratio, JAMAIS tilt_deg (tronqué à 14,07°)
      WHEN n_crops_detected = 1 AND axis_ratio >= 0.97
           AND listing_kind = 'single'               THEN 'S1_facile'
      ELSE 'S0_hors_strate'
    END AS strate
  FROM base
),
ranked AS (
  SELECT strat.*,
         ROW_NUMBER() OVER (PARTITION BY strate, verdict
                            ORDER BY draw_key, asset_id) AS rn
  FROM strat WHERE strate <> 'S0_hors_strate'
)
SELECT strate, verdict, asset_id, source_image_id, source, raw_path,
       width, height, bbox_json,
       ROUND(tilt_deg,1) AS tilt_deg, ROUND(axis_ratio,3) AS axis_ratio,
       n_crops_detected, listing_kind, quality_reason
FROM ranked
WHERE (verdict='accept' AND rn <= 8) OR (verdict='reject' AND rn <= 7)
ORDER BY strate, verdict, rn;
```

**Le 8/7 accept/reject n'est pas cosmétique** : c'est ce qui permet d'exécuter
RE-4 — vérifier que le juge prédit le verdict humain au lieu de se contenter
d'être géométriquement cohérent.

**Réserve : 6 images par strate** (`rn` 9-11 côté accept, 8-10 côté reject) pour
remplacer un cas déclaré indécidable sans retirer le tirage — soit **24 au
total**. *(Cette ligne annonçait « 8 par strate » ; le détail entre parenthèses
en donne 6, et c'est lui qui a été implémenté. Corrigé le 2026-08-28.)*

## L'outil d'annotation

### L'éditeur de review ne convient pas — mesuré

**Il ne trace qu'un CERCLE.** Le composant s'appelle littéralement
`CircleCropEditor.vue` : une seule poignée à `(cx + r, cy)`, `r = hypot(...)`,
aucune rotation, aucun second axe. Le payload est `{cx, cy, r}`
(`crop_edit_api.py`), et le stockage l'interdit aussi —
`bbox = {x: cx-r, y: cy-r, w: 2r, h: 2r}`.

Confirmation par la donnée, sans lire le code :

```sql
SELECT COUNT(*) n,
       SUM(ABS(json_extract(bbox_json,'$.w') - json_extract(bbox_json,'$.h')) < 0.01) carres
FROM image_assets WHERE detection_method LIKE 'manual%';
-- 2926 | 2926
```

**Les 2 926 recadrages manuels sont des carrés parfaits. Il n'existe pas une
seule ellipse humaine en base.**

Coût d'un passage à l'ellipse : ~10-12 fichiers, 500-700 lignes, une migration,
une modification de `_crop_mask_resize_float`, et un piège maison — le nouveau
champ doit entrer dans la liste explicite d'`emit_field_event`, faute de quoi la
géométrie **ne se synchronise pas au VPS, en silence**.

→ **Rejeté.** On ne fait pas 600 lignes sur le chemin de production pour 60
annotations. C'est la dette que R0 interdit.

### L'outil jetable — écrit le 2026-08-28

`ml/bench/gold_crop/` : `sample.py` produit le manifeste et copie les raws,
`annotate/serve.py` sert l'outil et écrit `gold.json`.

```bash
cd ml
python -m bench.gold_crop.sample   --out state/gold_crop/v1   # 60 + 24 réserve
python -m bench.gold_crop.annotate.serve --out state/gold_crop/v1
# puis http://127.0.0.1:8765 ; passe 2 : --passe 2 --n-double 10
```

Mesuré au premier lancement : **84/84 raws déjà en cache** (zéro réseau, 1,4 s)
et **84/84 pré-remplissages `measure_tilt` réussis**. `gold.json` est écrit à
chaque validation, atomiquement (`.tmp` puis `replace`) : une séance de 40
minutes ne se refait pas.

Écart assumé sur le geste : **3 poignées, pas 4.** La poignée du demi-grand axe
porte *aussi* la rotation (elle est à l'extrémité de cet axe : la traîner
définit `a` et `θ` d'un seul geste). Une quatrième poignée de rotation serait
redondante et coûterait un aller-retour de plus par image.

L'ellipse pointillée à `0,92·a` matérialise la bande du Boundary IoU
(`d = 0,08·a`) : l'annotateur voit ce que le juge regardera.

### Ce qui l'a fait préférer

Page HTML + `<canvas>`/`<svg>`, servie en local, qui lit un `manifest.json`
produit par la requête ci-dessus et écrit un `gold.json`.

Ce qui rend le coût faible : **tout le matériel existe déjà.**

- **Les 60 raws sont en cache disque.** Vérifié : 200/200 chemins présents dans
  `~/.cache/eurio/enrichment-raws` (35 352 fichiers, 14 Go). Zéro réseau, zéro
  MinIO, zéro présigné.
- `CircleCropEditor.vue` fournit le patron de calage pixel-exact
  (`<svg viewBox>` calé sur la box rendue + `ResizeObserver`) — à recopier.
- **`measure_tilt` pré-remplit l'ellipse** : il rend déjà
  `{cx, cy, major, minor, angle}` en pixels natifs. Le PO **corrige une
  proposition**, il ne part pas d'une page blanche.

Geste : 4 poignées (centre, demi-grand axe, demi-petit axe, rotation) + molette
+ `Entrée` pour valider. Plus deux cases qui ne coûtent rien :

1. **confirmation de strate** — rend la stratification robuste aux proxys
   textuels et à l'ambiguïté de `axis_ratio ≥ 0,97` ;
2. **« ellipse indécidable »** — pièce coupée par le bord du raw, floue, masquée.
   Un cas non annotable sort explicitement, il ne s'annote pas au jugé.

| poste | temps |
|---|---|
| écriture de l'outil (~250 lignes) + export du manifest | 1,5 – 2 h |
| annotation PO, 60 images à ~40 s | **~40 min** |
| double passe sur 10 images (reproductibilité, cf. `JUGE.md`) | +10 min |

⚠️ **Les 40 s/image sont SUPPOSÉS.** À valider sur les 5 premières ; au-delà de
90 s/image, c'est que le pré-remplissage `measure_tilt` est mauvais sur la strate
en cours — l'information est elle-même utile.

## Où vit l'or

**`gold.json` est un artefact de DONNÉES, pas du code.** Il vit sur MinIO
(`eurio-datasets/gold-crop/v1/`), avec le manifest et le hash de la requête. Le
dépôt git ne porte que le `sha256` et la requête d'échantillonnage — *git n'est
jamais un transport de données*.
