# Kickoff — C2a-2 : alias colloquiaux générés par LLM

> Brief auto-suffisant pour la session qui livre **C2a-2** du chantier
> recall theme-matcher. À reprendre dans une session neuve.
>
> Verrouillé 2026-05-22, après livraison P0 / C1 / C2a-1.
>
> Lire d'abord, dans l'ordre :
> 1. `theme-matcher-recall-kickoff.md` — le plan d'ensemble du chantier
> 2. `research/entity-matching-standards.md` — les findings industriels
> 3. `PROGRESS-improve-ebay-matching-indus-standard.md` — le journal vivant
>    (état P0/C1/C2a-1, découvertes, contraintes)

## Pourquoi cette session existe

Le theme-matcher eBay attribue un listing bruité multilingue à une
commémo de son groupe de découverte. Audit du run réel `b6bede99…` :
~⅔ des `theme_mismatch` étaient des **faux rejets** — pièces valides
jetées, parce que les traductions i18n sont *littérales* (« Ereignisse
vom Mai 1968 ») alors que les vendeurs écrivent le **vocabulaire de
marché** (« Studentenrevolte »).

Déjà livré :
- **P0** — socle de mesure (gold bench gelé + replay harness).
- **C1** — `no_match` → `ambiguous` : on ne jette plus une pièce valide,
  on la route en review.
- **C2a-1** — table `coin_aliases` + mining des **acronymes** en
  parenthèses des titres i18n (`(EMI)` → `emi`). Le matcher
  (`_theme_match_state`) poole déjà les alias, matchés en limite de mot.

