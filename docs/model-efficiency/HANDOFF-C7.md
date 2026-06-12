# HANDOFF — C7 : scan robuste (cascade face / dénomination / authenticité)

> Passation pour une **nouvelle session**. Pilier 1 (face avers/revers) **livré**.
> Ce doc cadre le **pilier 2 (gate dénomination « est-ce un 2€ ? » + authenticité)**,
> qui est ce que l'utilisateur a identifié comme manquant. Écrit le 2026-06-12.

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

1. **Bimétal géométrique** (le plus prometteur) : 1€/2€ sont **bimétal** (anneau +
   disque) ; 1/2/5 ct (cuivre) et 10/20/50 ct (nordic gold) sont **monométal**.
   Un détecteur anneau-concentrique + couleur (cuivre vs or vs bi-couleur) sépare
   nettement. Réutiliser `ml/vision/crop_detectors.py` (`measure_tilt`,
   `ring_contour`, Hough concentrique) + `ml/vision/census.py` (`nms_concentric`,
   déjà conscient du bimétal sur 2€). ⚠️ 1€ est aussi bimétal — mais hors scope des
   recherches 2€, et discriminable par taille relative / couleur d'anneau.
2. **Probe DINO dénomination** : petit classifieur logistique sur embeddings DINO
   (comme la probe fragment dormante `census.py:230`) entraîné 2€ vs autres-denoms.
   Gold : les 231 face=reverse + 2046 obverse confirmés sont 2€ ; miner des 1/2/20
   ct depuis les crops de lots (face_margin≈0, top1_sim bas) + curation visuelle.
3. **Suppression au niveau lot** : repenser si **tous** les crops d'une photo de
   lot doivent partir en review 2€. Un lot mixte → peut-être ne garder que les
   crops bimétal. Lien : `_kind_for_source_image` (lot detection, enqueue.py) +
   la review lot UI.

Métrique cible : précision/rappel du gate « est-ce un 2€ » sur un gold de crops
lot labellisés (denom). Semer le bench comme `bench_face_detection.py`.

## 3. Autre amélioration (pilier 1, optionnelle) — rappel revers wild

Le détecteur de face a une **précision excellente mais un rappel incomplet** (τ
conservateur, 2 ancres canoniques propres). Les revers *wild* (usés/inclinés)
sous le seuil sont ratés. Fix mesurable : **enrichir la banque `reverse_2eur`**
avec un échantillon de revers wild vérifiés (parmi les 231 `face=reverse` détectés,
margin élevé) → couvre les conditions réelles, devrait monter le rappel à τ
constant (précision préservée car même design). À tester via `bench_face_detection`
(FP doit rester ~0 sur les 562 avers).

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

## 5. Premiers pas (nouvelle session)

1. Lire [C7](./C7-robust-scan-classification.md) + ce handoff + `[[h4-zeroshot-beats-arcface-review]]`.
2. Reproduire le constat : run `059dc8d90dad42558e3c6319a722fd35`, groupe AT-2005,
   bucket `multi_coin_photo` → crops 1ct/20ct (montages dans `ml/state/face_bench/`).
3. Décider la piste gate dénomination (§2) — recommandé : **bimétal géométrique**
   (signal physique fort, pas de training). Semer un bench + gold denom d'abord.
4. Optionnel : enrichir les ancres revers (§3) pour le rappel.

## 6. État infra / garde-fous

- **eurio.db canonique** : lease tenu par le PC `desktop` (82 Mo). `ml:db:release`
  en fin de travail avant de reprendre sur le Mac. Cf. `[[eurio-db-scratch-on-pc]]`.
- Règles : benchmark-first (mesurer avant d'optimiser), R0 (pas de seuil bâclé —
  la preuve §1 que le seuil ne sépare pas), R1 proto-first pour l'UX Android
  « retourne la pièce » (`scene-parity.md` : `scan-flip-coin` ❌ à proto'er).
- API locale ML : `go-task ml:api` (:8042) ; front : `pnpm -C admin/packages/web dev`.
