# Kickoff — bootstrap Numista i18n (session dédiée)

> ⚠️ **PÉRIMÉ — 2026-05-19** ⚠️
>
> Cette doc supposait que Numista exposait des titres traduits par
> langue via ses sous-domaines (`<lang>.numista.com`). La probe
> empirique (`i18n-probe.md`) a montré que **seuls FR et EN sont
> vraiment traduits** ; les autres sous-domaines servent l'UI traduite
> mais conservent le titre EN du coin.
>
> La stratégie a été refondue : voir **`i18n-strategy.md`** pour les
> décisions actées, et les chunks exécutables associés :
> - `i18n-scrape-numista.md` (scrape FR+EN via TOR sur VPS)
> - `i18n-llm-translation.md` (LLM batch DE/IT/ES/NL sur PC)
>
> Le contenu ci-dessous est conservé comme archive de la décision
> originale (utile pour la traçabilité).
>
> ---
>
> Brief auto-suffisant pour la session qui livre **I1** du chantier
> `ebay-multi-marketplace`. Lire en premier, puis aller voir
> `language-probe.md` §"Étape 2bis" pour le matcher consommateur (I2).
>
> Verrouillé le 2026-05-19 après discussion stratégie API vs scrape.

## Pourquoi cette session existe

Pour matcher les titres eBay multilingues dans `EbayAdapter.discover()`
(B4 déjà livré), il faut un référentiel de **noms de pièces localisés**
par eurio_id. Aujourd'hui le matcher tombe sur `THEME_TOKEN_FR_ALIASES`
(hand-curated FR seulement) — fragile et incomplet.

Cette session bootstrappe la table `coin_names_i18n` (créée en B1) avec
les titres Numista en **9 langues**, qui alimenteront ensuite le
matcher multilingue (I2).

## Décisions actées (verrouillées 2026-05-19)

| Décision | Choix | Rationale |
|---|---|---|
| **D-i18n-1** Source des titres | Scrape `<lang>.numista.com/<numista_id>` | Quota Numista API trop précieux (3330+ calls API = 46 % du budget mensuel pour des labels texte). Scrape = 0 quota, future-proof. |
| **D-i18n-2** Langues V1 | 9 langues : `fr, en, de, it, es, nl, ru, pt, el` | Couvre les marketplaces eBay ciblés (6) + Numista en a 9 totaux (`hreflang` exposés) → autant tout ramasser tant qu'on y est, marginal en coût (1 fetch/lang). |
| **D-i18n-3** Scope coins V1 | Commémos 2€ + standards 2€ (~578 coins) | Aligné `coins WHERE face_value = 2.0`. Pas d'extension 1€/0.50€ V1 — orthogonal au chantier eBay. |
| **D-i18n-4** Throttle | **1 req/s strict** | Aligné sur la limite CDN observée (`numista-api-catalog.md` §6). Zéro risque 429. ~5200 HTTP / 3600 = ~**1h27 de run**. |
| **D-i18n-5** Idempotence | Skip-if-present par défaut + `--refresh` (lang ou all) | Reprise après interruption gratuite. Re-fetch sélectif si une langue a échoué. |
| **D-i18n-6** Branchement futur | Hook dans `bootstrap_coins_from_referential.py` | Quand un nouveau coin entre dans `coins`, fetch i18n automatique. Pas de pipeline orphelin. |

D-i18n-1 supplante l'ambiguïté de `D-MM3` qui mentionnait "scraping" sans
trancher API vs HTML. Idem pour D-i18n-2 qui élargit `D-MM3` de 5-6 à 9
langues.

## Probe terrain (2026-05-19)

Vérifié manuellement sur `https://en.numista.com/226447` :

- 9 langues exposées via `<link rel="alternate" hreflang="de|el|en|es|fr|it|nl|pt|ru">`.
- `<h1>` propre : `<h1>2 Euros <span style="font-size:50%;">Kneeling to Warsaw</span></h1>`.
- Pas d'auth requise, page publique.
- HTTP 301 sur `/catalogue/pieces<id>.html` → canonique = `/<id>`. Le
  script doit suivre les redirects ou cibler directement la forme courte.

