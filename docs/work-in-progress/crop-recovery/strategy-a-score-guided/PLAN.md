# PLAN — Stratégie A (chunks)

> Pré-requis : le **banc partagé (Chunk 0)** existe et expose l'interface `recrop()` + les
> jeux D1/D2/D3. Sinon, le construire d'abord (cf. `../BENCHMARK.md`).

## Chunk A1 — Générateur de candidats + recherche de score
- `recrop()` : balayage de rayon autour du `hint`, score probe gelée, argmax, retour de la
  liste scorée. Coarse-to-fine.
- **Livrable** : `recrop()` branché au banc, 1er passage sur **D2 EMU/globe**.
- **Mesure** : % récupéré + score médian du meilleur candidat vs baseline.

## Chunk A2 — Calage de la recherche (range, granularité, recentrage)
- Sweeper les hyper-params (rayon min/max, nb de paliers, balayage de centre on/off) sur D2.
- Trouver le **K minimal** (nb de scores DINO) qui plafonne la récupération.
- **Mesure** : récupération D2 vs K (courbe coût/gain).

## Chunk A3 — Gardes anti-sur-crop & multi-pièces (non-régression)
- Borne de rayon + pénalité fond + garde voisin-aware (lots).
- **Mesure** : **D3** complet — rétention `success`, fragments toujours coupés, pas de
  sur-crop sur lots. Doit passer les gardes de `../BENCHMARK.md` §6.

## Chunk A4 — Run de banc complet + RESULTS.md
- Lancer A sur D1 + D2 + D3, écrire le JSON + `RESULTS.md`.
- **Mesure** : tableau final D1/D2/D3, prêt pour le front et l'évaluateur hybride.

## (Optionnel A5) Intégration prod derrière flag
- Brancher dans `normalize_listing` (census) derrière un flag env, **sans** changer le
  défaut. À ne faire qu'après accord PO sur le résultat du banc.
