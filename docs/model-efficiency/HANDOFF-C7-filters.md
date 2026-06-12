# HANDOFF — Qualité de la cascade de filtres du scan (pour Fable 5 / workflows)

> **But** : améliorer **et garantir la qualité** de *chaque* filtre du scan, de bout
> en bout — vrais crops, vraie pièce, bonne face, bonne dénomination, bonne identité.
> Écrit le 2026-06-13 après livraison du gate dénomination (C7 pilier 2). Ce doc est
> pensé pour être pris par **Claude Fable 5 en workflows** (fan-out, vérif
> adversariale, loop-until-dry). Lis d'abord [C7](./C7-robust-scan-classification.md)
> et [HANDOFF-C7](./HANDOFF-C7.md) (cadrage pilier 2).

## 0. TL;DR — où on en est

La cascade (Stage 0→3) filtre un crop pour décider s'il est identifiable et le route.
Deux gates **zéro/léger-training** sont **livrés et en prod** ; les autres étages
existent mais ont des **trous de rappel/robustesse non chiffrés**. Le travail restant
est surtout de la **qualité** : élargir les golds, chiffrer le rappel, vérifier
adversarialement les décisions, durcir les classes faibles.

| Étage | Filtre | Statut | Métrique connue | Trou principal |
|---|---|---|---|---|
| 0 | Vrai crop (cercle/tilt/fragment) | ✅ prod (`normalize_snap`, `census`) | crop_gold | sous-crop bimétal 2€ (anneau perdu) |
| 0 | Vraie pièce vs dessin/3D/carton/répliq/slab | ❌ inexistant (pilier 3, H8) | — | aucun détecteur image |
| 0 | Non-pièce dans lots (médaille/jeton/mire/logo) | 🟡 partiel via gate dénom | gold denom (médailles 5/8, mire 1/6) | sous-captés (cents dominent) |
| 1 | Face avers vs revers commun 2€ | ✅ prod | FP 0 %/562 avers | **rappel wild non chiffré** (gold 40 revers) |
| 2 | Dénomination « est-ce un 2€ » | ✅ prod (2026-06-13) | AUC 0,922 · 99,5 % 2€ gardés | médailles/mires + gold 153 neg |
| 2 | Identité texte (serveur) | ✅ prod | 69,7 % @ 94,5 % | rappel/couverture langues |
| 2 | Identité DINO top-K (proposer) | ✅ prod | vitl14 80,9 % hit@5 | confond designs proches |
| 3 | Routage confiance (consensus) | ✅ prod | — | calibration des seuils |

**Principe directeur (mesuré cette session)** : pas de gate par **seuil de
similarité** ni par **couleur** (les 2€ usés/tonés/colorisés, et les crops saturés
rouge, trompent) → **probe sur embeddings DINO gelés** + features physiques en
auxiliaire. La **vision PROPOSE l'identité, ne vérifie pas une cible** (diag ccproxy).

## 1. Infra, conventions & garde-fous (À LIRE avant tout workflow)

- **Benchmark-first / R0** : mesurer avant d'optimiser ; aucun seuil bâclé. Chaque
  hypothèse = une entrée Hx dans `C7-*.md` (registre H7→H11bis). Un filtre ne se
  câble **qu'après** validation R0 (ne pas droper les vrais positifs).
- **eurio.db = source de vérité**, lease tenu par une machine (cf.
  [[eurio-db-scratch-on-pc]]). `go-task ml:db:release` en fin de session.
- **⚠️ Contrainte cache crops (IMPORTANTE pour les workflows)** : les crops vivent
  dans MinIO (`enrichment-crops`). En local seuls les crops **déjà cachés**
  (`~/.cache/eurio/enrichment-crops/…`) sont lisibles ; un fetch frais peut renvoyer
  **403** selon la clé/env, et le MCP minio écrit hors-box. ⟹ un workflow de
  labelling/mining doit **filtrer sur les crops cachés** (`local_cache.cache_path_for(...).exists()`)
  ou tourner sur une machine où le fetch est autorisé. Sinon `FileNotFoundError`/403.
