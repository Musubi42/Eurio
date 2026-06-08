# Mission — Repenser l'orchestration de l'auto-validation (modèle ensemble/consensus)

> **Statut : CONCEPTION (grounded, exécutable).** Décidé 2026-06-08 après exploration graphify du flux
> text-signals → attribution → review. Chantier à part entière (touche le chemin
> critique d'ingestion + le front admin). À faire en chunks audités, avec une
> **stratégie de non-régression par replay** (verdicts avant/après). Doctrine R0,
> SQLite-only (eurio.db = vérité), [[feedback_chunk_audit_flow]].
>
> **MàJ 2026-06-08 (grounding 6-agents vs code + `eurio.db`) :** §1 corrigé (seuils = floats
> fixes ≠ percentile, step **5.5** pas 7, gate **2-phases** avec enforcement dans `download.py`),
> §2/§5/§6 chiffrés sur la base réelle, §7 **tranché**, chunk **C2.5** (gold replay) inséré.

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
- **C0 — Modèle & seuils unifiés** : extraire le modèle de verdict back comme source unique,
  exposer au front (supprimer `useAutoValidateVerdict.ts` → lecture API). Gate : front affiche
  le même verdict qu'avant (parité).
- **C1 — Expert interface** : normaliser text/dino/crop_quality derrière une interface
  `Expert.evaluate(asset) -> Signal`. Gate : signaux identiques aux valeurs actuelles (text+dino).
- **C2 — crop_quality expert** : injecter tilt/undercrop comme 3e expert. ⚠️ Données :
  `tilt_deg`/`axis_ratio` peuplés sur **66.7 %** des assets mais **trustworthy à 36 %** seulement
  (détecteur fiable ≥35°, [[project_tilt_detection]]) → s'appuyer **aussi** sur `quality_score`/
  `quality_reason` (déjà colonnes de `image_assets`) et traiter tilt NULL/non-trustworthy comme
  **pénalité nulle**. Gate : mesurer son effet sur un échantillon labellisé.
- **C2.5 — Gold de replay** (NOUVEAU, bloquant C3) : geler `mix-zone-17` + amorcer une gold plus
  large depuis les 454 assets résolus manuellement. Gate : un diff de verdicts rejouable,
  quota-free, sur ≥1 cohorte réelle (cf. §6).
- **C3 — Règle de consensus** : remplacer le gauntlet. Neutraliser les **deux** points contradict
  (kill pipeline 2.5 **et** branche `contradict→divergent` du verdict) → `needs_review`.
  Pré-filtre junk-only conservé. Gate : **replay** (§6, gold C2.5) — diff verdicts avant/après,
  valider que les nouveaux `needs_review` sont des rescues légitimes, pas du bruit.
- **C4 — Resolver unifié commemo+standards**. Gate : attribution standards inchangée sur gold.
- **C5 — Rejets ré-ouvrables** (verdict reject vs suppression) + UI review. Gate : un rejet
  sémantique réapparaît en review et peut être ré-ouvert.

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
