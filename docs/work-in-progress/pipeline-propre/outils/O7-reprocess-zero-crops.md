# O7 · Reprocesser les 2 950 annonces sans crop

> **Statut : LIVRÉ le 2026-08-21** — `ml/scripts/reprocess_zero_crops.py`,
> tâche `ml:src:ebay:reprocess-zero`, 811 annonces déficitaires rejouées,
> **669 récupérées (82 %)**, 936 crops, 777 en file. Chiffres et requêtes :
> [`../JOURNAL.md`](../JOURNAL.md). Reste ouvert : l'étape 5 (repli plein
> cadre) pour les 341 images encore à zéro, et les 2 142 annonces non
> déficitaires qui attendent le mécanisme « parqué » (D3).
>
> *(Spec d'origine ci-dessous, écrite avant le run.)*
> Station 3 du [flow](../FLOW-ADMIN.md). Première version écrite le
> 2026-08-21 matin sous le titre « instrumenter » ; **réécrite l'après-midi**
> après avoir ouvert les images et rejoué le détecteur. L'étape
> « étiqueter 200 images à la main » est faite (60, seed 42) — ce document
> commence là où elle s'arrête.

## Le geste

Rejouer la détection sur les annonces dont **aucune** image n'a produit de
crop, avec la passe de récupération déjà écrite et jamais activée en prod.
Zéro appel eBay : les raws sont en MinIO.

## Ce qu'on sait maintenant, et comment on le sait

### L'unité de coût est l'annonce

`sources/ebay/adapter.py::_yield_listing_images` fait **un** `item/{id}` par
annonce et rend une `source_image` **par image** (`ebay_<id>_img<N>`). Les
images sont des téléchargements CDN, pas du quota. Donc la plaque se compte
par annonce :

```sql
WITH l AS (SELECT substr(source_ref,1,instr(source_ref,'_img')-1) listing,
                  SUM(crop_status='success') s
             FROM source_images WHERE source='ebay' GROUP BY 1)
SELECT COUNT(*), SUM(s>0), SUM(s=0) FROM l;
-- 7662 | 3937 | 2950      ← 38 % des annonces payées n'ont rien rendu (2026-08-21)
```

Par pays de recherche : FR 516 · DE 470 · BE 384 · AT 298 · ES 276 · FI 267 ·
AD 229 · CY 202 · IT 190 · EE 118. Par état de la classe visée
(`target_eurio_id` → `dino_class_references`, grain banque) : **808 annonces
visent 143 classes déficitaires**, 1 399 des classes pleines, 39 des classes à
8–9, 92 une cible qui n'est pas un `class_id` de banque (membre non
représentant — passer par `bank_classes`).

### Ce qu'il y a dans les images — 60 au hasard, seed 42

```sql
SELECT storage_path FROM source_images
 WHERE source='ebay' AND crop_status='zero_crops' AND source_ref LIKE '%_img0'
 ORDER BY random() LIMIT 400;   -- puis random.seed(42), filtre « présent en cache », [:60]
```

| ce qu'on voit | n | |
|---|---:|---|
| **une pièce de 2 €, seule, propre, plein cadre** | **42** | **70 %** — le gisement |
| boîtier / coincard / écrin (pièce minuscule ou absente) | 6 | perte normale |
| rouleau | 3 | perte normale |
| pièce de 2 cents | 2 | la porte `denom` l'aurait jetée |
| revers (face commune) | 2 | la porte `face` l'aurait jetée |
| deux pièces (avers + revers) | 5 | récupérable en partie |

Planches : `sheet0.jpg` / `sheet1.jpg` dans le scratchpad de la session du
2026-08-21 ; à rejouer avec le seed, pas à recopier.

### La cause racine, mesurée sur ces 60

Le détecteur (`vision/normalize_snap.py::detect_circles_multi`) est
**YOLO-first** : des bbox YOLO, puis Hough dans chaque bbox. Sur les 60 :