- **Pattern gold/bench (à RÉUTILISER tel quel)** : un `*_gold.jsonl` figé +
  un `bench_*.py` qui mesure + des **montages-contact** PNG pour vérif visuelle (le
  labelling humain/Claude passe par là). Exemples : `face_bench/`, `denom_bench/`.
- **224² = résolution native** des crops (dans une photo de lot 1600px une pièce ≈
  223px) → pas de re-crop source à gagner ; le plein détail est déjà là.
- **R1 proto-first** pour toute UX Android/admin nouvelle (`scene-parity.md`).
- **Encodeur** : DINOv2 **vitl14** pour suggestions/face/dénom (`SUGGESTIONS_ENCODER_VERSION`),
  vits14 pour consensus. Réutiliser le `vec` déjà encodé (gratuit) quand possible.

## 2. Patterns de workflow recommandés (le cœur du handoff)

Chaque filtre se durcit avec les **mêmes** patterns. Fable 5 doit composer ceux-ci :

1. **Mine → pré-label → vérif adversariale** (élargir un gold) :
   - fan-out de mineurs (par bande de score, par teinte, par run, par bucket) qui
     proposent des candidats sur les **crops cachés** ;
   - un pré-labeller (DINO/probe + heuristiques) assigne une classe + confiance ;
   - **N vérificateurs adversariaux** par candidat douteux (lens différents :
     couleur, design, contexte listing-texte) → garder si majorité confirme ;
   - les `conf=lo`/ambigus → montages pour confirmation **humaine** (toujours le juge
     final sur cent-vs-2€-usé : Claude s'y trompe, cf. crops saturés rouge).
2. **Cross-run generalization** : entraîner/figer sur run A, **mesurer sur run B**
   held-out. Un filtre n'est « robuste » qu'avec un chiffre cross-run (≠ in-sample).
3. **Adversarial false-drop / false-keep hunt** : fan-out d'agents qui cherchent
   activement des **vrais positifs droppés** (R0 !) et des **négatifs gardés**, en
   re-regardant les crops à la frontière du seuil. Sortie = hard examples → gold.
4. **Loop-until-dry** sur le mining de hard-negatives : répéter mine+vérif jusqu'à K
   tours sans nouveau hard example (le rappel sur la queue se gagne dans la traîne).
5. **Completeness critic** : un agent final « qu'est-ce qui manque ? » (une classe
   non couverte, une langue de texte, un design proche non testé, un run non backfillé).

## 3. Travaux par filtre (tâches concrètes, priorisées)

### A. Gate dénomination (Stage 2) — DURCIR (le plus proche du done)
État : probe DINO+bimétal en prod, AUC 0,922, seuil t=0,24 (99,5 % 2€ held-out). Gaps :
1. **Médailles / mires / jetons / sets sous-captés** (médaille 5/8, mire 1/6) car les
   **cents dominent** les 153 négatifs. → mining ciblé de **non-pièces** (workflow
   pattern 1) : médailles « Monnaie de Paris », mires de couleur, logos, sets
   multi-pièces, pièces étrangères. Re-entraîner, re-mesurer par **kind**.
2. **Gold encore modeste** (229/153). Loop-until-dry de hard-negatives (cents usés,
   nordic gold proches du centre or des 2€) + hard-positives (2€ tonés/colorisés/usés
   proches du seuil). Viser un gold équilibré ~500/500 multi-run.
3. **Cross-run** : backfill + mesure sur un run autre que 059 (pattern 2). Le seuil
   t=0,24 tient-il ? Re-calibrer si le rappel 2€ < 99 % cross-run.
