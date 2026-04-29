# Progress log

> Append-only. Une entrée datée par session significative. Quand tu reprends
> un sprint, **lis ce fichier en entier** (au moins les dernières entrées du
> sprint en cours) avant de toucher au code.
>
> Format d'entrée :
>
> ```
> ## YYYY-MM-DD · Sprint N · Session description
>
> **Done** : ce qui a été livré
> **Working** : ce qui marche end-to-end
> **Broken / partial** : ce qui ne marche pas ou est incomplet
> **Deviations from sprint doc** : si on s'est écarté du plan, pourquoi
> **Decisions taken** : choix non triviaux, avec justif
> **Handoff** : ce qu'il faut savoir pour la session suivante
> ```

---

## 2026-04-29 · Sprint 0 · Brainstorm + docs structure

**Done** :
- Brainstorm pipeline complète A→Z avec utilisateur (cf vision.md)
- 7 questions tranchées (cf decisions.md D-001 à D-011)
- Structure docs créée : README, vision, decisions, filesystem, glossary,
  progress, et 5 sprint files
- Plan de 5 sprints validé par l'utilisateur

**Working** : doc structure complète et autoportante.

**Broken / partial** : aucun code écrit, c'est volontaire. Sprint 1 prêt
à démarrer.

**Deviations from sprint doc** : N/A (pas encore de sprint actif).

**Decisions taken** :
- Approche append-only pour progress.md
- Sprint files éditables avec diff noté ici
- Glossary ajouté au plan original (pas dans la demande initiale, jugé
  utile pour cold start des agents)

**Handoff** : commencer par `sprint-1-foundation.md`. Pré-requis listés
dedans. Aucun blocage.

**Etat acquis avant ce sprint** (résumé pour rappel) :
- Cohort capture flow livré (cf `docs/admin/cohort-capture-flow/`).
  Captures device canoniques en `ml/datasets/<numista_id>/captures/`.
- Cache Vue Query + IDB persistence livré sur `/coins` et `/lab`.
  Lookup queries (trained, zones, source-counts) cachées 5min/24h.
- API ML : `/health` est maintenant un liveness probe instantané
  (le rich payload est sur `/health/full`).
- ML_API frontend : `http://127.0.0.1:8042` (évite le retry IPv6
  sur macOS).
- Cohort `green-v1` existante avec 1 pièce
  (`de-2020-2eur-50-years-since-the-kniefall-von-warschau`), status `draft`.

---
