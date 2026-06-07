# Standards industriels — entity matching, triage HITL, vocab gap

> Synthèse de 4 recherches indépendantes (2026-05-22) sur la façon dont
> les outils d'extraction/annotation visant l'autonomie résolvent les
> problèmes que pose notre theme-matcher eBay. Déclenché par l'audit du
> run `b6bede99…` : 164 `theme_mismatch`, dont ~⅔ de **faux rejets**
> (pièces valides du groupe jetées).
>
> Ce doc = ce qu'on a appris. Le plan d'implémentation qui en découle
> vit dans `../theme-matcher-recall-kickoff.md`.

## Le problème, en termes de la littérature

Notre matcher attribue un listing eBay bruité (titre multilingue) à une
des N pièces-sœurs d'un groupe de découverte `(dénom, pays, année)`. Il
fait de l'**overlap de tokens** entre le titre et les titres canoniques
pré-traduits, puis émet `single` / `ambiguous` / `no_match`, et
`no_match` **jette** le listing.

Trois pathologies, toutes nommées dans la littérature :

1. **Vocabulary gap / lexical gap** — la traduction LLM littérale
   (« Ereignisse vom Mai 1968 », « Europäisches Währungsinstitut ») et
   le terme de marché du vendeur (« Studentenrevolte », « EMI »)
   partagent zéro token. Tout scoreur bag-of-words score ~0. Problème
   IR vieux de 30 ans.
2. **Absent vs contradicting evidence** — un signal qui ne trouve rien
   (aucun token de thème) est traité comme un signal qui *contredit*.
   C'est faux et c'est la cause directe des faux rejets.
3. **Discard silencieux** — `no_match` supprime la donnée. Aucun outil
   d'annotation mature ne fait ça.

## Finding 1 — Le groupe EST le « blocking », il ne reste que le matching

L'entity resolution standard est un pipeline en 3 étages aux objectifs
opposés (*Papadakis et al., Blocking & Filtering Survey, ACM CSUR 2020*) :

- **Blocking** — génération de candidats, optimise le **recall** : jeter
  cheap-ment les non-matches évidents.
- **Matching** — scoring par paire, optimise la **précision**.
- **Decision** — accepter / abstenir / rejeter.

Notre groupe de découverte `(dénom, pays, année)` **est un blocking déjà
fait, propre, et fourni**. Les matchers open-world (Amazon, Google
Shopping) dépensent l'essentiel de leur ingénierie sur le blocking
contre des milliards d'offres ; nous, on matche contre N sœurs (une
poignée). **Notre problème de recall n'est donc PAS un problème de
blocking — c'est purement un problème de matcher.** Le token-overlap est
un matcher de 2010 ; il ne devrait pas être utilisé quand l'ensemble de
candidats est déjà aussi petit.

## Finding 2 — Reformuler : classification multi-classes + abstention

Matcher un listing contre N sœurs connues n'est pas un problème
match/non-match par paire — c'est une **classification multi-classes sur
un ensemble fermé** : N classes (les sœurs) + une classe `NONE`.

- *Peeters & Bizer, Supervised Contrastive Learning for Product Matching
  (WWW 2022)* + le benchmark **WDC Products** : la formulation
  multi-classes bat la formulation par paire de **3-6 % de F1**, et
  « excelle précisément sur la reconnaissance multi-classes de produits
  connus » — exactement notre cas (catalogue fixe).
