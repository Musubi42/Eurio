# Mission — Repenser l'orchestration de l'auto-validation (modèle ensemble/consensus)

> **Statut : C0→C5 LIVRÉS + câblés live (2026-06-10). Reste : polish front (badge consensus) +
> lancer le cleanup legacy `--apply`.** Décidé
> 2026-06-08 après exploration graphify du flux text-signals → attribution → review. Chantier à
> part entière (touche le chemin critique d'ingestion + le front admin). Chunks audités, avec une
> **stratégie de non-régression par replay** (verdicts avant/après). Doctrine R0,
> SQLite-only (eurio.db = vérité), [[feedback_chunk_audit_flow]].
>
> **MàJ 2026-06-08 (grounding 6-agents vs code + `eurio.db`) :** §1 corrigé (seuils = floats
> fixes ≠ percentile, step **5.5** pas 7, gate **2-phases** avec enforcement dans `download.py`),
> §2/§5/§6 chiffrés sur la base réelle, §7 **tranché**, chunk **C2.5** (gold replay) inséré.
>
> **MàJ 2026-06-10 : C0→C3 implémentés** (nouveau package `ml/review/validation/`). Voir le
> **Journal §8** pour le détail + l'état exact. Reste avant bascule live : mesurer le rescue des
> ex-contradicts *tués* (hors gold) + persister/câbler le consensus en prod, puis C4-C5.

## 1. État actuel (cartographié sur le code, 2026-06-08)

L'auto-validation/attribution est **éclatée sur 3 domaines, ~9 fichiers** :

| Pièce | Fichier | Rôle |
|---|---|---|
| Verdict texte | `sources/text_signals/comparator.py` | `compare_to_target()` → convergent/partial/absent/**contradict** vs `TargetIdentity` |
| Gate texte | `sources/_base/steps/text_signal.py` | **rejet dur** sur contradict (étape **2.5**, _deux phases_ : flush des `listing_text_signals` **puis** `_apply_text_contradict_rejections` en batch) → `discarded_listings(reason='text_contradict_{axe}')` + `route_decision='rejected_text'`, `route_reason={axe}`. L'**enforcement** (skip du download) vit dans `download.py`, pas ici. |
| DINO predictions | `sources/_base/steps/auto_validate.py` | `run_auto_validate_dino` écrit `image_asset_dino_predictions` (étape **5.5**, entre resolve=5 et enqueue=6). Scope V1 = `2eur_commemo` uniquement (standards `is_commemorative=0` silencieusement skippés). |
| Verdict combiné | `training/foundation/auto_validate.py` | `compute_auto_validate_verdict` = `f(DINO sim/spread country-restricted, text_verdict)` → level. **Port de `useAutoValidateVerdict.ts`** |
| Seuils | `training/foundation/thresholds.py` | `DinoVerdictThresholds` = **deux floats fixes** `top1_country_sim_min=0.55`, `country_spread_min=0.05` (« provisoires, calibrer après 200 reviews »). ⚠️ **PAS percentile-based** — le percentile ([[feedback_dino_thresholds]]) ne concerne que les zones de la *confusion-map* (`confusion_map.py`), un autre outil. |
| Review LLM | `training/foundation/claude_review.py` | lane `ccproxy` (vision Sonnet, cf. [[project_claude_vision_bench]]) |
| Verdict→lane | `review/review_lanes.py` | `verdict_to_lane(level)` → manual / auto_accept / ccproxy |
| Application lane | `sources/_base/steps/enqueue.py` | `compute_lane()` à l'enqueue (étape 8), lane figée |
| Attribution standards | `sources/ebay/standards.py` | `attribute_standard_listing()` — chemin **séparé** (pièces de circulation) |

Pipeline actuel (`sources/_base/orchestrator.py`, 9 étapes) :
```
discover → persist → text_signal(GATE dur) → download → detect_crop
        → resolve → auto_validate_dino → enqueue(lane) → price_aggregate
```

## 2. Problèmes (le « pourquoi » du redesign)

1. **Gauntlet séquentiel, pas un ensemble.** Le `contradict` texte **tue le listing à
   l'étape 2.5, avant que crop et DINO existent**. Un faux contradict (typo/ambiguïté du
   titre seller) = perte définitive **sans deuxième avis**. C'est le risque n°1.
   _Mesuré (2026-06-08) : 424 listings tués ainsi (16.3 % des discards) —
   `text_contradict_year`=393, `text_contradict_country`=31. Il y a en réalité **deux** points
   contradict : (a) ce kill pipeline à 2.5, et (b) une branche `text=='contradict' → divergent`
   dans l'arbre de verdict (`_verdict_from_signals` étape 2) ; le redesign doit neutraliser **les
   deux**._
2. **La qualité de crop est hors décision.** `tilt`/undercrop ([[project_tilt_detection]],
   [[project_crop_quality_overhaul]]) ne pèsent **nulle part** dans verdict/lane. Un bon
   match DINO sur un crop pourri s'auto-accepte.
3. **Verdict dupliqué front/back** (`useAutoValidateVerdict.ts` ↔ port Python) → dérive.
4. **Logique éparpillée sur 3 domaines + 2 chemins d'attribution** (commemo via verdict,
   standards via `ebay/standards.py`) → impossible à faire évoluer proprement.
5. **Rejet = suppression, pas verdict.** Un `discarded_listings` est opaque/peu ré-ouvrable
   (cf. le chantier rescue commemo qui a dû *rattraper* des rejets). Un rejet devrait être
   un **verdict auditable et ré-ouvrable**, pas une donnée jetée.

## 3. Design cible — auto-validation par **ensemble/consensus**

### 3.1 Principe
Plus de rejet dur prématuré sur signal sémantique. On **collecte tous les avis d'experts
puis on tranche** par une règle de consensus explicite. Un rejet devient un **verdict**
(stocké, auditable, ré-ouvrable), jamais une suppression silencieuse.

### 3.2 Domaine unique `validation/` (ou sous `review/`)
Possède tout ce qui décide :
- **Modèle de verdict** = **source de vérité unique** (le front *lit* le verdict calculé
  côté back, ne le recalcule plus → fin de la duplication `useAutoValidateVerdict.ts`).
- **Experts** = entrées normalisées, chacun produit `(score ∈ [0,1], label, raison, signaux)` :
  - `text` : `comparator.compare_to_target` (convergent/partial/absent/contradict).
  - `dino` : sim/spread country-restricted + consensus, vs seuils percentile.
  - `crop_quality` : tilt/axis_ratio/undercrop → pénalité (NOUVEAU dans la décision).
  - (extensible : `ccproxy` LLM vision comme expert *à la demande* sur les cas litigieux,
    pas systématique — coût).
- **Règle de consensus** explicite et testée : agrège les avis → `verdict ∈ {accept,
  needs_review, reject}` + `confidence` + `lane`. Exemples de règles à acter :
  - text=contradict **mais** dino fort+convergent → `needs_review` (humain tranche), **pas reject**.
  - dino fort + text convergent + crop OK → `accept`.
  - crop trop tilté/undercrop → plafonné à `needs_review` quel que soit DINO.
  - aucun signal exploitable → `needs_review` (filet humain, règle actuelle conservée).
- **`verdict → lane`** (déjà isolé dans `review/review_lanes.py`).
- **Resolver unique** commemo + standards (fusion de `ebay/standards.py` dans le même
  modèle d'attribution).

### 3.3 Pipeline cible
```
discover → cheap_junk_filter(HARD: non-EUR/noise only) → download → detect_crop
        → collect_signals(text + dino + crop_quality) → consensus_verdict → enqueue(lane)
```
- **Pré-filtre minimal** : on garde un rejet dur **uniquement** pour le bruit évident et
  bon-marché (non-EUR, non-pièce, prix aberrant) — pas pour les axes sémantiques. Ça borne
  le coût compute (cf. §5).
- Les contradictions sémantiques (pays/année/dénom) deviennent des **signaux du consensus**,
  plus des kills.

### 3.4 Modèle de données
- Une table/`vue` **verdict** par image_asset (ou source_image) : experts + scores + verdict
  + confidence + lane + version de la règle. Append-only ou versionnée → audit + replay.
- `discarded_listings` : conserver pour le bruit dur ; les rejets sémantiques migrent vers
  un verdict `reject` ré-ouvrable (pas une suppression). À trancher : fusionner ou coexister.
- Respecter [[feedback_store_autocommit_unique]] (UPSERT `review_queue`) et la machine à
  états `image_state_*` existante (`store/events.py`).

## 4. Plan en chunks (chacun = livrable + gate)
> Statut : ✅ livré · 🟡 livré en shadow (pas live) · ⬜ à faire. Détail dans le **Journal §8**.
- ✅ **C0 — Modèle & seuils unifiés** : extraire le modèle de verdict back comme source unique,
  exposer au front (supprimer `useAutoValidateVerdict.ts` → lecture API). Gate : front affiche
  le même verdict qu'avant (parité). — **fait, parité 600/600.**
- ✅ **C1 — Expert interface** : normaliser text/dino/crop_quality derrière une interface
  `Expert.evaluate(asset) -> Signal`. Gate : signaux identiques aux valeurs actuelles (text+dino).
- ✅ **C2 — crop_quality expert** : injecter tilt/undercrop comme 3e expert. ⚠️ Données :
  `tilt_deg`/`axis_ratio` peuplés sur **66.7 %** des assets mais **trustworthy à 36 %** seulement
  (détecteur fiable ≥35°, [[project_tilt_detection]]) → s'appuyer **aussi** sur `quality_score`/
  `quality_reason` (déjà colonnes de `image_assets`) et traiter tilt NULL/non-trustworthy comme
  **pénalité nulle**. Gate : mesurer son effet sur un échantillon labellisé.
  **Bonus (b, 2026-06-10) : `quality_score` backfillé** (était 100 % NULL — voir §8).
- ✅ **C2.5 — Gold de replay** (bloquant C3) : ~~geler `mix-zone-17`~~ + amorcer une gold depuis les
  assets résolus manuellement. Gate : un diff de verdicts rejouable, quota-free (cf. §6). — **fait,
  501 assets. mix-zone-17 demoté diff-only (labels non fiables, voir §8).**
- ✅ **C3 — Règle de consensus** : remplacer le gauntlet. Neutraliser les **deux** points contradict
  (kill pipeline 2.5 **et** branche `contradict→divergent` du verdict) → `needs_review`.
  Pré-filtre junk-only conservé. Gate : **replay** (§6, gold C2.5) — diff verdicts avant/après,
  valider que les nouveaux `needs_review` sont des rescues légitimes, pas du bruit.
  — **règle écrite + validée en SHADOW + persistée + CÂBLÉE LIVE (2026-06-10).**
- ✅ **C4 — Resolver unifié commemo+standards** (2026-06-10). Gate : attribution inchangée
  (test_ebay_adapter/standards verts).
- ✅ **C5 — Rejets ré-ouvrables** (2026-06-10) : un verdict consensus `reject` auto-rejette
  (`resolution_status='rejected'`) + reste dans `review_queue` (estampillé `consensus@v1`) → apparaît
  dans la grille `/rejected` existante, ré-ouvrable via `/restore`. Pas d'UI neuve. Legacy
  `text_contradict_*` nettoyables par script.

## 5. Coût compute (risque de l'option ensemble)
Tout collecter = on croppe + DINO-ise aussi des listings qu'on jetait tôt. Mitigations :
- pré-filtre junk **hard mais bon-marché** (texte non-EUR/non-pièce) en amont du download ;
- DINO déjà calculé pour tous les survivants aujourd'hui — le delta = les ex-contradicts
  (mesurer leur volume sur un run réel avant de s'engager) ;
- `ccproxy` (LLM vision) reste **à la demande** sur les litiges, jamais systématique.

**Mesuré (2026-06-08, `eurio.db`)** : risque coût **faible → feu vert**. Baseline DINO =
**2854** prédictions (toutes `2eur_commemo`). Les 424 ex-contradicts n'ajoutent que **~106 appels
DINO immédiats** (seuls ceux qui ont déjà un crop ; `text_contradict_country` en a **0**), soit
**+3.7 %** sur la baseline (+318 au plus si on doit aussi les détecter/cropper). → Le pré-filtre
junk se justifie par l'**hygiène d'ingestion**, pas par le compute. La contrainte réelle n'est
pas le coût, c'est la gold de replay (§6).

## 6. Stratégie de non-régression (obligatoire)
- **Shadow/replay** : rejouer N runs existants (source_images + crops + dino_predictions déjà
  en base) à travers la nouvelle règle **sans écrire** → produire un diff verdict ancien↔nouveau.
- Cibler la revue humaine sur les **divergences** (surtout reject→accept et accept→reject).
- Geler une **gold** de verdicts attendus (comme `theme_match_gold`/`crop_gold`) pour un
  bench replay quota-free réutilisable.
- Ne basculer le pipeline live qu'après validation du diff sur ≥1 cohorte réelle.

**État (2026-06-08)** : la gold de replay **n'existe pas encore** — c'est le **bloquant réel**.
Seul hold-out labellisé = `mix-zone-17` (**242 crops / 7 classes, encore `draft`**) ; les 2
cohortes `frozen` (smoke-2, be-2eur-standard-obverse-eval) ont `cohort_members` **vide**.
→ Construire la gold (geler `mix-zone-17` + amorcer depuis les **454 assets résolus
manuellement**, lane `manual`) **avant C3** = nouveau chunk **C2.5**.

## 7. Décisions de démarrage (tranchées 2026-06-08, après grounding)
- **Domaine** → `review/validation/` (sous `review/`). Le verdict décide le routage review ;
  `review_lanes.py` + la table `review_claude_verdicts` y vivent déjà. On y consolide
  **modèle de verdict + consensus + seuils + verdict→lane** ; les **experts restent chez leurs
  producteurs** (`comparator` dans `sources/text_signals`, step DINO dans `sources/_base/steps`).
- **Table verdict** → **persistée & versionnée** (1 row/`(asset, rule_version)`, REPLACE au rerun,
  scores experts + reason + lane), sur le modèle de `review_claude_verdicts`. Les *inputs*
  (`dino_predictions`, `listing_text_signals`, tilt) sont déjà persistés → replay d'une nouvelle
  règle **hors-ligne** sans toucher la table live. Front lit la dernière row (C0).
- **`discarded_listings`** → **coexister, migrer le *flux* pas la table.** `discarded_listings`
  reste pour le junk dur (clé `UNIQUE(source, source_ref)` — seul id dispo *avant* download ;
  `text_contradict_country` n'a aucun image_asset à clé). Les contradicts sémantiques **cessent
  d'y être écrits** et traversent crop→DINO→consensus → verdict `needs_review` dans `review_queue`.
  Un reject ne devient ré-ouvrable qu'**une fois l'image existante**.
- **Forme de la règle** → **arbre/table de décision lisible** (pas scores pondérés). L'arbre
  6-étapes existe et est testé ; le redesign bascule une branche (contradict→`needs_review`) +
  ajoute un cap crop_quality. Le `reason` est déjà affiché en UI → auditabilité conservée.

## 8. Journal d'avancement

> Tout en **working tree** (non commité au-delà des snapshots auto-WIP du hook). Code dans le
> nouveau package **`ml/review/validation/`**. Tests : `ml/tests/test_validation_experts.py` +
> `test_validation_consensus.py` (lancer dans le devShell `mac` — `pytest`/`cv2` absents du python nu).
> Le verdict consensus est calculé en **shadow** (diffé contre l'actuel) — **rien n'est encore câblé
> au pipeline live ni écrit en base** (hormis le backfill `quality_score`, additif).

### C0 — Verdict = source unique back (2026-06-08)
`compute_auto_validate_view()` ajouté dans `training/foundation/auto_validate.py` (level + reason +
criteria states ; réutilise `_verdict_from_signals` → strictement identique à triage-stats/auto-accept).
Embarqué dans la réponse `dino-suggestions` (`AutoValidateVerdictOut`, `review/review_queue_routes.py`).
Front : `computeDinoVerdict`/`computeAutoValidateVerdict` supprimés de `useAutoValidateVerdict.ts`
(→ display-only + `dinoCriteriaDisplay`), `AutoValidateVerdict.vue` lit le verdict serveur (drop du
fetch text-signals), `DinoVerdict.vue` lit les états serveur. **Parité 600/600.** Seul delta visible :
wording du `reason` (Python plus informatif, ex `partial` = "sim 0.42 < 0.55").

### C1 — Interface Expert → Signal (2026-06-08)
`Expert.evaluate(ctx: AssetContext) → Signal(expert, score, label, reason, raw)`, registre `EXPERTS`,
façade `collect_signals()`. Experts `text` + `dino` ; résolution faite **une seule fois**
(`fetch_and_resolve_signals` public côté foundation → pas de duplication du fallback country-restricted).
Gate : verdict reconstruit depuis les Signals == verdict canonique (6 branches + DB end-to-end).

### C2 — Expert crop_quality (2026-06-08)
`CropQualityExpert`. Priorité : label humain `too_tilted` → `quality_score` → tilt fiable ≥30° →
**abstention** (tilt NULL/non-trustworthy = pénalité nulle). `_QUALITY_MIN=0.85`, `_TILT_MAX_DEG=30`
(provisoires, tunables). Effet : signal défini sur 54 % des assets, cap conservateur de quelques
auto-accepts.

### b — Backfill `quality_score` (2026-06-10, demandé avant C3 live)
**Constat** : `quality_score` était **100 % NULL** — la passe « P3 Quality gate + score » du chantier
[[project_crop_quality_overhaul]] (écrire `quality_score`) n'a jamais été câblée (= sa question ouverte
#5). `quality_reason` ne porte que des états de review (`rejected_in_review`/`vision_standard_gate`),
pas de qualité crop. **Fix** : `ml/scripts/backfill_quality_score.py` remplit depuis l'oracle r_ratio
post-refine déjà calculé dans `state/crop_diag/results.csv` (formule `quality_score = clamp(min(r_ratio,
2-r_ratio), 0, 1)`, seuil 0.85 = seuil undercrop du chantier ; `quality_pipeline_version=1`).
**1052 assets écrits** (couverture oracle ~46 %, NULL ailleurs). Dry-run par défaut, idempotent,
réversible.

### C2.5 — Gold de replay (2026-06-10)
`ml/review/validation/replay.py` + CLI `ml/scripts/verdict_gold.py {build,replay,consensus}`. Gold figé
`ml/state/validation_gold/verdict_gold.jsonl` = **501 assets**. Sources : `human_admin` (405 décidés par
l'admin = **vérité fiable**) + `mix_zone_17` (96, **diff-only, sans label**). Diff build→replay = 0
(harness sain). Ancre de correction : **dino top1 == vérité humaine = 64.7 %** (262/405).
⚠️ **mix-zone-17 NON fiable comme hold-out** : le lien `run_id → cohort_jobs.target` ne partitionne pas
(`cohort_members` vide ; un run mélange des cibles ; plusieurs cibles sont des *standards* hors ancres
commemo → 0/96 top1==cible). À relabelliser (par asset) avant de l'utiliser comme vérité terrain.

### C3 — Règle de consensus (2026-06-10, **SHADOW**)
`ml/review/validation/consensus.py` : table de décision lisible, 8 branches nommées → `{accept,
needs_review, reject}` + lane + confidence + `rule`. Ordre : `no_signal` → `dual_contradict`(reject) →
`crop_cap` → `strong_accept`(accept) → `text_contradict_rescue` → `dino_mismatch` → `partial`. Invariant
de sûreté : **`accept` ⊆ auto_candidate actuel** (jamais plus permissif). Shadow sur le gold
(`verdict_gold.py consensus`) : **4 flips, tous `accept→needs_review` (crop_cap), 0 faux rejet, 0 nouvel
auto-accept**.
**Bug attrapé par le gate (1er run)** : 6 `needs_review→reject` étaient des **faux rejets** — des
**standards** que l'humain avait acceptés, où dino "mismatch" est spurieux (banc 2eur_commemo only → un
standard ne peut jamais matcher). **Fix** : l'expert dino **s'abstient hors scope d'ancres**
(`dino_in_scope` calculé via `coins.is_commemorative`, porté dans `AssetContext`). Re-run : ces 6 partent
en `text_contradict_rescue → needs_review` (correct), et un vrai dual-contradict *in-scope* reject
toujours. C'est la démonstration que **replay-avant-live** était la bonne stratégie.

### Mesure du rescue des ex-contradicts TUÉS (2026-06-10, gate item #1 — CLOS)
`ml/scripts/contradict_rescue.py` (lecture seule, rejoue `discarded_listings(text_contradict_*)` →
`collect_signals → consensus_verdict` sans écrire). **Funnel réel** (corrige l'estimation 2026-06-08) :
424 discards (`year`=393, `country`=31) → 394 ont un `source_image` → **56 listings ont un crop = 106
`image_assets`** → seulement **6** ont une prédiction DINO commemo. GAP ~368 listings exigeraient un
detect+crop avant mesure (hors scope de ce chunk, choix PO).
**Résultat sur les 106 crops** : **106/106 → `needs_review`** (règle `text_contradict_rescue`), **0
reject**. *Pourquoi 0 reject* : toutes les cibles tuées ici sont des **standards** (`be-*-standard`,
`es-*-standard`) → l'expert dino **s'abstient** (out-of-scope ancres commemo, garde `dino_in_scope`),
donc le 2e avis qui déclenche `dual_contradict` n'existe jamais sur cette population. Le kill dur perdait
donc **uniquement** des rescues légitimes, zéro vrai rejet. Spot-check : titres = vraies pièces euro de
même pays/dénom (souvent KMS/coincards/lots multi-années → c'est le titre multi-années qui a déclenché le
`contradict_year`), à arbitrer en review, pas à jeter. Cross-tab `resolution_status` actuel : 53 sont déjà
`rejected`, 46 `needs_review`, 6 `manual`, 1 `auto_phash`. Sanity inchangée : `verdict_gold.py consensus`
= 4 flips / 0 rejets.

### Persistance du verdict consensus (2026-06-10 — FAIT, SHADOW)
Table **`consensus_verdicts`** (schema.sql, modèle `review_claude_verdicts`) : 1 row/`(image_asset_id,
rule_version)`, REPLACE au rerun de la même version (`ON CONFLICT` sur la PK), coexistence des versions
(replay d'une règle révisée hors-ligne). Colonnes : `outcome` (accept/needs_review/reject) + `lane` +
`confidence` + `reason` + `rule` (branche, audit) + **`signals_json`** (snapshot des Signals experts) +
`computed_at`. API : `review/validation/persist.py` (`upsert_consensus_verdict` / `load_consensus_verdict`,
conn brute + commit explicite). Backfill SHADOW : `scripts/persist_consensus.py --scope {dino,gold,
contradict} [--apply]` (dry-run par défaut, idempotent, bootstrap la table via `StoreBase`).
**Baseline persistée (`--scope dino --apply`)** : **2852 rows** (rule_version=1) — 270 `auto_accept`,
2578 `ccproxy`, 4 `manual`. Tests : `tests/test_validation_persist.py` (6, DB en mémoire). **Rien ne lit
encore cette table en prod** (shadow) — le câblage live est l'étape suivante.

### Câblage live du consensus (2026-06-10 — FAIT)
Le gauntlet est remplacé par le flux ensemble dans le pipeline live :
- **Kill 2.5 supprimé** (`text_signal.py`) : un verdict `contradict` n'écrit plus dans
  `discarded_listings` ni ne pose `route_decision='rejected_text'` — il est juste persisté comme signal
  (`vs_target_verdict`). La fonction `_apply_text_contradict_rejections` + l'import `record_discarded_listing`
  sont retirés ; `TextSignalResult.n_rejected_contradict` aussi.
- **Skip download supprimé** (`download.py`) : plus de saut sur `route_decision='rejected_text'`. Un contradict
  traverse maintenant download → crop → dino → consensus. ⚠️ Les vieux `source_images` encore marqués
  `rejected_text` (data legacy) se re-téléchargent au prochain run de leur cohorte = le rescue voulu.
- **Enqueue route via consensus** (`enqueue.py`) : `compute_lane`/`_verdict_from_signals` remplacé par
  `collect_signals → consensus_verdict → lane` ; le verdict est **persisté** (`upsert_consensus_verdict`,
  `commit=False` — autocommit du Store). `accept→auto_accept`, `needs_review→ccproxy/manual`,
  `reject→manual` (l'item **reste en review_queue**, ré-ouvrable — pas de suppression, cf. C5).
- **Pré-filtre junk dur conservé** (non-EUR/bruit) : il vit en amont (discover/persist), pas touché.
- Gate avant bascule : `verdict_gold.py consensus` = **4 flips / 0 reject / 0 nouvel auto-accept**,
  `verdict_gold.py replay` = diff vide. Tests live : `tests/test_enqueue_consensus.py` (4 : strong_accept→
  auto_accept, contradict-alone→ccproxy rescue, dual_contradict in-scope→reject/manual, standard hors-scope→
  rescue) + `test_text_signal_step.py` réécrit (contradict = signal, plus de kill).

**Drift connu (front, suivi séparé)** : `_verdict_from_signals` reste la source du badge verdict affiché
(`dino-suggestions`, C0) — la lane vient désormais du consensus. Pour un crop-cap, le front peut afficher
`auto_candidate` alors que la lane est `ccproxy`. Unifier le front sur `consensus_verdicts` = polish ultérieur.

### Resolver d'attribution unifié (2026-06-10 — C4 FAIT)
Nouveau `review/validation/resolver.py` : **une entrée source-agnostique**
`resolve_listing(title, *, kind, denomination, country, year, conn, coin_ids=None)` → **un type
unique** `ListingAttribution(verdict, target_eurio_id, candidates, keep, reason)`. Remplace les deux
chemins divergents de l'adapter eBay (`_attribute_commemo_row` / `_attribute_standard_row`) + la branche
de rescue qui parsait `COMMEMO_IN_STANDARD_PREFIX` — collapsés en **un seul appel** dans `discover`.
Interface neutre (pas de `DiscoveryGroup`/marketplace) → réutilisable par toute source. Les *stratégies*
(`match_listing_to_group` theme-match, `attribute_standard_listing` plage) restent leurs implémentations
sous `sources/ebay`, **importées paresseusement** (motif déjà en place ; évite le cycle
`sources.ebay.__init__`→adapter→resolver). Le rescue commémo-dans-standard est désormais porté par le
résultat (`verdict='rescued'`, `keep=True`, `reason='rescued_to:<eid>'`), plus de string-parsing côté
appelant. Gate : attribution **inchangée** (`test_ebay_adapter`/`test_ebay_standards`/`test_slug_match`
verts) + mapping testé unitairement (`test_validation_resolver.py`, 11). Note : relocaliser les stratégies
elles-mêmes hors `sources/ebay` cascade via `theme_match_state`→`NAMES_BY_LANG` (config marketplaces) →
reporté ; le contrat est déjà agnostique.

### Rejets ré-ouvrables (2026-06-10 — C5 FAIT)
- **Auto-reject ré-ouvrable** (`enqueue.py`) : un verdict consensus `reject` (dual_contradict, in-scope)
  ne reste plus un item de queue à trier (C3) ni une suppression (pré-C3). Il prend l'**état terminal
  d'un reject** — `image_assets.resolution_status='rejected'`, `training_eligible=0`,
  `quality_reason='consensus_reject'` ; `review_queue` `status='done'`, `decided_by='consensus'`,
  `decision_engine_version='consensus@v1'`, `decision_metadata_json={reason,rule}` — mais estampillé
  machine. Réutilise tel quel les endpoints **`GET /review-queue/rejected`** (grille de récupération) et
  **`POST /review-queue/restore`** (ré-ouverture → `needs_review`), qui exigent une row `review_queue`
  (insérée d'abord). La garde `already` de l'enqueue rend un restore humain **sticky** (pas de
  re-rejet). State event `rejected` (actor `pipeline`, reason `consensus_<rule>`). Compteur
  `EnqueueResult.n_auto_rejected`. Aucune UI neuve.
- **Cleanup legacy** : `scripts/clean_legacy_text_contradict.py` (dry-run par défaut) supprime les
  `discarded_listings(text_contradict_*)` (424) + reset `source_images.route_decision='rejected_text'`
  (118) → un re-run de cohorte les redécouvre et les passe au consensus. ⚠️ destructif + retire les
  lignes du panneau front « rejetés pré-ingestion » → **à lancer sur décision** (`--apply`).

### Reste à faire
1. **Polish front** : faire lire au front le `consensus_verdicts` (badge verdict) → fin du drift C3.

### Fichiers livrés (working tree)
- `ml/review/validation/{__init__,experts,replay,consensus,persist}.py` (nouveau package)
- `ml/state/schema.sql` (table `consensus_verdicts`, versionnée par `rule_version`)
- `ml/training/foundation/auto_validate.py` (C0 : `compute_auto_validate_view`, `ResolvedSignals`,
  `fetch_and_resolve_signals`)
- `ml/review/review_queue_routes.py` (C0 : `AutoValidateVerdictOut` dans `dino-suggestions`)
- Câblage live C3 : `ml/sources/_base/steps/{text_signal,download,enqueue}.py` (kill 2.5 + skip download
  supprimés ; enqueue route + persiste via consensus)
- C4 : `ml/review/validation/resolver.py` (nouveau) + `ml/sources/ebay/adapter.py` (2 méthodes
  `_attribute_*_row` + branche rescue → 1 appel `resolve_listing`)
- C5 : `ml/sources/_base/steps/enqueue.py` (auto-reject ré-ouvrable) +
  `ml/scripts/clean_legacy_text_contradict.py` (nouveau)
- `ml/scripts/{backfill_quality_score,verdict_gold,contradict_rescue,persist_consensus}.py`
- `ml/state/validation_gold/verdict_gold.jsonl` (gold figé, 501)
- Front : `admin/packages/web/src/features/review/{composables/useAutoValidateVerdict.ts,
  composables/useDinoSuggestions.ts, components/AutoValidateVerdict.vue, components/DinoVerdict.vue}`
- Tests : `ml/tests/{test_validation_experts,test_validation_consensus,test_validation_persist,
  test_enqueue_consensus,test_validation_resolver}.py` + `test_text_signal_step.py` (réécrit pour le no-kill)
