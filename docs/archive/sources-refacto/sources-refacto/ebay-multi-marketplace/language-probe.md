# Language probe — quelle langue chaque marketplace retourne vraiment

> But : confirmer empiriquement la langue principale (et secondaire) des
> titres retournés par chaque marketplace eBay qu'on cible, pour alimenter
> la table d'aliases multilingues du theme-matcher. Pas d'instinct, pas
> de "le marketplace DE est forcément en allemand" — on mesure.

## Pourquoi un probe et pas juste la langue affichée

Le marketplace définit la langue de l'**interface**, mais les sellers
peuvent rédiger leurs titres dans la langue de leur choix. On observe en
pratique :

- EBAY_FR : ~85 % FR, ~10 % EN (sellers pros internationaux), ~5 % mixte.
- EBAY_GB : ~70 % EN, ~30 % autres (sellers EU listent en local + EN
  partiel, parfois titre 100 % FR/DE/IT).
- EBAY_DE : ~80 % DE, ~15 % EN, ~5 % autres.
- EBAY_IT : ~80 % IT, ~10 % EN, ~10 % FR/DE selon le seller.

(Ordres de grandeur intuitifs du probe S3 ; à confirmer en mesure.)

Conséquence : pour matcher correctement le theme dans le titre, on a
besoin **par marketplace** d'un dict d'aliases dans **les 2-3 langues
qui y dominent**, pas seulement la langue native du marketplace.

## Étape 1 — Bootstrap Numista i18n

Source canonique des théme-tokens multilingues. Implémentation cf.
`ebay-strategy-v2-kickoff.md` §2.A — on reprend tel quel mais on étend
le scope (NL en plus de FR/EN/DE/IT/ES si EBAY_NL est utilisé).

### Script

`ml/scripts/bootstrap_coin_names_i18n.py`

- Input : table `coins` (filtrée commémos 2€ non-eu en priorité).
- Pour chaque coin avec `numista_id`, scrape les 6 sous-domaines :
  `fr/en/de/it/es/nl.numista.com/catalogue/pieces<numista_id>.html`,
  extrait `<h1>`.
- Throttling 1-2 req/sec.
- Output : table `coin_names_i18n` (cf. `schema.md` §"Table i18n").

### Coût

~3000 coins × 6 langues = 18 k requêtes ≈ 3-4 h de run. Lancement unique
(`--refresh` pour re-run sélectif).

### Critère de succès

Tous les coins ciblés (commémos 2€ non-eu) ont au moins 4 langues
remplies sur les 6 sondées. Si < 80 % couverture sur une langue → soit
le scrape a échoué, soit Numista ne traduit pas ce coin dans cette langue
(légitime, on accepte).

## Étape 2 — Probe marketplaces × langues

### But

Pour chaque marketplace qu'on appelle effectivement (FR, GB, DE, ES, IT,
NL, AT, BE, IE), mesurer sur un échantillon contrôlé :

1. La proportion de titres écrits dans la langue native.
2. La proportion en EN.
3. La proportion en autres langues européennes.
4. Le recall absolu (n_results) avec query construite dans la langue
   native du marketplace.

### Méthodologie

Réutiliser le pattern de `ml/scripts/probe_ebay_query_strategies.py`
(le code legacy déjà débuggé). Nouveau script :

`ml/scripts/probe_marketplace_languages.py`

- Échantillon de 8 eurio_ids commémos variés (1 par grand pays + 2 micro-États).
- Pour chaque eurio_id × chaque marketplace cible :
  - Construit `q` dans la langue native du marketplace (cf. `vision.md` §P3).
  - Tire les 50 premiers `itemSummaries`.
  - Détection de langue sur chaque titre via `langdetect` ou
    `langid` (déjà dans `requirements.txt` ? sinon ajouter une dépendance
    light). Fallback : si la détection est ambiguë (< 0.6 confiance),
    classifie en `unknown`.
- Output : `ml/state/probe_marketplace_languages_<timestamp>.json` —
  agrège par (marketplace, langue détectée) → count + sample titres.
- Coût quota : 8 × 9 = **72 calls** (négligeable).

### Format attendu de sortie

