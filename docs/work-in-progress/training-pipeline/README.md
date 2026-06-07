# Training pipeline — unifying lab + benchmark + device

> Plan d'unification de la boucle d'entraînement : sélection coins →
> capture device → augmentations → training → benchmark studio →
> comparaison aug↔réelles → app de test custom → live tests device →
> décision/itération.
>
> **Statut : sprints 1-5 LIVRÉS (2026-04-29/30)** — code en place dans `ml/training/`.
> Le chantier suivant `harvest/` (DINOv2 + scraping massif) est **non démarré** (design only).
> Statut détaillé dans `progress.md`. _(Mesuré doc↔code via graphify 2026-06-07.)_

## Pourquoi ce dossier existe

Aujourd'hui les pages `/lab` (cohort + iterations) et `/benchmark` (R@1 sur
photos studio) vivent en parallèle, alors qu'elles devraient être deux faces
d'une même pipeline. La pipeline complète n'existe nulle part : on capture
des photos d'un côté, on lance des augmentations de l'autre, on benchmark
ailleurs, on teste le modèle device avec rien du tout.

Ce dossier décrit **une seule pipeline cohérente** où une cohort est l'unité
de pilotage et où chaque iteration porte tout le contexte reproductible
(recipe, augmentations, modèle, benchmark studio, comparaison aug↔réel,
live tests device).

## Comment lire ce dossier

| Si tu veux… | Lis… |
|---|---|
| Comprendre l'objectif global | [`vision.md`](./vision.md) |
| Voir les décisions architecturales | [`decisions.md`](./decisions.md) |
| Comprendre la structure disque + DB | [`filesystem.md`](./filesystem.md) |
| Connaître le vocabulaire | [`glossary.md`](./glossary.md) |
| Savoir ce qui a été fait | [`progress.md`](./progress.md) |
| Implémenter un sprint | `sprint-N-*.md` |

**Si tu reprends un sprint en cold start**, commence toujours par
`progress.md` puis le `sprint-N-*.md` correspondant. Ce dernier liste les
pré-requis et la doc à lire avant.

## Sprints (résumé)

| # | Titre | Périmètre | Statut |
|---|---|---|---|
| 1 | [Foundation](./sprint-1-foundation.md) | Augmentations stockées sur disque + stop training + recipe interactive | ✅ livré |
| 2 | [Aug vs réelles](./sprint-2-aug-vs-real.md) | Galerie comparison + distance DINO + déprécation `/benchmark` | ✅ livré |
| 3 | [Cohort test app](./sprint-3-cohort-test-app.md) | Gradle flavor cohortTest + build commands surfacées | ✅ livré |
| 4 | [Live tests](./sprint-4-live-tests.md) | Prescription on-device + sync admin + confusion matrix réelle | ✅ livré (device walkthrough non loggé) |
| 5 | [Polish](./sprint-5-polish.md) | Dashboard cross-cohort + GC augmentations + doc finale | ✅ livré (routes /benchmark FastAPI pas encore purgées) |

## Workflow de session avec un agent

1. L'utilisateur dit "agent, fais le sprint N"
2. L'agent lit `progress.md` puis `sprint-N-*.md`
3. L'agent suit les tâches du sprint dans l'ordre
4. À la fin de la session (ou en cas de blocage), l'agent **append** dans
   `progress.md` une entrée datée avec : ce qui a été fait, ce qui marche,
   ce qui est cassé, les écarts vs le sprint doc, les décisions prises
5. Une nouvelle session reprend depuis ce point

`progress.md` est append-only — on ne réécrit pas l'historique, on annote
en bas. Le sprint doc lui peut être édité si on identifie un meilleur plan
(en notant le diff dans progress.md).

## Liens externes

- [`docs/admin/cohort-capture-flow/design.md`](../work-in-progress/cohort-capture-flow/design.md) — la pipeline de capture, déjà livrée, base de tout
- [`docs/scan-normalization/`](../archive/scan-normalization/) — la normalize device
- [`CLAUDE.md`](../../CLAUDE.md) — règles repo (R0 pas de dette, R1 proto-first, etc.)
