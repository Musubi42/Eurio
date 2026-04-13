# Eurio — Design docs

> Un dossier par vue (ou groupe de vues cohérent). Chaque dossier contient un `README.md` qui sert d'ADR de la vue : objectif, décisions tranchées, questions ouvertes, liens vers les sous-docs de recherche.
>
> Les décisions transverses (auth, stockage local, stratégie offline) vivent dans `_shared/` et sont référencées depuis chaque vue.
>
> **Dernière mise à jour** : 2026-04-13
> **Scope v1** : Onboarding + Scan + Coffre + Profil. Explorer et Marketplace sont explicitement hors scope.

---

## Conventions

- **README.md d'une vue** = ADR de la vue. Lead avec l'objectif UX, puis décisions prises, puis questions ouvertes.
- **Sous-docs de recherche** = fichiers thématiques dans le dossier de la vue (ex : `scan/ux-research.md`, `scan/ml-pipeline.md`).
- Ne jamais dupliquer ce qui est déjà dans `docs/research/` ou `docs/phases/` — **lier**.
- Ne pas écrire de code Kotlin ici. Ces docs guident l'implémentation, ils ne sont pas le code.
- Quand une décision est prise en conversation, la capturer dans le README de la vue avec la date.

---

## Transverses

- [`_shared/offline-first.md`](./_shared/offline-first.md) — Qu'est-ce qu'on ship dans l'APK, qu'est-ce qu'on fetch, stratégie de mise à jour des modèles ML et des métadonnées pièces.
- [`_shared/auth-strategy.md`](./_shared/auth-strategy.md) — Auth silencieuse/différée, pattern Duolingo, Credential Manager Android, upgrade anonymous → compte complet.
- [`_shared/data-contracts.md`](./_shared/data-contracts.md) — Schema Room local, mapping avec le schema canonique Supabase, points de synchronisation.

## Vues v1

| Vue | Statut | Lien |
|---|---|---|
| Onboarding | À designer | [`onboarding/`](./onboarding/) |
| Scan | ML prêt (Phase 2B en cours), UX à designer | [`scan/`](./scan/) |
| Fiche pièce | À designer (vue partagée paramétrée) | [`coin-detail/`](./coin-detail/) |
| Coffre | À designer | [`vault/`](./vault/) |
| Profil | À designer | [`profile/`](./profile/) |

## Vues hors scope v1

- **Explorer** — reporté après la beta. Le coffre + le scan couvrent le core loop. On reviendra dessus quand la v1 sera stable.
- **Marketplace** — Phase 2+ du produit, conditionne la stack auth complète, le paiement Stripe, le listing, etc. Pas dans ce dossier pour l'instant.

---

## Process

1. On brainstorme une vue en conversation.
2. Les décisions partent dans le README.md de la vue, avec une ligne de contexte.
3. Les questions ouvertes restent ouvertes — pas de décisions forcées.
4. Quand la vue est "assez designée", on passe à l'implémentation Kotlin Compose.
5. Si l'impl révèle un problème de design, on revient ici et on met à jour le README.