```jsonc
{
  "generated_at": "2026-...",
  "samples": ["ad-2025-...", "be-2006-...", ...],
  "marketplaces": {
    "EBAY_FR": {
      "n_titles_total": 400,
      "by_lang": {"fr": 320, "en": 50, "es": 18, "de": 12, "unknown": 0},
      "sample_titles_by_lang": { ... }
    },
    "EBAY_GB": {
      "n_titles_total": 400,
      "by_lang": {"en": 240, "fr": 60, "de": 50, "it": 30, "es": 15, "unknown": 5},
      "sample_titles_by_lang": { ... }
    }
    // …
  }
}
```

### Critère d'arbitrage par marketplace

Une langue X est considérée "active" sur le marketplace M si
`by_lang[X] / n_titles_total ≥ 0.10`. Le matcher theme pour M doit
inclure les aliases dans toutes ses langues actives (issus du bootstrap
i18n). Exemple attendu :

| Marketplace | Langues actives prédites |
|---|---|
| `EBAY_FR` | fr, en |
| `EBAY_GB` | en, fr, de, it, es |
| `EBAY_DE` | de, en |
| `EBAY_IT` | it, en |
| `EBAY_ES` | es, en |
| `EBAY_NL` | nl, en |
| `EBAY_AT` | de, en |
| `EBAY_BE` | fr, nl, en |
| `EBAY_IE` | en |

À reconfirmer par le probe — peut-être que EBAY_GB porte aussi du
portugais ou du grec à 10 %, auquel cas on ajoute ces langues à la
matrice.

## Étape 2bis — Tokenisation theme multilingue (spec gap-fill)

Le matcher actuel extrait les théme-tokens depuis le **slug anglais
eurio_id** (`_theme_keywords()` dans `queries.py:184`), avec un dict
`STOP_WORDS` mixant filler EN+FR. Pour passer multilingue, deux voies
existent ; on tranche ici pour éviter la dette technique.

### Voie retenue — "slug EN + titre Numista localisé → tokens par langue"

Pour chaque eurio_id et chaque langue active du marketplace courant,
on dérive une liste de tokens dans **cette langue** à partir du titre
Numista `coin_names_i18n[eurio_id, lang].title`. La logique :

```python
# ml/sources/ebay/theme_tokens.py — nouveau module

# Stop-words par langue. Volontairement courts : on cible les mots
# fonctionnels qui apparaissent partout et n'aident pas à discriminer
# un thème de commémo. Sources : listes ISO standard + curation manuelle
# sur ~50 titres Numista par langue lors du chunk I2.
STOP_WORDS_BY_LANG: dict[str, set[str]] = {
    "en": {"of","the","in","and","a","an","to","for","with","on","by",
           "anniversary","years","since","birth","death","th","st","nd","rd",
           "euro","euros"},
    "fr": {"de","la","le","les","du","des","et","au","aux","à","pour","en",
           "anniversaire","ans","naissance","mort","décès",
           "euro","euros"},
    "de": {"der","die","das","den","dem","des","und","von","im","in","zu","mit",
           "jahre","jahrestag","geburtstag","jahrhundert",
           "euro"},
    "it": {"di","del","della","dei","delle","il","lo","la","i","gli","le","e",
           "anniversario","anni","nascita","morte",
           "euro"},
    "es": {"de","del","la","el","los","las","y","en","para",
           "aniversario","años","nacimiento","muerte",
           "euro","euros"},
    "nl": {"van","de","het","een","en","in","op","voor",
           "jaar","jubileum","geboorte","overlijden",
           "euro"},
}

# Tokens "pays" par langue, retirés comme dans COUNTRY_SLUG_TOKENS aujourd'hui
# (Andorra/Andorre/Andorra/Andorra/Andorra/Andorra etc.). Bootstrappé en
# I2 à partir de `coins.country_name` × Numista headers.
COUNTRY_TOKENS_BY_LANG: dict[str, set[str]] = { ... }

def extract_tokens(
    title: str, lang: str, *, max_words: int = 6, min_len: int = 4
) -> list[str]:
    """Tokens discriminants d'un titre Numista localisé.

    Pipeline :
    1. lowercase + NFKD-normalize (drop accents pour matching robuste).
    2. split sur `\\W+`.
    3. drop si dans STOP_WORDS_BY_LANG[lang] ou COUNTRY_TOKENS_BY_LANG[lang].
    4. drop si len < min_len (évite "war"-style false positives).
    5. drop si pure-digits (années) ou ordinal (`100th`, `2e`, `100º`).
    6. cap à max_words pour limiter le risque de matches accidentels.
    """
    ...
```

