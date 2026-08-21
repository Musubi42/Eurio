# Journal — pipeline propre

> Une entrée par geste : ce qu'on a fait, la commande, le témoin qui prouve
> que ça a tourné, la mesure **avec sa requête**, et la décision ou le lien
> vers [`DECISIONS.md`](DECISIONS.md). Le plus récent en haut. Les chiffres
> sont ceux d'une minute sur `ml/state/eurio.replica.db` : relance la
> requête, ne recopie pas le nombre.

---

## 2026-08-21 — Revue de la vision, ouverture des `zero_crops`, décisions D1–D6

**Contexte.** Revue des docs écrits la veille (`VISION.md`, `FLOW-ADMIN.md`,
`outils/O1..O7`) contre la réplique (pull du 20/08 21:07, WAL du 21/08
12:56) et le code. Aucun appel eBay.

**Corrigé dans les docs et la skill.**
- `eurio-banque` §2 et §4 : `dino_class_references.class_id` est l'`eurio_id`
  du représentant, pas `COALESCE(design_group_id, eurio_id)` —
  `SELECT COUNT(*) FROM (SELECT DISTINCT class_id FROM dino_class_references
  WHERE anchors_kind='2eur_all') WHERE class_id IN (SELECT design_group_id
  FROM coins WHERE design_group_id IS NOT NULL)` → **0**.
- `VISION.md` §M1 : les recherches vides existent dans
  `discovery_searches.status='empty'` (9, toutes Andorre) ; l'allocateur lit
  `coin_source_status`, qui n'en a aucune.
- Migrations : la réplique est à `0011` (`SELECT * FROM _schema_migrations
  ORDER BY 1 DESC LIMIT 1`) — PREREQUIS et la skill disaient « 0008 ».
  `dino_thresholds` est vide (tout `source='code'`).

**Les `zero_crops`, au grain annonce** (l'unité de coût eBay est l'`item/{id}`) :

```sql
WITH l AS (SELECT substr(source_ref,1,instr(source_ref,'_img')-1) listing,
                  SUM(crop_status='success') s
             FROM source_images WHERE source='ebay' GROUP BY 1)
SELECT COUNT(*), SUM(s>0), SUM(s=0) FROM l;   -- 7662 | 3937 | 2950
```

Par état de la classe visée (`target_eurio_id` joint à `dino_class_references`
grain banque) : **808 annonces → 143 classes déficitaires**, 1 399 → 55
classes pleines, 39 → classes à 8–9, 92 → cible non représentante.

**Échantillon** : 60 images `_img0` (`ORDER BY random() LIMIT 400`, puis
`random.seed(42)`, filtre « présente en cache », `[:60]`) → **42 pièces
seules propres plein cadre (70 %)**, 6 boîtiers, 3 rouleaux, 2 × 2 cents,
2 revers, 5 doubles.

**Cause racine** (rejoué en local, `normalize_listing_with_detections`) :
YOLO ne rend aucune bbox ≥ 60 % du petit côté sur les 60 ; seuls des cercles
intérieurs (`r/short` 0,02–0,09) → `radius_too_small` / `gated_fragment`.
`detections_json` du run `473c2225…` (433 images) : `radius_too_small` 1 584,
`gated_fragment` 1 149, 43 images sans aucun cercle.

**Remède** : `EURIO_CENSUS_RECOVER=1` rattrape **32/42** ; un Hough plein
cadre (ROI = image, `r ≥ 0,30·short`, centré) **40/42**. Le run du
2026-08-16 porte 0 crop `score_recover` sur 601 acceptés : la passe n'a
jamais tourné en prod.

**Courbe émissions communes** (`bench_refs_curve --bank-classes/--gold-classes`
sur les 87 `eurio_id` des `design_group_id` multi-pays, `vitl14`, 102 crops /
15 classes held-out) : pays@1 **90,2 % (N=0) → 97,1 % (N=5)**, plat ensuite ;
global@1 17,6 → 29,4 %. → D4, cible 5 pour cette famille.

**Décisions** : D1–D6 dans [`DECISIONS.md`](DECISIONS.md). Ordre :
O7 → O6 → O1/O5 → design O2/O4 → O3 → scrape.

**Plan du sprint 1** : `~/.claude/plans/ok-mon-ami-c-est-binary-jellyfish.md`
(Lot 0 journal · Lot 1 `scripts/reprocess_zero_crops.py` + tâche + tests ·
Lot 2 run réel par paliers, 808 annonces déficitaires · Lot 3 mesures).
