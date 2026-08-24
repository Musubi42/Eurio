# Phase 0 — Lecture de l'audit (priorisation P1–P5)

> Interprétation du tableau de bord `phase0-audit.md` (généré par
> `ml/scripts/audit_dino_suggestions.py`, re-runnable). Rédigé le 2026-06-11.
> Set = 478 crops décidés en review (vérité terrain), banque 508 ancres
> `2eur_commemo`, encodeur `dinov2-vits14`.

## TL;DR

1. **Le spread (top1−top2) est le signal d'abstention, pas la sim.** La sim
   top1 ne sépare RIEN : médiane hors-scope 0.834 ≈ médiane correcte 0.836.
   Le spread sépare bien : médiane 0.047 (correct) vs 0.010 (faux) vs 0.006
   (hors-scope). Un seuil spread ≥ 0.05 donne 91.7 % de précision et élimine
   100 % du hors-scope observé (au prix de 52.6 % des corrects perdus →
   seuil à calibrer, 0.02–0.03 est le compromis).
2. **P1 (trou de scope) est confirmé mais sous-mesuré** : 8.8 % de
   hors-scope sur le set décidé — toutes des 2€ courantes — mais le set est
   biaisé (le pipeline n'enqueue que des cibles commémo ; le lot kickoff de
   24 courantes est 100 % `open`). Le vrai taux en production est plus haut.
3. **P2 (biais pays) est non mesurable sur ce set** : 1 seul crop avec pays
   vérité ≠ pays cible. Sur les listings mono-pays (99 % du set décidé), la
   bande pays AIDE massivement : 90.7 % recall@5 vs 71.6 % global. Le fix P2
   doit donc garder le prior pays sur les lots mono — exactement le « prior
   souple » du kickoff.
4. **P3 (sim peu discriminante) confirmé** : même in-scope et avec le bon
   pays, global@1 = 53.6 % seulement, et les distributions de sims
   correct/faux se chevauchent largement (0.70–0.90 des deux côtés).

## Chiffres clés

| Métrique | Valeur |
|---|---|
| Recall@1 / @5 global (in-scope) | 53.6 % / 71.6 % |
| Recall@1 / @5 bande pays (in-scope, mono-pays) | 73.8 % / 90.7 % |
| Hors-scope (vérité pas dans la banque) | 8.8 % (42/478, 100 % courantes) |
| Sim top1 médiane correct / faux / hors-scope | 0.836 / 0.761 / 0.834 |
| Spread médian correct / faux / hors-scope | 0.047 / 0.010 / 0.006 |
| Abstention spread ≥ 0.02 | précision 74.3 %, élimine 83.3 % du hors-scope |
| Abstention spread ≥ 0.05 | précision 91.7 %, élimine 100 % du hors-scope |

## Caveats (à garder en tête)

- **Circularité** : le reviewer voit les suggestions Dino quand il décide →
  le set décidé sur-représente les cas où Dino était bon. Les recalls
  ci-dessus sont **optimistes**. Indice : le segment `decided_face=unknown`
  (46 crops) est à 100 % recall@5 — vraisemblablement des validations
  directes de suggestion.
- **P2 invisible** : pour mesurer le biais pays il faut labelliser des lots
  multi-pays (ex. le lot kickoff `267449922852`, 24 crops open). Tant que ce
  n'est pas fait, l'effet P2 reste qualitatif.
- Pas de prédiction stale détectée (3/478 sans prédiction seulement).
- `quality_score` n'existe que sur 119/478 → segmentation qualité non
  significative (la largeur de crop ne discrimine rien : tout ≥ 200px).

## Priorisation issue des chiffres

| Rang | Levier | Justification chiffrée |
|---|---|---|
| 1 | **P5 abstention par spread** | Signal déjà dans la DB, zéro ML, élimine 83–100 % du hors-scope selon seuil. Débloque aussi P1 (tant que la banque est trouée, l'abstention protège). |
| 2 | **P1 banque courantes** | 8.8 % mesuré = plancher ; les lots de courantes sont aujourd'hui du bruit pur (recall 0 % par construction). |
| 3 | **P2 prior souple** | Coût actuel quasi nul sur le set décidé (mono-pays), mais bloquant pour reviewer les lots multi-pays — à livrer AVEC le labelling de ces lots pour le mesurer. |
| 4 | **P3/P4 encodeur + metric-learning** | Plafond réel : 53.6 % global@1 même in-scope. Gros chantier, à attaquer une fois 1–3 posés et le set de vérité élargi (re-mesure automatique via le script). |

## Prochains chunks proposés (Phase 1)

1. **Chunk 1.1** — Abstention spread dans l'endpoint review + UI « incertain /
   hors scope » (seuil percentile, cf. `feedback_dino_thresholds`).
2. **Chunk 1.2** — Banque `2eur_standard` via design groups
   (`_fetch_standard_candidates`) + routage par kind.
3. **Chunk 1.3** — Détection lot multi-pays → ranking global en tête, pays en
   prior souple ; puis labelliser le lot kickoff pour mesurer P2 réellement.

Chaque chunk re-passe `audit_dino_suggestions.py` pour mesurer le delta.