- **Gate sur la marge top-1/top-2** (standard HITL, *CIKM 2019* ;
  *APE, 2024*). On score les N sœurs, on prend `s1` (top-1) et `s2`
  (top-2) :
  - `s1 ≥ τ_high` ET `(s1 − s2) ≥ δ` → **auto-attribution** (confiant ET
    non-ambigu dans le groupe) ;
  - `s1 ≥ τ_high` mais `(s1 − s2) < δ` → **review** (deux sœurs trop
    proches — le cas classique des sœurs qui ne diffèrent que d'un mot) ;
  - `s1 < τ_low` → **no-match** (rien dans le groupe ne colle).
  Un score unique de token-overlap ne peut pas distinguer « ambigu entre
  sœurs » de « ne matche aucune sœur » — il faut au moins la marge top-2.
- Les **sœurs d'un groupe sont des hard negatives par construction**
  (même dénom/pays/année). Ne pas viser zéro review : calibrer `δ` pour
  une file de review petite mais non vide.

## Finding 3 — « Évidence absente » ≠ « évidence contradictoire »

C'est le cœur du bug, et c'est formellement fondé.

- **Snorkel / data programming** (*Ratner et al., NeurIPS 2016 ; VLDB
  2019*) : chaque signal est une *labeling function* qui vote une classe
  OU **s'abstient** (`ABSTAIN`). Une LF qui s'abstient contribue un
  **poids zéro** — elle ne vote ni pour ni contre. C'est différent d'un
  vote négatif. Une LF à faible couverture mais haute précision est
  utile *parce qu'*elle s'abstient sur ce qu'elle ne sait pas juger.
- **Open-set recognition / selective prediction** : « aucune évidence
  pour aucune classe connue » → abstention (épistémique). « Évidence
  pour une mauvaise classe » → prédiction (contradiction). Conflater les
  deux est un pattern de défaillance connu.

→ **`no_match` ne devrait se déclencher que sur une contradiction
positive.** Un listing sans token de thème mais avec bon pays/année/
dénom : le signal thème **s'abstient** (poids zéro), les signaux pays/
année/dénom **soutiennent**. Le verdict doit être `ambiguous` → review,
**jamais** `no_match` → discard.

## Finding 4 — Jamais de discard silencieux (outils HITL)

Sur 7 plateformes d'annotation auditées (Label Studio, Snorkel, Prodigy,
SageMaker Ground Truth, Cleanlab, Scale AI, Roboflow) : **6 n'ont aucun
chemin de rejet silencieux**. L'incertain part toujours dans une file.

- Le split par défaut de l'industrie est **2 voies** : auto-accept vs
  file humaine. Le vrai 3ᵉ tier « reject » vient de la littérature
  *selective prediction* et n'est sûr que si son seuil est calibré
  contre une **borne d'erreur prouvée**.
- Quand un tier reject existe, c'est un **auto-reject motivé et
  récupérable** (état requêtable + raison machine + audit échantillonné),
  jamais un delete.
- **Best practices du chemin reject** : (1) reject = état terminal de
  file, pas suppression ; (2) chaque rejet porte une raison machine +
  le score ; (3) audit échantillonné régulier du bucket reject — la
  métrique « % de valides dans le reject » pilote la calibration du
  seuil ; (4) seuils conservateurs : dans le doute, review, jamais
  reject.
- Seuils **par cohorte**, pas globaux (Cleanlab : un seuil par classe).
- Router sur le **désaccord** des signaux, pas seulement le low-confidence.

→ Notre taux de ~60 % de faux rejets = symptôme exact d'un `τ_low` non
calibré + d'un reject qui supprime au lieu de mettre en file.

## Finding 5 — Le vocab gap : 2 fixes standards, complémentaires

### (A) Enrichir les surface forms — modèle alias

Les KB matures (Wikidata, DBpedia) séparent, par entité et par langue :
`label` canonique + **`altLabel`** (le jeu d'alias : acronymes, surnoms,
noms historiques, termes colloquiaux). Notre erreur : faire porter tout
le sens au seul titre traduit.

Construction **automatique** des alias :
- **Anchor-text mining** — les textes d'hyperliens Wikipedia pointant
  vers un événement/une institution *sont* son jeu d'alias, par langue.
- **Détection d'acronymes** — patterns « X (Y) » dans le texte ;
  *Mining Acronym Expansions, Microsoft WWW 2013*. Résout directement
  EMI ↔ Europäisches Währungsinstitut.
- **Mining sur notre propre corpus** — les n-grammes fréquents des
  titres eBay déjà correctement matchés.