## Ce qu'il faut implémenter

### Chunk I1-A — Extension schema (5 min)

Le `CHECK` actuel de `coin_names_i18n.lang` (B1) autorise seulement
`('fr','en','de','it','es','nl')`. Pour stocker `ru/pt/el`, **étendre
la contrainte** :

```sql
-- ml/state/schema.sql §coin_names_i18n
CHECK (lang IN ('fr','en','de','it','es','nl','ru','pt','el'))
```

SQLite ne supporte pas `ALTER TABLE … DROP CONSTRAINT`. Pattern à
utiliser dans `store.py._bootstrap` : si la table existe avec l'ancien
CHECK, recréer-et-copier. Helper `_recreate_table_with_new_check()`
à écrire (ou recycler si déjà présent ailleurs).

Alternative simple : drop ce CHECK entièrement et valider côté Python
(plus permissif, moins de friction si on ajoute des langues). À
discuter au début de la session.

### Chunk I1-B — Script `bootstrap_coin_names_i18n.py` (1h30 code)

Emplacement : `ml/scripts/bootstrap_coin_names_i18n.py`.

```python
"""Scrape Numista localized titles into coin_names_i18n.

Pour chaque coin avec numista_id (filtre face_value = 2.0 V1), fetch
<lang>.numista.com/<numista_id>, extrait le <h1>, persiste 1 row par
(eurio_id, lang).

Usage:
    python bootstrap_coin_names_i18n.py            # skip-if-present
    python bootstrap_coin_names_i18n.py --refresh  # re-fetch all
    python bootstrap_coin_names_i18n.py --refresh-lang de
    python bootstrap_coin_names_i18n.py --only-eurio fr-2015-2eur-paix
"""
```

Détails :
- Sélection coins : `SELECT eurio_id, numista_id FROM coins WHERE
  face_value = 2.0 AND numista_id IS NOT NULL`. Skip ceux sans
  `numista_id` (log explicite).
- Parse HTML via `bs4` ou regex sur `<h1>` (preférer bs4 — déjà
  utilisé dans le projet ? sinon regex robuste sur la balise).
- **Extraction du titre** : on prend **tout le texte du h1**
  (denom + thème). Le tokenizer du matcher (I2) gère le filtrage des
  stop-words par langue (`STOP_WORDS_BY_LANG` dans
  `language-probe.md`).
- Persistence via `INSERT OR REPLACE INTO coin_names_i18n` ou
  upsert manuel.
- Throttle : `time.sleep(1.0)` entre chaque fetch. Pas de
  parallélisation.
- User-Agent honnête : `"Eurio bootstrap (https://github.com/Musubi42/Eurio)"`.
- 429 / 5xx : backoff exponentiel + retry 3×. 4xx autre (incl. 404) :
  log warning, skip ce (coin, lang), continue.
- Output progress : tqdm avec ETA. Log final par langue : "X/Y
  fetched, Z skipped (already present), W failed".

### Chunk I1-C — Test unit + intégration (30 min)

`ml/tests/test_bootstrap_coin_names_i18n.py` :

- Mock 1 page Numista (fixture HTML), vérifier extraction `<h1>`.
- Test idempotence : 2 runs successifs ne dupliquent pas.
- Test `--refresh-lang fr` : seules les rows `lang='fr'` sont touchées.
- Test 404 gracieux : coin avec numista_id inexistant → row absente,
  pas de crash.

### Chunk I1-D — Hook dans le bootstrap référentiel (30 min)

`ml/scripts/bootstrap_coins_from_referential.py` (existant) appelle
en fin de run :

```python
from scripts.bootstrap_coin_names_i18n import fetch_i18n_for_eurio_ids
fetch_i18n_for_eurio_ids(store, eurio_ids=newly_imported, langs=ALL_LANGS)
```

