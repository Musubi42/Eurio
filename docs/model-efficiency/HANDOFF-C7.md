# HANDOFF — C7 : scan robuste (cascade face / dénomination / authenticité)

> Passation pour une **nouvelle session**. Pilier 1 (face avers/revers) **livré**.
> Ce doc cadre le **pilier 2 (gate dénomination « est-ce un 2€ ? » + authenticité)**,
> qui est ce que l'utilisateur a identifié comme manquant. Écrit le 2026-06-12.
>
> **⚠️ MIS À JOUR 2026-06-13 (soir) : le pilier 2 est LIVRÉ** — probe v2 dino⊕bm en
> prod (out-of-fold **1,9 % de vrais 2€ perdus / 78,8 % de junk capturé**, seuil
> 0,331), rejet `--reject` armé et validé PO, boucle rétroactive tour 1 bouclée
> (gold 952 rows, 19 vrais 2€ rescued+restaurés). Les §1-§2 ci-dessous restent
> valables comme **diagnostic historique** ; l'état courant et la suite sont dans
> [C7 §H11/H11bis/H12](./C7-robust-scan-classification.md) et le §5 réécrit.

## 0. Où on en est

Chantier [C7](./C7-robust-scan-classification.md) = rendre la classification d'un
crop robuste via une **cascade** : Stage 0 (vraie photo de pièce unique) → Stage 1
(face) → Stage 2 (identité texte+DINO) → Stage 3 (confiance). Diagnostic d'origine :
la lane ccproxy/Claude « pourrie » posait la mauvaise question ; la vision doit
**proposer une identité** (DINO top-K), pas vérifier une cible.

**Pilier 1 — face avers vs revers commun 2€ : LIVRÉ** (commits `16496f65`,
`29d8c021`). Détecteur zéro-training `face=reverse si sim_revers − sim_avers ≥ τ`
(τ=0,05), câblé dans `auto_validate.py` (réutilise le vec vitl14), rejet
`face_reverse` (pattern consensus factorisé), bucket cliquable dans le funnel
bench, backfill (`ml:backfill-face`). Mesuré : 0 % FP sur 562 avers, backfill
231 reverse / 2046 obverse. **Ça marche et c'est en prod.**

## 1. Le problème à traiter (pilier 2)

**Constat utilisateur** (run `059dc8d…`, groupe AT-2€-2005) : le grid de review est
pollué par des pièces **qui ne sont pas des 2€** (1 cent, 2 cent, 20 cent).

**Cause racine mesurée** : ces crops viennent de **photos de LOTS** (le vendeur
photographie une collection entière). Le détecteur de crop crope **toutes** les
pièces, y compris d'autres dénominations. Le détecteur de face les compare aux
ancres avers/revers **2€**, aucune ne matche → `face_margin ≈ 0` → étiqueté
`obverse` par défaut → part en review comme un faux « avers 2€ ».

**Le funnel isole déjà le problème** : sur AT-2005, les **165 crops `needs_review`
restants sont TOUS dans les buckets lot** (`multi_coin_photo` 149 +
`is_lot_suspected` 12 + `listing_kind_lot` 4) ; le bucket `single_unmatched`
n'a **aucun** junk en attente. Donc le manque est un **gate de dénomination
DANS les crops de lots**.

**Pas de fix par seuil de similarité** (mesuré, 2026-06-12) — les non-2€
chevauchent les vrais avers 2€ usés :

| Seuil `max(obverse-ness, reverse-ness)` | Junk capturé | Vrais avers 2€ perdus |
|---|---|---|
| < 0,60 | 25 % | 4 % |
| < 0,65 | 46 % | 8 % |
| < 0,70 | 68 % | 16 % |

Distributions `top1_sim` (obverse-ness, banque 2eur_all) :
- avers 2€ humains : p10=0,664 · p50=0,795
- crops leaked (lot AT-2005) : p10=0,507 · p50=0,656

→ Un seuil propre n'existe pas. Il faut un **vrai signal « 2€-ness »**, pas la
similarité aux ancres avers.

## 2. Pistes pour le gate dénomination (à mesurer, benchmark-first)

