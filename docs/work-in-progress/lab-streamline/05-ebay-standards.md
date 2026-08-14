# Chunk 05 — eBay scrape des pièces STANDARD

> **But** : élargir la découverte eBay aux pièces **standard** (`is_commemorative=0`),
> pas seulement les commémoratives. Débloque les images d'entraînement des
> standards (sur `mix-zone-17` : `ad-2014`, `at-2002`, `be-2007`, `es-1999`).
> Supersède la décision « standards = Numista-only » de `03-ebay-cohort-scope.md`.

## Contrainte doctrine

**Passes eBay = user-owned, manuel** (`feedback_ebay_pass_user_owned`). Tout le
chantier est **câblé + validé en pur SQL / offline** ; aucun appel Browse n'est
lancé (même `--dry-run` consomme le quota). Le vrai scrape, c'est toi.

## La vraie difficulté

Un standard 2 € n'a **pas de thème par année** : sa face nationale est identique
sur toute une **ère de design** (carte 1ʳᵉ/2ᵉ, portrait, type). Une ère = une
ligne canonique `coins` dont `year` est l'année de *début*. Conséquences :

1. **Grouper par `(pays, année)` est inadapté** — le design ne dépend pas de
   l'année. Piège concret : `compare_to_group._year_axis` voit « 2 Euro
   Österreich **2015** » vs `at-2002` (year=2002) → `contradict` → discard, alors
   que c'est un standard autrichien parfaitement valide (ère 2nd-map `at-2008`).
2. **Le theme-matcher est commémo-orienté** — un standard n'a pas de thème
   positif (sauf le nom de portrait). Il ne sait pas attribuer « 2 euros
   Autriche 2002 ».
3. **Collision standards/commémos** — une recherche large « 2 euro Espagne »
   ramène autant de commémos que de standards.

## Design livré

**Groupe de découverte standard = `(dénomination, pays)`** (PAS l'année).
Une recherche large « 2 euro {pays} » par marketplace couvre toutes les ères ;
quota ~25 pays × 2 mkt pour un sweep complet, 4 pays pour `mix-zone-17`.

**Attribution** (`sources/ebay/standards.py::attribute_standard_listing`,
fonction pure) — funnel par listing :

1. **garde-fou contradiction** pays + dénomination seulement (l'axe **année est
   désactivé** : un standard couvre toute sa durée de vie) → `no_match` ;
2. **garde négatif mot-clé commémo** (« Gedenkmünze / Sondermünze /
   conmemorativo / commémorative » sans mot-clé standard « Kursmünze /
   circulation » co-présent) → `commemo` (attrape les lots « alle Nationen /
   todos los paises ») ;
3. **millésime unique requis** pour pinner l'ère ; sinon → `ambiguous` ;
4. **exclusion commémo par theme-match** : le titre *hit* une commémo de
   `(pays, année)` → `commemo` (déjà captée par le run commémo) ;
5. **appartenance de plage** : `ère(Y)` = plus grand début d'ère ≤ Y →
   `single` ; collision même-année (MT 2026) ou millésime hors-référentiel →
   `ambiguous`.

**Doctrine « tout en review d'abord »** (chemin neuf, faillible) : `single` et
`ambiguous` partent en review. `target_eurio_id` n'est qu'un **prior**
(None si ambiguous) ; les ères du pays sont **toujours** portées en candidates
pour que l'humain tranche / corrige. Aucun gating spécifique à coder : le step
`resolve` marque déjà `needs_review` tout crop non dup-pHash, `auto_validate`
n'est pas décisionnel en V1.

**Variantes** : on scrape les **canoniques (ères) seules** ; les variantes
`canonical_eurio_id` non-NULL (pattern/mule/coloured = non-circulantes) restent
`non_scrapable`.

## Surface de code

| Fichier | Changement |
|---|---|
| `ml/state/schema.sql` | + vue `v_ebay_standard_groups` `(dénom, pays, n_eras, …)`. |
| `ml/sources/ebay/standards.py` | **NEW** — `StandardEra`, `load_standard_eras`, `eras_for_year`, `StandardMatch`, `attribute_standard_listing`. |
| `ml/sources/ebay/queries.py` | `theme_match_state` rendu public ; `build_group_query` accepte `year=None` (requête sans millésime). |
| `ml/sources/_base/adapter.py` | `DiscoveryGroup` : `+ kind` (`commemorative`/`standard`), `year` optionnel + validation. |
| `ml/sources/ebay/adapter.py` | `discover` dispatch par `kind` ; helpers `_attribute_commemo_row` / `_attribute_standard_row` ; `_resolve_group` standard-aware. |
| `ml/sources/cohort_scope.py` | `EbayGroup` (dataclass typé + `kind`) ; route les standards via `v_ebay_standard_groups`. |
| `ml/sources/cli.py`, `ml/serving/sources_routes.py`, `ml/serving/lab_routes.py` | threadent `kind` / `year=None` (CLI cohort+freshness, `GroupSpec`, ebay-status). |

## Validation offline (zéro appel eBay)

- **`ml/scripts/standards_attribution_diag.py`** — rejoue l'attribution sur
  16 cas craftés (assertions dures) + les vrais titres ES/AT déjà en base, puis
  la **preuve d'expansion cohort**. Exécution :
  ```bash
  python -m scripts.standards_attribution_diag            # défaut : mix-zone-17
  ```
  → vue (25 pays, 56 ères) ; plages d'ères (ES/AT/MT/VA) ; 16/16 cas ;
  expansion `mix-zone-17` = **11 commémo + 4 standard, non_scrapable = 0**.
- **`ml/tests/test_ebay_standards.py`** — 11 tests (plages, attribution,
  cohort-routing standard/commémo/variante, discover smoke). `test_ebay_adapter`
  (47, chemin commémo) inchangé.

## Lancer le vrai scrape (TOI, manuel — consomme le quota eBay)

Identique au commémo : le cohort-scoping expanse maintenant aussi les standards.

```bash
python -m sources.cli --source ebay --cohort-id <COHORT_ID>
# ou POST /sources/ebay/runs  body {"cohort_id":"<id>"}
```

## Résidu connu

Un listing standard d'année donnée sans aucun mot-clé ni thème reconnu (ex.
`2 EUROS ESPAÑA 2016 S/C`) est attribué à l'ère du millésime (es-2015 Felipe) —
souvent **correct**. Les lots commémo « toutes nations » sont attrapés par le
garde mot-clé (`commemo_keyword`). Reste un faux-positif théorique (commémo à
i18n absente, sans mot-clé) → prior erroné, rattrapé en review (sans perte).

## Journal

- 2026-06-03 — Chunk A (référentiel + attribution + harnais) & Chunk B
  (câblage découverte + cohort) livrés & validés offline. Le scrape réel reste
  manuel (doctrine eBay user-owned). Reste Chunk C (badge lab UI « scrapable »
  sur les standards).
