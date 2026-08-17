---
name: eurio-review
description: Trancher les crops scrapés et décider ce qui entre en training (training_eligible). À lire avant d'accepter des crops, de bricoler une planche de contrôle, ou de lire `image_asset_dino_predictions` à la main.
---

# Trancher les crops

> La review est le seul endroit du projet où une **décision humaine** entre dans
> la donnée. Ce qu'elle produit — `training_eligible = 1` — n'est régénérable par
> aucun calcul : c'est la vérité-terrain de l'entraînement. Une erreur ici ne
> plante rien, elle dégrade le modèle des mois plus tard.

## La règle numéro un : la review se fait DANS le front de review

`go-task front:dev` → `http://localhost:5173/review`. Les pages existent déjà et
sont marquées `meta.heavy` (donc locales, cf. `CLAUDE.md` §R0bis) :

| Page | Ce qu'elle fait |
|---|---|
| `/review` | tableau de bord, stats de triage |
| `/review/manual` | trancher un crop à la fois |
| `/review/auto-accept` | valider en lot ce que le moteur juge sûr |
| `/review/lot/:listing_key` | annonces multi-pièces (kind `lot`) |
| `/review/recover` | rattraper des crops écartés |
| `/review/peer-arbitration` | désaccords entre décisions |

Les cinq premières sont `meta.heavy` (donc locales). **`peer-arbitration` ne l'est
pas, volontairement** — « GET arbitrage léger + URLs images ML », accessible en
hébergé (`router.ts`).

⛔ **Ne fabrique pas d'outil de review parallèle.** Vécu le 2026-08-17 : une
planche HTML de 111 vignettes a été produite pour faire trancher un humain, alors
que le front existait — et elle affichait 24 candidats espagnols dont **2** bons,
parce qu'elle interrogeait la table brute au lieu du verdict du projet (voir
ci-dessous). Le front, lui, applique la bonne règle.

## Le verdict, et pourquoi la marge compte plus que le seuil

`serving/review_queue/service.py::compute_auto_validate_verdict` classe chaque
crop en `auto_candidate` / `partial` / `divergent` / `unknown`, **dans cet ordre** :

1. aucune prédiction DINO → `unknown`
2. signal **texte** `contradict` → `divergent`
3. cible de découverte absente → `unknown`
4. **`top1 != target` → `divergent`** ← la règle qui tranche le plus souvent
5. sim ≥ seuil **ET** marge ≥ seuil **ET** texte `convergent` → `auto_candidate`
6. sinon → `partial`

Donc le verdict **ne se joue pas que sur les scores** : un crop qui passe les deux
seuils reste `partial` si le signal texte n'est pas `convergent`, et bascule
`divergent` si le top1 contredit la cible de découverte.

