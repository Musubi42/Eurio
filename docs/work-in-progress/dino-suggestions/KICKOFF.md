# Kick-off — Améliorer les suggestions Dino (review)

> **Hand-off pour une nouvelle session (Fable 5).** Niveau : cadrage + pistes.
> L'investigation profonde et le benchmark sont à mener PAR la nouvelle session.
> Rédigé le 2026-06-11 après une session UX review lot.

---

## 0. TL;DR

Les **suggestions Dino** (colonne droite de la review) sont souvent inutiles sur
les lots eBay « diverses pièces / divers pays ». Cas observé :
`ebay_v1|267449922852|...` — *« 2 Euro **Kursmünze** 2011 — Diverse Länder nach
Wahl »* : 24 crops de **2€ courantes de pays différents**, et Dino ne propose
quasi que de la Belgique (la cible du listing) ou des commémoratives sans rapport.
La bonne pièce n'est souvent ni dans le top-K, ni trouvable en recherche libre
(le reviewer ne connaît pas la pièce).

**Objectif** : que la liste Dino propose la bonne pièce en tête (ou s'abstienne
honnêtement) sur un éventail bien plus large de pièces.

**Périmètre validé (PO)** : **tout, séquencé** — d'abord les gains structurels
(scope + biais pays), puis l'investissement ML (encodeur / metric-learning).
**Contrainte PO** : ne PAS retoucher la technique de crop (hors sujet ici).

---

## 1. Les 5 problèmes (du plus structurel au plus profond)

