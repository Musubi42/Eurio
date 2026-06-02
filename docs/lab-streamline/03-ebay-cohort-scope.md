# Chunk 03 — eBay scopé cohort (discovery + design)

> **But** : depuis le lab, lancer un scrape eBay limité aux coins d'une cohort,
> et voir les images eBay déjà présentes par coin. Cohort pilote : `mix-zone-17`
> (16 coins après drop bleuet).

## Contrainte doctrine

**Passes eBay = user-owned, manuel** (mémoire `feedback_ebay_pass_user_owned`).
→ Je **ne lance aucun appel eBay** autonome (même `--dry-run` appelle l'API Browse
et consomme le quota). Je construis le câblage + valide l'expansion en **pur SQL**.
Le vrai scrape, c'est toi qui le déclenches.

## Comment eBay découvre aujourd'hui

Découverte **par groupe** `(denomination, country, year)`, pas par coin. Un groupe =
1 recherche Browse API par marketplace, puis theme-matching des listings vers les
coins du groupe. Source des groupes : vue `v_ebay_freshness_groups`.

Points d'injection (cf. map) : CLI `ml/sources/cli.py` (`_resolve_ebay_groups`),
API `POST /sources/{id}/runs` (`RunQueryBody`), orchestrateur `run_pipeline`.
Accès cohort depuis ml/ : `Store.get_cohort(id).eurio_ids`. Quota : `api_quota.py`
+ préflight `check_ebay_quota`.

## Découverte clé : la vue est commémoratives-only

```sql
-- v_ebay_freshness_groups
WHERE c.face_value = 2.0 AND c.is_commemorative = 1
  AND c.country != 'eu' AND c.canonical_eurio_id IS NULL
```

Expansion de mix-zone-16 → **15 groupes distincts** ; **13 dans la vue**, 2 hors vue :
- `(2€, AT, 2002)` → `at-2002-2eur-standard-1st-map` (**standard**, is_commemorative=0)
- `(2€, ES, 1999)` → `es-1999-2eur-standard-juan-carlos-i-1st-type-1st-map` (**standard**)

→ **14/16 coins** scrapables par groupe ; les **2 standards** ne le sont pas
(la découverte eBax cible les commémoratives). Pas de drop silencieux : le scoping
doit reporter ces 2 coins comme « non eBay-scrapables par groupe ».

## Design proposé (à valider)

**Scoping par groupe** (le plus propre, réutilise la découverte native eBay) :
1. `cohort_groups(store, cohort_id)` → (groupes-dans-la-vue, coins-non-scrapables).
2. CLI : `--cohort-id` (filtre la freshness queue aux groupes de la cohort).
3. API : `RunQueryBody.cohort_id` (même expansion server-side).
4. Lab UI (chunk 03b) : section « images eBay par coin » + bouton « Lancer scrape
   cohort » (toi qui confirmes le run, quota affiché).

**Question ouverte — les 2 standards** : (a) on les laisse en training Numista-only
(eBay ne les enrichit pas), ou (b) on tente un scrape per-coin (`target_eurio_ids`)
pour eux aussi (chemin générique, hors vue commémo).

## Décisions actées (2026-06-02)

- **Standards = Numista-only** : pas de chemin per-coin eBay pour eux. Le scoping
  les reporte dans `non_scrapable` (pas de drop silencieux).
- **Build backend d'abord (03a)** ; lab UI = 03b.

## 03a livré — backend cohort-scoping

- **`ml/sources/cohort_scope.py`** : `cohort_ebay_groups(store, cohort_id)` →
  `(groups, non_scrapable)`. Mappe les eurio_ids de la cohort vers leurs
  `(denom,country,year)`, garde ceux présents dans `v_ebay_freshness_groups`.
- **CLI** `ml/sources/cli.py` : flag `--cohort-id` (branche eBay, préflight quota,
  log des `non_scrapable`).
- **API** `ml/api/sources_routes.py` : `RunQueryBody.cohort_id` → expansion dans
  `trigger_run` avant build de la query ; `TriggerResponse.non_scrapable`.

**Validé offline (aucun appel eBay)** sur mix-zone-16 :
`13 groupes scrapables / 14 commémoratives`, `non_scrapable = [at-2002-standard,
es-1999-standard]`. (sum n_coins = 20 : certains groupes pays/année portent une
2ᵉ commémo catalogue, découverte aussi par le scrape groupé — la review filtre.)

### Lancer le vrai scrape (TOI, quand tu veux — consomme le quota eBay)

```bash
# CLI
python -m sources.cli --source ebay --cohort-id <COHORT_ID>
# ou via l'API (POST /sources/ebay/runs  body {"cohort_id":"<id>"})
```

## Reste — 03b (lab UI)

- Section « images eBay par coin » sur la fiche cohort (read-only, compte
  `source_images`/`image_assets` par coin — pas de quota).
- Bouton « Lancer scrape eBay (cohort) » → `POST /sources/ebay/runs {cohort_id}`,
  avec préflight quota affiché + liste `non_scrapable`. Toi qui confirmes le run.

## Journal

- 2026-06-02 — discovery + design + **03a backend livré & validé offline**.
  Reste 03b (lab UI). Le scrape réel est manuel (doctrine eBay user-owned).
