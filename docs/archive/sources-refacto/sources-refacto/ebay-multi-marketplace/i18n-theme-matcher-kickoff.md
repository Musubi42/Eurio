# Kickoff — I2 theme matcher multilingue

> Brief auto-suffisant pour la session qui livre **I2** du chantier
> `ebay-multi-marketplace`. À reprendre sur Mac.
>
> Verrouillé 2026-05-20, après livraison I1 (FR+EN scraped).
>
> Lire d'abord `progress.md` puis `language-probe.md` §"Étape 2bis".

## Pourquoi cette session existe

Le matcher de titres eBay actuel (`title_matches_theme` dans
`ml/sources/ebay/queries.py:304`) tape sur des **tokens extraits du
slug EN** de l'eurio_id, puis tente une traduction via le dict
hand-curated `THEME_TOKEN_FR_ALIASES`. C'est :

- **Asymétrique** : seul FR a des aliases, les marketplaces DE/IT/ES/NL
  matchent sur les tokens EN sans traduction → recall écrasé sur les
  vrais titres locaux des sellers.
- **Du travail manuel sans fin** : chaque nouveau coin = N entrées
  d'alias à maintenir à la main.
- **Indépendant du vocabulaire seller** : le slug EN (`bearded-vulture`)
  n'est pas ce que les vendeurs écrivent en DE (`Bartgeier`,
  `Gedenkmünze`).

I1 a livré les titres Numista localisés (`coin_names_i18n` FR+EN
peuplée à ~100%). I2 branche le matcher dessus, par langue active
du marketplace courant.

## Ce que l'utilisateur attend de la session

1. Un module `ml/sources/ebay/theme_tokens.py` qui extrait des tokens
   discriminants depuis un titre Numista localisé.
2. Une refacto de `title_matches_theme` qui prend la connection DB +
   le marketplace en plus du titre, et matche sur **toutes les langues
   actives** du marketplace.
3. Une plomberie côté `adapter.py` pour passer `conn` + `marketplace`.
4. Une validation empirique : sur 50 titres FR + 50 EN, médiane de
   tokens "utiles" dans `[2, 6]` (cf. spec). Sinon on tune les
   stop-words.
5. Un fallback compat propre : si `coin_names_i18n` n'a rien pour
   `(eurio_id, lang)`, on retombe sur l'ancien chemin slug + aliases
   sans casser. Le fallback est marqué deprecated, à retirer en V2.
6. Tests verts (75/75 actuels + ajouts pour le nouveau module).

## Décisions actées (verrouillées 2026-05-20)

