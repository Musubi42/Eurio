# Progress — sources refacto

> Append-only. Une entrée par session significative. Format : date,
> phase touchée, ce qui a été fait, ce qui bloque ensuite.

## 2026-05-02 — Doc initiale

- Discussion produit : matrice photos + matrice prix, séparation
  stricte par source, dédup intra-source uniquement.
- Décisions actées (cf. `README.md` § Décisions actées).
- Doc `docs/sources-refacto/` créée avec :
  - `README.md` (vision + index + décisions)
  - `analysis.md` (état par source)
  - `schema.md` (DDL des 2 nouvelles tables)
  - `module-contract.md` (structure `ml/sources/<source>/`)
  - `quality-pipeline.md` (filtre photos)
  - `admin-ux.md` (page détail `/sources/:id`)
  - `phase-1-foundations.md`
  - `phase-2-new-sources.md`
  - `phase-3-quality-pipeline.md`
  - `phase-4-admin-ux.md`
  - `open-problems.md`
- **Aucun code livré.**
- **Prochaine étape** : phase 1 — migration DB + `ml/sources/_base/` +
  refacto eBay.
