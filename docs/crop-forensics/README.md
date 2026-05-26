# Crop Forensics — chantier autonome

> Améliorer le crop natif (pipeline YOLO+Hough+polish) **sans dépendre des 340
> captures cohorte** ni d'un ré-entraînement modèle. Travail itératif piloté
> par observation visuelle + théorie + expérimentation.

## Objectif

Réduire le taux de "mauvais crops" produits par `ml/scan/normalize_snap.py`
sur les listings eBay réels. "Mauvais" = un humain (Raphaël) regarde la
sortie et juge qu'elle ne correspond pas à la pièce attendue : undercrop
bimétal, mauvaise pièce dans un album, fond capturé, etc.

Critère de succès : sur un échantillon représentatif d'image_assets du run
`059dc8d9` (2 € commémo 2010-2020), la proportion de "mauvais crops"
descend, mesurable visuellement via le bench `/bench/runs/{id}/crops#crop`.

## Contraintes

- **Pas de retrain YOLO** (YOLO11-nano embarqué, hors scope ici).
- **Pas de capture cohorte** (les 340 photos device sont pour l'ablation
  format, autre chantier).
- **Modifications légales** : algorithmique pure (heuristiques OpenCV,
  post-traitement Python), ou re-paramétrisation du pipeline existant.
- **Mesure** : visuelle (bench page) + scriptable (sample → assertion).

## Méthode de travail

```
   ┌─────────────────┐
   │ OBSERVATION     │ ← screenshots via headless Chrome, inspection visuelle
   └────────┬────────┘
            │
   ┌────────▼────────┐
   │ THÉORIES        │ ← hypothèses falsifiables, 1 fichier .md / théorie
   └────────┬────────┘
            │
   ┌────────▼────────┐
   │ RECHERCHE       │ ← web search via subagents, état de l'art coin recog
   └────────┬────────┘
            │
   ┌────────▼────────┐
   │ EXPÉRIENCE      │ ← scripts dans ml/scripts/crop_exp/, mesure A/B
   └────────┬────────┘
            │
   ┌────────▼────────┐
   │ COMMIT ou TUER  │ ← si win : merge into normalize_snap. Si lose : doc.
   └─────────────────┘
                 ↑
                 │
            BACK AND FORTH
```

## Règle "petits fichiers"

Aucun fichier markdown > ~200 lignes. Si une analyse grossit, splitter
en plusieurs fichiers thématiques. Permet de feed un subagent avec juste
le bout pertinent (pas tout le chantier).

## Index

- **Contexte**
  - [00-context.md](./00-context.md) — d'où on part (chunks 1-3)
  - [01-known-limits.md](./01-known-limits.md) — ce qu'on sait déjà cassé
- **Observations**
  - [inspection-log.md](./inspection-log.md) — running log
  - [findings/](./findings/) — résultats d'analyses ponctuelles
- **Théories**
  - [theories/README.md](./theories/README.md) — index avec statut
- **Expériences**
  - [experiments/README.md](./experiments/README.md) — index avec verdict
- **Handoffs**
  - [handoffs/](./handoffs/) — briefs courts pour subagents

## Statut

Chantier ouvert le 2026-05-26. Piloté par Claude en autonomie. Toute
décision majeure (changement de cap, fin de chantier) doit remonter à
Raphaël avant exécution.
