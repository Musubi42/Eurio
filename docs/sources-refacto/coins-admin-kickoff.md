# Kickoff Coins admin — vue produit agrégée

> Vision de la page `/coins` et `/coins/:eurio_id` dans l'admin web.
> Document d'intention : ne décrit pas l'implémentation, mais ce que
> ces pages doivent **être** dans le mental model admin.
>
> Pas planifié pour une session immédiate. À ouvrir quand on aura
> assez de données accumulées (post-eBay V1.5 + 2-3 sources actives)
> pour que la vue produit ait du sens à regarder.

## Pourquoi ce doc

Pendant l'analyse de l'organisation admin (cf. `lot-review-kickoff.md`
et l'échange du 2026-05-03), on a identifié 3 axes orthogonaux :

1. **Sources** — opérationnel, "qu'est-ce que ce fournisseur ramène ?"
2. **Coins** — produit, "qu'est-ce que je sais sur cette pièce ?"
3. **Review** — file de travail, "qu'est-ce qui attend ma décision ?"

Aujourd'hui (mai 2026), seul l'axe **Sources** est implémenté. La
page `/coins` existante est un placeholder (liste tirée du snapshot
catalogue). Ce doc grave l'intention pour quand on s'y attaquera.

## Mental model

`/coins` est la **vue SQL produit** d'admin Eurio. C'est l'endroit où
Raphaël va quand il se demande :

- *"Qu'est-ce que j'ai sur la 2€ Andorre 2014 Conseil de l'Europe ?"*
- *"Combien de pièces n'ont aucune image canonique ?"*
- *"Quelles pièces ont une cote eBay obsolète (>60j) ?"*
- *"Quel est le ratio training-eligible / total pour les commémo allemandes ?"*

Pas un outil de décision (c'est `/review`). Pas un outil opérationnel
(c'est `/sources`). C'est l'**état de la data, pièce par pièce**.

## `/coins` — liste filtrable

Tableau dense, une ligne = un eurio_id, colonnes triables/filtrables :

| Colonne | Source de la donnée |
|---|---|
| `eurio_id` | `coins.eurio_id` |
| Pays · année · dénom · variant | `coins.*` |
| Thumbnail (image canonique si dispo) | `image_assets WHERE variant_kind='canonical'` |
| Nb images totales | `count(image_assets) GROUP BY eurio_id` |
| Nb training-eligible | idem `WHERE training_eligible=1` |
| Cote actuelle (P50 dernière) | `coin_market_quotes` dernière `period_start` |
| Fraîcheur quote (jours) | `now() - max(fetched_at)` côté quotes |
| Fraîcheur image (jours) | `now() - max(fetched_at)` côté assets |
| Statut review (badge) | dérivé : `count(review_queue WHERE status='open')` |
| Drapeaux qualité | dérivé : "no_canonical_image", "stale_quote", "needs_review" |

**Filtres essentiels** :
- pays, dénomination, année, type (circulation / commémo)
- "sans image canonique"
- "fraîcheur quote > N jours"
- "items en review (single ou lot)"
- "training-eligible == 0"

**Tri par défaut** : fraîcheur quote desc (les plus stales en haut →
on voit ce qu'il faut re-runner).

## `/coins/:eurio_id` — page dédiée à une pièce

C'est *la* fiche admin d'une pièce. Trois sections :

### 1. Header identité

- eurio_id, label, pays, année, dénom, variant_kind, mintage si connu
- Image canonique large (la `variant_kind='canonical'` si elle existe,
  sinon la mieux scorée)
- Lien externe Numista (id stocké dans `coins.numista_id`)

### 2. Données — onglets

#### Tab Images

Grille de **toutes** les `image_assets` pour cet eurio_id, peu importe
la source :
- thumbnail
- badge source (numista / wiki / ebay / catawiki…)
- badge variant_kind (canonical / official_press / in_hand / …)
- badge face (obverse / reverse)
- score qualité, training-eligible (✓/✗ + raison si exclu)
- bouton "ouvrir l'asset full" + "voir le source_image parent"

Filtre rapide : par source, par variant_kind, par face,
training-eligible only.

#### Tab Prix

Tableau des `coin_market_quotes` pour cet eurio_id :
- source, condition, P10/P50/P90, sample_size, période, fetched_at
- graphe simple P50 dans le temps (sparkline) si on a ≥ 3 points

#### Tab Runs

Historique des `source_runs` qui ont touché cette pièce
(JOIN via `source_images.target_eurio_id` + `image_assets`/`coin_market_quotes`):
- date, source, kind, ce qui a été produit pour CETTE pièce
  (X images, Y quotes, Z en review)
- bouton "Voir le breakdown du run" → `/sources/:id/runs/:run_id`
  (cf. `run-breakdown-kickoff.md` à créer)

#### Tab Review

Items en review pour cet eurio_id (single + lot) :
- thumbnail, source, kind, statut, enqueued_at
- bouton "Reviewer" → `/review?eurio_id=...&kind=...`

### 3. Actions admin

- **Re-run cette pièce sur source X** → bouton qui pré-remplit
  `target_eurio_ids=[eurio_id]` sur `/sources/:id` (déjà supporté
  côté API, juste l'UX à câbler)
- **Marquer image canonique** → set `variant_kind='canonical'` sur
  un asset (utile pour piloter le snapshot Android)
- **Forcer re-quote** (eBay) → re-fetch des annonces récentes pour
  cette pièce uniquement

## Ce que `/coins` n'est PAS

- ❌ Une page de décision (review) — la review vit dans `/review`
- ❌ Une page de monitoring opérationnel — santé pipeline = `/sources`
- ❌ Une page d'édition du référentiel — les coins viennent du
  bootstrap Numista + JOUE (cf. `data-referential` memory). Si on
  veut éditer, c'est V2 et passer par un endpoint admin dédié

## Liens entre les 3 axes

```
                ┌──────────────────────┐
                │  /sources/:id        │
                │  └─ /runs/:run_id    │
                │     (breakdown par   │
                │      eurio_id)       │
                └──────┬──────┬────────┘
                       │      │
              "voir la pièce" │ "reviewer ces crops"
                       ▼      ▼
              ┌──────────────┐ ┌──────────────────┐
              │ /coins/:id   │ │ /review?run_id=X │
              │ (fiche full) │ │     &eurio_id=Y  │
              └──────┬───────┘ └────────┬─────────┘
                     │                   │
            "voir items en review"       │
                     ▼                   │
              ┌──────────────────────────┘
              │  /review (page unique,
              │   toggle Single | Lot)
              └─
```

Le breakdown par-eurio_id d'un run est la **passerelle** entre
Sources et Coins. La page Coins est la **destination produit**. La
page Review est la **file de travail** consommée depuis n'importe où.

## Données à exposer côté API (V2, pas maintenant)

- `GET /coins` → liste paginated avec colonnes ci-dessus (un seul
  endpoint, agrégats SQL côté serveur, pas N+1)
- `GET /coins/:eurio_id` → header + counts par tab
- `GET /coins/:eurio_id/images` → list paginated
- `GET /coins/:eurio_id/quotes` → list + sparkline data
- `GET /coins/:eurio_id/runs` → list par source_runs joint
- `GET /coins/:eurio_id/review` → list review_queue ouverts

Tout ça lit `image_assets`, `coin_market_quotes`, `source_runs`,
`review_queue` — pas de schéma à toucher, que des JOIN.

## Pré-requis avant d'attaquer

1. ✅ Pipeline sources opérationnel (eBay V1 livré)
2. ⏳ Lot review V1.5 livré (sinon les counts review sont incomplets)
3. ⏳ Run breakdown view livré (sinon le lien Coins → Sources/run
   atterrit dans le vide)
4. ⏳ Au moins 3 sources actives avec ≥ 50 pièces couvertes pour
   que la vue agrégée ait du jus (sinon c'est mock)

## Décisions à valider quand on attaquera

1. **Cardinalité** : `/coins` peut afficher ~3000 pièces (eurozone
   complet). Pagination 50/page + filtres serveur, ou virtual scroll ?
   Vote : pagination classique, plus simple à câbler.

2. **Quel niveau de fraîcheur déclenche un drapeau "stale"** ?
   Probablement par-source : eBay 30j, Numista 180j, Wiki ∞ (donnée
   éditoriale). À gérer via `sources.expected_cadence_days` × facteur
   (×2 = warning, ×4 = error).

3. **Image canonique : auto-pick ou manuel** ? Auto par défaut sur
   meilleur quality_score d'une source canonique (numista, wiki),
   override manuel via action admin. Le résultat alimente le snapshot
   Android.

4. **Sparkline P50** : nécessite ≥ 3 quotes dans le temps. En attendant
   d'avoir ce volume, juste le dernier P50 + Δ vs précédent.

## Hors scope (V2+)

- Édition du référentiel coins (passer par bootstrap script)
- Bulk actions (re-run 50 pièces d'un coup) — V2 si besoin
- Export CSV — V2
- Suggestion automatique "il faudrait re-runner X" basée sur fraîcheur
  + drift de prix — pourrait devenir un widget homepage admin V3

## Pourquoi pas d'implémentation maintenant

- Lot review V1.5 et run breakdown sont prioritaires (cf. lot-review-kickoff)
- Sans données accumulées (post-eBay), une page produit affiche du vide
- L'organisation 3-axes (Sources / Coins / Review) doit d'abord être
  validée par l'usage du flow lot review V1.5
