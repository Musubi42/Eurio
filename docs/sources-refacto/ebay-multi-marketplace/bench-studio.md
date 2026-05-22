# Studio bench — theme-matcher eBay

> Outil d'audit visuel du theme-matcher : le gold gelé rejoué recherche
> par recherche, pour qu'un humain **juge lui-même** chaque décision de
> filtrage au lieu de faire confiance au juge LLM.
>
> État verrouillé 2026-05-22. Chunks 1 / 2 / images livrés ; le
> ré-étiquetage (chunk 3) est en attente — voir §"Reste à faire".

## Pourquoi cet outil

Le chantier recall du theme-matcher (`theme-matcher-recall-kickoff.md`,
clôturé) s'appuie sur un **gold gelé** de 196 listings eBay réels, chacun
porteur d'un verdict de vérité. Ces 196 verdicts ont été posés par un
**juge LLM** (Claude Code). L'admin voulait pouvoir les juger lui-même —
voir, étape par étape, ce que le pipeline garde et jette, et trancher.

Le studio est ce hublot. Et il a immédiatement prouvé sa valeur : il a
révélé un **bug de catalogue** que personne ne cherchait (voir
§"Découverte").

## Architecture

```
ml/state/discovery_bench/
  theme_match_gold.jsonl   ← le gold gelé (196 listings + verdict humain)
  gold_images.jsonl        ← sidecar : listing_id → URL image eBay
  batch.jsonl, labels.jsonl, groups.json   ← artefacts de construction

ml/scripts/bench_theme_match.py
  replay_bench(conn)       ← rejoue accept_listing + match_listing_to_group
                             sur le gold, rend le détail par listing +
                             les métriques agrégées. Source de vérité
                             unique, partagée CLI ↔ API.

ml/scripts/enrich_bench_images.py
  one-time : remplit gold_images.jsonl (gardés depuis source_images,
  rejetés re-fetchés via Browse API getItem). `go-task ml:bench:enrich-images`

ml/api/bench_routes.py
  GET /bench/theme-match   ← replay + image_url par annonce +
                             contexte des groupes (sœurs : thème, i18n,
                             alias, obverse_url). Lecture seule.

admin/packages/web/src/features/bench/
  pages/BenchStudioPage.vue        ← orchestration, 3 colonnes
  components/BenchMetricsBar.vue   ← bilan global du gold
  components/BenchSearchTabs.vue   ← les 5 recherches eBay
  components/BenchFunnel.vue       ← l'entonnoir-sélecteur
  components/BenchDetailPanel.vue  ← annonces du nœud sélectionné
  components/BenchCoinCard.vue     ← pièce canonique (face + i18n + alias)
  components/BenchListingCard.vue  ← annonce eBay (photo + verdict + lien)
  composables/useBenchApi.ts       ← fetch + dérivation des entonnoirs
```

## La maille : la recherche eBay

L'unité d'audit n'est **ni la pièce ni le listing — c'est la recherche
eBay** : trois critères `(pays, dénomination, année)`. Le gold couvre
**5 recherches** : BE · 2 € · {2017…2021}. Chaque recherche vise N
commémos-sœurs (2017 mono-pièce, les autres 2).

## L'UX — 3 colonnes

| Gauche | Milieu | Droite |
|---|---|---|
| **Pièces canoniques** visées par la recherche — face, thème, titres i18n, alias. Toujours visibles (référence de comparaison). | **Entonnoir** vertical : plaques `brut → passé filtre 1 → retenu` (largeur ∝ compte), transitions = les filtres (`✗ N rejetées · ✓/⚠ M à tort`), branches d'attribution. Chaque nœud est un sélecteur. | **Annonces** du nœud cliqué, en grille de cartes : grande photo eBay, titre, verdict humain, badge d'issue, lien vers l'annonce eBay. |

Au-dessus : le **bilan global** du gold (6 métriques, ★ auto-attribution)
et les **5 recherches** sélectionnables.

Le « à tort » de chaque filtre est posé en comparant la décision du
pipeline au verdict humain du gold — c'est ce qui transforme une simple
visualisation en outil de **jugement**.

## Lancer le studio

```bash
go-task ml:api                         # backend (sert /bench/theme-match)
cd admin/packages/web && pnpm dev      # front → onglet « Studio bench »
go-task ml:bench:theme-match           # le même replay, en CLI
go-task ml:bench:enrich-images         # (ré)enrichir les images du gold
```

Local-only : le front dégrade proprement si le backend ML est éteint.

## Découverte — le bug catalogue Ghent / Liège

En auditant la recherche **BE · 2 € · 2017**, l'admin a vu que la pièce
canonique affichée (« 200 ans université de Ghent ») montrait en réalité
l'**image et les titres i18n de Liège**.

Diagnostic confirmé en base : `training.db` **et**
`ml/datasets/eurio_referential.json` ne contiennent qu'**une** commémo
BE 2017 — `be-2017-2eur-200-years-ghent-university`, numista_id 108778 —
dont les 6 titres i18n et l'image obverse sont **tous Liège**. C'est un
**merge bâclé** : un slug *Ghent* sur des données *Liège*.

Or il existe **deux** vraies pièces (l'admin l'a vérifié dans son
référentiel à jour) :

- `be-2017-2eur-200-years-of-the-university-of-ghent`
- `be-2017-2eur-200-years-of-the-university-of-liege`

Conséquences sur le bench :

1. **Mauvaise image** affichée — l'obverse stocké du coin bâclé est celui
   de Liège.
2. **Le matcher ne peut pas discriminer Ghent/Liège** : (a) les i18n du
   coin sont 100 % Liège → ses tokens discriminants sont des mots
   « Liège » ; (b) 2017 est un **groupe mono-pièce** → verdict `single`
   systématique → toute annonce 2017 auto-attribuée à l'unique coin.
3. Le **gold gelé** étiquette ses ~28 entrées 2017 sur l'eurio_id bâclé.

→ Cause racine : la donnée du catalogue est **désynchronisée** entre ses
multiples lieux de stockage (re-scrape Numista non propagé). Ce n'est pas
un bug du studio ni du matcher — c'est un problème de **données**. Il est
traité dans son propre chantier : `docs/data-harmonization-kickoff.md`.

## Reste à faire

- **Chunk 3 — ré-étiquetage** : corriger un verdict depuis le front
  (réécrit `labels.jsonl` puis relance `ingest`). Conçu, non implémenté.
  **Bloqué/motivé par** l'harmonisation des données : tant que le
  catalogue 2017 n'est pas corrigé (2 pièces), re-juger le gold 2017
  serait prématuré. À reprendre après le chantier harmonisation.
- Quand le catalogue 2017 sera corrigé : re-bootstrapper, re-juger les
  ~28 entrées 2017 du gold (Ghent vs Liège), re-pointer les
  `coin_aliases`, re-bencher.
