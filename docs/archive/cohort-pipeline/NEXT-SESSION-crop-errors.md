# Prompt de reprise — réduire RÉELLEMENT les erreurs de crop

> Copie-colle le bloc ci-dessous dans une nouvelle session Claude Code. Tout y est : où lire, ce qui marche, ce qui a échoué, et comment reprendre proprement.

---

```
CONTEXTE — Reprise du chantier "réduire les erreurs de crop eBay" (Eurio, repo
/Users/musubi42/Documents/Musubi42/bizz/Eurio).
Conventions : ml/.venv, lancer depuis ml/ avec PYTHONPATH=. (préfixe PYTHONWARNINGS=ignore) ;
eurio.db = ml/state/eurio.db (source de vérité) ; toujours `go-task` (jamais `task`) ;
lire CLAUDE.md (R0 = zéro dette) ; commits autorisés par chunk validé ; flux chunk-audit
(livrer + attendre rétro, ne pas enchaîner sans "go").

⚠️ LIRE D'ABORD (tout y est) :
  - docs/cohort-pipeline/census-detector-design.md   ← LE doc du sous-chantier (§5 plafond, §6 v1+audit,
                                                        §7 extension banque négatif, §8 câblage prod+re-crop test)
  - docs/cohort-pipeline/coin-census-bench.md         ← méthodo bench + gotchas
  - docs/cohort-pipeline/README.md                    ← journal du chantier parent
  - mémoires : project_coin_census_detector, project_crop_quality_overhaul,
               project_cohort_training_pipeline, feedback_subagent_model_and_workflow_args

OBJECTIF RÉEL : faire produire au détecteur des CROPS PROPRES, prêts pour le training (pas de
zéro-crop sur pièce visible, pas de fragments). Le but final = pouvoir ADOPTER le mode census en
prod (flag EURIO_CENSUS_DETECT) sans noyer la review de déchets.

OÙ ON EN EST (sous-chantier "détecteur census" CLÔTURÉ, 7 commits sur branche sources-jo-wikipedia,
du `25fb85f` au `114e00b`) :
  ✅ CE QUI MARCHE (acquis, ne pas refaire) :
   - Le RAPPEL est résolu off-the-shelf, SANS entraînement : le YOLO coin_detector existant à conf 0.10
     (au lieu de 0.35 prod) + sans les filtres stricts (rmin 0.08, low_structure, off_edge) récupère
     ~89% des 55% zéro-crop et fait tomber le faux-single (poison) de 48%→0%. C'étaient conf+filtres qui
     jetaient des pièces VISIBLES (surtout emballées capsule/coincard).
   - v1 "census-ladder" livrée : scan/census.py (① nms_concentric avec gardes taille≥0.7×+bord ;
     ② is_coin = sim DINO vs banque coin-ness + structure-guard). Tests tests/test_census.py (10 ✅).
   - Harnais de bench : scripts/measure_census_ceiling.py (proposeurs yolo/sam/ladder, métriques
     zero_recovery/false_single/fs_real/false_lot/exact sur ml/state/coin_census_bench/bench_v0.json,
     110 raws labellisés vision). Métrique clé fs_real = poison RÉEL (vrai lot aux pièces VISIBLES vu ≤1).
   - Flag prod EURIO_CENSUS_DETECT=1 (OFF par défaut, chemin prod byte-équivalent) câblé dans
     scan/normalize_snap.detect_circles_multi. Comparateur scripts/compare_census_recrop.py (mesure pure,
     ne mute PAS la base) : rendement crop prod vs census par classe + contact sheet.

  ❌ CE QUI A ÉCHOUÉ / LES MURS (ne pas re-tenter à l'identique) :
   - Le gate is-coin ② (sim DINO ≥ τ) ÉCHANGE poison↔faux-lot ~1:1 → PAS adopté. Les vraies pièces en
     lot (usées/inclinées/glare/revers) scorent aussi bas que le clutter ; aucun τ global ne sépare.
   - Extension banque coin-ness (cause B, +81 crops validés hors-bench) = NÉGATIF (mêmes lots échouent ;
     données propres épuisées : le reste = needs_review non validé → réinjecterait du clutter).
   - Re-crop test du câblage prod sur at-2002 (46 raws) : 24→126 crops, 21/32 zéro-crops récupérés MAIS
     audit visuel = MAJORITÉ DE FRAGMENTS (bouts de lettres R/RO/EUR, anneaux internes, bords partiels).
     → census en prod échangerait zéro-crops contre crops-fragments. Pas adoptable tel quel.

LE VRAI PROBLÈME À RÉSOUDRE MAINTENANT = la FRAGMENTATION (cause A) :
  YOLO@0.10 détecte des BOUTS de pièce (lettres, anneau interne) SANS détecter la pièce entière → il n'y
  a pas de boîte parente pour que nms_concentric les absorbe → ils deviennent des crops séparés = déchets.
  C'est un problème de PROPOSEUR (pas d'is-coin). C'est LE blocage pour la qualité de crop en prod.

PISTES CONCRÈTES (à explorer, bench-first, par ordre de promesse/coût) :
  1. Signal "pièce ENTIÈRE vs fragment" GÉOMÉTRIQUE, sans data (le plus prometteur) : le pipeline calcule
     déjà un cercle (cx,cy,r) par boîte via Hough+rim-refine. Un fragment n'a pas d'anneau complet/centré.
     Réutiliser la logique de measure_tilt (scan/crop_detectors.py : Canny sur l'anneau + couverture
     angulaire arc_coverage + fitEllipse) pour exiger un RIM circulaire complet → rejeter les arcs
     partiels / crops décentrés. Ça filtre les fragments sans toucher au rappel des vraies pièces.
  2. Containment/clustering : regrouper les boîtes très proches/chevauchantes et ne garder que la
     DOMINANTE par cluster (la pièce entière englobe ses fragments). Variante de nms_concentric avec
     un clustering spatial plutôt que pur concentrique. ⚠️ NE PAS re-fusionner 2 pièces distinctes d'un
     lot (asymétrie : poison > review) — garder les gardes taille+bord.
  3. Option B (probe is-coin entraînée) reformulée comme "pièce entière vs fragment/clutter" (pas
     "coin vs non-coin", qui a échoué car les fragments SONT coin-like). ~150 ex. labellisés depuis le
     re-crop test at-2002 (le contact sheet donne déjà des positifs/négatifs évidents). Régression
     logistique 1 couche sur features DINO. Plus lourd, garder en réserve si 1+2 ne suffisent pas.
  4. (lourd, dernier recours) retrain du coin_detector YOLO pour qu'il sorte des boîtes pièce-entière
     plutôt que des fragments à bas seuil. À ne tenter que si tout le reste plafonne.

COMMENT MESURER (bench-first, R0) :
  - Pour la QUALITÉ de crop (≠ comptage) : utiliser scripts/compare_census_recrop.py --target <eurio_id>
    --contact-sheet out.jpg (mesure pure, ne mute pas la DB). Définir une métrique "taux de fragments" :
    labelliser à la main (ou via LLM-vision, cf. census_label_workflow.js) un petit set de crops at-2002
    "pièce entière / fragment / vide" → driver le taux de fragments ↓ en gardant le recall ↑.
  - Réutiliser l'infra crop-quality existante : /crop-bench (admin), ml/state/crop_scores/gold/crop_gold.jsonl,
    scan/crop_detectors.py. Cf. mémoire project_crop_quality_overhaul.
  - Cible chiffrée à viser : sur at-2002, garder ~21/32 zéro-crops récupérés MAIS ramener les 126 crops
    vers ~le nb réel de pièces (≈ 40-60 ?) en coupant les fragments — SANS retomber sous le recall prod.

PRINCIPES NON-NÉGOCIABLES (issus de tout le chantier) :
  - Asymétrie de coût : à compte/qualité incertains, pencher LOT/garder (un faux-single = poison training ;
    un faux-lot/crop en trop = une review). Mais ici l'objectif bascule vers la QUALITÉ → un fragment
    validé par erreur = poison aussi. Le bon arbitre = l'humain en review + un filtre anti-fragment fiable.
  - JAMAIS compter/juger des cercles Hough bruts (anneau bimétal/capsule/fenêtre = FP). Raisonner OBJET.
  - JAMAIS mettre des images du bench dans une banque/probe (= fuite → mesure faussée). Set d'extension =
    image_assets validés (manual/auto_phash/training_eligible) HORS source_image_id du bench.
  - Le flag EURIO_CENSUS_DETECT doit rester OFF par défaut (0 impact prod) tant que la qualité n'est pas là.
  - Si un workflow multi-agent : Sonnet (pas Opus) pour les subagents, args typés (incident ~100$ passé),
    et pour de l'audit/perspectives indépendantes — PAS pour écrire du code couplé.

GOTCHAS (gagner du temps) :
  - HoughCircles param2 bas (~22) = livelock multi-thread (20 min CPU) ET inutile → cv2.setNumThreads(1)
    + param2≥35 + downscale ≤1024 si jamais besoin.
  - Mac suffit largement (YOLO 0.04s/img, FastSAM 0.3s/img). SAM2/MobileSAM everything = 25-40s/img → GPU only.
  - Profiler load vs steady-state séparément (le "8s/img" était du warmup amorti, pas un coût/img).
  - L'API admin tourne sur 127.0.0.1:8042 (pas 8000). Le backend uvicorn peut mouliner à ~97% CPU
    (watcher --reload) → un restart le calme, sans impact fonctionnel.

PREMIER PAS PROPOSÉ : relire census-detector-design.md (§6/§7/§8), puis sur at-2002 (classe affamée déjà
étudiée) lancer compare_census_recrop.py pour re-voir les 126 crops census, prototyper le filtre
anti-fragment GÉOMÉTRIQUE (piste 1, rim-completeness via Canny+arc_coverage), mesurer le taux de fragments
avant/après, et présenter les chiffres au PO AVANT de câbler quoi que ce soit. On avance bench-first,
on regarde les chiffres, on discute, on commit par chunk validé.
```

---

*Généré 2026-06-05 — récap du sous-chantier détecteur census (commits `25fb85f`→`114e00b`).*