**C2a-1 a montré sa limite** : seuls 5 acronymes dans tout le catalogue
(tous EMI). Le gros du vocab de marché — « Studentenrevolte », « Iris »
(surnom d'ESRO-2B), « BLEU », « Brügel » — n'est PAS en parenthèses.
C2a-2 le couvre via génération LLM ancrée.

## 📊 Tableau de bord — évolution du bench

Bench fidèle (`accept_listing` + theme-matcher) sur le gold gelé v1
(196 listings réels, run `b6bede99`, BE 2017-2021).

| Étape | Faux rejet | Recall | **Auto-attribution ★** | Review | Junk false-keep |
|---|---|---|---|---|---|
| Baseline | 34,3 % | 65,7 % | 65,7 % | 0 % | 2,4 % |
| C1 | 14,1 % | 85,9 % | 65,7 % | 20,2 % | 42,4 % |
| C2a-1 | 14,1 % | 85,9 % | **68,7 %** | 17,2 % | 42,4 % |
| **C2a-2** | _cible_ | _cible_ | **↑ à mesurer** | ↓ | = |

**Étoile polaire = taux d'auto-attribution.** C2a-2 doit le faire
monter (faire matcher « Studentenrevolte » & co → review → auto).
C2a-2 ne touche PAS le faux rejet (C1 l'a déjà traité) ni le junk
false-keep (garde-fou de contradiction = chunk séparé).

## Ce que C2a-2 doit livrer

Le matcher poole déjà `coin_aliases` (fait en C2a-1) — **C2a-2 ne touche
pas le code du matcher**, il ne fait que PEUPLER la table avec des alias
colloquiaux. Trois pièces :

### 1. Workflow d'export/ingest LLM (même pattern que le LLM-juge du bench)

- `go-task ml:aliases:export-batch` — pour un périmètre de coins (filtre
  `--country` / `--years`, défaut = le périmètre du gold : BE 2017-2021),
  sort un JSONL : par coin → `eurio_id`, `theme`, titres i18n (6 langues),
  et **les sœurs du groupe** (eurio_id + thème) comme contexte
  anti-collision.
- Claude Code lit le batch, génère par coin les **termes de marché /
  surnoms / variantes** réellement employés par les vendeurs eBay (toutes
  langues utiles), écrit un JSONL d'alias.
- `go-task ml:aliases:ingest` — ré-ingère dans `coin_aliases` avec
  `source='llm'`. **Garde-fou anti-collision** : un alias candidat est
  rejeté s'il matche (en limite de mot, normalisé) le titre i18n ou un
  alias d'une **sœur du groupe** — sinon il ferait hit sur la mauvaise
  pièce. Logguer les alias rejetés pour collision.

Réutiliser le script `scripts/bench_theme_match.py` comme modèle (mode
export/ingest, JSONL, `Store`, ancres). Nouveau script
`scripts/llm_coin_aliases.py` ou étendre `mine_coin_aliases.py`.

### 2. Génération des alias (le travail de juge LLM = Claude Code)

Gaps connus du bench à couvrir (NON exhaustif — la session doit lire
chaque coin du batch) :

| Coin | Manque dans l'i18n | Alias de marché à générer |
|---|---|---|
| `…esro-2b` (2018) | le surnom | `iris` (ESRO-2B était surnommé Iris) |
| `…may-1968` (2018) | tout le vocab | `studentenrevolte`, `maiaufstande`, `studentenaufstand`, `studentendemonstration`, `studentenproteste`, `revuelta`, `estudiantil`, `mai 68` |
| `…pieter-bruegel` (2019) | les variantes | `brugel`, `breugel` (orthographes vendeurs de « Brügel ») |
| `…belgium-luxembourg` (2021) | l'abréviation | `bleu` (abréviation BLEU — confidence basse, « bleu » = bleu en FR) |
| `…ghent-university` (2017) | Gand vs Liège | `gent`, `gand`, `ghent`, `gante` — *cf. découverte catalogue ci-dessous* |

Règles : alias **normalisés** (lowercase, sans accents — `theme_tokens.
normalize`). Pas d'orthographes fautives uniques ; viser les termes
canoniques du marché. Tagger `confidence` (`high` si terme établi,
`low` si ambigu type `bleu`).

### 3. Vérification & mesure

- Re-lancer le bench : `go-task ml:bench:theme-match` → comparer
  l'auto-attribution à la ligne C2a-1 (68,7 %).
- A/B propre : le changement est de la DONNÉE (`coin_aliases`), pas du
  code. Pour isoler l'effet → `DELETE FROM coin_aliases WHERE
  source='llm'` puis replay, ré-ingérer puis replay. Ou bencher juste
  avant / juste après l'ingest.
- Mettre à jour le tableau de bord ci-dessus + le PROGRESS.

## Comment bencher (rappel complet)

Le bench découple la mesure du progrès de la donnée live (re-scraper
donne des listings différents). Tout est dans `scripts/bench_theme_match.py`.

```
go-task ml:bench:theme-match            # replay sur le gold gelé → métriques
go-task ml:bench:theme-match -- -v      # + détail par listing
```

- Gold gelé : `ml/state/discovery_bench/theme_match_gold.jsonl`
  (196 entrées, NE PAS regénérer sans raison — c'est la référence).
- Le replay rejoue `accept_listing` PUIS `match_listing_to_group` (le
  vrai pipeline), hors quota, déterministe.
- **A/B d'un changement de code** : `git stash` le changement → replay →
  `git stash pop` → replay. Le gold étant fixe, le matcher est la seule
  variable.
- **A/B d'un changement de donnée** (cas C2a-2) : replay avant / après
  l'ingest des alias.

Métriques clés du rapport : taux de faux rejet, **taux d'auto-attribution
(★)**, recall, précision, junk false-keep.

## Découvertes / contraintes à connaître (depuis le PROGRESS)

1. **Catalogue Ghent/Liège incohérent** — `be-2017-…ghent-university` :
   slug + `theme` disent *Ghent*, les 6 titres i18n disent tous *Liège*.
   Même pièce (bicentenaire des universités de 1817). 2017 est un groupe
   **mono-pièce** → le matcher renvoie `single` sans theme-check → les
   alias 2017 n'ont AUCUN effet sur le bench. Les générer quand même
   (cohérence catalogue) mais sans en attendre un gain mesuré.
2. **Groupes mono-pièce auto-attribuent tout** (`len(ids)==1 → single`).
   Garde-fou différé — hors C2a-2.
3. **Junk false-keep à 42 %** — hérité de C1 : le junk qui atteint le
   matcher part en review au lieu d'être jeté. C2a-2 n'y touche pas ;
   c'est un chunk « garde-fou de contradiction » distinct.
4. **`text_signal` tourne après `discover`** — au moment du matcher,
   seul `accept_listing` a filtré (millésime/prix/devise/bruit).
5. **Étiquetage en masse = ancres obligatoires** — toute génération
   indexée doit porter des assertions d'ancrage (un décalage d'index
   avait corrompu la 1ʳᵉ passe du gold).
6. **Reste P0** : spot-check humain d'une tranche ~40 du gold (validation
   du juge), à faire à la main.

## Fichiers clés

| Fichier | Rôle |
|---|---|
| `ml/state/schema.sql` | table `coin_aliases` (eurio_id, lang, alias, source, confidence) |
| `ml/sources/ebay/theme_tokens.py` | `load_aliases()`, `normalize()`, `extract_tokens()` |
| `ml/sources/ebay/queries.py` | `_theme_match_state` (poole les alias, match limite de mot), `match_listing_to_group` |
| `ml/scripts/mine_coin_aliases.py` | mining acronymes (C2a-1) — modèle pour le script LLM |
| `ml/scripts/bench_theme_match.py` | bench export/ingest/replay — modèle de workflow |
| `ml/state/discovery_bench/` | gold gelé + batch + labels |

## Definition of done

- Workflow `aliases:export-batch` / `ingest` livré, idempotent, avec
  garde-fou anti-collision.
- `coin_aliases` peuplée d'alias `source='llm'` pour le périmètre BE
  2017-2021 (a minima les gaps du tableau ci-dessus).
- Bench re-mesuré, auto-attribution comparée à 68,7 %, tableau de bord +
  PROGRESS à jour.
- Tests : génération de collision rejetée, alias LLM produit un hit.
- Commit `C2a-2 — …` ; chunk-by-chunk, livrer puis attendre rétro.