4. **1€** (bimétal, hors scope 2€) : aujourd'hui rangé en `not_2eur`. Vérifier qu'il
   est bien droppé (un 1€ n'est pas la cible) et ne pollue pas les positifs.
   Code : `vision/denom_probe.py`, `scripts/{train_denom_probe,bench_denom,backfill_denom}.py`,
   gold `state/denom_bench/denom_gold.jsonl`, dict éditable `scripts/_seed_denom_gold.py`.

### B. Gate face (Stage 1) — CHIFFRER LE RAPPEL
État : précision excellente (FP 0 %/562), mais **rappel wild non chiffré** (gold = 40
revers seulement, τ conservateur, 2 ancres canoniques). Gaps :
1. **Élargir le gold revers** par mining + vérif (les 231 `face=reverse` détectés à
   marge élevée sont des candidats) → fixer τ sur **précision ET rappel** (pattern 1).
2. **Robustesse v1/v2** : tester l'ajout de quelques ancres de revers **wild**
   (usés/inclinés) à la banque `reverse_2eur` → devrait monter le rappel à précision
   constante. Re-bench `bench_face_detection.py` (FP doit rester ~0 sur 562 avers).
   Code : `scripts/bench_face_detection.py`, `state/face_bench/face_gold.jsonl`,
   `training/foundation/anchors.py` (`build_anchors_reverse_2eur`).

### C. Stage 0 — qualité de crop (sous-crop bimétal)
État : crop OK en général, mais **sous-crop des 2€ bimétal** (disque or gardé, anneau
argent perdu) — cf. [[crop-bimetal-harden]]. C'est un problème de **détection** (pas
de marge) qui dégrade *aussi* le gate dénom (un crop sans anneau n'a pas de signal
bimétal, cf. H10 cause 2) ET le matching ArcFace.
1. Bench le taux de sous-crop sur un gold de 2€ (anneau présent/absent), via
   `census.py`/`crop_detectors.py` (Hough concentrique conscient du bimétal).
2. Workflow : fan-out de détecteurs (Hough/ellipse/otsu) + vote → meilleur rayon
   externe. Mesurer la baisse du sous-crop, puis l'effet sur dénom + identité.
   Code : `vision/crop_detectors.py`, `vision/census.py`, contrat de sortie cross-platform
   (cf. [[output-contract-parity]] : train↔Android ε sur la sortie, pas même impl).

### D. Stage 0 — authenticité / non-pièce (pilier 3, H8) — CONSTRUIRE
État : **aucun détecteur image** de dessin / rendu 3D / impression carton / réplique
plastique / slab. Recouvre B/C (médailles, mires). Hypothèse H8 (forte, non mesurée).
1. **Construire un gold** par mining (marqueurs texte « replica/copy/copie », +
   curation visuelle) — pattern 1, loop-until-dry.
2. Tester une **coin-ness DINO** (banque `foundation_coinness.npz` — **absente** sur
   desktop, build archivé `archive/scripts/build_coinness_bank.py` à ressusciter) :
   rejette-t-elle médailles/mires/logos/dessins ? Sinon, probe dédiée 2€-réel-vs-faux.
   Note : une **probe unique « 2€ réel vs tout »** pourrait subsumer B-non-pièce + D
   (les négatifs du gold dénom contiennent déjà médailles/mires). À benchmarker.

### E. Identité (Stage 2) — texte & DINO top-K — AMÉLIORER LE RENDEMENT
1. **Texte** (69,7 % @ 94,5 %) : couverture multilingue, rappel sur titres pauvres.
   Code : `listing_text_signals`, `serving/*` (auto-attribution). Cf.
   [[h4-zeroshot-beats-arcface-review]] (texte 75,8 % @ 94,9 % en auto-attribution).
2. **DINO top-K** (vitl14 80,9 % hit@5) : confusions entre **designs proches**
   (mêmes monuments/portraits). Workflow : panel de juges par design-cluster +
   confirmation top-1 par un appel cher (H9 : retourner la question Claude =
   confirmer le top-1 DINO au lieu de vérifier une cible — **non mesuré**, à tester).
3. **H4 confirmée** : zero-shot vitl14 > ArcFace en review (62,8 % vs 28,7 % top-1
   gold eBay). En tenir compte pour le rerank.

