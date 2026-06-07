# Auto-validation — index

> Chantier qui ajoute une couche de pré-validation automatique entre
> `detect_crop` et `enqueue` dans la pipeline sources. L'objectif final :
> qu'une majorité de crops scrapés arrivent **directement** sur la page
> Coin (côté Eurio ID) sans passer par la review humaine, et que la
> review humaine ne traite plus que les cas ambigus.

## Ordre de lecture

1. [`vision.md`](./vision.md) — la cible end-state, les principes,
   ce qu'on fait et ce qu'on ne fait pas. **Lire en premier.**
2. [`dino-verifier-kickoff.md`](./dino-verifier-kickoff.md) — kickoff
   technique des chunks (foundation + pipeline + API + front).
3. [`progress.md`](./progress.md) — journal des chunks livrés, chiffres
   mesurés, observations vs théorie, ajustements. **À mettre à jour à
   chaque chunk livré.**

## Sessions à venir

Cf. `vision.md` §"Découpage du chantier" pour le tableau à jour. Pivot
2026-05-05 : insertion d'un chunk 0 *visibilité du stream* avant le signal
texte (le pipeline a déjà des filtres + une trace en DB que le front
n'expose pas). Détails dans `progress.md` §"Pivot 2026-05-05".

## Contexte amont

- `docs/sources-refacto/sessions-overview.md` — ce qu'on a fait sur la
  pipeline scrape avant ce chantier
- `docs/training-pipeline/harvest/auto-validator.md` — design écrit en
  amont du chantier scrape, multi-signal
- `docs/training-pipeline/harvest/phase-1-dinov2-bring-up.md` — plan
  initial du bring-up DINOv2 (que ce chantier consomme)
- `docs/research/_drafts/coin-similarity-encoder-followup.md` — analyse
  de l'inflation Dino sur euros (raison du percentile-based)
