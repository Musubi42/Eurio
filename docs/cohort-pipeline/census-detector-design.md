# Design — étage dedup + verify + fusion d'identité (census de pièces)

> **Statut : LEVIER ANTI-FRAGMENT TROUVÉ (2026-06-05) — probe face-vs-fragment entraînée, voir §9.** La fragmentation (cause A, §8) qui bloquait la qualité de crop est résolue par une **régression logistique sur features DINO « face entière vs fragment »** : LOCO-CV AP **0.918** sur 9 classes, validée end-to-end sur une classe held-out. Câblée derrière `EURIO_CENSUS_FRAGMENT_TAU` (défaut 0.45), **flag census toujours OFF par défaut** (0 impact prod). Reste : confirmer τ multi-dénom + décision PO d'activation. **Ceci rouvre le sous-chantier** clôturé le 2026-06-04 (ci-dessous), dont les acquis restent valides.
>
> **[2026-06-04] v1 ACTÉE.** La v1 livrée = **`yolo@0.10 + ① nms_only`** (domine yolo brut, **poison 0 %**, rappel 89 % ; faux-lot 64 % = review, pas poison). Le **gate is-coin ② (sim DINO « coin-ness ») n'a PAS été adopté** : impasse confirmée (échange poison↔faux-lot 1:1 ; extension banque cause B = négatif §7). → **dépassé par la probe entraînée §9** (le bon signal n'était pas « coin-ness » mais « face vs fragment »). Infra gardée (`scan/census.py`, `--include-real`, `--bank`). Résultats & verdict détaillés en **§6-§7**.
>
> **Décidé PO** : signal is-coin = **option A (prototype coin-ness large, DINO)** · v1 = **① NMS-concentrique + ② verify is-coin** (fusion ③ repoussée, bench front/back trop mince) → mesurer le résidu.

## 0. Ce que l'étage doit faire (contrat)

Entrée : un raw eBay + les **boîtes YOLO-low@0.10** (haut rappel, sur-compte). Sortie : **le nombre de pièces physiques distinctes** `n_coins` (+ les régions retenues, pour le crop). Découplé du format de crop. Benché sur `bench_v0.json` (mêmes métriques : faux-single = poison à garder à 0, faux-lot à écraser, exact/±1 à monter).

## 1. Évidence — de quoi est fait le sur-comptage

Caractérisation des **239 boîtes « extra »** (au-delà de la plus grosse) sur les **55 singles sur-comptés** (n_coins=1, ≥2 boîtes YOLO@0.10) :

| Classe de boîte extra | Part | Quoi | Étage qui l'adresse |
|---|---|---|---|
| **CONCENTRIC** | **8 %** | centre dans la box principale ou IoU>0.3 (doublon, anneau bimétal interne, fragment) | NMS-concentrique (géométrique) |
| **LOW_COIN** | **69 %** | sim DINO faible : texte, fenêtre/cadre coincard, logo, fond, reflet | **verify is-coin** |
| **COINLIKE_SEP** | **22 %** | disjointe ET « coin-like » : avers/revers, 2e vraie pièce, ou médaille/visuel imprimé coin-like | fusion-identité / réel |

**Lecture : le sur-comptage est d'abord un problème de VERIFY** (69 % = clutter non-pièce), pas de dedup (8 %) ni de fusion (22 % tail). L'ordre d'impact dicte l'effort.

## 2. L'échelle proposée (ladder), dans l'ordre

```
boîtes YOLO-low@0.10
  → ① NMS-concentrique      (géométrique, fusionne doublons/anneaux/contenus)   ~8% du bruit
  → ② verify is-coin        (garde « pièce, toute dénom/face » ; jette clutter)  ~69% du bruit
  → ③ fusion d'identité     (colle avers+revers d'1 pièce ; exemplaires ⟂)       ~22% tail
  → count = n pièces distinctes
```

### ① NMS-concentrique — tranché, peu de risque
Fusionner les boîtes dont l'une **contient** le centre de l'autre, ou IoU > ~0.3, en gardant la plus grande (rim externe). Couvre l'anneau bimétal interne + fragments + doublons. Pur géométrique, 0 dépendance. **Pas de débat** — à coder tel quel.

