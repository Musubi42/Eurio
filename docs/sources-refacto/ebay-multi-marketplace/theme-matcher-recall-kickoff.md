# Kickoff — recall du theme-matcher (couches 1 → 2 + mesure)

> Plan d'implémentation pour corriger les **faux rejets** du theme-matcher
> de la découverte groupée. Déclenché par l'audit du run `b6bede99…`.
>
> Lire d'abord `research/entity-matching-standards.md` (les findings) et
> `discovery-groupee-handoff.md` (le contexte découverte groupée).
>
> Verrouillé 2026-05-22.

## Pourquoi cette session existe

Run réel `b6bede99…` (5 groupes BE 2017-2021) : **289 rejets**, dont
`theme_mismatch` **164**. Classification grossière : **~102 / 164 sont
des faux rejets** — des pièces valides du groupe, jetées.

Cause racine (croisée avec les titres i18n) : la couverture i18n est à
100 %, mais les traductions LLM sont **littérales** alors que les
vendeurs eBay emploient le **vocabulaire de marché** :

| Coin | Titre i18n DE (LLM) | Ce que les vendeurs écrivent |
|---|---|---|
| Mai 1968 | « 2 Euro Ereignisse vom Mai 1968 » | « Studentenrevolte », « Maiaufstände » |
| Institut Monétaire Européen | « …Europäisches Währungsinstitut » | « EMI » (l'acronyme) |

Le matcher (`match_listing_to_group` / `title_matches_theme` dans
`ml/sources/ebay/queries.py`) fait de l'overlap de tokens : zéro token
commun → `no_match` → listing **jeté**.

## Architecture cible (issue des findings)

```
listing ─► [accept_listing]──► [text_signals]──► [match_listing_to_group]──► verdict
            année/prix/         pays/année/        score chaque sœur          │
            devise (déjà OK)    dénom contradict   du groupe                  │
                                (déjà OK)                                     ▼
                                              ┌───────────────────────────────────┐
                                              │ s1 = top-1, s2 = top-2 (marge)     │
                                              ├───────────────────────────────────┤
                                              │ s1≥τ_high & marge≥δ → single (auto)│
                                              │ s1≥τ_high & marge<δ → ambiguous    │
                                              │ s1 faible, pas de contradiction    │
                                              │        → ambiguous (review)        │
                                              │ contradiction positive → no_match  │
                                              └───────────────────────────────────┘
```

Principes (cf. findings) :
- Le **groupe est le blocking** — déjà fait. On ne travaille que le
  *matcher* + la *décision*.
- **Multi-classes sur ensemble fermé** (N sœurs + `NONE`), pas du
  pairwise. Décision par **marge top-1/top-2**.
- **Absent ≠ contradiction** : un thème non reconnu fait *abstenir* le
  signal, il ne vote pas contre. `no_match` ne se déclenche que sur
  contradiction positive.
- **Jamais de discard silencieux** : tout rejet est un état récupérable,
  motivé, audité.

## Prérequis — P0 : socle de mesure

Rien ne peut être calibré ni « challengé » sans un instrument de mesure
stable. **P0 vient avant les couches.** Détail dans la section
« Cadre de mesure » plus bas. Livrables P0 :

- **Gold benchmark gelé** — `ml/state/discovery_bench/theme_match_gold.jsonl` :
  **~200 titres de listings réels (lean v1)**, sous-échantillon stratifié
  par année/groupe des ~620 listings du run `b6bede99…` déjà en DB, chacun
  étiqueté par un verdict de vérité. Le bench grandit ensuite via I3.
- **Replay harness** — `go-task ml:bench:theme-match` : rejoue le matcher
  courant sur le gold gelé, hors quota, sort recall / précision /
  taux-de-faux-rejet / taux-d'auto-attribution.
- **LLM-judge** — workflow d'étiquetage du gold + audit du bucket reject
  d'un run réel, opéré par Claude Code (cf. I3).

## Couche 1 — `no_match` → `ambiguous` (filet immédiat)

**Le plus petit fix, zéro dépendance, consensuel.** Quand un listing
atteint `match_listing_to_group`, il a déjà passé `accept_listing` et
n'est pas `text_contradict` — donc bon pays/année/dénom. Un `no_match`
du theme-matcher signifie « bon groupe, thème non reconnu ».

- `match_listing_to_group` : le verdict `no_match` devient `ambiguous`
  dès lors qu'aucun signal ne **contredit** le groupe (garanti à ce
  stade). Le vrai `no_match` est réservé à une future contradiction
  explicite (V2).
- Conséquence : le listing part en `review_queue` avec ses
  `group_candidates` (chunk 5b) — le reviewer attribue en 1 clic.
