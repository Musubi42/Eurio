# PROGRESS — amélioration du matching eBay (standards industriels)

> Journal vivant de l'implémentation du chantier « recall du theme-matcher ».
> Plan : `theme-matcher-recall-kickoff.md`. Findings : `research/entity-matching-standards.md`.
> On y consigne **découvertes, changements, contraintes** au fil de l'eau.

## État

| Chunk | Statut |
|---|---|
| P0 — socle de mesure (gold bench + replay harness + LLM-juge) | ✅ livré (baseline mesurée) |
| C1 — couche 1 (`no_match` → `ambiguous`) | ✅ livré (faux rejet 34→14 %) |
| C2a — `coin_aliases` + mining | ⏳ |
| C2b — scoreur sémantique LaBSE + fusion | ⏳ |
| C2c — matcher LLM (conditionnel) | ⏳ |
| C3 — calibration seuils + runbook audit | ⏳ |

---

## P0 — socle de mesure

### Découvertes / contraintes

- **Le groupe d'un listing est récupérable précisément**, malgré l'absence
  de colonne dédiée :
  - listing *gardé* (`source_images`) → `target_eurio_id` → année du coin ;
  - listing *rejeté* (`discarded_listings`) → le `raw_payload.item_web_url`
    contient le paramètre `_skw` (= la requête de recherche, ex.
    `2+euro+Belgien+2017`) → année du groupe extraite par regex.
  → pas besoin de schéma supplémentaire pour seeder le gold.
- Run seed = `b6bede99…` : **575** images gardées (≈ N listings après
  dédup par item_id) + **289** listings rejetés. Tous BE 2017-2021.
- Format d'`item_id` eBay hétérogène selon la table : `source_images`
  `ebay_v1|<id>|<var>_img<N>` ; `discarded_listings`
  `ebay_listing_v1|<id>|<var>`. Normalisés vers `v1|<id>|<var>`.
- Gold lean v1 : **~200 listings** échantillonnés stratifié par
  (année × bucket {kept, theme_mismatch, autre rejet}).

### Changements

- `ml/scripts/bench_theme_match.py` — script 3 modes (export / ingest /
  replay). Go-tasks : `ml:bench:export-batch`, `ml:bench:ingest-labels`,
  `ml:bench:theme-match`.
- `ml/state/discovery_bench/` — `batch.jsonl` (196 listings échantillonnés),
  `groups.json` (contexte coins), `labels.jsonl` (verdicts LLM-juge),
  `theme_match_gold.jsonl` (gold gelé, 196 entrées).
- Distribution du gold v1 : 94 `coin:*`, 78 `wrong-scope`, 12 `lot`,
  7 `not-a-coin`, 5 `ambiguous`.

### 📊 BASELINE — matcher actuel (run replay sur gold v1)

| Métrique | Valeur |
|---|---|
| Taux de faux rejet | **22,2 %** (22/99 pièces valides jetées) |
| Recall (gardé qq part) | 77,8 % |
| **Taux d'auto-attribution ★** | **77,8 %** (77/99) |
| dont routé en review | **0 %** — le matcher ne route jamais en review |
| Précision des auto-attributions | 81,9 % (0 attribution erronée) |
| False-keep (junk gardé) | 14,1 % (12/85) |
| Lots | 5 → `single`, 7 → `no_match` |

→ point de départ pour mesurer C1 / C2.

### Découvertes notables (audit du gold)

1. **Catalogue Ghent/Liège incohérent.** `be-2017-2eur-200-years-ghent-
   university` : slug + `theme` disent *Ghent*, mais **les 6 titres i18n
   disent tous Liège** (Lüttich / Liège / Lieja / Liegi / Luik). C'est la
   même pièce 2017 (bicentenaire des universités de 1817, Gand ET Liège
   figurent dessus) — mais l'incohérence slug ↔ i18n est réelle. Non
   bloquant (groupe mono-pièce) ; à corriger côté catalogue.
2. **Les groupes mono-pièce auto-attribuent TOUT.** `match_listing_to_group`
   fait `len(ids)==1 → single` sans aucun theme-check. Le groupe BE-2017
   n'a qu'1 coin → tout listing qui passe `accept_listing` (y compris
   **catalyseurs de voiture**, lots, KMS « pick your year ») est
   auto-attribué à GHENT. → 11/12 des false-keep du bench sont des 2017.
   Contrainte : C1/C2 doivent garder un garde-fou même pour les groupes
   de taille 1.
3. **Les acronymes SONT dans l'i18n mais filtrés par le tokenizer.**
   Titres i18n EMI : « European Monetary Institute (EMI) »,
   « Europäisches Währungsinstitut (EWI) ». L'acronyme est là, entre
   parenthèses — mais le tokenizer drop les tokens < 4 chars → EMI/EWI/IME
   jetés → la pièce EMI massivement faux-rejetée. Fixable C2a (garder les
   acronymes courts comme tokens discriminants).
