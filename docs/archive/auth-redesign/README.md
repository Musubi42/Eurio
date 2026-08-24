# auth-redesign — ARCHIVÉ

> 🗄️ **Archivé le 2026-08-24.** Chantier clos : le backend auth (C1→C4) et le front
> (F1→F9) sont livrés et déployés depuis le 2026-06-19.
>
> Les décisions vivantes sont sorties d'ici :
> **[ADR-010](../../adr/010-authentik-oidc-et-pat.md)** (Authentik + PAT + RBAC) et
> **[ADR-011](../../adr/011-front-admin-unique.md)** (front unique — le pivot dual-front
> décrit dans `ARCHITECTURE.md` a été abandonné dix jours après avoir été décidé).

## Ce que ce dossier garde

| Fichier | Pourquoi le lire encore |
|---|---|
| `DESIGN.md` | la cible auth telle que validée le 2026-06-19, avec ses 9 décisions D1-D9 |
| `ARCHITECTURE.md` | le pivot dual-front, et pourquoi le mixed content l'avait motivé |
| `ROADMAP.md` | le statut final de chaque chunk (C1-C9, F1-F9, D1-D7, K1-K4) |
| `PAT-WORKFLOW.md` | comment générer / coller / révoquer un PAT — **encore opératoire** |
| `Cx-HANDOFF-*.md` | les handoffs d'implémentation. C6/C7/C8/C9 sont périmés par le pivot |

## Ce qui reste ouvert, et où

- **K2** — retrait de `admin/packages/review/` et de `eurio-review.musubi.dev` :
  lot 9 de [`review-collaborative-v2/`](../../work-in-progress/review-collaborative-v2/).
- **F4** — recette manuelle d'un PAT réel bout en bout : [`docs/BACKLOG.md`](../../BACKLOG.md).