| # | Problème | Effet | Levier |
|---|----------|-------|--------|
| **P1** | **Trou de scope** : la banque d'ancres est `2eur_commemo` UNIQUEMENT (`is_commemorative=1`). Les **2€ courantes** (Kursmünze) et les autres dénominations ne sont **pas** dans la banque. | Un lot de courantes est 100% hors-scope → suggestions = commémo la moins éloignée = bruit. | Élargir la banque (courantes via `design_groups`, puis autres dénominations). |
| **P2** | **Biais pays faux sur lots multi-pays** : la bande « PAYS CIBLE XX » filtre les ancres au pays de la cible du listing. Sur un lot « divers pays », chaque crop est d'un autre pays → le biais est nuisible. | La bonne pièce (souvent meilleure sim globale) est reléguée en *fallback* sous des candidats faux du pays cible. | Détecter les lots multi-pays → ranking global par défaut, pays = prior souple seulement. |
| **P3** | **Sim peu discriminante** : `dinov2-vits14` (plus petit ViT) sur des euros qui se ressemblent (format, étoiles, métal) → sims **gonflées et tassées** (0.70–0.82 sur des faux, spread ~0.026). | La bonne pièce hors top-K même quand elle EST dans le scope. Cf. mémoire « Dino inflate sim sur euros ». | Encodeur plus fort + **domain adaptation** + **metric-learning (ArcFace)**. |
| **P4** | **Écart de domaine + crops denses** : ancres = **avers catalogue Numista propre** ; query = **photo eBay bruitée**, et sur les lots denses le crop est **basse résolution** (~166×166, sombre). | Embeddings query/ancre dans des distributions différentes → matching dégradé. | Ancres issues de vraies photos / multi-vues / augmentation (P4 ⊂ P3). PAS de retouche crop (PO). |
| **P5** | **Pas d'abstention** : hors scope ou spread faible, l'UI affiche quand même une liste classée trompeuse. | Le reviewer perd du temps sur des suggestions fausses au lieu de passer en recherche libre / skip. | Seuil de confiance → « incertain / hors scope » explicite (lié au consensus d'auto-validation). |

**Pour le cas montré** : P1 + P2 expliquent l'essentiel de l'échec. P3/P4 sont le
plafond de qualité une fois le scope et le biais réglés.

---

## 2. Architecture actuelle (pointeurs code)

Pipeline : `crop (image_asset)` → encode DINOv2 → cosine top-K contre une banque
d'ancres → persistance → endpoint review → colonne droite.

- **Encodeur** : `DEFAULT_ENCODER_VERSION = "dinov2-vits14"` (torch.hub
  `facebookresearch/dinov2`). Module : `ml/training/foundation/` (encoder +
  matching). 1 vecteur par crop.
- **Banque d'ancres** : `ml/training/foundation/anchors.py`
  - `anchors_kind` actuel : **`2eur_commemo` seulement**.
  - Source d'une ancre : **avers canonique Numista** = `datasets/{numista_id}/obverse.jpg`
    (`_select_2eur_commemo` + `_resolve_obverse_path`), **1 ancre par pièce**.
  - Fichier : `ml/state/foundation_anchors_2eur_commemo.npz` (508 ancres).
  - ⚠️ **Bug de chemin corrigé le 2026-06-11** (`ML_DIR` pointait sur
    `ml/training/` → banque introuvable → tout recompute Dino échouait en
    silence). Garder `ML_DIR = …parent.parent.parent`.
- **Prédiction** : `predict_and_persist_one` dans
  `ml/sources/_base/steps/auto_validate.py` → calcule `top_k` (global) ET
  `top_k_country` (`top_k_match_country`, filtre ancres `eurio_id[:2] == pays cible`).
  Upsert `image_asset_dino_predictions`.
- **Endpoint review** : `ml/review/review_queue_routes.py`
  - `_build_dino_response` + `get_dino_suggestions` (`/asset/{id}/dino-suggestions`).
  - `_lazy_compute_dino` : calcule à la volée si la prédiction manque (self-heal).
  - Candidats « standards » (design groups) : `_fetch_standard_candidates`
    (`canonical_obverse_url`, COALESCE `design_group_id`) — **infra déjà là pour
    le scope courantes**.
- **Frontend** : `admin/.../review/composables/useDinoSuggestions.ts`,
  `ReviewRightColumn.vue`, `LotReviewDetailPage.vue` (bande « SUGGESTIONS DINO »
  pays-cible puis « TOUTE LA BANK — fallback »).
- **Consensus / auto-validation** : `compute_auto_validate_view`,
  `consensus_verdict` (seuils dans `foundation/thresholds.py`) — c'est là que
  l'abstention (P5) doit se brancher.

---

## 3. Plan séquencé

> Démarrer par **Phase 0** (objectiver), puis Phase 1 (structurel), puis Phase 2 (ML).

### Phase 0 — Audit chiffré (à faire par la nouvelle session)
But : remplacer les impressions par des chiffres avant de coder.
- Construire un **petit set labellisé** (crops review déjà décidés = vérité terrain).
- Mesurer : **% de crops hors-scope** (la vraie pièce n'est pas dans la banque) ;
  **recall@1 / @5** global vs bande-pays ; **distribution des sims top1** (vraies
  vs fausses) ; **spread** vrai-positif vs faux-positif.
- Segmenter par : courante vs commémo, lot multi-pays vs mono, qualité crop.
- Livrable : un tableau de bord (même brut) qui priorise P1–P5 par impact réel.

### Phase 1 — Gains structurels (fort levier, risque faible)
1. **Scope courantes (P1)** : nouvel `anchors_kind` (ex. `2eur_standard`) bâti
   sur les **design groups** standard (avers national, `_fetch_standard_candidates`
   donne déjà le représentant). Décider : banque unifiée vs banques par kind +
   routage. Réutiliser `build_anchors_*` / `save_anchors`.
2. **Biais pays multi-pays (P2)** : détecter le lot multi-pays (titre
   « divers/diverse/mixed/Länder », `is_lot_suspected`, ou incertitude pays
   par-crop) → **ranking global en tête**, pays = prior souple (re-rank léger),
   pas un filtre dur. Adapter l'UI (ne plus reléguer le global en « fallback »
   quand le pays cible n'a pas de sens).
3. **Abstention (P5)** : seuil sim/spread → état « incertain / hors scope »
   explicite (brancher sur le consensus). Mieux qu'une fausse liste.

### Phase 2 — Investissement ML (plafond de qualité)
4. **Encodeur (P3)** : tester `dinov2-vitl14` / `vitg14` (ou un backbone fine-tuné).
   Re-bâtir la banque au même encodeur (le `encoder_version` est tracé dans le
   `.npz` et les prédictions). Mesurer recall vs coût.
5. **Domain adaptation (P4)** : ancres depuis de **vraies photos** (pas que le
   catalogue), **multi-vues** par pièce, augmentation (patine/éclairage). Cf.
   `project_overlay_textures_procedural`.
6. **Metric-learning ArcFace (P3)** : séparer les euros qui se ressemblent.
   Recherche déjà amorcée (cf. §5). Label = `design_group` (cf.
   `project_arcface_design_group_label`). Converger avec l'embedding scan device.

---

## 4. Critères de succès

- **Recall@1 / @5** sur le set labellisé Phase 0, segmenté courante/commémo et
  multi/mono-pays. Cible chiffrée à fixer après l'audit.
- **Précision d'abstention** : quand Dino dit « incertain », il a souvent raison
  (ne pas masquer de vraies bonnes réponses).
- **Couverture de scope** : % de crops dont la vraie pièce est dans la banque
  (doit monter franchement après Phase 1.1).
- Non-régression sur le scope commémo actuel (le `.npz` 508 ancres reste bon).

---

## 5. Pointeurs lecture (à lire en début de session)

**Recherche existante :**
- `docs/research/arcface-few-shot.md` — metric-learning few-shot (P3/6).
- `docs/research/embedding-vs-classification.md` — embedding vs classif.
- `docs/research/detection-pipeline-unified.md` — pipeline YOLO+Hough+ArcFace rerank.
- `docs/research/prompt-embedding-scalability.md`.
- `docs/work-in-progress/training-pipeline/harvest/phase-1-dinov2-bring-up.md` — bring-up DINOv2.
- `docs/archive/.../auto-validation/dino-verifier-kickoff.md` — kickoff vérif Dino (archivé).

**Mémoire (recall) :**
- `feedback_dino_thresholds` — Dino inflate la sim sur euros ; seuils percentile.
- `project_arcface_design_group_label` — ArcFace label = design_group.
- `project_design_groups_standards` — grouper standards par avers (pour P1).
- `project_data_referential` — eurio_id canonique, ArcFace dual-usage.
- `project_review_lot_crop_reconciliation` — contexte review + bug chemin ancres.

**Code (entrées) :** `ml/training/foundation/{anchors.py, auto_validate.py}` ·
`ml/sources/_base/steps/auto_validate.py` (`predict_and_persist_one`) ·
`ml/review/review_queue_routes.py` (`_build_dino_response`, `_lazy_compute_dino`,
`_fetch_standard_candidates`) · `foundation/thresholds.py`.

---

## 6. Notes pour la session Fable 5

- **Commencer par Phase 0** : ne pas coder avant d'avoir chiffré (le PO veut
  objectiver, pas deviner). Le set de vérité = crops déjà décidés en review.
- **Doctrine repo** : chunks 30 min–3 h, livrer + attendre rétro (cf.
  `feedback_chunk_audit_flow`) ; pas de dette (R0) ; `go-task` (pas `task`) ;
  SQLite `eurio.db` = source de vérité ; admin exempté du proto-first.
- **Ne PAS** toucher la technique de crop (décision PO).
- **Encodeur lourd** : prévoir le coût GPU (Mac M4 / 1080 Ti) ; le `encoder_version`
  est tracé partout → un changement impose de re-bâtir banque + prédictions.
- **Garde scope** : tant que la banque ne couvre pas une pièce, l'abstention (P5)
  vaut mieux qu'une fausse suggestion — c'est un livrable Phase 1 à part entière.