Seuils canoniques — source : `training/foundation/thresholds.py`, dont
`review_queue/service.py` est un **miroir** (le front, lui, les lit via l'API) :

```
top1_country_sim_min = 0.55      # similarité, comparaison scopée au PAYS cible
country_spread_min   = 0.05      # écart top1 − top2  ← le garde-fou qui compte
```

**Une similarité élevée ne prouve rien sans marge.** Mesuré le 2026-08-17 :

| Classe | écart top1−top2 moyen | candidats à `sim ≥ 0,855` | dont marge ≥ 0,05 |
|---|---|---|---|
| `fr-2euro-standard-t1` | **0,169** | 38 | **38** |
| `es-2euro-juan-carlos-i-t2` | **0,006 – 0,031** | 24 | **2** |

Les 2ᵉˢ hypothèses des crops espagnols étaient Philippe, Benoît XVI, Albert II :
pour DINO, **tous les standards à portrait se ressemblent**, et le top1 gagne au
bruit. L'humain qui a regardé la planche a dit « deux ou trois sont vraiment des
Juan Carlos » — la marge en garde 2. L'œil et le seuil du projet tombent
d'accord ; le seuil seul, non.

⚠️ Donc : **ne jamais trier sur `top1_sim` seul.** Mieux : ne pas interroger la
table du tout et passer par le verdict. Si tu dois vraiment écrire du SQL, sache
que le service utilise `country_spread` **avec repli sur le `spread` global**
quand la bande pays est NULL — un filtre naïf sur la seule colonne country exclut
en silence des crops que le verdict, lui, évalue :

```sql
coalesce(p.country_spread, p.spread) >= 0.05      -- et non p.top1_sim seul
```

(La colonne `country_spread` existe déjà : ne la recalcule pas à la main. Et
attention, `training_eligible != 1` exclut les NULL en SQL — préfère
`training_eligible IS NOT 1`.)

## La file

`review_queue` (schéma : `ml/state/schema.sql`) —
`status` ∈ `open` / `in_progress` / `done` / `skipped` ·
`kind` ∈ `single` / `lot` ·
`lane` ∈ `manual` / `auto_accept` / `ccproxy` / NULL ·
`lane_source` ∈ `auto` / `human`.

État au 2026-08-17 : **6918 items ouverts** (5332 lot, 1586 single). Le stock est
donc profond : une session de review n'a de sens que **cadrée** — par classe, par
lane, ou par run. Ne pas « vider la file ».

Lecture : `GET /review-queue` (+ `/triage-stats`, `/stats`, `/lots`, `/rejected`).
Décision : `POST /review-queue/{review_id}/decide` · `/skip` · `/reject` ·
`/move-lane` (`serving/review_queue/writes.py`) ; les lots ont la leur :
`POST /review-queue/lots/{listing_key}/decide` (`serving/funnel_writes.py`).
Côté lab, sur un asset précis : `POST /lab/assets/{id}/accept-training` ·
`/training-eligible` · `/reassign` · `/reopen-review`.

⚠️ **Ne pas confondre avec `/review/items/{id}/decide|skip|claim`** : ces
routes-là (`serving/review_routes.py`) appartiennent au **service de peer-review
multi-utilisateur**, qui vit sur une **autre base** (`review_items` dans
`review.db`) et sert `eurio-review.musubi.dev`. Deux systèmes homonymes ; le front
`studio-local` n'appelle que `/review-queue/*`.

## Ce qui compte pour l'entraînement, précisément

Le bake ne prend un crop eBay que si **tout** est vrai (`iteration_augmentations
._ebay_training_sources`) :

- `training_eligible = 1` — la décision de review ;
- `storage_status = 'present'` ;
- `face IS NULL` ou `face != 'reverse'` — le revers commun 2 € n'entre jamais ;
- l'attribution qui fait foi est **`image_assets.eurio_id`** (le label tranché),
  pas `source_images.target_eurio_id` (la cible de découverte). Un crop réattribué
  suit son nouveau label ;
- ⚠️ **et une 5ᵉ condition qui n'est pas en base** : le fichier doit exister dans
  le cache local (`local_path("enrichment-crops", …)`), sinon il est **ignoré en
  silence**. Un crop parfaitement éligible en base n'entre pas au bake si le cache
  ne l'a pas — c'est une des façons dont un bake « réussit » avec moins de sources
  que prévu.

Et le compte se fait **par classe**, pas par pièce (cf. `eurio-enrichment`).

## Où va l'écriture

Sous le flip Direction A, une décision de review part au **canonique** (C3 :
décisions review/funnel/lot + reassign sont reroutées). Si une route répond
`503 canonical_readonly`, elle n'a pas encore été reroutée — lire
**`eurio-data-writes`**, ne pas contourner en écrivant en local.

## Ensuite

→ **`eurio-run-local`** : créer l'itération sur la cohorte enfin nourrie.
→ Puis la promotion : `docs/architecture/parcours.md` §5.

## Ce que cette skill ne couvre PAS

- Le moteur de décision complet : `ml/serving/review_queue/service.py` (~400 l.)
  et `ml/training/foundation/auto_validate.py` pour les signaux (face, denom,
  texte, DINO).
- La review de **lots** (annonces multi-pièces, 77 % de la file ouverte) : elle a
  sa propre plaque d'examen, cf. `detections_json` sur `source_images`.
- La provenance des crops : `eurio-enrichment`.