### ② verify is-coin — LE CŒUR, et la vraie question ouverte
69 % du sur-comptage = des boîtes qui **ne sont pas des pièces**. Un bon gate les jette et on a quasiment gagné. **MAIS** le signal is-coin doit être **agnostique à la dénomination ET à la face** : une pièce de 1 cent, un revers national, une pièce hors-cible restent des pièces. Le piège : le signal « sim DINO vs ancres 2€-commémo *avers* » (celui du bench) confond « pas une pièce » et « pas une 2€-commémo-avers » → l'utiliser comme gate **retuerait des vraies pièces** (= faux-single réintroduit sur les lots de cents/revers). À NE PAS faire.

**Options pour le signal is-coin (à choisir ensemble) :**

| Opt | Signal | Pour | Contre |
|---|---|---|---|
| **A. Prototype coin large** | sim DINO vs une banque « coin-ness » multi-dénom × 2 faces (cents→2€, avers+revers, bâtie depuis nos réfs Numista/BCE) | réutilise DINO déjà chargé ; agnostique dénom/face ; 0 entraînement | il faut construire+calibrer la banque ; un médaillon coin-like peut passer |
| **B. Probe is-coin** | régression logistique (1 couche) sur features DINO, coin vs non-coin | très précis ; léger | = un mini-entraînement (mais ≠ détecteur complet) ; besoin d'un petit set labellisé pos/neg |
| **C. Géométrie + YOLO-conf** | conf YOLO (percentile) + circularité/fill du masque + structure-guard (Laplacian, déjà en prod) | 0 modèle en plus ; rapide | le texte/fenêtre coincard peut être circulaire ; moins robuste |
| **D. Combo** | ① géométrie pré-filtre cheap → A ou B sur les survivants | étage cheap d'abord, modèle sur le résidu | plus de pièces mobiles |

> **✅ Décidé : option A (prototype coin-ness large, DINO).** Garder **C (structure-guard Laplacian, déjà en prod)** en pré-filtre cheap. **B** en réserve si A ne sépare pas assez (la banque large risque de laisser passer les visuels imprimés sur coincard).
>
> **Sous-questions A (pour le build)** : (a) sources de la banque = avers **+ revers** Numista (`ml/datasets/<nid>/{obverse,reverse}.jpg`) sur toutes dénoms (1c→2€), + BCE ; combien d'items vise-t-on ? (b) seuil τ calibré sur le bench (sweep, comme §5) ; (c) faut-il un set de **négatifs** (texte/coincard/fond) pour fixer τ proprement, ou le sweep sur le bench suffit ?

### ③ fusion d'identité — le tail 22 %, partiellement bench-limité
Deux sous-cas dans COINLIKE_SEP :
- **avers + revers d'1 même pièce** : 2 disques coin-like, même diamètre, dans un listing « single ». La fusion **n'est pas** par cosinus brut (les 2 faces sont visuellement différentes) → heuristique **contextuelle** : même taille + listing single + 2 disques isolés ⇒ 1 pièce. Signal d'appui possible : un classifieur avers/revers, ou la cohérence « paire » (mêmes dimensions, fond identique).
- **exemplaires identiques** (rouleau, lot de la même pièce) : là le cosinus DINO **élevé** entre disques colle bien → dedup par similarité.

⚠️ **Bench mince** : `single_two_faces` = **1** seul échantillon (4/110 front/back au total). On benche cet étage à l'aveugle. → **étendre le bench front/back** (cf. §1 gotcha bench) avant d'investir lourd ici. Pour la v1, viser ① + ② et **mesurer le résidu** ; ne coder ③ que si le résidu le justifie ET le bench le couvre.

## 3. Plan de validation (bench-first, R0)
- Étendre `measure_census_ceiling.py` (ou un module dédié) avec un proposeur **`yolo_low+ladder`** : boîtes YOLO@0.10 → ① → ② → (③) → count. Mêmes métriques que §5.
- **Cible** : faux-single **reste 0 %**, faux-lot **69 % → vers ~5-10 %**, `exact pièces` **25 % → ↑**, sur le même bench.
- Ablation : mesurer après ① seul, après ①+②, après ①+②+③ — pour isoler l'apport de chaque étage (et confirmer la lecture 8/69/22).