- `discarded_listings` : un `theme_mismatch` cesse d'être une
  suppression. Soit on route en review, soit (si on garde une trace de
  rejet) c'est un état **récupérable + motivé**, jamais un delete.
- Effet attendu : ~100 pièces/run sauvées immédiatement. La charge bascule
  sur la file de review — d'où l'urgence des couches 2 pour la réduire.

Touche : `ml/sources/ebay/queries.py` (`match_listing_to_group`),
`ml/sources/ebay/adapter.py` (le branchement verdict). Tests :
`test_ebay_adapter.py`.

## Couche 2a — enrichissement par alias

Modèle Wikidata `label` + `altLabel`. Nouvelle table `coin_aliases`
(eurio_id, lang, alias, source, confidence) — additive.

- **Construction** (offline, one-shot + rejouable) :
  - extraction d'acronymes par pattern « X (Y) » ;
  - anchor-text Wikipedia de l'événement/institution sous-jacent ;
  - n-grammes fréquents minés sur notre corpus de titres eBay déjà
    correctement matchés ;
  - génération LLM **ancrée** (contexte Numista/Wikipedia fourni,
    extraction et non invention).
- **Garde-fous** : chaque alias vérifié contre un corpus réel + check
  anti-collision (rejeté s'il matche aussi une autre pièce) +
  `source`/`confidence` tagués (cf. `i18n-strategy.md`).
- Le matcher token-overlap **marche tel quel** sur l'index enrichi
  (`titres i18n + alias`). Chemin le moins disruptif, 100 % inspectable
  — colle à R0 (pas de dette cachée).

Touche : migration `coin_aliases`, script de mining
(`ml/scripts/`), `theme_tokens.py` / `title_matches_theme` (poole les
alias en plus des titres i18n).

## Couche 2b — scoreur sémantique multilingue

Filet pour la longue traîne que les alias ratent.

- Embedding **LaBSE** (ou `paraphrase-multilingual-mpnet-base-v2`) —
  tourne en local, cohérent avec la stack DINOv2/ArcFace.
- Le listing et chaque sœur du groupe sont encodés → similarité cosinus
  → un **score par sœur**. C'est ce qui donne enfin de vrais scores
  exploitables pour la **marge top-2** de l'architecture cible.
- **Fusion hybride** lexical (2a) + sémantique (2b) par Reciprocal Rank
  Fusion (`Σ 1/(60 + rank)`) — le lexical garde sa force sur les
  discriminants durs, le sémantique rattrape le vocab gap.
- Plus de pré-traduction nécessaire au matching : LaBSE matche
  l'allemand brut contre le canonique directement.

Touche : un module `ml/sources/ebay/` (ou `ml/foundation/`) pour
l'encodeur, intégration dans le matcher, dépendance `sentence-transformers`.

## Couche 2c — matcher LLM (conditionnel, à évaluer)

Mettre les N sœurs dans un prompt → l'LLM retourne `eurio_id` + confiance
+ `NONE`. Le plus robuste (gère le multilingue nativement, peu de data).

**Statut : évalué sur le bench, adopté seulement si 2a+2b laissent le
recall court.** Réserves :
- coût + latence **par listing**, dépendance externe récurrente — contre
  la préférence zéro-infra.
- **circularité avec la mesure** : si le juge de la mesure est un LLM
  (cf. plus bas), un matcher LLM doit utiliser un prompt / idéalement un
  modèle distinct du juge, sinon on mesure le matcher avec lui-même.

Décision reportée après la mesure de 2a+2b.

## Cadre de mesure — comment « challenger » les couches

Problème : re-scraper donne des **listings différents à chaque fois**
(marketplace live) → on ne peut pas comparer run A vs run B directement.
Il faut **découpler la mesure de la donnée live**. Quatre instruments :

### I1 — Gold benchmark gelé (la métrique stable)

`ml/state/discovery_bench/theme_match_gold.jsonl` : **~200 listings réels
(lean v1)**, chacun `{titre, marketplace, groupe (dénom,pays,année),
verdict}`. Verdict de vérité ∈ :
- `coin:<eurio_id>` — pièce valide, attribuable à cette pièce ;
- `lot` — lot / coffret / collection ;
- `not-a-coin` — billet « 0 euro », accessoire, etc. ;
- `wrong-scope` — mauvais pays / année / dénomination ;
- `ambiguous` — réellement 2+ sœurs plausibles.

Construit par **passe LLM-juge (I3) + relecture humaine d'une tranche
d'ancrage (~40 items)**, puis **gelé** (committé, versionné).
Sous-échantillon stratifié par année/groupe des ~620 listings du run
`b6bede99…` déjà en DB (titres dans `discarded_listings` + attribués).
Le bench grandit ensuite : les faux rejets confirmés par I3 sur les runs
suivants y sont ajoutés (après spot-check).

### I2 — Replay harness (la porte de régression)

`go-task ml:bench:theme-match` : rejoue le matcher **courant** sur le
gold gelé, **hors quota**, et sort :
- **recall** = pièces valides correctement gardées (auto-attribuées OU
  routées en review avec la bonne pièce dans les candidats) / total
  valides ;
- **précision** = attributions correctes / total auto-attributions ;
- **taux de faux rejet** = valides jetées / total valides — *le chiffre
  phare* ;
- **taux d'auto-attribution** = auto-attribuées / total valides — la
  métrique d'autonomie (recall via review = bien, via auto = mieux) ;
- **charge de review** = items routés en review / total.

Chaque version du matcher (couche 1, 2a, 2b…) est scorée sur le **même**
gold → comparaison propre. C'est l'outil pour « challenger » : on
implémente une couche, on relance le harness, on lit l'évolution.

**Étoile polaire** : le **taux d'auto-attribution à précision fixée**.
Subtilité — la couche 1 seule fait sauter le recall à ~100 % (plus rien
n'est jeté) mais tout part en review ; le vrai gain des couches 2 est de
convertir *review → auto-attribution*. C'est donc cette courbe-là, pas
le recall brut, qu'on suit couche après couche.

### I3 — LLM-juge sur les runs réels (le moniteur continu)

**Opéré par Claude Code, scripté — pas d'API tierce.** Le mécanisme :
- `go-task ml:bench:export-batch` exporte les listings à juger (bucket
  `theme_mismatch` d'un run, ou seed du gold) en JSONL : pour chaque
  listing, son titre + le marketplace + **les pièces candidates de son
  groupe** (eurio_id, thème, titres i18n).
- Claude Code lit ce batch dans une session, classe chaque listing
  (`coin:<id>` / `lot` / `not-a-coin` / `wrong-scope` / `ambiguous`) avec
  une courte justification, et écrit le JSONL de verdicts.
- `go-task ml:bench:ingest-labels` ré-ingère les verdicts (vers le gold
  gelé pour P0, ou comme rapport d'audit pour un run réel).

Double rôle : (a) monitoring du taux de faux rejet sur donnée live,
(b) **alimente le gold** — les faux rejets confirmés sont ajoutés au
benchmark (après spot-check), qui grandit run après run.

Indépendance : le juge (Claude Code) ne doit jamais être le mécanisme du
matcher (cf. couche 2c — raison de plus de la garder conditionnelle et
non-LLM). Le taux d'erreur du juge est ancré par la tranche relue à la
main (~40 items du gold v1).

### I4 — Audit narratif Claude Code (le « pourquoi »)

Runbook documenté : Claude lit le résultat d'un run en DB et produit un
doc de findings qualitatif (comme l'audit de `b6bede99…`). Pas une
métrique — la couche explicative qui dit *quelle pièce / quel vocabulaire*
casse. C'est le « Claude Code qui lit les résultats de lui-même ».

### Snapshot pour replay

Idéalement, à chaque scrape réel, snapshotter les `itemSummaries` bruts
→ ce run devient lui-même rejouable hors-ligne. La donnée live sert à
**découvrir** de nouveaux modes de défaillance ; le gold gelé sert à
**mesurer** le progrès. Les deux, pas l'un OU l'autre.

## Ordre de livraison proposé

| Chunk | Contenu | Dépend de |
|---|---|---|
| **P0** | Gold benchmark (I1) + replay harness (I2) + LLM-juge (I3) | — |
| **C1** | Couche 1 — `no_match` → `ambiguous` | P0 (pour mesurer l'effet) |
| **C2a** | Couche 2a — `coin_aliases` + mining + matcher enrichi | P0, C1 |
| **C2b** | Couche 2b — scoreur LaBSE + fusion RRF + marge top-2 | P0, C2a |
| **C2c?** | Couche 2c — matcher LLM, **si** le bench le justifie | mesure C2a+C2b |
| **C3** | Calibration des seuils (`τ_high`, `τ_low`, `δ`) par cohorte + audit narratif (I4) en runbook | C2b |

Découpage chunk-by-chunk avec audit visuel entre chaque (cf. règle de
travail) : livrer une couche, relancer le harness, lire l'évolution,
discuter, continuer.

## Références

- `research/entity-matching-standards.md` — les findings industriels
  qui fondent ce plan.
- `discovery-groupee-handoff.md` — le chantier découverte groupée.
- `i18n-strategy.md` — la stratégie i18n existante (alias = même modèle
  `source`/`confidence`).
