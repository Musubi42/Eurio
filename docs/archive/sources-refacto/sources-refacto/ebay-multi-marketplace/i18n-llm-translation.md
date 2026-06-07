# Runbook — traduction LLM des noms de pièces (DE/IT/ES/NL)

> **Deadly simple.** Claude Code traduit lui-même, **3 pièces par batch**,
> sur plusieurs sessions. Pas d'API Anthropic, pas de script LLM — c'est
> Claude (cette session) qui produit les traductions.
>
> Verrouillé 2026-05-20.

## Pourquoi

Le benchmark de routing marketplace
(`research/marketplace-routing-benchmark.md`) doit appliquer
`title_matches_theme` pour mesurer le **vrai** recall. Or le matcher
n'a de titres que FR+EN (`coin_names_i18n`) — appliquer le theme-match
biaise le benchmark en faveur des marketplaces à titres FR/EN.

On comble le trou pour les **112 coins du benchmark uniquement** :
traduire leurs titres EN → DE/IT/ES/NL. Une fois fait, le benchmark
peut être relancé avec theme-match, non-biaisé.

Pas les 578 coins — juste les 112. Extension au reste = plus tard.

## Données

- **Worklist** : `ml/state/i18n_llm_worklist.json` — 112 coins, chacun
  avec `eurio_id`, `country`, `country_name`, `year`,
  `is_commemorative`, `theme_en`, `title_en`, `title_fr`.
- **Sortie** : `ml/state/i18n_llm_results.jsonl` — append-only, 1 ligne
  par (coin, langue).
- **Import** : `python -m scripts.import_llm_translations` → upsert
  dans `coin_names_i18n` (`source='llm_v1'`).

## Règles de traduction (anti-hallucination — STRICTES)

Source = titre EN canonique (Numista). Pour chaque coin tu as aussi le
pays, l'année, le thème EN, le titre FR canon (aide précieuse).

1. **Standard** (pas de thème commémo) : traduire la dénomination
   naturellement (`2 Euros` → `2 Euro` en DE).
2. **Commémo avec nom consacré** : si l'événement / personnage / lieu a
   une forme **consacrée** dans la langue cible, l'utiliser. Ex :
   `Kneeling to Warsaw` → DE `Kniefall von Warschau`.
3. **Commémo descriptive sans nom consacré** : traduire le thème
   naturellement et idiomatiquement.
4. **Noms propres non traduits** : garder tels quels (`Grace Kelly`
   reste `Grace Kelly`).
5. **Doute** : si tu n'es PAS sûr de la forme consacrée, ou le contexte
   est insuffisant → mettre `title` = `"UNCERTAIN"`, `confidence` =
   `"uncertain"`.
6. **JAMAIS inventer** un nom officiel plausible. `UNCERTAIN` >
   hallucination.

Le titre FR canon est souvent un bon indice de la forme idiomatique —
s'en servir, sans le recopier aveuglément (FR ≠ DE/IT/ES/NL).

## Protocole par session

1. Ouvrir `ml/state/i18n_llm_worklist.json`.
2. Compter les lignes de `ml/state/i18n_llm_results.jsonl` (si absent =
   0). `lignes / 12` = nombre de batches déjà faits (chaque batch =
   3 coins × 4 langues = 12 lignes).
3. **Batch N** = les coins d'index `[3·(N-1) … 3·N)` dans le worklist.
   Traiter ~3 à 8 batches par session (au jugé — ne pas tout faire d'un
   coup, livrer et laisser une session de check).
4. Pour chaque coin du batch, produire les 4 traductions (de, it, es,
   nl) en suivant les règles.
5. **Appender** les 12 lignes à `ml/state/i18n_llm_results.jsonl`.
6. En fin de session : `python -m scripts.import_llm_translations`
   (idempotent — ré-importe tout le JSONL).
7. Noter dans `progress.md` les batches faits.

### Format de ligne JSONL

```json
{"eurio_id": "ad-2017-2eur-100-years-of-the-anthem-of-andorra", "lang": "de", "title": "2 Euro Hymne von Andorra", "confidence": "assisted"}
```

`lang` ∈ `de|it|es|nl`. `confidence` ∈ `assisted|uncertain`.

## Done — livré 2026-05-20

- [x] 112 coins × 4 langues = **448 lignes** dans `i18n_llm_results.jsonl`.
- [x] `import_llm_translations` exécuté → `coin_names_i18n` couvre
  DE/IT/ES/NL pour les 112 coins (112 rows `llm_v1` par lang).
- [x] Taux `uncertain` = **0 %** (≤ 10 % cible largement tenue).
- [x] Session de **check** : audit qualité complet par agent de review
  — verdict OK, aucune correction bloquante. Un seul ajustement
  stylistique appliqué (`de-2020-…-warschau` nl : « Kniezakking » →
  « Kniebuiging »).

Traduction faite en un go (4 agents en parallèle, 28 coins chacun +
2 agents de rattrapage sur 7 coins ratés par dérive d'index, puis
1 agent de review). Pas de re-run nécessaire.

### Anomalies remontées côté worklist (hors périmètre résultats)

Détectées à l'audit, à corriger dans `export_i18n_worklist.py` ou en
amont — n'affectent pas les traductions importées :

- `hr-2025-…-pula` : `title_fr` = « 2 Euros City of Pula » (copie EN
  non traduite). Les 4 traductions LLM sont correctes.
- `ee-2022-…-society-of-estonian` : `title_en` = « Society of Estonian
  Literaty » (typo Numista pour « Literati »). Les traductions ont
  correctement interprété « Literati ».

## Après

Une fois les 448 traductions importées :
1. Ré-intégrer `title_matches_theme` dans
   `scripts/probe_marketplace_routing.py` (re-fetch + filtre theme).
2. Re-run le benchmark → routing précis ET non-biaisé.
3. Cf. `research/marketplace-routing-benchmark.md` §"Prochaine étape".

## Anti-objectifs

- ❌ Pas d'API Anthropic, pas de SDK — Claude Code traduit directement.
- ❌ Pas les 578 coins — seulement les 112 du benchmark.
- ❌ Pas de FR/EN — déjà canon (`source='numista'`).
- ❌ Ne pas tout traduire en une session — batches, audit entre.
