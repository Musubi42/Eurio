# Phase 1 livrée — suggestions Dino (scope + biais pays + abstention) + bench encodeur

> Livraison du 2026-06-11, dans la foulée de l'audit Phase 0 (`phase0-audit.md`
> / `phase0-findings.md`). Tout est codé, backfillé, testé (unit + E2E
> TestClient) et re-mesuré. Rien n'est commité.
>
> **Addendum même jour — bascule vitl14 APPLIQUÉE sur la couche suggestions**
> (go PO) : voir §« Bascule vitl14 » en fin de doc. Les chiffres « Phase 1 »
> ci-dessous sont l'état vits14 intermédiaire ; l'état live est vitl14
> (`phase2-audit-2eur_all-vitl14.md`).

## Ce qui change

### Chunk 1.2 — P1 : banque élargie aux 2€ courantes

- Deux nouveaux `anchors_kind` dans `ml/training/foundation/anchors.py` :
  - `2eur_standard` — 38 ancres = 1 par design group de 2€ courante
    (représentant = plus ancien millésime, même convention que la review ;
    l'image vient du premier membre du groupe avec un `obverse.jpg`, ce qui
    rattrape lt/lv/mt 1st-type sans dataset). 3 groupes restent sans ancre
    (aucun membre avec image).
  - `2eur_all` — 546 ancres = concat commémo (508) + standards (38), sans
    ré-encodage. **C'est la banque des suggestions review.**
- **Architecture retenue : banques par kind + concat, et séparation
  suggestions/consensus.** Le consensus/lanes (règle C0–C5, calibrée et
  câblée live) reste sur `2eur_commemo` — constantes
  `CONSENSUS_ANCHORS_KIND` / `SUGGESTIONS_ANCHORS_KIND`.
- `steps/auto_validate.py` passe en multi-kind avec **un seul encodage par
  crop** partagé entre banques (`LIVE_ANCHORS_KINDS = (2eur_commemo,
  2eur_all)`) : orchestrateur, backfill (`--kind`), lazy-compute review et
  recompute post-recrop (`predict_and_persist_kinds`) sont alignés.
- Backfill fait : **3002 prédictions `2eur_all`** (54 s, M4/MPS).
- Endpoints `…/dino-suggestions` : défaut `anchors_kind=2eur_all` ; le front
  retombe sur `2eur_commemo` si la banque large n'est pas bâtie côté serveur.

### Chunk 1.1 — P5 : abstention par spread

- Découverte Phase 0 : la sim top1 ne sépare pas le hors-scope (médiane
  0.834 hors-scope ≈ 0.836 correct) ; le spread global si (0.047 / 0.010 /
  0.006). Seuils calibrés dans `foundation/thresholds.py`
  (`DINO_ABSTENTION_THRESHOLDS` : uncertain < 0.02 ≤ low_margin < 0.05 ≤
  confident) avec la justification chiffrée en commentaire.
- La réponse expose `abstention_state` + `abstention_thresholds` (calcul
  server-side, source unique).
- UI (`DinoSuggestions.vue`) : bannière « Dino incertain — pièce probablement
  hors banque ou design ambigu, préférer la recherche libre (F) » + listes
  atténuées quand `uncertain` ; chip « incertain » en variante compacte.

### Chunk 1.3 — P2 : lots multi-pays, prior pays souple

- Détecteur de titre multi-pays (`_is_multi_country_lot`, routes) :
  adjectif divers/verschiedene/mixed/gemischt/misti/varios… à ≤ 2 mots d'un
  mot « pays » (Länder/countries/pays/paesi/países) + formes explicites
  (`aus allen Ländern`, `Euroländer`). Haute précision voulue : un faux
  positif démote la bande pays qui aide massivement sur mono-pays
  (92.2 % vs 73.5 % @5). 13 listings matchent en base (dont le lot kickoff).
- Réponse : `multi_country_lot: bool`. UI : sur ces lots, le **ranking
  global passe en premier** (« Lot multi-pays — toute la bank ») et la bande
  pays devient « prior indicatif » en secondaire. Sur mono-pays : inchangé.
- Le re-rank numérique « prior souple » (bonus pays sur le score global) est
  volontairement différé : impossible à calibrer sans labels multi-pays
  (1 seul crop « vérité ≠ cible » dans le set décidé).

## Mesures après Phase 1 (`phase1-audit-2eur_all.md`)

| Métrique (set labellisé, 478 crops) | Phase 0 (commémo) | Phase 1 (2eur_all) |
|---|---|---|
| Couverture de scope (niveau design group) | 91.2 % | **100 %** |
| UI recall@5 (bande effective) | 82.7 % | **92.2 %** |
| Recall@5 courantes (bande pays) | 0 % (hors banque) | **92.9 %** |
| Non-régression commémo UI@5 | 90.8 % | 92.2 % |

L'audit normalise désormais la vérité des courantes au représentant de
design group (sinon fausse détection hors-scope) et filtre les prédictions
par kind (`--kind`).