- **Génération LLM ancrée** — pas de génération libre (hallucination
  d'alias) : donner au LLM le contexte Wikipedia/Numista de la pièce et
  lui faire *extraire* les termes réellement utilisés. Puis **vérifier**
  chaque alias contre un corpus réel + **anti-collision** (rejeter un
  alias qui matche aussi une autre pièce) + tagger `source`+`confidence`.

**Document expansion** (doc2query, SPLADE) est le cadre formel : on
indexe `label + alias + termes d'expansion`, et le matcher token-overlap
existant **marche tel quel** sur l'index enrichi. Chemin le moins
disruptif, totalement inspectable.

### (B) Matching sémantique — embeddings multilingues

- **LaBSE** (*Google, ACL 2022*, 110 langues) — le meilleur pour le
  matching cross-lingual direct (titre allemand ↔ titre canonique
  français, sans passer par une traduction).
- **`paraphrase-multilingual-mpnet-base-v2`** (sentence-transformers,
  50+ langues) — fine-tuné **paraphrase** : « Studentenrevolte » vs
  « Ereignisse vom Mai 1968 » EST une relation de paraphrase.
- **multilingual-E5** — fort en retrieval, mais meilleur avec l'anglais
  en pivot.
- Tous tournent en local (cohérent avec la stack DINOv2/ArcFace
  existante, zéro infra).

### Fusion — hybride lexical + sémantique

Le consensus industriel : faire **les deux**. Le lexical garde sa force
sur les discriminants durs (année, code pays, « 2 Euro ») ; le sémantique
rattrape le vocab gap. Fusion par **Reciprocal Rank Fusion**
(`score = Σ 1/(60 + rank)`) — ignore les échelles de score incompatibles.

Pur embeddings = perd sur les identifiants exacts. Pur lexical = perd
sur le vocab gap (notre panne actuelle). Il faut les deux.

## Finding 6 — Calibration & boucle d'apprentissage

- Un **compte de tokens** (ou une somme pondérée à la main) est un score
  monotone, **pas une probabilité**. La règle de rejet optimale (Chow)
  n'est optimale que sur des **probabilités calibrées**.
- **Calibration post-hoc** : Platt scaling (logistique sur un score,
  faible data), temperature scaling (préserve l'argmax), isotonic.
  Mesure : **ECE** + reliability diagram + Brier score.
- Il faut un **petit gold set** annoté pour calibrer quoi que ce soit
  (seuils, marge). La courbe **risk-coverage** est la métrique
  d'évaluation standard d'un classifieur à abstention.
- **Boucle active** : chaque décision de review humaine devient une
  paire d'entraînement étiquetée → recalibration des seuils + ré-
  entraînement du matcher. Ordonner la file de review par incertitude
  (uncertainty sampling) pour que l'humain voie d'abord l'informatif.

## Mapping Eurio — ce qu'on a déjà

- **La cible de deferral existe** : `ambiguous → review` avec
  `group_candidates` (chunk 5b) est exactement le filet que les findings
  1-4 recommandent. Déjà construit.
- **La distinction absent/contradict existe en schéma** :
  `listing_text_signals.vs_target_verdict ∈
  convergent|partial|absent|contradict` + `contradictions_json` (chunk
  C2), et un filtre dur `text_contradict_*`. Pays/année/dénom
  contradictoires sont **déjà** traités séparément, en amont.
- Conséquence : quand un listing atteint `match_listing_to_group`, il a
  déjà passé `accept_listing` et n'est pas `text_contradict`. Un
  `no_match` du theme-matcher signifie donc littéralement « bon groupe,
  thème non reconnu » → cas d'école du *defer*, pas du *discard*.
- Stack ML locale en place (DINOv2, ArcFace) → un embedding LaBSE tourne
  en local sans infra nouvelle.

## Références

Entity matching / blocking
- Papadakis et al., *Blocking and Filtering Techniques for ER*, ACM CSUR 2020
- Li et al., *Ditto — Deep EM with Pre-Trained LMs*, VLDB 2021
- Peeters & Bizer, *Supervised Contrastive Learning for Product Matching*, WWW 2022
- *WDC Products: A Multi-Dimensional EM Benchmark*, 2023
- Peeters & Bizer, *Entity Matching using LLMs (MatchGPT)*, 2023-24

Weak supervision / abstention / calibration
- Ratner et al., *Data Programming*, NeurIPS 2016 ; *Snorkel*, VLDB 2019
- Geifman & El-Yaniv, *Selective Classification for DNNs*, NeurIPS 2017 ; *SelectiveNet*, ICML 2019
- Chow, *On Optimum Recognition Error and Reject Tradeoff*, 1970
- Mozannar & Sontag, *Consistent Estimators for Learning to Defer*, ICML 2020
- Guo et al., *On Calibration of Modern Neural Networks*, ICML 2017

Vocab gap / multilingue
- Feng et al., *LaBSE — Language-agnostic BERT Sentence Embedding*, ACL 2022
- Formal et al., *SPLADE v2*, SIGIR 2021
- Nogueira et al., *Document Expansion by Query Prediction (doc2query)*, 2019
- *Mining Acronym Expansions Using Query Click Log*, Microsoft WWW 2013
- Reciprocal Rank Fusion (Cormack et al., SIGIR 2009)

HITL / outils d'annotation
- SageMaker Ground Truth (auto-labeling), Label Studio, Snorkel Flow,
  Prodigy, Cleanlab, Roboflow — docs produit (auto-label vs review queue)