### Pourquoi PAS l'autre voie ("extension du dict THEME_TOKEN_FR_ALIASES")

Continuer à extraire les tokens depuis le slug EN puis les traduire via
un dict EN→{lang: aliases} a l'air plus simple, mais :

1. Le slug EN est **maintenu à la main** (numista → eurio_id) et a un
   vocabulaire très restreint vs un titre Numista localisé qui contient
   le vocabulaire que les vendeurs vont effectivement utiliser. Exemple :
   slug `bearded-vulture` → token `vulture` ; titre DE Numista
   `"Bartgeier — 2 Euro Gedenkmünze"` → tokens `bartgeier`, `gedenkmünze`.
   Le second est strictement plus large et plus aligné avec les titres
   sellers.
2. Maintenir un dict EN→{6 langues} pour 466 commémos serait du travail
   manuel sans fin (chaque nouveau coin = 6 entrées de dict). La voie
   "extraire depuis Numista" se bootstrappe une fois pour toutes via
   le scrape déjà spec'é.
3. C'est la dette technique qu'on refuse (cf. R0 CLAUDE.md) : un dict
   d'aliases hand-curated est par définition incomplet et asymétrique.

### Schéma logique du matcher (mis à jour)

```python
# ml/sources/ebay/queries.py — refacto I2

def title_matches_theme(
    title: str,
    eurio_id: str,
    *,
    marketplace: str,
    conn: sqlite3.Connection,
) -> bool:
    """Theme-match multilingue, conscient du marketplace courant."""
    active_langs = MARKETPLACE_ACTIVE_LANGS[marketplace]  # ex: ["en", "fr", "de"]
    title_low = _normalize(title)  # lowercase + NFKD drop accents
    for lang in active_langs:
        numista_title = load_i18n_title(conn, eurio_id, lang)
        if numista_title is None:
            continue  # coin pas couvert dans cette langue, on skip
        tokens = extract_tokens(numista_title, lang)
        for tok in tokens:
            if tok in title_low:
                return True
    return False
```

### Fallback compat

Si `coin_names_i18n` est vide pour un eurio_id (run avant bootstrap I1),
le matcher tombe sur l'ancien `_theme_keywords(eurio_id)` + l'ancien
`THEME_TOKEN_FR_ALIASES`. Ce fallback est **temporaire** et supprimé
par V2 (cutover) une fois la couverture i18n confirmée > 95 %.

### Stop-words : critère de validation

Les listes par langue ci-dessus sont un **premier jet** à valider en
I2 :

- Prendre 50 titres Numista par langue (échantillon stratifié).
- Mesurer le nombre de tokens "utiles" par titre après filtrage.
- Si médiane > 6 tokens → stop-words sous-spécifiés (faux positifs en
  vue), enrichir.
- Si médiane < 2 tokens → stop-words trop agressifs (faux négatifs),
  alléger.
- Documenter la version retenue en commentaire avec date.

## Étape 3 — Matcher theme-tokens étendu (résumé)

L'implémentation suit Étape 2bis. Aucun détail supplémentaire ici.

### Dépréciation

`THEME_TOKEN_FR_ALIASES` (`queries.py:88`) devient legacy une fois la
i18n live. À retirer **au chunk V2** après validation couverture i18n.

## Liens utiles

- Probe legacy : `ml/scripts/probe_ebay_query_strategies.py`
- Probe S3 data : `ml/state/probe_ebay_query_strategies_20260504T212313Z.json`
- Numista API specs : `docs/research/ebay-api-strategy.md` (mention rapide
  des sub-domains)
- Aliases FR actuels : `ml/sources/ebay/queries.py:88` (`THEME_TOKEN_FR_ALIASES`)
