# HANDOFF — Crop rim over-fit (le détecteur crope un motif interne au lieu du rebord)

> **Pour une nouvelle session Claude Code.** Mission : améliorer le **crop** des
> listings eBay, qui se concentre sur un **cercle interne** (motif central) au lieu
> du **rebord de la pièce**. On repart d'un run eBay réel où le problème est flagrant.
> Écrit le 2026-06-15. ⚠️ Tout le travail de la session source est **non committé**
> (voir §État git). **Doctrine** : benchmark-first (mesurer avant d'optimiser, R0),
> entraînements lourds = **sur PC (1080 Ti)**, pas sur le Mac.

---

## 0. TL;DR

Un run eBay (`AT/2009` + `AT/2012`, 2 pièces) a produit **341/562 images en `zero_crops` (61 %)**.
En auditant, ce ne sont **pas** de mauvaises photos : le **détecteur trouve bien la pièce**
mais la **crope sur un sous-motif circulaire** (le € en globe du design EMU 2009, l'aigle
autrichien…), puis le **gate anti-fragment éjecte** ce crop tronqué. Résultat : **beaucoup
de faux négatifs** (vrais 2€ perdus avant même la review). C'est un **problème de crop**,
pas de gate ni de probe. **On va corriger le crop**, en mesurant sur ces cas précis.

---

## 1. Ce qu'on a fait dans la session source (2026-06-14/15)

1. **Run eBay réel** `--batch 2` → run_id **`fa8a9af939ce43e6a3eee6842ecae170`**, pièces
   **AT/2009 + AT/2012** (commémo « 10 ans de l'UEM » + standards).
2. **Audit du funnel** (lecture seule sur `ml/state/eurio.db`, la DB runtime 94 Mo —
   PAS `shared/state/eurio.db`).
3. **Diagnostic remonté à la source** : le crop sur-ajuste sur le cercle interne
   (confirmé par le commentaire **`vision/normalize_snap.py:125`** : *« On bimétal coins
   Hough picks the inner cupro/or ring rather than the rim ~36 % of the time. The
   "largest centred" rule mitigates but does not fully fix it. »*).
4. **Outils construits** (réutilisables) : page `/fragment-audit` + scripts de prep/mesure
   (voir §4).

### Aussi livré la même session (contexte, hors scope crop)
- Page **`/denom-gold`** (validation gold denom à 2 axes : dénomination + qualité crop) +
  `denom_gold_routes.py` + `harvest_denom_gold --override` + `train_denom_probe --exclude-bad-crops`.
  L'humain a validé les **87 crops ambigus** (50 pos / 29 neg / 8 indéterminables, **42 crop_bad
  dont 40 partiels** → déjà un signal « le crop déconne »). Données dans
  `ml/state/denom_bench/human_validation.jsonl` (merge + retrain = **étape PC**).

---

## 2. Le run en chiffres (run_id `fa8a9af939ce43e6a3eee6842ecae170`)

| Étape | Valeur |
|---|---|
| raws téléchargés | 541 |
| crops produits | 596 |
| **`zero_crops`** | **341 / 562 images (61 %)** |
| …dont ≥1 cercle détecté | **305** (donc Hough/YOLO marche, c'est la sélection/refine qui rate) |
| crops éjectés `gated_fragment` (depuis les zero-crops) | **787** (tous score < τ=0,55) |
| …gros cercles r≥120 (probables vrais coins) | 149 |
| enqueue review | 284 (214 lot / 70 single) |
| auto-rejetés (gate) | 261 (148 `not_2eur` + 111 `face_reverse` + 1 consensus) |
| auto_phash | 53 |

Distribution des scores des 787 éjectés : **max 0,53 · médiane 0,04** (palier τ=0,55).
→ Même les vrais coins scorent bas **parce que le crop est tronqué** : un crop plein-rebord
remonterait mécaniquement le score. **Ne PAS baisser τ** (mesuré : à τ=0,30 on réadmet autant
de fragments que de coins — le seuil ne sépare pas). **Ne PAS ré-entraîner la probe d'abord** :
c'est traiter le symptôme.

---

## 3. Cause racine (confirmée dans le code)

Pipeline de détection (eBay, `census=True`) :
`YOLO bbox pièce → Hough cercles → nms_concentric → rim-refine / polish → gate face_scores`.

Deux points fautifs :
1. **Sélection du cercle** — règle « **largest centred** » (`vision/normalize_snap.py:290`).
   Échoue quand le **motif interne est grand + centré + net** : le € globe de l'EMU 2009,
   l'aigle autrichien. Elle vote alors le cercle interne.
2. **`rim-refine` / `_radial_gradient_polish`** (`vision/normalize_snap.py:681`, ~`:859-881`,
   tag `+rimrefine`) — ajuste le rayon sur le **bord fort le plus proche** → le rebord du globe €,
   pas le rebord de la pièce. Agit **après** `nms_concentric` (qui, lui, travaille sur les
   bboxes), donc **rien ne l'empêche de rétrécir sous la vraie pièce**.

Pire cas observé : design **EMU 2009** (motif central = un gros cercle € en globe à grille) —
**~100 occurrences** dans ce seul run. Voir `state/fragment_audit/` (les vignettes « globe » r80,
r104, r107, r158…).

Le gate qui éjecte (`vision/normalize_snap.py:983`) est **correct dans son rôle** : il jette les
fragments. Le bug est **en amont** (le crop tronqué ressemble à un fragment).

---

## 4. Outils & artefacts déjà en place (réutiliser, ne pas refaire)

- **Page `/fragment-audit`** (`admin/.../features/fragment-audit/pages/FragmentAuditPage.vue`,
  route dans `router.ts`, **volontairement HORS nav**). Grille des 787 crops éjectés : image +
  **score** + **r** + bordure rouge (sous τ). Clic 1×=coin / 2×=fragment → compteur live + tags
  persistés. **Sert au avant/après visuel.**
- **Backend** `ml/serving/fragment_audit_routes.py` : `GET /fragment-audit/items`,
  `/crop/{name}`, `POST /tag`. Lit `ml/state/fragment_audit/`.
- **Prep** `ml/scripts/prep_fragment_audit.py --run <id>` : régénère les crops éjectés + scores
  → `ml/state/fragment_audit/{NNNN.png, manifest.json}`. **À relancer après chaque essai de crop**
  pour voir le nouveau résultat.
- **Mesure** `ml/scripts/measure_fragment_gate.py --run <id>` : distribution scores +
  table de récupération par τ + montage des gros cercles tués. (A servi à prouver que τ ne suffit pas.)
- **Données brutes** : les raws des zero-crops sont dans MinIO `enrichment-raws` (clés
  `ebay/fa8a9af9…/*.jpg`), accessibles via `shared.storage.local_cache.local_path("enrichment-raws", sp)`.
  Requête des `source_images` zero-crop : `crop_status='zero_crops' AND run_id='fa8a9af9…'`
  (colonne `detections_json` = constat fidèle des cercles acceptés/rejetés avec `reject_reason`).

---

## 5. Plan : améliorer le crop sur ces cas, stratégie par stratégie

**Périmètre de départ : ~50 cas** (pas les 787). Prendre en priorité les **EMU 2009 globe**
(le plus flagrant) + quelques standards autrichiens. Les sélectionner via la page
`/fragment-audit` (tag « coin ») ou par r≥120 dans le manifest.

### Échelle de stratégies (dérouler dans l'ordre, mesurer chacune)

- **Stratégie A — Ancrer sur la bbox YOLO + clamp rim-refine (RECO, en premier).**
  - Interdire au rim-refine/Hough de descendre **sous ~85 % de la bbox YOLO** (YOLO voit la
    pièce entière).
  - Préférer le cercle **le plus externe** parmi les concentriques (renforcer « largest centred »
    ou ajouter une règle « outer-most » quand plusieurs cercles partagent le centre).
  - **Ciblé sur le bug documenté, borné, mesurable.** Risque : rappel YOLO sur designs bizarres.
- **Stratégie B — Segmentation du disque (métal vs fond), en filet.**
  - Trouver le disque par sa couleur métal (le motif interne est le **même métal**) → masque plein
    → cercle sur le masque. Immunisé aux motifs internes. Piège : fond métallique / capsule.
- **Stratégie C — Anneau bimétal comme ancre.**
  - Le liseré argent/or au **rebord** est au bord de la pièce → ancrer dessus. Réutilise
    `vision/denom_geometry.py` (bimetal). Ne marche que sur bimétal.
- **Stratégie D — Post-filtre « under-crop ».**
  - Détecter qu'il reste du métal **au-delà** du bord du crop → ré-élargir. Rustine, dernier recours.

**La probe coin-ness (`state/fragment_face_probe.npz`, 7 Ko) : on n'y touche qu'APRÈS.** Un crop
plein-rebord remontera beaucoup de scores ; ne ré-entraîner que le résidu réel.

### Protocole de validation (benchmark-first)
Pour chaque stratégie :
1. Appliquer le changement dans `vision/normalize_snap.py` (sélection cercle / rim-refine).
2. Re-détecter les ~50 raws → relancer `prep_fragment_audit --run <id>` (ou un mode « rejeu sur
   un sous-ensemble »).
3. Mesurer : (a) **% de pièces qui cropent maintenant plein-rebord** (œil via `/fragment-audit`),
   (b) **% qui repassent le gate** (score ≥ τ après bon crop). Comparer avant/après.
4. **Garde-fou non-régression** : vérifier que les vrais fragments (tranches/lettrage/capsules)
   restent éjectés, et que les crops déjà bons (cohortes device, `crop-bench`) ne cassent pas.

### Branchement sur l'existant (ne pas réinventer)
- `docs/work-in-progress/crop-quality-overhaul/` (`detect_bbox_refine`, ~92 % eBay — mais EMU le casse).
- `docs/work-in-progress/crop-forensics/` (scores composites).
- Mémoires : `project_crop_quality_overhaul`, `project_listing_detection_pipeline`,
  `feedback_recrop_multicoin_guard` (NE PAS casser la garde multi-pièces), `project_tilt_detection`.

---

## 6. État git (session source — NON COMMITTÉ)

Fichiers de la session (à committer proprement ou repartir dessus) :

**Nouveaux**
- `ml/serving/fragment_audit_routes.py`, `ml/serving/denom_gold_routes.py`
- `ml/scripts/prep_fragment_audit.py`, `ml/scripts/measure_fragment_gate.py`
- `admin/.../features/fragment-audit/…`, `admin/.../features/denom-gold/…`
- `ml/state/fragment_audit/` (gitignoré ? c'est de l'état runtime)

**Modifiés**
- `ml/serving/server.py` (monte les 2 routers), `admin/.../app/router.ts` (2 routes ;
  `/fragment-audit` hors nav), `admin/.../app/nav.ts` (lien `/denom-gold` seulement)
- `ml/scripts/harvest_denom_gold.py` (`--override` + porte `sp`/`crop_bad`),
  `ml/scripts/train_denom_probe.py` (`--exclude-bad-crops`)
- `ml/referential/canonical_image_local.py` (write-through MinIO — autre chantier, harmo-images)
- `ml/serving/referential_routes.py` (redirect canoniques CDN — idem harmo-images)

⚠️ `ml/shared/state/eurio.db` est « M » mais c'est le **WIP C7 antérieur** (12 Ko), pas touché par
le run (qui écrit `ml/state/eurio.db`, 94 Mo, gitignoré).

## 7. Démarrage rapide (nouvelle session)
```bash
go-task ml:api                      # API :8042 (sert /fragment-audit)
pnpm -C admin/packages/web dev      # front :5173 → http://localhost:5173/fragment-audit
# Re-préparer l'audit après un changement de crop :
.venv/bin/python -m scripts.prep_fragment_audit --run fa8a9af939ce43e6a3eee6842ecae170
```

Premier pas conseillé : ouvrir `/fragment-audit`, **taguer ~50 « coin »** sur les EMU 2009 globe,
puis implémenter **Stratégie A** et re-mesurer. Discuter avec le PO avant de committer.