Idempotent (skip-if-present), donc déjà-bootstrappés = no-op. Seulement
les nouveaux coins paient le scrape.

### Chunk I1-E — Run unique du bootstrap (1h27 attente)

Lancer `go-task ml:bootstrap-coin-names-i18n` (nouvelle task à ajouter
au `Taskfile.yml`). Run en background. Vérifier à la fin :

- Couverture par langue : `SELECT lang, count(*) FROM coin_names_i18n
  GROUP BY lang`. Critère ≥ 80 % par lang (cf. `language-probe.md`
  §"Critère de succès"). Si < 80 %, investiguer (Numista n'a pas
  toujours traduit tous les coins).
- Spot-check manuel sur 5 coins (vérifier que `bartgeier` apparaît bien
  dans la version DE de l'Andorre 2025 bearded-vulture).

## Volume estimé

| Métrique | Valeur |
|---|---|
| Coins ciblés (face_value=2.0 ∧ numista_id≠NULL) | ~578 |
| Langues | 9 |
| HTTP requests total | ~5200 |
| Run time @ 1 req/s | ~1h27 |
| API quota Numista consommé | **0** |
| Rows `coin_names_i18n` attendues | 4000-5200 (80-100 % couverture) |
| Storage SQLite | ~1 MB |

## Anti-objectifs

- **Pas d'extraction du span** (`<span style="font-size:50%;">Kneeling to
  Warsaw</span>`) séparément. On garde le titre complet — le tokenizer
  I2 fait le tri.
- **Pas de scrape API en parallèle**. Si une page HTML n'a pas de `<h1>`,
  on log et skip — pas de fallback API qui coûterait du quota.
- **Pas d'enrichissement images / dates / autre data**. Scope strict =
  titres uniquement. Tout le reste reste sur l'import API canonique.
- **Pas de parallélisation HTTP**. 1 req/s strict, sequential. La
  simplicité l'emporte sur les 30 min gagnés.

## Définition de "done"

- [ ] Schema étendu (9 langues OK dans CHECK ou CHECK retiré).
- [ ] Script `bootstrap_coin_names_i18n.py` livré + tests.
- [ ] Hook ajouté dans `bootstrap_coins_from_referential.py`.
- [ ] Task `go-task ml:bootstrap-coin-names-i18n` dans `Taskfile.yml`.
- [ ] Run terminé, ≥ 80 % couverture par langue cible.
- [ ] Spot-check 5 coins OK.
- [ ] `progress.md` mis à jour (chunk I1 → done).

Une fois I1 livré, **I2 (theme matcher)** peut démarrer — il consomme
`coin_names_i18n` selon la spec déjà figée dans `language-probe.md`
§"Étape 2bis".

## Fichiers touchés

| Fichier | Nature |
|---|---|
| `ml/state/schema.sql` | Extension CHECK lang (I1-A) |
| `ml/state/store.py` | Recreate-and-copy helper si CHECK extension (I1-A) |
| `ml/scripts/bootstrap_coin_names_i18n.py` | **Nouveau** (I1-B) |
| `ml/scripts/bootstrap_coins_from_referential.py` | Hook (I1-D) |
| `ml/tests/test_bootstrap_coin_names_i18n.py` | **Nouveau** (I1-C) |
| `Taskfile.yml` | Task `ml:bootstrap-coin-names-i18n` (I1-B) |
| `docs/sources-refacto/ebay-multi-marketplace/progress.md` | Update (fin de session) |

## Liens utiles

- Probe HTML manuelle : `https://en.numista.com/226447` (Allemagne 2020 Warsaw)
- API Numista doc : `docs/research/numista-api-catalog.md`
- Quota tracker : `ml/api_quota.py` + clés via `ml/referential/numista_keys.py`
- Tokenizer I2 (consommateur) : `language-probe.md` §"Étape 2bis"
- Decision log eBay multi-mkt : `README.md` §"Décisions actées"
