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

**Premier pas proposé** : mesurer le **plafond sans entraînement** sur les 110 du bench — SAM2 (propose) + notre `is-coin`/DINO (verify), et/ou YOLO11 actuel à seuil bas — pour chiffrer combien des 55 % zéro-crop on récupère avant d'investir dans l'entraînement. Métriques : `n_coins` exact / ±1, et surtout le **faux-single rate** (le coûteux).

**Briques connues à concevoir** : (a) **fusion d'identité avers/revers** (révélée par le bench) ; (b) gestion **pièces emballées** (capsule/coincard → trouver la pièce dedans) ; (c) **LLM-professeur** pour labelliser plus + bootstrap (compositing synthétique) un YOLO census local.

---

## 5. Gotchas / leçons (pour la prochaine session)
- **Per-image vs per-listing** : le bench labellise `n_coins` PAR PHOTO ; le routing est PAR LISTING. Un set (CARTERA/KMS) vu via une photo à 1 pièce → « faux-lot » au sens image, mais lot correct au sens listing. Pour le **training** (on crope la photo), c'est le compte PAR IMAGE qui prime.
- **Multi-années = piège** : ≥3 millésimes capture les offres « au choix » (1 pièce vendue). Retiré.
- **`aus KMS`** : « depuis un KMS » = provenance d'1 pièce, pas un set → léger FP du token `kms`. Acceptable (1 cas) vu l'asymétrie de coût.
- **Workflow `args`** : lors du 1er run du census, l'`args` n'a pas été transmis au script (`args.path` undefined) → 0 agent. **Fix** : hardcoder le chemin dans le script du workflow (ou un agent Phase-0 qui lit le fichier), pas compter sur `args`.
- **Bench limité** : mix-zone-17 uniquement, front/back sous-représenté (3/110). L'étendre (autres cohortes / stock eBay large) avant de conclure sur le détecteur.