## 4. Décisions (2026-06-04)
1. **Signal is-coin** : ✅ **A (prototype coin-ness large, DINO)** + C (structure-guard) en pré-filtre.
2. **Périmètre v1** : ✅ **①+②**, mesurer le résidu ; **③ fusion repoussée** (bench front/back trop mince).
3. **Bench front/back** : à étendre **après** ①+② (pas un pré-requis tant que ③ est repoussé).
4. **Où vit le code** : d'abord **proposeur de bench** (`yolo_low+ladder` dans/à côté de `measure_census_ceiling.py`) → promotion en module `scan/census.py` une fois les chiffres validés. Bench-first.

## 5. Prochain pas concret (v1)

> **Réfs dispo (constat 2026-06-04)** : `ml/datasets/` = 688 nid, **564 obverse + 563 reverse**, mais **tous face_value 2€** (682 coins, 623 commémo). Pas de cents/1€/50c en réfs locales. → la banque v1 sera **2€ avers+revers (~1100 imgs)**, **bien alignée avec ce bench** (mix-zone-17 = 16 classes, toutes 2€). **Trou dénom assumé** (cents/1€) → à combler (scrape réfs / BCE) quand le pipeline touchera des cohortes non-2€. Bench-first : on valide d'abord ce que ce bench mesure.

1. **Banque coin-ness** : encoder avers+revers 2€ (Numista, ~1100 imgs ; + BCE si dispo) en DINO → `state/foundation_coinness.npz`. Script type `build_coinness_bank.py`.
2. **Ladder** : `nms_concentric(boxes)` → `is_coin(crop) = simDINO(crop, banque) ≥ τ` (+ structure-guard) → count. Ajouter le proposeur `yolo_low+ladder` au harnais de bench.
3. **Mesurer** sur `bench_v0.json` : ablation ① / ①+② ; cible faux-single **0 %**, faux-lot **69 %→~5-10 %**, exact ↑. Présenter au PO.

## 6. Résultats v1 + AUDIT (2026-06-04) — bench `ceiling_ladder.json`

Code livré : `scripts/build_coinness_bank.py` (banque **1127** réfs : 564 avers + 563 revers 2€, dim 384 → `state/foundation_coinness.npz`), module `scan/census.py` (① `nms_concentric` + ② `is_coin`), proposeur `ladder` dans le harnais, `tests/test_census.py` (10 ✅).