| Décision | Choix | Rationale |
|---|---|---|
| **D-I2-1** Source des tokens par lang | `coin_names_i18n[eurio_id, lang].title` (FR+EN dispo aujourd'hui) | Spec language-probe §"Étape 2bis". Le vocabulaire seller est dans le titre Numista, pas dans le slug. |
| **D-I2-2** Langues actives matchées | `MARKETPLACE_ACTIVE_LANGS[mkt]` (nouveau dict dans `marketplaces.py`) | Distinct de `query_lang` (qui construit la query). Le matching scan toutes les langs qu'un mkt sert (ex EBAY_BE = fr + nl + en). |
| **D-I2-3** Langues non couvertes | Skip silencieux si titre i18n absent. Fallback global = `_theme_keywords` legacy sur slug EN | Pas de blocage : si DE/IT/ES/NL pas encore livrés (LLM chunk), le matcher continue de tourner sur ce qu'il a. |
| **D-I2-4** Stop-words | Listes par langue dans `theme_tokens.py`, jet initial spec'é dans language-probe §"Étape 2bis" | À tuner empiriquement avant cutover V2. Critère : médiane tokens utiles ∈ [2, 6]. |
| **D-I2-5** Normalisation | lowercase + NFKD drop-accents | Robuste aux variantes seller (`bearded` vs `Bearded`, `Gypaète` vs `gypaete`). |
| **D-I2-6** Fallback compat | Conservé tout au long de I2, **supprimé en V2** | R0 : pas de dette, mais on bascule progressivement (mesure recall I2 → V2 décide cutover). |
| **D-I2-7** API du matcher | `title_matches_theme(title, eurio_id, *, marketplace, conn)` | Spec language-probe. La signature change vs l'ancienne `(title, theme_tokens)` — adapter doit aussi changer. |

## Architecture cible

### Nouveau module — `ml/sources/ebay/theme_tokens.py`

Contient :

- `STOP_WORDS_BY_LANG: dict[str, set[str]]` — jet initial dans
  language-probe §"Étape 2bis" (6 langues définies : en/fr/de/it/es/nl).
- `COUNTRY_TOKENS_BY_LANG: dict[str, set[str]]` — bootstrappé depuis
  `coins.country_name` + variantes Numista (FR : "France", "française" ;
  DE : "Deutschland", "deutsche" ; etc.). Le détail du bootstrap :
  parser ~50 titres Numista par langue, extraire les tokens "pays"
  récurrents, les figer dans le dict. Pas de cron / auto-update.
- `normalize(s: str) -> str` — lowercase + `unicodedata.normalize("NFKD")` +
  drop combining marks. Pure function.
- `extract_tokens(title, lang, *, max_words=6, min_len=4) -> list[str]` —
  pipeline :
  1. `normalize(title)`
  2. split sur `\W+`
  3. drop si dans `STOP_WORDS_BY_LANG[lang]` ou `COUNTRY_TOKENS_BY_LANG[lang]`
  4. drop si `len < min_len`
  5. drop si pure digits OU ordinal regex (`^\d+(th|st|nd|rd|e|er|me|º|ª)$`)
  6. cap à `max_words`

### Modif `ml/sources/ebay/marketplaces.py`

Ajouter un dict :

```python
# Langues servies par chaque marketplace, pour matcher les titres
# multi-langues. Distinct de `query_lang` (qui construit la query
# côté discovery). EBAY_BE est bilingue FR+NL, EBAY_GB est anglo
# mais peut porter des listings expédiés EU avec titres en FR/DE/IT/ES.
# À reconfirmer empiriquement en V1 probe.
MARKETPLACE_ACTIVE_LANGS: dict[str, list[str]] = {
    "EBAY_AT": ["de", "en"],
    "EBAY_BE": ["fr", "nl", "en"],
    "EBAY_DE": ["de", "en"],
    "EBAY_ES": ["es", "en"],
    "EBAY_FR": ["fr", "en"],
    "EBAY_GB": ["en", "fr", "de", "it", "es", "nl"],  # catch-all multilingue
    "EBAY_IE": ["en"],
    "EBAY_IT": ["it", "en"],
    "EBAY_NL": ["nl", "en"],
}
```

### Refacto `ml/sources/ebay/queries.py`

- `_theme_keywords()` reste accessible (fallback compat). Marqué
  deprecated en docstring.
- Nouvelle signature de `title_matches_theme` :

```python
def title_matches_theme(
    title: str,
    eurio_id: str,
    *,
    marketplace: str,
    conn: sqlite3.Connection,
) -> bool:
    """Theme-match multilingue, conscient du marketplace courant.

    Pour chaque langue active du marketplace, charge le titre Numista
    localisé et compare ses tokens discriminants au titre seller. Match
    si ≥ 1 token apparaît dans le titre seller normalisé.

    Si aucun titre i18n n'est dispo pour (eurio_id, langs actives),
    fallback sur ``_theme_keywords(eurio_id)`` + ``THEME_TOKEN_FR_ALIASES``
    (deprecated, retiré en V2).
    """
```

- Helper interne `_load_i18n_title(conn, eurio_id, lang) -> str | None`
  qui fait un `SELECT title FROM coin_names_i18n WHERE eurio_id=? AND
  lang=?` (utilise un petit cache LRU intra-process si trop coûteux —
  à mesurer, possiblement pas nécessaire pour les volumes en jeu).
- `THEME_TOKEN_FR_ALIASES` reste dans le module — utilisé par fallback
  uniquement.

### Plomberie `ml/sources/ebay/adapter.py:455`

Le call actuel :

```python
if title_matches_theme(r.get("title") or "", ebay_q.theme_tokens):
```

devient :

```python
if title_matches_theme(
    r.get("title") or "", coin.eurio_id,
    marketplace=current_marketplace,
    conn=self._store._connection(),
):
```

`current_marketplace` est déjà accessible dans la boucle multi-mkt
(B4). `ebay_q.theme_tokens` devient inutile dans cette branche —
peut rester sur l'`EbayQuery` pour log/audit ou être retiré
(petite décision à prendre, je pencherais pour retirer en même
temps pour éviter le code mort).

## Plan d'attaque (proposé, 1 session)

1. **Lire** `language-probe.md` §"Étape 2bis" en entier (la spec qui
   nous concerne), puis `queries.py:245-330` + `adapter.py:440-470`
   pour bien cadrer le delta.
2. **Module `theme_tokens.py`** : écrire stop-words + country tokens +
   `normalize` + `extract_tokens` + tests unitaires (fixtures de
   titres Numista réels tirés de `coin_names_i18n`).
3. **`MARKETPLACE_ACTIVE_LANGS`** dans `marketplaces.py`.
4. **Refacto `title_matches_theme`** + helper `_load_i18n_title`.
   Tests : titre seller FR matche via i18n FR, titre seller EN via
   i18n EN, titre DE sur marketplace DE matche via fallback si DE
   pas encore peuplé.
5. **Plomberie `adapter.py`** : passer `conn` + `marketplace` au
   matcher. Vérifier que les tests adapter restent verts.
6. **Validation stop-words** : script jetable `scripts/probe_i18n_tokens.py`
   qui lit 50 FR + 50 EN dans `coin_names_i18n`, extrait les tokens,
   imprime médiane/min/max + 5 exemples. Tuner les stop-words si
   hors `[2, 6]`.
7. **Smoke run end-to-end** : 5 eurio_ids cibles, comparer recall
   I2 vs baseline legacy (avant cutover). Si recall ≥ baseline sur
   FR, et > 0 sur DE/IT/ES/NL (via fallback en attendant LLM),
   on a réussi.

## Open questions

- **OQ-1** : `_load_i18n_title` doit-il être thread-safe ? L'adapter
  multi-mkt boucle séquentiellement (B4) mais le matcher est appelé
  dans une thread `discovery_searches` peut-être ? À vérifier dans
  `adapter.py`. Si single-thread → pas besoin de cache thread-safe.
- **OQ-2** : Cache LRU sur `_load_i18n_title` ? Volume = ~600 coins ×
  6 langues = 3600 rows max. Le query SQLite est trivial — cache
  probablement inutile, à mesurer avant de bricoler.
- **OQ-3** : Faut-il livrer dès I2 les **LLM translations** DE/IT/ES/NL
  ou laisser la fallback couvrir ? L'utilisateur a explicitement
  marqué l'LLM-translation chunk comme **optionnel/conditionnel à
  une perte de recall mesurée** (cf. progress.md). Donc : I2 livre
  juste la plomberie, mesure recall sur DE/IT/ES/NL en fallback,
  on décide ensuite. **Mon avis** : ne pas le faire en I2, garder
  scope serré.
- **OQ-4** : `ebay_q.theme_tokens` : on retire de la dataclass ou
  on garde pour log ? Mon avis : retirer dans I2 pour éviter le code
  mort, et nettoyer les rows `theme_tokens` dans `discovery_searches`
  (juste arrêter de les écrire, les anciennes restent). Mais ça
  touche aussi `record_search` → vérifier l'impact tests.

## Fichiers à lire avant d'attaquer

| Fichier | Pourquoi |
|---|---|
| `docs/sources-refacto/ebay-multi-marketplace/language-probe.md` §"Étape 2bis" | La spec exhaustive, source de vérité |
| `docs/sources-refacto/ebay-multi-marketplace/progress.md` | État courant + ce que I1 a livré |
| `docs/sources-refacto/ebay-multi-marketplace/i18n-strategy.md` | Pourquoi FR+EN scraped + DE/IT/ES/NL en LLM (si livré) |
| `ml/sources/ebay/queries.py` (245-330) | Le matcher actuel + `THEME_TOKEN_FR_ALIASES` |
| `ml/sources/ebay/adapter.py` (440-470) | Point d'appel du matcher |
| `ml/sources/ebay/marketplaces.py` | Où ajouter `MARKETPLACE_ACTIVE_LANGS` |
| `ml/state/schema.sql` ligne 676 | Schéma `coin_names_i18n` (livré en I1) |

## Définition de "done"

- [ ] Module `ml/sources/ebay/theme_tokens.py` livré avec `STOP_WORDS_BY_LANG`,
      `COUNTRY_TOKENS_BY_LANG`, `normalize`, `extract_tokens` + tests
- [ ] `MARKETPLACE_ACTIVE_LANGS` ajouté à `ml/sources/ebay/marketplaces.py`
- [ ] `title_matches_theme` refactoré (nouvelle signature `(title, eurio_id, *, marketplace, conn)`)
- [ ] Plomberie `adapter.py` mise à jour
- [ ] Fallback compat `_theme_keywords` + `THEME_TOKEN_FR_ALIASES` conservé,
      docstring "deprecated, removed in V2"
- [ ] Probe `scripts/probe_i18n_tokens.py` lancé sur 50 FR + 50 EN,
      médiane tokens dans `[2, 6]` (sinon tuner les stop-words)
- [ ] Smoke run 5 eurio_ids : recall I2 ≥ recall baseline sur FR/EN
- [ ] Tests verts (75/75 + nouveaux)
- [ ] `progress.md` à jour, I2 marqué ✅

## Anti-objectifs

- ❌ Pas de scrape ni de LLM dans I2 — I1 est livré, LLM est un chunk
  séparé optionnel
- ❌ Pas de retrait de `THEME_TOKEN_FR_ALIASES` dans I2 — c'est V2
- ❌ Pas de refacto des autres modules eBay (filters, client) — scope
  matcher uniquement
- ❌ Pas de nouvelle migration schema — `coin_names_i18n` est déjà à jour

## Reprise après cette session

Quand I2 sera done, regarder dans cet ordre :

1. **Mesurer le recall** sur 10-20 eurio_ids cross-langue (FR, DE,
   IT, ES, NL). Si < baseline sur DE/IT/ES/NL → trigger le chunk
   `i18n-llm-translation.md` (LLM batch DE/IT/ES/NL via OpenAI/Claude
   batch API, persisté avec `confidence='llm'`).
2. **V1** : probe langues marketplaces empirique (1 query par mkt,
   sample 50 titres, compter la distribution des langues) →
   confirmer / corriger `MARKETPLACE_ACTIVE_LANGS`. Décider PT
   routing.
3. **V2** : cutover legacy — retirer `THEME_TOKEN_FR_ALIASES`,
   retirer le fallback, smoke run 10 eurio_ids, mesure recall KPI ≥ ×3.
