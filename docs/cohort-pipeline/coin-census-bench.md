# Coin-census bench — combien de pièces sur le raw ?

> Sous-chantier de [cohort-pipeline](./README.md). Objectif : décider lot/single de façon fiable = **recenser les pièces physiques distinctes** sur la photo d'annonce, sans faux-single (empoisonne le training) ni faux-lot.
>
> **Statut (2026-06-04)** : ✅ **quick-win lot/single livré** (routing multilingue via `listing_kind`) — ⏳ **détecteur visuel = prochain chantier** (le résidu non soluble au titre).

---

## 1. Le bench (vérité-terrain v0)

- **110 raws** de la cohorte mix-zone-17 (`b0299ca0252b`), stratifiés : 45 single · 20 lot · 20 coincard/capsule (pièges FP) · 15 vrais-lots-titre · 10 au-choix.
- **Labellisés par LLM-professeur (vision)** : chaque agent *ouvre* l'image (outil Read sur le chemin local) et compte les **pièces physiques distinctes**, avec règles strictes :
  - avers+revers d'**1** pièce = **1** (2 disques, 1 pièce) · bimétal = **1** (anneau interne ≠ 2e pièce) · coincard/capsule/coffret = **1** · 2 pièces différentes = **2+** · objet rond non-pièce = **0**.
  - Champs : `n_coins`, `n_disks_visible` (ce qu'un détecteur naïf verrait — mesure le piège front/back), `scene_type` (single_one_face / single_two_faces / multi_distinct / packaged_single / set_or_roll / au_choix_offer / unclear), `is_lot`, `confidence`, `note`.
- **Qualité** : 95 high / 13 med / 2 low → vérité-terrain solide.

### Artefacts & outils (tout dans `ml/state/coin_census_bench/`)
| Fichier | Quoi |
|---|---|
| `bench_v0.json` | **LA vérité-terrain** : 110 items = labels vision joints à `n_crops`/`route_decision`. |
| `analysis_v0.json` | Confusion vision↔détecteur (output du workflow). |
| `manifest.json` | Échantillon (id, raw_path local, titre, n_crops, stratum). |
| `census_label_workflow.js` | Workflow de labelling LLM (prompt + schema + batchs) — relançable via `Workflow({scriptPath})`. |

| Outil (repo) | Quoi |
|---|---|
| `ml/scripts/build_coin_census_bench.py` | (Re)construit `manifest.json` (sampler stratifié + résolution des chemins cache). `--cohort`, `--out`. |
| `ml/scripts/backfill_listing_kind_routing.py` | Re-classe `listing_kind` + re-route les single→lot (quick-win). Idempotent, dry-run par défaut, `--apply`. |

**Reproduire** : `PYTHONPATH=. .venv/bin/python scripts/build_coin_census_bench.py` → relancer `census_label_workflow.js` (vérifier que son `PATH` pointe le manifest) → labels.

⚠️ `bench_v0.json` a été labellisé **avant** le backfill ; ses `route_decision` peuvent dater, mais les labels vision (`n_coins`/`scene_type`) sont la vérité stable. Données **locales** (chemins machine-spécifiques) → non versionnées.

---

## 2. Findings (vision vs détecteur actuel `n_crops`)
| Métrique | Valeur |
|---|---|
| Accord exact `n_crops == n_coins` | **33 %** (37/110) |
| **Sous-compte** (`n_crops < n_coins`) | **63 %** |
| Sur-compte | 4 % |
| **`n_crops=0` sur une pièce visible** | **55 %** (61/110) |
| Vrais lots (vision) | 27/110 |
| **Faux-single** (vrai lot routé pending/single) | **13/27 = 48 %** ⚠️ training poison |
| Faux-lot (vrai single routé review_lot) | 6/83 = 7 % |
| Front/back (1 pièce, ≥2 disques) | 3/110 (rare ici, fréquent en stock réel) |

**Lecture :**
1. **Échec dominant = sous-détection / zéro-crop** (55 %), surtout sur les **pièces emballées** (capsule/coincard/coffret = `packaged_single`, 41/110). Le détecteur est **muet**, pas sur-compteur → problème de **RAPPEL**.
2. **Erreur coûteuse (faux-single) = lots déclarés au titre** : 13/13 ont un marqueur explicite (`3x`, KMS, `8 VALORES`, multi-pays) raté par le regex FR/EN. → corrigé par le quick-win.
3. **Front/back** (avers+revers = 2 disques, 1 pièce) rare ici mais fréquent sur eBay → un détecteur objet naïf compterait 2 → besoin d'une **fusion d'identité**.

---

## 3. Quick-win lot/single — ✅ LIVRÉ (commit `b8fe31c`)

- **Routing via `listing_text_signals.listing_kind`** (multilingue) dans `enqueue._kind_for_source_image`, au lieu du seul `is_lot_suspected` (FR/EN).
- **Vocabulaire enrichi** dans `sources/text_signals/dictionaries.py` : DE/ES/IT/NL (KMS/Kursmünzensatz/Satz/cofre/cartera/divisionale), compteurs `N valores/piezas/münzen/stück/pezzi`, plage `1 cent–2 euro` (`DENOM_RANGE_RE`).
- **Résultat bench** : faux-single **12→4** (les 4 restants = détecteur-only). Faux-lot ~1→4 (surtout des listings réellement multi vus depuis 1 photo + 1 « aus KMS » provenance).
- **Backfill cohorte appliqué** : 175 `listing_kind` reclassés, **9 single→lot** (dont `aae133f1fa` Austria+Italia). `review_single` cohorte 387→378.
- Tests : `ml/tests/test_lot_detection.py` ✅ 14/14.
- **Décision actée** : signal **multi-années retiré** (sur-captait les « pick your year » = 1 pièce). NE PAS le réintroduire sans garde au-choix.

---

## 4. Détecteur visuel — LE prochain chantier (non soluble au titre)

Le résidu : **4 faux-singles « titre nomme 1 pièce / image en montre N »** + les **55 % de zéro-crop** (rappel sur emballé). Le titre ne peut rien y faire — c'est de la compréhension d'image.

**Architecture retenue (cf. README §design)** : `propose (haut rappel, objet pas cercle) → verify is-coin (composite/DINO existants) → fusion d'identité (avers/revers & exemplaires identiques via embedding) → dedup (NMS/concentrique) → count`. **Découplé du crop**, validé bench-first.

**Premier pas (✅ FAIT — cf. §5)** : plafond sans entraînement mesuré sur les 110 du bench. Verdict net : le **rappel est déjà résolu off-the-shelf** par YOLO à seuil bas ; le résidu bascule vers le **sur-comptage** (job dedup/fusion, pas proposeur).

**Briques connues à concevoir** : (a) **fusion d'identité avers/revers** (révélée par le bench) ; (b) gestion **pièces emballées** (capsule/coincard → trouver la pièce dedans) ; (c) **LLM-professeur** pour labelliser plus + bootstrap (compositing synthétique) un YOLO census local.

---

## 5. Plafond SANS entraînement — RÉSULTATS (2026-06-04)

> Mesure locale déterministe (aucun agent LLM, ~0 coût token) via `ml/scripts/measure_census_ceiling.py` sur les 110 raws. Artefact : `ml/state/coin_census_bench/ceiling_v0.json`. Métriques **au niveau du compte** (le bench labellise des comptes, pas des boîtes).

**Proposeurs comparés** : (a) **YOLO-low** = le `coin_detector` existant à conf basse, SANS les filtres stricts de prod ; (b) **FastSAM→DINO** = FastSAM everything (objet, pas cercle) → bbox → is-coin (sim DINO vs ancres 2€-commémo, sweep τ) ; (c) **baseline prod** = `n_crops` actuel (YOLO+Hough+filtres). *(Le Hough nu plein-cadre a été écarté : pathologique — 3-20 s/img, livelock multi-thread — ET inutile, le principe n°1 le bannit déjà.)*

| proposeur | zéro-récup /61 | faux-single /27 ⚠️ | faux-lot /80 | exact pièces | ±1 pièces |
|---|---|---|---|---|---|
| **baseline prod** (aujourd'hui) | **0 %** | **48 %** ☠️ | 5 % | 34 % | 85 % |
| YOLO conf 0.05 | **93 %** | **0 %** ✅ | 81 % | 18 % | 36 % |
| **YOLO conf 0.10** | **89 %** | **0 %** ✅ | 69 % | 25 % | 45 % |
| YOLO conf 0.15 | 79 % | **0 %** ✅ | 65 % | 23 % | 46 % |
| FastSAM propose (pré-verify) | 100 % | 0 % | 100 % | 1 % | 5 % |
| FastSAM→DINO τ0.55 | 93 % | 7 % | 85 % | 15 % | 42 % |
| FastSAM→DINO τ0.60 | 92 % | 15 % | 78 % | 19 % | 46 % |

**Breakdown zéro-récup sur le cas dur `packaged_single`** (18 zéro-crop) : baseline **0 %** → YOLO@0.10 **83 %** → FastSAM **94 %**. Les pièces emballées étaient *vues* par le modèle ; conf=0.35 + filtres stricts (`rmin 0.08`/`low_structure`/`off_edge`) les jetaient.

### Lecture (verdict)
1. **Le rappel n'est PAS le problème dur.** YOLO entraîné (existant) à conf 0.05-0.10 récupère **89-93 % des 55 % zéro-crop** et fait tomber le **faux-single (poison) de 48 % → 0 %**. Récupérable **sans entraînement**, juste en abaissant le point de fonctionnement + relâchant les filtres.
2. **FastSAM→DINO ne bat PAS YOLO-low.** Il sur-segmente plus (faux-lot 78-100 % vs 65-69 %), et le gate is-coin DINO ne sépare pas proprement pièce/non-pièce sur ce bench (les ancres = 2€-commémo *avers* seulement → cents & revers matchent mal ; capsule/fond sont ronds aussi). Monter τ échange du faux-lot contre du faux-single. **SAM2 (lourd, GPU) non justifié** : un proposeur-objet n'apporte rien ici.
3. **Le problème BASCULE vers le sur-comptage** (faux-lot 65-73 %). Sur les singles 1-disque, YOLO tire des boîtes en trop (fenêtre coincard / texte / fragments). C'est le job des étages `verify is-coin → fusion d'identité avers/revers → dedup (NMS/concentrique)` — **en aval du proposeur, qui est déjà résolu**.

### Reco (à ratifier PO)
- **Ne pas entraîner de nouveau détecteur** ni investir SAM2 pour le PROPOSE. Adopter **YOLO-low @ conf ~0.10** comme proposeur haut-rappel (faux-single 0 %).
- **Prochain chantier = l'étage DEDUP + VERIFY + FUSION-IDENTITÉ** sur les boîtes YOLO-low, benché sur ce même bench. Cible : ramener le faux-lot de ~69 % vers les ~5 % de la baseline **sans réintroduire de faux-single**, et faire monter `exact pièces`.
- Limite : `single_two_faces` (avers+revers, 1 seul échantillon ici) = le cas que SEULE la fusion d'identité résout. Bench à étendre côté front/back avant de conclure sur cet étage.

---

## 6. Gotchas / leçons (pour la prochaine session)
- **Per-image vs per-listing** : le bench labellise `n_coins` PAR PHOTO ; le routing est PAR LISTING. Un set (CARTERA/KMS) vu via une photo à 1 pièce → « faux-lot » au sens image, mais lot correct au sens listing. Pour le **training** (on crope la photo), c'est le compte PAR IMAGE qui prime.
- **Multi-années = piège** : ≥3 millésimes capture les offres « au choix » (1 pièce vendue). Retiré.
- **`aus KMS`** : « depuis un KMS » = provenance d'1 pièce, pas un set → léger FP du token `kms`. Acceptable (1 cas) vu l'asymétrie de coût.
- **Workflow `args`** : lors du 1er run du census, l'`args` n'a pas été transmis au script (`args.path` undefined) → 0 agent. **Fix** : hardcoder le chemin dans le script du workflow (ou un agent Phase-0 qui lit le fichier), pas compter sur `args`.
- **Bench limité** : mix-zone-17 uniquement, front/back sous-représenté (3/110). L'étendre (autres cohortes / stock eBay large) avant de conclure sur le détecteur.
- **HoughCircles `param2` bas = piège mortel** : à `param2≈22`, HoughCircles devient pathologique (3-20 s/img, jusqu'au **livelock multi-thread** — 20 min CPU observé) ET sort 50-87 « cercles » sur une pièce unique. Toujours `cv2.setNumThreads(1)` + `param2≥35` + downscale ≤1024 si on doit en faire. Mieux : ne pas compter de cercles bruts du tout (principe n°1).
- **SAM everything-mode sur Mac** : MobileSAM/SAM2 everything = **25-40 s/img** (CPU **et** MPS) à cause de la grille de prompts 32×32 — non viable pour un sweep. **FastSAM** (YOLOv8-seg, 1 passe) = **~0.3 s/img** : c'est l'outil pour Mac. SAM2 « vrai » → réserver au GPU CUDA (1080Ti).
- **Profiling > extrapolation** : le coût « 8 s/img » mesuré sur 5 images était l'**amortissement du warmup**, pas un coût par image (YOLO post-warmup = 0.04 s/img). Toujours profiler load vs steady-state séparément avant d'extrapoler.
