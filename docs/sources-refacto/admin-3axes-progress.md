# Progress — Admin 3-axes (Sources / Review / Coins)

> Suivi exclusif des 3 phases du chantier admin 3-axes décidé le
> 2026-05-03. Pour le contexte produit, lire d'abord :
> - `coins-admin-kickoff.md` (vision Coins + 3-axes)
> - `run-breakdown-kickoff.md` (Phase 1)
> - `lot-review-kickoff.md` (Phase 2, V1.5)
>
> Cadence : chunk-by-chunk avec audit visuel — je livre, on review,
> on valide, on continue. Pas d'enchaînement sans "go".

## Vue d'ensemble

| Phase | Objet | Statut |
|---|---|---|
| 1 — Sources | Run breakdown par eurio_id | 🟡 in-progress |
| 2 — Review | Page unique Single \| Lot (V1.5) | ⏸ planifié |
| 3 — Coins | Vue produit agrégée multi-source | ⏸ planifié post-Phase 2 |

## Phase 1 — Run breakdown

| Chunk | Périmètre | Statut | Livré le | Reviewé le |
|---|---|---|---|---|
| RB.A | Endpoint backend + tests | 🟢 livré | 2026-05-03 | ✅ validé 2026-05-04 |
| RB.A+ | via_lot sur les deux axes | 🟢 livré | 2026-05-04 | ✅ validé 2026-05-04 |
| RB.B | Page Vue + nav | 🟢 livré | 2026-05-04 | ✅ validé 2026-05-04 |
| RB.C | Polish UX (rows clickables, header Review, tooltips) | 🟢 livré | 2026-05-04 | ⏳ à reviewer |

### Sessions

#### 2026-05-03 — RB.A livré

- `compute_run_breakdown()` + endpoint `GET /sources/:id/runs/:run_id/breakdown`
  dans `ml/api/sources_routes.py` (~210 lignes ajoutées, dont
  models Pydantic + 2 helpers SQL).
- 6 tests dans `ml/tests/test_run_breakdown.py` : 404, ciblés vides,
  ciblés auto-résolus, ciblés en review (single+lot), bonus via lot,
  run dry sans filtres.
- Suite globale : **72/72 verts** (65 baseline + 6 nouveaux + 1 qui
  n'était pas compté dans la baseline du kickoff).
- **Refacto sémantique post-feedback Raphaël (2026-05-04)** : abandon
  du modèle 2-blocs (targeted/bonus) à cause du double-comptage. Nouveau
  modèle :
  - **Un seul bloc `per_eurio`** (was_targeted=True d'abord, puis
    discovered alphabétique).
  - **Deux axes strictement disjoints** par eurio_id :
    - Search axis (`si.target_eurio_id = E`) : `n_listings` +
      `n_crops_searched` partitionnés en `n_searched_{auto,
      review_single, review_lot, pending, rejected}` (somme = total).
    - Attribution axis (`ia.eurio_id = E AND si.target_eurio_id != E`) :
      `n_attributed_from_other` + `via_lot`.
  - **Ajouts** : `n_searched_pending` et `n_searched_rejected` (demandés
    par Raphaël). `n_searched_pending` exclut les crops ayant une row
    `review_queue` open (sinon double-comptage avec n_searched_review_*).
- Tests : 7/7 verts (404, ciblés vides, ciblés auto+quote, ciblés review
  single+lot, ciblés rejected, attribution via lot, dry sans filtres).
- Suite globale Phase 1 : **73/73 verts**.
- **Reste smoke curl** : serveur tourne sur **port 8042** (uvicorn
  --reload), donc la nouvelle route est dispo sans redémarrage manuel.

#### 2026-05-04 — RB.A+ et RB.B livrés

**RB.A+** : `via_lot` étendu aux deux axes. Désormais `via_lot=true`
si soit l'attribution axis (crops résolus depuis un autre listing
lot), soit le search axis (target qui a ramené un listing
is_lot_suspected ou multi-crop). Helper `_has_lot_context` ajouté.
Tests : 7/7 verts (1 assertion ajustée).