| test | résultat |
|---|---|
| YOLO : une bbox ≥ 60 % du petit côté ? | **0 / 60** — YOLO ne voit pas une pièce qui remplit le cadre |
| pipeline prod (`census=True`, recover OFF) | 0 crop ; seulement des cercles intérieurs, `r/short` 0,02–0,09 → `radius_too_small` / `gated_fragment` |
| Hough plein cadre (ROI = image, `r ≥ 0,30·short`, centre à < 0,2·short) | **40 / 42** pièces seules trouvées (et 15 / 18 des autres, qui sont aussi des cercles — c'est aux portes de trier) |
| `EURIO_CENSUS_RECOVER=1` (`vision/score_recover.py`, stratégie A) | **32 / 42 (76 %)** récupérées |

Les `detections_json` du run du 2026-08-16 disent la même chose sur 433 images :
`radius_too_small` 1 584, `gated_fragment` 1 149, 43 images sans aucun cercle.
**C'est le diagnostic du chantier [`crop-recovery`](../../crop-recovery/VISION.md)**
(« la détection se rabat sur le motif central », jeu D2 = 341 `zero_crops`) —
la première version de ce document disait le contraire, à tort.

### Le remède existe et n'a jamais tourné

- `score_recover` est **OFF par défaut** (R0), activé par
  `EURIO_CENSUS_RECOVER=1` que seule la tâche `ml:src:ebay:run` pose
  (`ml/tasks.yml:832`). Le run du 2026-08-16 porte **0** crop de méthode
  `score_recover` sur 601 acceptés (`detections_json`, `accepted=1`) : le flag
  n'était pas actif. Le dernier run a donc encore 54 % de `zero_crops`.
- `detect_crop.run(retry_zero_crops=True)` existe (`detect_crop.py:96`) et
  n'est exposé **nulle part** (ni `sources/cli.py`, ni orchestrateur, ni
  `tasks.yml`). Le commentaire dit pourquoi on skippe par défaut : le
  détecteur est déterministe — ce qui cesse d'être vrai dès qu'on change un
  réglage.
- Les 7 531 raws : `storage_status='present'` 7 531 / 7 531 ; 105 / 200 déjà
  dans `~/.cache/eurio/enrichment-raws`.

## Ce que l'outil fait, dans l'ordre

1. **Exposer le reprocess** : un drapeau `--retry-zero-crops` sur l'étape
   `detect` (CLI + tâche), qui pose `EURIO_CENSUS_RECOVER=1` **et le dit** dans
   le log de run (« recover=ON »). Un reprocess qui tourne recover OFF
   reproduit le même zéro en silence.
2. **Périmètre** : les annonces à `s=0` **dont la cible vise une classe
   déficitaire** d'abord (808, D3 : on ne gonfle pas la file des classes
   pleines) ; les 1 399 autres ensuite, et leurs crops sont **gardés mais
   parqués** (D3).
3. **Le reste de la chaîne est inchangé** : les crops passent `resolve`
   (portes `denom` / `face`) puis `enqueue`, et la banque `2eur_all` leur
   donne un top-1 au backfill. C'est là que les 2 cents et les revers tombent.
4. **Mesurer** sur le run de reprocess : annonces rejouées → annonces avec
   ≥ 1 crop → crops survivant aux portes → par classe visée. Et garder les
   `detections_json` (ils sont écrits même à 0 crop) pour compter ce que
   recover **rate** encore : c'est la population du repli plein cadre.
5. **Seulement ensuite** : le repli plein cadre (Hough sur l'image entière
   quand YOLO ne rend rien et que l'image est ~carrée — 4 207 `zero_crops`
   carrées contre 1 997 `success`). 40 / 42 à la sonde ; à bencher sur D1/D3
   de `crop-recovery` avant d'entrer en prod, comme les stratégies A et B.

## Comment on vérifie qu'il marche

- **Le témoin** : le log de run annonce `recover=ON` et le nombre d'images
  rejouées = le périmètre demandé, à l'unité.
- **Le contrôle sur l'échantillon** : les 60 images de la planche, rejouées par
  le vrai point d'entrée, rendent ≥ 32 crops sur les 42 pièces seules. Moins,
  c'est que le flag n'est pas passé — pas que « ça ne marche pas ».
- **Le compte par classe** : après backfill, `pending` (O1) des 143 classes
  visées a bougé. S'il n'a pas bougé, lire `eurio-verify` avant de chercher
  ailleurs : le push au canonique est muet.
- **Le dénominateur tient** : `zero_crops + success + failed + autre` = le
  total eBay, avant et après.

## Ce que cet outil n'est pas

- **Ce n'est pas une amélioration du détecteur** (sauf l'étape 5, et elle
  passe par le banc). C'est l'activation d'un remède déjà benché.
- **Ce n'est pas un auto-accept.** Chaque crop récupéré passe les portes puis
  un humain.
- **Ce n'est pas un scrape.** Zéro appel eBay. C'est précisément pourquoi il
  passe devant tout le reste (D5).