4. **Le matcher est binaire — il ne route JAMAIS en review** (0 %
   `ambiguous` sur le bench). Les 5 listings réellement ambigus du gold
   (« 2 EUROS BÉLGICA 2021 S/C », sans thème) → tous `no_match` → faux
   rejet. C1 (`no_match`→`ambiguous`) cible exactement ça.
5. **Vocab de marché ≠ i18n littéral — confirmé.** May 1968 : i18n DE
   « Ereignisse vom Mai 1968 » vs titres vendeurs « Studentenrevolte /
   Maiaufstände / Studentendemonstrationen / Studenrevolution ». ESRO-2B
   surnommé « Iris » par les vendeurs (« Satellit Iris 2 »,
   « satélite de investigación iris »). Tous faux-rejetés.
6. **`item_web_url._skw` = la requête de recherche** → le groupe d'un
   listing rejeté est récupérable précisément, sans schéma supplémentaire.
7. **Contrainte process — étiquetage en masse = ancres obligatoires.**
   La 1ʳᵉ passe d'étiquetage avait un décalage d'index (1 verdict perdu
   en position 150 → tout décalé après). Rattrapé par des assertions
   titre ↔ verdict sur 8 ancres. Tout futur étiquetage doit en porter.

### Reste P0

- Spot-check humain d'une tranche ~40 du gold (validation du juge) —
  à la main, hors session.

---

## C1 — couche 1 : `no_match` → `ambiguous`

### Changements

- `match_listing_to_group` (`queries.py`) : le verdict de sortie est
  désormais ∈ {`single`, `lot`, `ambiguous`}. Quand aucun thème ne
  matche, verdict = `ambiguous` (`matched` vide → target None → review),
  jamais `no_match`. `no_match` réservé à une future contradiction
  explicite (V2), plus produit par ce module.
- `GroupMatch` : `ambiguous` renvoie `matched=()` → `target_eurio_id`
  None → le listing part en review (group_candidates, chunk 5b).
- `adapter.py` : suppression de la branche `if verdict == "no_match":
  discard theme_mismatch`. `ambiguous` flue dans `kept` avec target None.
- **Bench rendu fidèle** : `replay` rejoue maintenant `accept_listing`
  PUIS le matcher (le pipeline réel). Export enrichi de `price` /
  `currency`. Sinon le bench mesurait le matcher seul et imputait au
  matcher du junk que `accept_listing` filtre en amont.
- Test : `test_discover_no_theme_match_routed_to_review_not_discarded`
  (ex-`..._is_discarded`, sémantique inversée).

### 📊 C1 — A/B sur bench fidèle (accept_listing + matcher)

| Métrique | PRE-C1 | POST-C1 |
|---|---|---|
| Taux de faux rejet | 34,3 % | **14,1 %** ✅ |
| Recall | 65,7 % | **85,9 %** ✅ |
| Auto-attribution ★ | 65,7 % | 65,7 % (inchangé — attendu) |
| Routage en review | 0 % | 20,2 % ✅ |
| Précision auto-attrib. | 92,9 % (0 erronée) | 92,9 % (0 erronée) |
| Junk false-keep | 2,4 % | **42,4 %** ⚠️ |

C1 sauve **20 pièces valides** du discard (elles passent en review). Le
recall grimpe de 20 pts. L'auto-attribution est inchangée — normal, C1
ne crée aucun hit, il ne fait que ne plus jeter.

### Découvertes / contraintes C1

1. **C1 troque le discard contre la review** — 34 junk qui étaient
   `no_match`→discardés passent maintenant en `ambiguous`→review
   (false-keep 2,4 % → 42,4 %). Attendu et conforme aux findings (« never
   silently discard »), mais **C2 doit faire redescendre ce junk** : le
   garde-fou de contradiction (pays/dénom via `text_signal`) ou un filtre
   junk avant le matcher. Le junk en review reste rejetable en 1 clic ;
   les 20 pièces valides, elles, étaient perdues.
2. **Les 14 faux rejets restants ne sont PAS le fait du matcher** —
   `matcher_rej = 0`, `accept_listing_rej = 70`. Les 14 pièces valides
   encore jetées le sont toutes par `accept_listing` (year-in-title /
   noise). → la précision d'`accept_listing` est le prochain levier
   au-delà du theme-matcher.
3. **`text_signal` tourne APRÈS `discover`** dans le pipeline
   (`PIPELINE_STEPS`). Donc au moment où `match_listing_to_group`
   s'exécute, seul `accept_listing` a filtré — PAS la détection de
   contradiction. La prémisse du kickoff (« aucune contradiction garantie
   à ce stade ») est partiellement fausse : `accept_listing` couvre
   millésime/prix/devise/bruit, pas pays ni dénomination.
4. Le garde-fou des groupes mono-pièce (découverte P0 #2) reste différé :
   le groupe BE-2017 auto-attribue toujours tout (catalyseurs inclus).