### F. Routage confiance (Stage 3) — CALIBRER
Le consensus (texte+dino+crop_quality) fixe la lane. Workflow : mesurer la
calibration des seuils sur un gold de décisions (auto/humain/junk), chercher les
mauvaises routes (un vrai 2€ identifiable parti en junk = R0). Code :
`review/review_lanes.py`, `consensus_verdict`.

## 4. Carte du code (sources de vérité)

- **Cascade & routing** : `sources/_base/steps/{auto_validate,enqueue}.py`
  (détecteurs réutilisent le `vec` vitl14 ; rejet **per-crop** ré-ouvrable ;
  `_route_decision_for_source_image` → buckets funnel ; **jamais rejeter la photo
  entière** d'un lot mixte → garde les avers).
- **Gates livrés** : face = `auto_validate._decide_face` / `enqueue` `face_reverse` /
  `scripts/backfill_face.py`. dénom = `vision/denom_probe.py` /
  `enqueue` `not_2eur` (`_DENOM_ENGINE_VERSION`) / `scripts/backfill_denom.py`
  (`go-task ml:backfill-denom`).
- **Signaux physiques** : `vision/denom_geometry.py` (`bimetal_score`),
  `vision/crop_detectors.py`, `vision/census.py` (`nms_concentric`, coin-ness).
- **Colonnes** : `image_assets.{face,denom}` (verdicts, écrits si NULL = anti-clobber),
  `image_asset_dino_predictions.{reverse_sim,face_margin,denom_2eur_score}` (audit/ranker).
- **Bench/gold** : `scripts/{bench_face_detection,bench_denom,train_denom_probe}.py`,
  `state/{face_bench,denom_bench}/`, montages `*_verify.png`/`band_*.png`.
- **Funnel** : `serving/bench_routes.py` (`_HUMAN_REASON`),
  `admin/.../bench/pages/BenchRunAuditPage.vue` (`REASON_LABELS`, drill par
  `route_decision`/`route_reason`). ⚠️ le grid montre la **photo brute du listing**,
  pas les crops — prévoir un affichage crop-level pour un labelling efficace.

## 5. Garde-fous spécifiques workflow

- **R0 d'abord** : tout durcissement de gate doit prouver le **false-drop des vrais
  positifs** sur un held-out (la face : FP 0 %/562 ; la dénom : 99,5 % 2€/419). Un
  workflow qui resserre un seuil sans ce chiffre est invalide.
- **Humain = juge final** sur les classes ambiguës (cent usé vs 2€ usé, colorisés,
  capsules). Les workflows **proposent** ; ils ne figent pas un gold sur les `conf=lo`
  sans confirmation. (Claude s'est trompé sur 23/144 candidats — partiels & saturés.)
- **Idempotence & sticky** : écritures only-if-NULL, rejets ré-ouvrables, garde
  `/restore` humain sticky (cf. `backfill_*`). Ne jamais clobber un label humain.
- **Contrainte cache/403** (cf. §1) : scoper les mineurs sur les crops **cachés**.
- **Parité de sortie** train↔device : ε sur la **sortie sémantique**, pas même impl
  (cf. [[output-contract-parity]]).

## 6. Ordre suggéré (si Fable démarre à froid)

1. **A.1–A.2** (durcir dénom : non-pièces + hard-negatives, loop-until-dry) — le plus
   proche du done, valeur immédiate sur la review polluée.
2. **A.3** (cross-run) — chiffrer la généralisation, re-calibrer le seuil si besoin.
3. **B** (chiffrer le rappel face) — petit gold, fort levier.
4. **D** (authenticité/coin-ness) — construire le gold manquant ; tenter la probe
   unique « 2€ réel vs tout ».
5. **C, E, F** — qualité crop, identité, calibration routage.

Chaque étape : gold → bench → (workflow mine/vérif) → mesure → câblage **seulement si
R0 tient** → backfill → funnel. Tout nouveau résultat = une entrée Hx dans `C7-*.md`.