**Lot kickoff `267449922852`** (24 crops de courantes, target commémo BE) :
9/24 crops ont maintenant une courante en top1 (avant : 0 par construction),
le reste part majoritairement en « incertain » via l'abstention, et le panel
affiche le ranking global en premier (multi-pays détecté). Vérifié E2E.

## Phase 2.4 — bench encodeur (`phase2-encoder-bench.md`)

| Modèle | global@1 | global@5 | pays@1 | pays@5 | ms/img (M4 MPS) |
|---|---|---|---|---|---|
| dinov2-vits14 (prod) | 55.1 % | 73.3 % | 74.9 % | 92.2 % | 28 |
| **dinov2-vitl14** | **77.2 %** | **87.9 %** | **89.1 %** | **95.0 %** | 116 |

**+22 points de recall@1** pour 4× le coût d'encodage (3000 crops ≈ 6 min).
La bascule N'EST PAS faite : `encoder_version` est tracé partout et les
seuils du consensus C0–C5 sont calibrés sur les sims vits14 → basculer
implique re-bâtir les banques, re-backfiller, et re-calibrer (replay gold
C2.5). **Décision PO.** Piste à coût minimal : ne basculer que la couche
SUGGESTIONS sur (vitl14, 2eur_all) en gardant le consensus sur (vits14,
2eur_commemo) — la table des prédictions est déjà clée par
(asset, encoder_version, kind).

## Fichiers touchés

- `ml/training/foundation/anchors.py` — builders standard/all, constantes kinds
- `ml/training/foundation/__init__.py`, `thresholds.py`
- `ml/sources/_base/steps/auto_validate.py` — multi-kind, encode partagé
- `ml/serving/crop_edit.py` — recompute multi-kind post-recrop
- `ml/review/review_queue_routes.py` — abstention, multi-pays, défaut 2eur_all,
  verdict/consensus épinglés au kind consensus
- `ml/scripts/{build_dino_anchors,backfill_dino_predictions}.py` — `--kind`
- `ml/scripts/audit_dino_suggestions.py` — `--kind`, normalisation design group
- `ml/scripts/bench_encoder_dino.py` — nouveau (bench offline, aucune écriture)
- `admin/.../composables/useDinoSuggestions.ts` — types, défaut 2eur_all + fallback
- `admin/.../components/DinoSuggestions.vue` — bannière abstention, inversion bandes
- `ml/Taskfile.yml` — descs kinds + procédure post-renommage de slugs

## Bascule vitl14 (appliquée, go PO du 2026-06-11)

La couche SUGGESTIONS tourne sur **dinov2-vitl14** ; le consensus reste sur
vits14 (seuils C0–C5 inchangés, zéro impact lanes).

- `encoder.py` : registre `ENCODER_HUB_MODELS`, `load_encoder(encoder_version=…)`.
- `anchors.py` : `ENCODER_VERSION_FOR_KIND` / `encoder_version_for_kind()` —
  `2eur_all` → vitl14, `2eur_commemo`/`2eur_standard` → vits14. Le builder
  `2eur_all` encode from scratch (plus de concat : encodeurs différents).
- `steps/auto_validate.py` : singleton encodeur PAR version ; un crop est
  encodé une fois par encodeur requis (consensus + suggestions = 2 encodes,
  inévitable). Garde : une banque dont l'`encoder_version` ne correspond pas
  à son kind est traitée comme absente (force le rebuild explicite).
- Routes : `get_dino_prediction` résout l'encodeur via le kind.
- Banque rebâtie (546 ancres, dim 1024, 78 s) ; **3002 prédictions vitl14
  backfillées** (142 ms/crop M4) ; lignes (vits14, 2eur_all) purgées.
- Seuils d'abstention **re-validés sur vitl14** (encore meilleurs : sous
  0.02 on ne perd que 8 % des corrects ; ≥ 0.05 → précision 97.8 %) —
  inchangés à 0.02/0.05.

Mesures live (`phase2-audit-2eur_all-vitl14.md`, set labellisé) :

| Métrique | vits14 (Phase 1) | vitl14 (live) |
|---|---|---|
| UI recall@1 | 74.8 % | **87.4 %** |
| UI recall@5 | 92.2 % | **95.2 %** |
| Spread médian correct / faux | 0.045 / 0.008 | 0.097 / 0.011 |

Lot kickoff : 14/24 crops avec courante en top1 (9 sous vits14, 0 à
l'origine), 8 « net », 9 « incertain ». Tests : 38 unit + E2E TestClient OK
(suggestions=vitl14/546, consensus explicite=vits14/508).

## Reste à faire (prochaine rétro)

1. Labelliser quelques lots multi-pays (le kickoff en tête) pour mesurer P2
   réellement et calibrer un éventuel re-rank souple.
2. Étendre la banque aux autres dénominations (1€, 50c…) quand des listings
   hors 2€ entreront dans le pipeline — le routage par kind est prêt.
3. 3 design groups standards sans `obverse.jpg` (aucun membre avec dataset) :
   fetch des avers manquants.
4. Optionnel : bascule du CONSENSUS sur vitl14 (gros chantier — re-replay
   gold C2.5 + recalibrage des seuils C0–C5).