`fs_real` = **poison réel** = vrai lot dont les pièces sont VISIBLES (`n_disks_visible≥2`, 25 lots) vu ≤1. Distinct du `false_single` brut, qui comptait à tort des lots scellés/album où les pièces ne sont pas visibles (correctif d'audit).

| variante | zéro-récup /61 | faux-single /27 | **fs_real /25** ⚠️ | faux-lot /80 | exact /110 |
|---|---|---|---|---|---|
| baseline prod | 0 % | 48 % | **44 %** ☠️ | 5 % | 34 % |
| yolo@0.10 (proposeur) | 89 % | 0 % | **0 %** | 69 % | 25 % |
| **① nms_only** *(garde taille+bord)* | **89 %** | **0 %** | **0 %** ✅ | **64 %** | **30 %** |
| ①② τ0.35 | 82 % | 19 % | 16 % | 41 % | 46 % |
| ①② τ0.50 | 57 % | 41 % | 36 % | 22 % | 43 % |
| ①② τ0.60 | 33 % | 48 % | 44 % | 8 % | 33 % |

### Verdict de l'audit (4 auditeurs Sonnet + synthèse, run `wf_a95d6db2-8fa`)
1. **v1 livrée = `yolo@0.10 + ① nms_only` (SANS le gate DINO).** Elle **domine** yolo brut : même rappel (89 %), **0 poison** (fs_real 0 %), et améliore exact (30 % vs 25 %) + baisse le faux-lot (64 % vs 69 %). Strictement meilleure que la baseline prod (0 % vs 44 % poison). Le faux-lot résiduel (64 %) = **review humaine, pas du poison** (bon côté de l'asymétrie de coût).
2. **Le gate is-coin ② n'est PAS prêt** : il échange poison↔faux-lot ~1:1 (fs_real grimpe à 16 % dès τ0.35). **Deux causes** : (A) **fragmentation YOLO** — 1 pièce → 5-13 boîtes disjointes coin-like qu'aucun τ ne sépare (problème de PROPOSEUR) ; (B) **trou de domaine banque** — capsule/revers/multi-dénom Numista canonique ≠ vues eBay réelles. Non calibrable au seuil seul.
3. **Bugs R0 corrigés post-audit** : blocker (banque absente → `RuntimeError` au lieu de 0 silencieux) ; `nms_concentric` ne fusionne plus 2 pièces distinctes d'un lot (gardes **taille** ≥0.7× + **bord**, cas `172ac301` validé : fs_real nms_only 4 %→0 %) ; CLI (`hough` retiré, `all`=yolo+ladder, proposeur inconnu → erreur) ; `false_single` décomposé en `fs_real` ; assert d'alignement banque ; tests pures.

### Décision (à ratifier) & prochain levier
- **Livrer `① nms_only` comme proposeur de compte v1** (training corpus + signal lot/single), **gate DINO désactivé**.
- **Prochain levier (reco audit) : étendre la banque AVANT d'itérer τ** — ajouter vues capsule (20-30 crops du bench), multi-dénom (1c-1€), pour combler les 5 défaillances structurelles. Si elles persistent → option B (probe is-coin 2 classes `physical_coin` vs `printed/capsule`). NB : la **fragmentation YOLO (cause A)** ne se règle pas par la banque — c'est un sujet PROPOSEUR (NMS plus agressif sur boîtes très chevauchantes d'un même single, ou retrain) à traiter séparément.

## 7. Extension banque (cause B) — testée, NÉGATIF (2026-06-04)

> ⚠️ Anti-fuite : la reco audit (« 20-30 crops capsule du bench ») aurait créé une **fuite banque→bench**. On a donc pris **81 crops eBay validés humainement HORS-bench** (`manual`/`auto_phash`/`training_eligible`, incl. FI 5 + AT 40 = les domaines des échecs structurels) via `build_coinness_bank.py --include-real`. Banque 1127 → **1208**. A/B via `--bank` du harnais.

| variante | banque | fs_real | faux-lot | exact |
|---|---|---|---|---|
| ①② τ0.35 | défaut | 16 % | 41 % | 46 % |
| ①② τ0.35 | étendue | **16 %** | 46 % | 42 % |
| ①② τ0.45 | défaut | 28 % | 28 % | 46 % |
| ①② τ0.45 | étendue | **28 %** | 30 % | 49 % |

**Verdict : l'extension ne débloque PAS le gate.** `fs_real` identique à chaque τ (les **mêmes lots échouent**), faux-lot inchangé-à-pire, exact marginalement mieux à τ haut seulement. Cause : 81 crops = 6,7 % d'une banque de 1208, `is_coin = max sim` → trop dilué pour relever les capsules récalcitrantes ; et on ne peut pas avoir plus de crops PROPRES (les 2237 hors-bench restants sont `needs_review` non validés → y piocher réinjecterait le clutter que le gate doit rejeter). **Levier cause B épuisé avec les données propres dispo.** Banque étendue NON versionnée (pas de gain). Infra (`--include-real`, `--bank`) gardée pour re-tester si un set capsule validé plus large arrive.

→ Le gate ② n'est pas débloquable maintenant. Leviers restants : **cause A (fragmentation YOLO)** — proposeur, sans data, le plus gros morceau du faux-lot ; ou **option B (probe is-coin entraînée)** — needs ~150 ex. labellisés. **v1 reste `① nms_only`.**

## 8. Câblage prod derrière flag + re-crop test (2026-06-05)

Demande PO : tester l'impact RÉEL du câblage census sur le flow `/lab/cohorts/...` (search→crop→valide→train). Câblé **derrière flag `EURIO_CENSUS_DETECT=1` (OFF par défaut)** dans `scan/normalize_snap.detect_circles_multi` : conf YOLO 0.35→0.10, `nms_concentric` (gardes taille+bord) en amont, **off_edge + low_structure désactivés** (ils jetaient les pièces emballées) ; Hough refine/polish/rim-refine de qualité conservés. Comparateur réutilisable `scripts/compare_census_recrop.py` (mesure PURE, ne mute pas la base).

**Re-crop test sur `at-2002-2eur-standard-1st-map` (46 raws téléchargés)** :

| | PROD (flag off) | CENSUS (flag on) |
|---|---|---|
| crops produits | 24 | **126** (×5.25) |
| raws à 0 crop | 32 | **11** |

**Recall réel : 21/32 zéro-crops récupérés.** MAIS audit visuel (contact sheet) : la majorité des +102 crops = **fragments** (bouts de lettres `R`/`RO`/`EUR`, anneaux internes, bords partiels), PAS des images de training. Cause : YOLO@0.10 détecte des *bouts* de pièce sans la pièce entière → `nms_concentric` n'a pas de boîte parente pour les absorber, et le gate is-coin qui les filtrerait n'est pas prêt.

**Verdict : NE PAS adopter en prod.** Pour le *comptage* lot/single, OK (l'asymétrie tolère le sur-comptage). Pour *produire des crops training propres*, non — ça échange zéro-crops contre crops-fragments. **Le re-crop test confirme la décision bench-only.** Flag gardé OFF (0 impact) + comparateur, pour re-tester quand le maillon is-coin / anti-fragment sera prêt.

## 9. Gate anti-fragment = probe entraînée face-vs-fragment (2026-06-05) — ✅ LEVIER TROUVÉ

> Reprise PO : « réduire RÉELLEMENT les erreurs de crop ». Le problème §8 = **fragmentation** (cause A). Exploration bench-first des 3 pistes du kickoff sur `at-2002` (46 raws, 126 crops census), via `scripts/measure_antifragment.py` + `scripts/diag_fragment_geometry.py`.

**Pistes 1 & 2 = écartées (mesurées) :**
- **Piste 1 (rim-completeness géométrique)** — NÉGATIF. `arc_coverage` (couverture angulaire Canny, repris de `measure_tilt`) : **117/126 crops ≥ 0.90**. La couverture par secteurs se sature dès qu'il y a de la texture → un fragment circulaire (lettrage de tranche, anneau interne) coche autant de secteurs qu'une face. La géométrie du rim ne sépare PAS face vs fragment (les fragments SONT des disques).
- **Piste 2 (containment/clustering NMS)** — gain marginal. Seulement **25/126 (20 %)** détections nichées dans une plus grande, dont 16 absorbables (<0.70). La cause dominante (gros plans de **tranche** = l'image entière EST la tranche, pas de boîte parente) n'a **pas de parent** → le clustering ne la touche pas. Plafond ~13 %.

**Piste 3 (probe entraînée) = ✅ LE LEVIER.** Le fragment dominant est circulaire (géométrie inopérante) ET coin-like (sim DINO « coin-ness » le laisse passer — c'est littéralement de la pièce). Seul un **classifieur face-entière vs fragment** le rejette.

- **Probe** = régression logistique 1 couche sur **embeddings DINO des crops normalisés 224** (= sortie de `normalize_listing`, PAS les bbox). `scripts/build_fragment_probe.py` → `state/fragment_face_probe.npz` (coef 384 + intercept).
- **Dataset** (`scripts/build_fragment_probe_set.py`) : 705 crops census labellisés `face_whole`/`fragment`/`capsule`/`clutter` sur **9 classes 2€**, anti-fuite (110 `source_image_id` du bench census exclus au niveau IMAGE). Labelling : `at-2002` à la main (held-out fiable), 8 classes train via agents vision Sonnet.
- **Calibration HONNÊTE = Leave-One-Class-Out CV** (aucune fuite inter-classe) : **AP moyenne 0.918** sur 9 classes ; at-2002 fold AP 0.922, le plus faible at-2005 0.718 (garde quand même 9/9 faces — ses fragments fuient en review, pas en poison).

| τ (agrégat 9 classes) | recall faces | coupe fragments |
|---|---|---|
| 0.40 | 97.5 % | 86.9 % |
| **0.45** *(défaut)* | **96.0 %** | **88.7 %** |
| 0.50 | 94.1 % | 89.9 % |
| 0.60 | 89.6 % | 92.4 % |

- **Validation end-to-end sur classe 100 % held-out** (`de-2007-...-treaty-of-rome`, jamais dans la probe, `scripts/audit_fragment_gate.py`) : **270 crops census → 79 gardés / 191 coupés** à τ=0.45. Audit visuel : gardés ≈ **95 % faces propres**, coupés ≈ fragments (lettrage tranche, partiels, textures, capsule). Le gate transforme census de « majorité fragments » en « ~30 % gardés, propres ».

**Câblage** (`scan/census.py` `load_face_probe`/`face_scores` ; filtre dans `scan/normalize_snap.normalize_listing` APRÈS le crop) : env **`EURIO_CENSUS_FRAGMENT_TAU` (défaut 0.45)**, τ≤0 = census brut (§8). **Sans effet hors mode census** (flag `EURIO_CENSUS_DETECT` toujours OFF par défaut → 0 impact prod). R0 : probe absente ⇒ `RuntimeError` (pas de fallback silencieux). Tests `tests/test_census.py` (12 ✅).

**Contraste avec le gate is-coin DINO (§6-7)** : celui-ci échangeait poison↔faux-lot 1:1 (sim « coin-ness » ne sépare pas face/fragment, les deux SONT coin-like). La probe **face-vs-fragment** entraînée résout exactement ce que la sim ne pouvait pas, et **généralise à une classe non vue**. Levier débloqué.

**Reste avant adoption prod** : confirmer τ sur d'autres dénominations (banque/probe = 2€ only), et décider d'activer le flag census (ou intégrer le gate dans un mode dédié au corpus training). Décision PO.

### Activation sur le corpus training (2026-06-05, PO go)

Décision PO : **2€ uniquement** (multidénom différée), **activer sur le corpus training** de la cohorte mix-zone-17, **settings actuels** (τ=0.45). Périmètre **additif & sûr** : `scripts/recrop_cohort_census.py` ne re-crope QUE les raws eBay à **0 crop présent** (zéro-crops) — aucune écriture sur des crops déjà reviewés/`training_eligible`. Persistance identique à `detect_crop` (crop_key→MinIO→`upsert_image_asset`, dédup phash, bbox forensics), `run_id=census-recover-<cohort>`, commit par classe, dry-run par défaut.

**Run committé sur mix-zone-17 (v1, τ=0.45)** : 1899 candidats zéro-crop → **425 raws récupérés (+733 crops propres)**, dont 16 auto-résolus phash, 717 `pending_match`. Tous `training_eligible=0` → **review queue** (rien n'entre en training sans review humaine). Gain concentré : at-2005 +174, fr-2008 +180 (lots multi-pièces, faces gardées par le gate), fr-2016 +59, fi-2016 +54. **Réversible** : `DELETE FROM image_assets WHERE run_id='census-recover-b0299ca0252b'` + purge MinIO préfixe. Observation préalable : `scripts/cohort_census_observe.py` (mesure pure, sans mutation).

### Probe v2 (hard-negative mining) + τ=0.55 (2026-06-05)

Review PO du run v1 : le gate v1 (négatifs surtout = fragments tranche/rocheux) laissait passer ~10-20 % de borderline — **disques vierges/délavés (blank)**, **cartes/certificats packaging** (« MONNAIE DE PARIS », « 2008 PRÉSIDENCE »), sombres/flous — surtout fr-2008/at-2005. Ces modes d'échec manquaient au train de v1.

**Hard-negative mining** : `scripts/build_hardneg_set.py` exporte les 733 crops du run v1 (= exactement les sorties du gate v1, donc ses faux positifs + vraies faces), labellisés (face_whole / blank / packaging / dark_blur / fragment / capsule) → split `hardneg` ajouté à `build_fragment_probe.py`. Distribution : 427 faces + **116 blank, 80 capsule, 55 fragment, 32 packaging, 23 dark_blur**. Probe v2 = 1438 crops (629 faces). LOCO-CV (15 classes) AP moy **0.885** — *plus basse que v1 (0.918) mais non comparable* : les négatifs v2 (blanks quasi-identiques à des faces en espace DINO) sont intrinsèquement plus durs.

**Validation end-to-end held-out** (`de-2007-treaty`, jamais en train) à **τ=0.55** : 270 crops → **66 gardés (~clean faces) / 204 coupés**. Audit visuel : v2 **coupe maintenant les blank/packaging/dark** que v1 gardait, précision des gardés nettement meilleure ; coût = ~17 % de vraies faces aussi coupées (assumé, asymétrie favorable : faces abondantes, review légère prioritaire). **τ par défaut relevé 0.45 → 0.55** (`_census_fragment_tau`). Probe v2 persistée (écrase `state/fragment_face_probe.npz`, dim 384 inchangée). Outils review : `scripts/review_sheets_census.py` (planches par classe).

**Reste à décider (PO)** : re-rouler `recrop_cohort_census` avec v2@0.55 (remplace les 733 crops v1 par un set plus propre — supprimer l'ancien run_id d'abord), et intégration pipeline (faire de census+gate le mode de crop par défaut de la cohorte).