1. ~~**Bimétal géométrique**~~ → **TESTÉ & RÉFUTÉ comme gate dur (2026-06-13, H10)**.
   `bimetal_score` (contraste chroma a*/b* anneau↔disque, `ml/vision/denom_geometry.py`,
   bench `ml/scripts/bench_denom.py`) : à τ=4 il **false-drop 25 % des vrais 2€**
   (usés/tonés/mal éclairés indistinguables d'une monométal). Distributions qui se
   chevauchent. **Reste utile** comme *ranker doux* (bande score≥18 = ~100 % vrais
   2€) pour le triage de lot (piste 3), **pas** comme porte binaire. Détail : C7 §H10.
2. **Probe DINO 2€-vs-junk** (PISTE PRIMAIRE désormais) : classifieur logistique sur
   embeddings DINO (comme la probe fragment dormante `census.py:230`). Positifs :
   2843 crops `face IN obverse,reverse` (vrais 2€). **Bloqueur mesuré (2026-06-13) :
   le catalogue est 2€-only** → aucun négatif labellisé. Il FAUT curer un gold de
   négatifs. **Gold provisoire déjà labellisé** (pass visuel Claude full-res 2026-06-13) :
   `state/denom_bench/denom_gold.jsonl` = **76 pos / 32 neg / 4 unk**, dict éditable
   `scripts/_seed_denom_gold.py`, verif `gold_verify.png`. 67 `conf=hi` (charts,
   médailles MdP, cents, 2€ nets = ancres sûres) ; 45 `conf=lo` + 4 `unk` (3 crops
   « bleuet » colorisé + 1 obscurci) **à valider humainement** avant d'entraîner.
   NB 224² = résolution native (pièce ~223px dans la photo lot 1600px) → pas de
   re-crop source à gagner. Pas de page web crop-level dédiée (la `crop-bench` Vue
   existe mais générique, non câblée au gold denom). NB la pollution lot dépasse la dénom (médailles « Monnaie de Paris »,
   logos, mire couleurs) → le probe doit viser **2€ vs tout-le-reste**, pas 2€ vs cents.
3. **Suppression au niveau lot** : repenser si **tous** les crops d'une photo de
   lot doivent partir en review 2€. Un lot mixte → peut-être ne garder que les
   crops bimétal. Lien : `_kind_for_source_image` (lot detection, enqueue.py) +
   la review lot UI.

Métrique cible : précision/rappel du gate « est-ce un 2€ » sur un gold de crops
lot labellisés (denom). Semer le bench comme `bench_face_detection.py`.

## 3. Autre amélioration (pilier 1) — rappel revers wild → **FAIT (2026-06-13 soir)**

Le détecteur de face avait une **précision excellente mais un rappel incomplet**
(2 ancres canoniques propres). Mesuré sur les 15 revers wild rescued du tour de
boucle denom : rappel **0 %** à τ=0,05. Fix livré : banque `reverse_2eur` enrichie
de **32 ancres wild vérifiées** (`state/face_bench/reverse_wild_anchors.jsonl`,
curées top-margin hors gold), τ recalibré **0,065** → **FP 0/566 · rappel revers
durs 73,3 % · faciles 100 %** (bench replay `scripts/bench_face_recall.py`,
gold face élargi à 621 rows). Détail : C7 §Caveats pilier 1.

## 4. Carte du code (pilier 1 livré — réutiliser)

- Détecteur face : `ml/sources/_base/steps/auto_validate.py` (`_decide_face`,
  `_get_reverse_bank`, `FACE_REVERSE_TAU`, calcul dans `_run_inner`).
- Banque revers : `ml/training/foundation/anchors.py` (`build_anchors_reverse_2eur`,
  `REVERSE_ANCHORS_KIND`) ; `go-task ml:dino-anchors:build -- --kind reverse_2eur`.
- Rejet/route : `ml/sources/_base/steps/enqueue.py` (`_reject_crop_terminal`
  partagé consensus/face, `_route_decision_for_source_image` → `face_reverse`).
- Backfill : `ml/scripts/backfill_face.py` (`go-task ml:backfill-face`).
- Bench + gold : `ml/scripts/bench_face_detection.py`,
  `ml/state/face_bench/face_gold.jsonl` (+ `mined_candidates.jsonl`, planches
  `band_*.png`, montages diag AT-2005).
- Funnel : `admin/.../bench/pages/BenchRunAuditPage.vue` (rendu générique des
  drops ; `REASON_LABELS`/`DECISION_COLORS`), `ml/serving/bench_routes.py`
  (`_run_groups`/`_run_listings`/`_human_reason`). Le grid drill filtre par
  `route_decision`/`route_reason`. ⚠️ Le grid montre la **photo brute du listing**
  (raw_payload), pas les crops — pour un gate crop-level, prévoir un affichage crop.
- Colonnes audit : `image_asset_dino_predictions.reverse_sim/face_margin`
  (schema.sql + `_ensure_column` connection.py).

## 5. Premiers pas (nouvelle session) — RÉÉCRIT 2026-06-13 soir, pilier 2 livré

Le gate dénomination est en prod (probe v2, C7 §H12). La **boucle rétroactive**
est outillée et a tourné une fois : `harvest_denom_gold.py` (récolte labels) →
`train_denom_probe.py` (entraînement+bench CV) → `--save` + restart API →
`bench_denom_probe.py` (replay) → `backfill_denom.py` (audit puis `--reject`) →
`audit_denom_rejects.py` (planches PO). Prochains pas par ordre de levier :

1. **Tour 2 du gold denom** : faire valider humainement les **27 unk + 60 conf=lo**
   (le sanity hold-out lo est à 27,8 % de perte — labels ambigus, petit volume,
   passe rapide dans l'admin) puis ré-entraîner. Enrichir aussi les négatifs
   médailles/charts (encore minoritaires vs 186 cents).
2. ~~**Pilier 1, rappel revers**~~ → **FAIT le 2026-06-13 soir** (§3) : banque
   enrichie 34 ancres + τ=0,065, FP 0/566, rappel durs 0 → 73,3 %.
3. **Premier run eBay post-gate** : test live de la probe v2 sur des crops frais
   (le rejet à l'enqueue est actif), puis planches + tour de boucle suivant.
4. **Pilier 3 — authenticité** : à cadrer (cf. C7 §Pilier 3).

## 6. État infra / garde-fous

- **eurio.db canonique** : lease tenu par le PC `desktop` (82 Mo). `ml:db:release`
  en fin de travail avant de reprendre sur le Mac. Cf. `[[eurio-db-scratch-on-pc]]`.
- Règles : benchmark-first (mesurer avant d'optimiser), R0 (pas de seuil bâclé —
  la preuve §1 que le seuil ne sépare pas), R1 proto-first pour l'UX Android
  « retourne la pièce » (`scene-parity.md` : `scan-flip-coin` ❌ à proto'er).
- API locale ML : `go-task ml:api` (:8042) ; front : `pnpm -C admin/packages/web dev`.