**RB.B** : page `/sources/:id/runs/:run_id` opérationnelle.
- `useRunBreakdown.ts` : composable + types + `RunBreakdownError`
  (~70 lignes).
- `SourceRunDetailPage.vue` : ~360 lignes. Header (run_id, source,
  status pill, started_at, count ciblés/découverts). 2 sections :
  - **Ciblés** : tableau dense 12 colonnes (eurio_id cliquable copy,
    n_listings, n_crops, partition exhaustive search axis colorée
    par signal, n_attributed_from_other, n_quotes, badge lot, lien
    review). Ligne Total en bas.
  - **Découverts** : tableau réduit (eurio_id, attr, lot, quotes, review)
    visible seulement si non-vide.
  Légende en pied pour expliciter la sémantique des colonnes.
- Route `/sources/:id/runs/:run_id` ajoutée dans `app/router.ts`.
- `SourceDetailPage.vue` : rows table runs cliquables (hover bg +
  navigation, exclu si click sur un bouton enfant comme "log").
- Type-check `vue-tsc` : 0 erreur sur nos fichiers (les erreurs
  préexistantes dans `features/sets/` ne sont pas touchées).
- Tests Python : 73/73 verts.

#### 2026-05-04 — RB.C (polish UX) livré

Feedback Raphaël après revue RB.B → 3 ajustements :
1. **Rows entières cliquables** dans les deux tableaux (Ciblés +
   Découverts), avec hover bg `var(--surface-1)` (mimique de la
   table runs sur SourceDetailPage). Click → `/coins/:eurio_id`.
   Helper `onRowClick` qui exclut les clics sur boutons enfants
   (`closest('button, a')`) + `@click.stop` sur le bouton review
   pour double-sécurité. La copie clipboard sur eurio_id est
   supprimée — le click ouvre maintenant la fiche pièce.
2. **Header colonne "Review"** ajouté avec icône `Search`
   (lucide). Bouton review enrichi : icône Search + texte "review"
   + ExternalLink, sur fond bordé qui s'allume gold au hover. Quand
   pas d'item review : `·` (inchangé).
3. **Tooltips `title=""` sur tous les headers** des deux tableaux
   (List., Crops, Auto, Rev.S, Rev.L, Pend., Rej., Attr., Quotes,
   Lot ?, Review). Explicite la sémantique sans lire la légende.

Phase 1 livrée techniquement. Smoke fait (le user a confirmé que le
curl renvoie bien le breakdown du run Andorre, et a navigué sur la
page UI).

## Phase 2 — Review unifié + Lot V1.5

| Chunk | Périmètre | Statut |
|---|---|---|
| R.0 | Refacto ReviewPage en shell + extract SingleReviewView | ⏸ |
| L.A | API endpoints lots (list / detail / decide) | ⏸ |
| L.B | LotReviewView + LotCard + LotDetailDrawer | ⏸ |
| L.C | Wiring décision multi-crop + integration toggle | ⏸ |
| L.D | Tests + smoke vraies données | ⏸ |

## Phase 3 — Coins admin

À planifier après validation Phase 2 et accumulation de données
(≥ 3 sources actives, ≥ 50 pièces couvertes). Cf.
`coins-admin-kickoff.md` §"Pré-requis avant d'attaquer".

## Décisions prises pendant le chantier

(à compléter au fil des sessions ; les décisions structurelles
restent dans `decisions.md` global, ici on note seulement les micro
ajustements liés à l'exécution)

## Tests verts à conserver

```
tests/test_sources_base.py        8/8
tests/test_orchestrator.py       12/12
tests/test_bootstrap_coins.py     4/4
tests/test_ebay_adapter.py       24/24
tests/test_ebay_api.py            8/8
tests/test_resolve_lot_quote.py   9/9
                                ────
                                 65/65 ✅
```

Phase 1 ajoute ~5 tests. Phase 2 ajoute ~10 tests. Phase 3 TBD.
