# Plan — sessions à exécuter

> **Fichier mutable.** À chaque fin de session, mets à jour les statuts
> et ajoute les sessions découvertes. Pas plus d'**un objectif par
> session**.
>
> Statuts : ⬜ pending · 🟡 in-progress · ✅ done · ❌ refuted · ⏸ paused

## Sessions

### S1 ✅ Composite scorer is_coin (théorie 04)

Verdict : asymétrique. TOP 83 % cat D, BOTTOM 30 % A+B.
→ [experiments/01](../experiments/01-composite-scorer-ab-d.md)

### S2 ✅ Brancher composite = tri par défaut UI

Backend : `_load_composite_scores` + sort `score_desc/asc`. Frontend :
badge `s 0-100` sur cards + 2 boutons sort.
→ commit `5a5184d`

### S3 ✅ Unified score v2 (composite × area_ratio_factor)

Verdict : marginal. TOP 85 % D (+2), BOTTOM 27 % A+B (-3). Théorie 04
refuted. Scoring global échoue car B et C ont tous deux area_ratio bas.
→ [experiments/02](../experiments/02-unified-score-v2.md)

### S4 ❌ Anti-A dédié — bg_uniformity (théorie 01)

Verdict : refuted — double échec.

1. `bg_uniformity` (std hors disque) : dégénéré, normalize_snap masque le
   fond en noir → 80.9 % des crops ont std=0.
2. `near_white_ratio` (V>220 dans disque intérieur, révisée) : TOP-30
   ≈ 10 % cat A, dominé par pièces surexposées (cat D). Seuil 80 % non atteint.

**Cause racine** : flash/lightbox photographique → V >> 220 sur métal
réfléchissant → indiscernable de papier blanc.

→ [experiments/03](../experiments/03-anti-a-bg-uniformity.md)

### S5 ❌ Anti-B dédié — inner_feature_score (théorie 02)

Verdict : refuted comme anti-B *pur*.

Scope : DE / 2 € / 2010 (221 assets, 74 raws). Distribution saturée
(99 % ≥ 1.3). TOP-30 ≈ 13 % cat B (~22 cat C album, ~4 cat B macro,
~3 cat D, 0 cat A — filtré par "circle contient bbox"). Seuil 80 % loin.

Le filtre ne discrimine pas B vs C : un album multi-pièces a toujours un
gros cercle plausible englobant un des bboxes par géométrie.

→ [experiments/04](../experiments/04-anti-b-inner-feature.md)

### S6 ❌ inner_feature_score × singles (théorie 02 conditionnelle)

Verdict : marginal, refuted comme anti-B *strict*.

Deux filtres testés sur DE/2010 :
- `is_lot_suspected=0` (167 raws) : pas d'amélioration vs S5, collector
  folders pas flaggés `lot` polluent toujours TOP-30 (~70 % cat C).
- `n_crops_detected=1` (30 raws true singles) : signal plus propre, mais
  TOP-30 cat B fort ≈ 33-40 %. Loin du seuil 80 %.

Le score reste **un proxy d'undercrop général** (corrèle visuellement
avec la qualité), pas un détecteur cat B spécifique.

→ [experiments/05](../experiments/05-anti-b-inner-feature-singles.md)

**Théorie 02 archivée comme post-filter**. Pour fixer cat B sans
modifier le producer il faudrait un signal "rim circulaire manquante à
un radius supérieur au bbox" — plus sophistiqué, non priorisé.

### S7 ⬜ Reject auto à 2 thresholds indépendants

Pré-requis : S4 OU S5/S6 win.

**Objectif** : poser un `auto_reject_reason` calculé côté backend en
combinant les 2 signaux :
- `composite < 0.2 AND bg_uniformity > t_bg` → `reject: not_a_coin`
- `area_ratio < 0.05 AND inner_feature_score > t_inner` → `reject: undercrop_b`

**UI** : ajouter sort `reject_first` + filter `auto_rejects_only`.
**Pas de modification de la DB** (pas de status auto-rejected) — seulement
calcul dérivé. Le pipeline ingère, l'orchestrateur affiche.

### S8 ⬜ Adopter v2 comme default sort (au choix)

Si on veut pousser le tri v2 (composite × area_ratio_factor) dans le
backend. Petit changement : `_load_composite_scores` lit le sidecar
`_v2.json` si présent, sinon `.json`. Pas urgent — v1 est déjà OK.

### S9 ⏸ Théorie 03 — area_ratio noisy

Marqué pausée : on a déjà appris en S3 que area_ratio est utile mais
insuffisant seul. À reprendre seulement si on veut un seuil adaptatif
par cat de raw (album vs single).

## Sessions futures candidates

### S10 ⬜ OCR léger sur bbox (anti-A)

**Objectif** : tester un OCR ultra-léger (tesseract ou easyOCR) sur le
crop pour détecter présence de digits → marqueur cat A (strip
numérique). Cibler les crops avec composite bas + near_white_ratio
moyen. Test ciblé sur ~50 cards visuellement identifiées cat A dans le
run V.3.

**Décision** : à valider avec Raphaël avant de coder (coût modéré,
dépendance externe à installer dans le venv).

### S11 ⬜ Décision produit — clore vs continuer

Après S5+S6 refuted, théorie 02 morte, théorie 01 morte. Reste :
- théorie 03 (area_ratio adaptive, paused)
- théorie 02b (re-rank Hough upstream, hors-scope "post-filter")
- OCR anti-A (S10)

→ Discuter avec Raphaël : (a) on continue avec S10/théorie 02b, ou
(b) on accepte le composite v1 (livré S2) comme état final et on clos
le chantier, ou (c) on pivote vers un classifier ML léger
(cat A/B/C/D) entraîné sur des labels Raphaël manuels.

## Backlog (idées non-priorisées)

- OCR léger sur la bbox pour détecter cat A (digits = strip) — voir S10
- Couleur dominante : bronze/cuivre/argent → metal, sinon flag
- Périodicité radiale : un strip a une période courte, une pièce non
- Adaptive area_ratio threshold selon raw dimensions / aspect
- Crop quality histogram par groupe (DE-2010 a 73 % undercrops vs FR-2018 38 %)
