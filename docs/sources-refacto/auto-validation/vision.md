# Vision — auto-validation des crops scrapés

> Cible end-state, principes, scope V1, anti-objectifs.
> Doit être lu avant tout kickoff de chunk dans ce dossier.

## Cible end-state

Sur la **page Coin** (admin, fiche d'une pièce identifiée par `eurio_id`),
on voit la galerie d'images associées à cette pièce s'enrichir
automatiquement au fur et à mesure des runs de scrape.

Trois flux d'arrivée pour une image dans cette galerie :

1. **Auto-validée par la pipeline** — Dino + signal texte ont convergé
   avec une confiance suffisante. L'image apparaît avec un badge
   `auto` et la sim cosine, l'humain n'a rien fait.
2. **Validée par review humaine** — la pipeline a flaggé
   `needs_review`, l'humain a confirmé/corrigé dans `/review`, l'image
   apparaît avec un badge `manual` et le nom du reviewer.
3. **Rejetée** — la pipeline ou l'humain a flagué `rejected`.
   L'image n'apparaît pas sur la page Coin (mais reste en DB pour
   audit).

**KPI cible 6 mois** : ≥ 70 % des images training arrivent par le flux 1
(auto), avec une precision spot-checked ≥ 99 %. Le restant en review
humaine, dont la file ne grossit plus aussi vite que le scrape.

Pour atteindre ça, on construit progressivement une **chaîne
multi-signal** qui se branche entre `detect_crop` et `enqueue` dans
la pipeline 6 étapes existante. Une nouvelle étape `auto_validate`
applique deux signaux indépendants au crop :

- **Signal image (Dino)** — embedding du crop comparé aux ancres
  obverse Numista du catalog Eurio. Top-K + spread.
- **Signal texte** — heuristique sur le titre + description du listing,
  parse le pays / la valeur / l'année / le thème commémoratif.

L'une des deux ne suffit jamais. La conjonction des deux dans le même
sens, avec marges de spread suffisantes, débloque l'auto-accept. Tout
désaccord ou toute zone tiède reste `needs_review`. Tout désaccord
fort déclenche un `rejected`.

## Principes non négociables

### P1 — Multi-signal indépendant

Pas un seuil unique sur Dino. Pas un fallback texte. **Deux signaux
indépendants qui doivent converger.** Inspiré de
`docs/training-pipeline/harvest/auto-validator.md`. La raison : aucun
signal pris isolément ne tient sur des marketplaces où les vendeurs
mislabellent. Dino seul gonfle les sim sur euros (mémorisé dans
`feedback_dino_thresholds`). Texte seul prend tout pour argent
comptant.

### P2 — Obverse only

Le matcher Eurio est obverse-only par construction (le côté commun
2€/1€ est identique pour toutes les pièces de même valeur d'une époque,
zéro discrimination). On encode comme ancres **uniquement les obverse
canoniques Numista**. Quand la pipeline tombe sur un reverse, le top1
sera médiocre + le spread faible : on s'en sert comme **signal de
détection** "c'est un reverse, skip" plutôt que d'essayer de le
matcher.

### P3 — Auto-accept seulement quand le faux positif est rare ET réversible

Un faux positif auto-accepté pollue le training set ET la galerie de
la page Coin. Donc :

- **Seuils calibrés pour precision ≥ 99 %** sur le set de calibration
  (recall sacrifiable, c'est la review humaine qui rattrape).
- **Status `auto_dino` distinct** dans `image_assets.resolution_status`
  (et plus tard `auto_dino_text` quand le texte est branché). Permet
  de filtrer / re-flagger / rollback massivement si on découvre un
  bug.
- **Rollback prévu dès la V1** : un bouton admin "re-flagger en
  needs_review" sur la page Coin pour les images en `auto_*`.
- **Spot-check périodique** : sur 50 auto-accept tirés au hasard,
  combien sont vraiment bons. Tracké, dégradation détectée.

### P4 — Scope V1 minimaliste

V1 = **2€ commémoratives uniquement**. Standards exclus du
auto-accept (les 2€ standards inter-pays sont quasi-jumeaux côté
obverse, Dino ne sait pas les distinguer — cf. inflation 0.85-0.90
mémoirée). Les standards continuent à passer en `needs_review` 100 %
du temps. À ré-évaluer en V2 quand on aura un signal complémentaire
(OCR, géolocalisation seller, etc.).

### P5 — Audit en `/review`, pas bench autonome

On ne construit pas un bench standalone hors-pipeline. **Dino se branche
en surcouche de `/review` dès la V1 comme couche d'aide visuelle
(suggestions top-K + sim + spread)**, sans toucher la décision
auto/manual. Raphaël passe sa review queue habituelle ; à chaque crop
il voit ce que Dino propose. C'est `/review` enrichi qui *est* le
bench.

Pourquoi pas un set hand-labelled séparé : aujourd'hui la review queue
contient ~1 crop validé `manual`. Construire un bench statistique
demanderait de labelliser à la main 100-200 crops avant même que
Raphaël ait jamais vu Dino tourner sur un seul exemple. Pas le bon
ordre.

À la place : Dino tourne sur les 524 reviews actuels (backfill), les
suggestions s'affichent dans le drawer, et chaque review humaine devient
une mesure (Dino disait X, l'humain a confirmé/contredit). Quand on
aura accumulé 200+ reviews avec annotations Dino, on aura un set
calibration *gratuit*. **Là** on code l'auto-accept (chunk 3+).

Cohérent avec `feedback_chunk_audit_flow` (chunk-by-chunk avec audit).

### P6 — Pas de ré-entraînement Dino en V1

DINOv2 zero-shot ImageNet-pretrained suffit pour démarrer. Le
fine-tuning sur euros est une option ultérieure (voir
`coin-similarity-encoder-followup.md`) mais n'est pas dans le périmètre
de ce chantier. On consomme l'encoder tel quel.

## Cible de la V1 (l'auto-accept "minimum useful")

À la fin du chantier auto-validation V1, on doit avoir :

```
Pipeline scrape (eBay sur 2€ commémo)
  ↓
detect_crop (existant)
  ↓
auto_validate ← NOUVEAU
  │   ├─ Signal image Dino (top-1, spread vs target_eurio_id)
  │   └─ Signal texte (parse titre, extrait country/year/theme)
  │
  ├──► auto_dino    : status='auto_dino_text', eurio_id assigné, page Coin OK
  ├──► needs_review : status='needs_review', drawer admin avec suggestions
  └──► rejected     : status='rejected', signaux contradictoires forts
  ↓
enqueue (existant, ne touche que les needs_review)
```

Le drawer lot **utilise les top-K Dino comme suggestions** pour
accélérer la review humaine sur les crops qui n'ont pas été
auto-acceptés.

## Découpage du chantier

| # | Chunk | Statut |
|---|---|---|
| 1 | Foundations `ml/foundation/` + ancres + table `image_asset_dino_predictions` | ✅ livré 2026-05-04 |
| 2 | Étape pipeline `auto_validate_dino` + backfill + endpoint API | ✅ livré 2026-05-04 |
| 3 | Front : suggestions Dino dans drawer single + lot (`/review`) | ✅ livré 2026-05-04 |
| 0 | **Visibilité du stream sources → review** (préalable à signal texte) | À faire (kickoff courant) |
| 4 | Extracteur `ListingTextSignals` (pur, tests sur titres réels) | Plus tard |
| 5 | Étape pipeline `text_signal_extract` + table `listing_text_signals` (sans décision) | Plus tard |
| 6 | Comparateur `vs_target` + filtre dur `text_contradict_*` → `discarded_listings` | Plus tard |
| 7 | Panel front "Texte" dans drawer review (à côté Dino) | Plus tard |
| 8 | Combinatoire Dino × texte → auto-accept (multi-signal P1) | Plus tard |
| 9 | Rollback tooling page Coin (re-flagger `auto_*` en `needs_review`) | Plus tard |
| 10 | Spot-check / monitoring drift | Plus tard |

On ne dépasse jamais le chunk en cours sans audit visuel + go.

### Pourquoi un chunk 0 hors-séquence

Le chantier a basculé après les chunks 1-3 sur un constat simple : **le pipeline
sources a déjà des filtres** (`accept_listing` rejette `noise_title`,
`year_mismatch`, `non_eur`, `below_face`, `above_extreme`, `no_price` ; un
filtre `theme_tokens` drop silencieusement quand `(country, year)` est ambigu)
et **persiste leurs verdicts** (`discarded_listings`, `discovery_searches`),
mais l'admin n'expose **aucun de ces rejets**. Conséquence pratique : quand
Raphaël regarde un run, il voit `n_raw_results=50 → n_kept_results=12` sans
savoir pourquoi 38 listings ont été virés ni à quelle étape.

Avant d'ajouter un nouveau filtre (signal texte), on rend visibles ceux qui
existent. Sinon on empile des décisions opaques. Cohérent avec
`feedback_chunk_audit_flow` (audit = condition d'avancement).

Périmètre chunk 0 :

- Persister la ventilation **N0 → N1 → N2 → N3** dans `discovery_searches` :
  N0 = retour brut Browse (`itemSummaries`), N1 = post group expansion
  (`getItemsByGroup`), N2 = post theme-token drop, N3 = post `accept_listing`.
- Tracer le **theme-token drop** dans `discarded_listings(reason='theme_mismatch')`
  (aujourd'hui silencieux).
- **Endpoint API** `/sources/{id}/runs/{run_id}/discarded` qui expose
  `discarded_listings` du run avec `reason`, `title`, `source_url`, payload.
- **Panel front "Listings rejetés"** dans `SourceRunListingsPage`, groupé par
  `reason` avec compteurs et drill-down par row. Affichage de la chaîne
  `N0 summaries → +groups N1 → −theme N2 → −accept N3` dans le panel
  Discovery searches.

### Cible UX d'arrivée (post chunks 4-8)

Drawer review avec **trois panels parallèles** par crop :
- **Texte** — `ListingTextSignals` extrait + verdict vs target (convergent /
  partial / absent / contradict)
- **Dino** — top-K + sims + spread (existe déjà, chunk 3)
- **Auto-validate** — combinaison des deux + décision finale (auto / review /
  reject) avec justification

Et `SourceRunListingsPage` qui devient une **vue de stream** où chaque listing
porte la trace complète de son passage : retour brut eBay → filtres successifs
→ verdict final, avec à chaque étape le nombre, la raison, et la possibilité
de cliquer sur un listing rejeté pour le voir individuellement.

## Ce qui reste explicitement en `needs_review` V1

- Toute pièce 2€ standard (obverse quasi-jumeau inter-pays)
- Toute pièce 1€, 50c, 20c, 10c, 5c, 2c, 1c (V1 ne couvre pas)
- Tout crop où Dino top1 ≠ target_eurio_id
- Tout crop où le spread top1−top2 est en zone tiède (entre `δ_low` et
  `δ_high`)
- Tout crop d'un listing où le signal texte donne un pays/year qui
  contredit le target_eurio_id
- Tout crop d'un lot (à terme : suggestions seulement, pas auto-accept)

## Anti-objectifs

- **Pas d'appel LLM dans le pipeline** — règle de
  `auto-validator.md`. Le signal texte sera regex/dictionnaire, pas
  un prompt OpenAI. Latence + coût + non-déterminisme inacceptables.
- **Pas de seuil unique global** — par groupe de pièces si nécessaire,
  jamais "0.85 partout".
- **Pas de feedback du model entraîné vers le verifier** — le
  verifier reste indépendant de l'ArcFace en cours d'entraînement
  (sinon boucle de pollution). Dino zero-shot fixe.
- **Pas d'auto-accept sur lots V1** — uniquement suggestions. La
  sémantique "quelle pièce du coffret est laquelle" est trop
  ambiguë sans humain.
- **Pas de drag-drop fancy front V1** — quand le drawer lot ingère
  des suggestions Dino, c'est un simple pré-remplissage du modal
  CoinSearchModal.
- **Pas de sortie sur les pièces non-2€-commémo V1** — le scope tient
  ou pète, pas de scope creep.

## Ce qui peut faire pivoter le plan

Trois découvertes possibles dans le bench :

1. **Dino précision auto-accept < 95 % même seuils stricts** sur
   commémo → on ne peut pas auto-accepter, V1 devient "Dino =
   suggestions seulement". On revoit la stratégie globale.
2. **Distribution top1 reverse vs top1 obverse non séparable** → on
   ne sait pas skipper les reverse, on les laisse passer en review
   humaine. Pas dramatique, juste plus de bruit en review.
3. **Le set de validation hand-labelled est trop petit** (< 50
   exemples par cas) → le calibrage des seuils est non fiable, on
   colle d'abord du temps sur agrandir le set avant de toucher
   l'intégration.

Chaque pivot doit être documenté dans le journal du chunk concerné,
pas écrasé.

## Mémoires liées

- `feedback_dino_thresholds` — Dino inflate sur euros, percentile-based
- `feedback_chunk_audit_flow` — chunks 30min-3h, livrer + attendre
- `feedback_no_debt` — pas de shortcut qui crée de la dette
- `project_arcface_design_group_label` — labels = design_group, pas
  numista_id (l'auto-validate écrit l'eurio_id, pas le design_group)
- `feedback_training_source_obverse_only` — obverse uniquement (cohérent
  P2)

## Glossaire interne

| Terme | Définition |
|---|---|
| **target_eurio_id** | L'eurio_id qui a piloté le scrape (la pièce qu'on cherchait). C'est un *prior*, pas une vérité. |
| **Ancre canonique** | L'image obverse Numista officielle d'un eurio_id. Une par eurio_id. |
| **top-K** | Les K eurio_id les plus proches d'un crop selon Dino cosine. |
| **Spread** | `top1_sim − top2_sim`. Mesure la séparation du gagnant. |
| **Auto-accept** | La pipeline assigne `eurio_id` automatiquement sans humain. |
| **Auto-dino** | Status `image_assets.resolution_status` = auto-acceptée par Dino seul. |
| **Auto-dino-text** | Status auto-acceptée par Dino + signal texte convergent. |
