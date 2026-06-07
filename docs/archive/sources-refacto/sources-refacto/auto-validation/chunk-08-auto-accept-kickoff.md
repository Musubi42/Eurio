# Kickoff — Chunk 8 : combinatoire Dino × texte → auto-accept

> Brief auto-suffisant pour reprendre le chunk 8 dans une session
> nouvelle. Doit être lisible sans charger la conversation précédente.

## Pré-lecture obligatoire

1. [`vision.md`](./vision.md) — surtout §"Cible end-state", principes
   P1 (multi-signal indépendant), P3 (auto-accept seulement quand FP
   rare ET réversible), P4 (V1 = 2€ commémo only), §"Cible de la V1".
2. [`progress.md`](./progress.md) — §"Chunk 2" (chiffres Dino réels),
   §"Chunk 3.5" (country-aware re-rank, R@1=34 %), §"Chunk 6.a+b"
   (verdict texte, distribution 88.8 % convergent / 9.7 % partial /
   0.9 % contradict sur 783), §"Chunk 7" (panel front).
3. Mémoire `feedback_dino_thresholds` — Dino inflate sur euros, sims
   tassées, **percentile-relatif** plutôt qu'absolu.
4. Mémoire `feedback_chunk_audit_flow` — chunk-by-chunk avec audit, pas
   d'enchaînement sans go.

## Contexte courant (état du code au démarrage)

Les chunks 0-7 sont livrés. Concrètement :

- **524 crops** 2€ commémo en `needs_review` ont leur prédiction Dino
  backfillée dans `image_asset_dino_predictions` (encoder
  `dinov2-vits14`, anchors_kind `2eur_commemo`, 376 ancres). Country
  band rerank actif : `top1_country_eurio_id`, `top1_country_sim`,
  `country_spread`.
- **783 source_images** ont leur `listing_text_signals` avec verdict
  `vs_target_verdict` (chunk 6).
- **Step `auto_validate_dino`** (chunk 2) calcule les prédictions Dino
  mais ne décide rien — `image_assets.resolution_status` reste
  `needs_review`.
- **Step `text_signal`** (chunk 5+6) calcule + persiste verdict +
  écrit `discarded_listings(reason='text_contradict_*')` sur
  contradict + pose `route_decision='rejected_text'`. Les contradicts
  sont déjà filtrés en amont — la queue ne contient plus que
  convergent/partial/absent.
- **Front review** (chunk 3+7) montre les suggestions Dino + le panel
  texte parallèle. Aide visuelle pour calibrer.
- **Statuses existants sur `image_assets.resolution_status`** :
  `pending_crop`, `pending_match`, `auto_name`, `auto_phash`,
  `needs_review`, `manual`, `rejected`. **Manque** : `auto_dino_text`
  (à ajouter via _ensure_column + CHECK étendu).

## Périmètre du chunk 8

**Ce qui est dans le scope** :

1. Script de calibration **8.a** : balayage des seuils sur les 524
   crops backfillés, mesure precision/recall vs `decided_eurio_id`
   humain quand disponible (cf. §Calibration).
2. Step pipeline **8.b** : `auto_accept_combined` (ou extension de
   `auto_validate.py`) qui applique la règle calibrée → set
   `resolution_status='auto_dino_text'`, `eurio_id=target_eurio_id`,
   `resolution_confidence=top1_country_sim`. Tests.
3. Backfill **8.c** : recompute la décision sur les 524 + audit DB
   (combien d'auto-accept, distribution sims, échantillon manuel).
4. Front **8.d** : badge `auto` sur la galerie page Coin pour
   distinguer `auto_dino_text` du reste. Filtre review queue pour
   exclure les `auto_dino_text`.

**Hors scope** (chunks suivants ou jamais V1) :

- Pas d'auto-accept sur lots (`is_lot=True` → review humaine forcée).
- Pas d'auto-accept sur 2€ standards (P4 : V1 = commémo only).
- Pas d'auto-accept sur 1€ et fractions (P4).
- Pas de combinaison avec OCR/seller-geo/autres signaux (V2 si besoin).
- Pas de re-fine-tuning Dino (P6).
- Pas de rollback tooling (chunk 9).
- Pas de monitoring drift (chunk 10).

## Décisions actées (post-brainstorm pré-session)

### Règle V1 (stricte, calibrable)

```
auto_accept ⇔
    text.verdict == "convergent"                       // 3/3 axes texte
  ∧ text.is_lot == False                                // jamais de lots V1
  ∧ dino.top1_country_eurio_id == target_eurio_id      // Dino bande pays confirme
  ∧ dino.country_spread >= δ_min                        // séparation minimale
  ∧ dino.top1_country_sim >= σ_min                      // sim absolue minimale
```

**Justifications** :
- `text.verdict == "convergent"` (3/3) plutôt que `≠ "contradict"` :
  P3 (FP rare). On ne donne le feu vert que quand le titre confirme
  *tous* les axes. Les `partial` restent en review.
- `is_lot == False` : la sémantique "quelle pièce du coffret est
  laquelle" est trop ambiguë sans humain (vision §"Anti-objectifs").
- `top1_country_eurio_id == target_eurio_id` plutôt que `top1_eurio_id`
  global : R@1 country = 34 % vs R@1 global = 10 % (mesure chunk 3.5),
  donc la bande pays est notre meilleur signal Dino.
- `country_spread + country_sim` : double seuil. Sims tassées sur
  euros, donc spread seul ne suffit pas ; sim absolue seule non plus
  (right=0.739 / wrong=0.679, recouvrement large).

### Calibration empirique

- **Set de calibration** : `image_assets.resolution_status='manual'`
  (où l'humain a déjà tranché) qui ont aussi une prédiction Dino + un
  signal texte. Le `decided_eurio_id` est la vérité terrain.
- **Au moment du démarrage** : ce set est très petit (~1 review
  validée d'après progress.md chunk 2). Il faut **d'abord** que
  Raphaël ait reviewé ~50-100 crops dans le drawer pour qu'on ait un
  set utilisable. Si pas le cas au démarrage de la session, le chunk
  8.a se transforme en "balayage à blanc avec audit visuel sur des
  cas typés" (l'utilisateur regarde les auto-acceptés candidats et dit
  oui/non en ad-hoc).
- **Métriques** :
  - **Precision** = #(auto_accept ∧ top1_country == decided_eurio_id) / #auto_accept
  - **Yield** = #auto_accept / #candidates_eligible
  - **Cible** : precision ≥ 99 %, yield max sous cette contrainte.
- **Format de sortie** : CSV `seuils.csv` avec colonnes
  `δ_min, σ_min, n_auto_accept, n_correct, n_wrong, precision, yield`
  + un résumé console avec recommandation. Pas de plot PNG en V1.
- **Si precision ≥ 99 % impossible** même très strict → on revient
  brainstormer. Hypothèses : signal Dino encore trop bruité (besoin
  fine-tune), set de calibration trop petit (besoin labelliser plus),
  ou la règle stricte de V1 ne suffit pas (ajouter un signal V2).

### Sub-chunks

- **8.a** : `ml/scripts/calibrate_auto_accept.py` — pure analyse,
  pas d'écriture DB. Console + CSV. Audit obligatoire.
- **STOP — go/no-go avec Raphaël sur les chiffres calibration.**
- **8.b** : step + tests. Quand on est ici on a `(δ_min, σ_min)`
  arrêtés.
- **8.c** : backfill + audit DB.
- **8.d** : front (badge page Coin + filtre review queue).

## Design proposé du step `auto_accept_combined`

### Position dans la pipeline

Aujourd'hui : `discover → persist → text_signal → download → detect → resolve → auto_validate → enqueue`.

Le step `auto_accept_combined` se branche **après `auto_validate`**
(qui calcule les prédictions Dino) et **avant `enqueue`** (qui pousse
en review queue). Il lit les deux sorties :

- `image_asset_dino_predictions` (top1_country_eurio_id, sims, spread)
- `listing_text_signals` (vs_target_verdict, is_lot)

Et applique la règle. Sur match :

```python
conn.execute(
    """
    UPDATE image_assets
       SET resolution_status     = 'auto_dino_text',
           eurio_id              = target_eurio_id,
           resolution_confidence = ?,
           resolved_at           = datetime('now'),
           resolution_attempts_json = ?
     WHERE id = ?
    """,
    (top1_country_sim, json.dumps({
        "auto_accept_kind": "auto_dino_text",
        "rule_version": "v1",
        "thresholds": {"delta_min": ..., "sigma_min": ...},
        "signals": {
            "text_verdict": "convergent",
            "is_lot": False,
            "dino_top1_country_eurio_id": ...,
            "dino_country_sim": ...,
            "dino_country_spread": ...,
        },
    }), asset_id),
)
```

Le step `enqueue` saute déjà les `auto_*` (cf. condition existante),
donc rien à modifier là.

### Schema migration

```sql
-- Ajouter 'auto_dino_text' au CHECK de image_assets.resolution_status.
-- SQLite ne permet pas ALTER CHECK, donc on rebuild la contrainte via
-- _ensure_column ou via une recréation de table. Le pattern utilisé
-- jusqu'ici (additif via _ensure_column) ne marche pas pour CHECK.
--
-- Option simple : DROP CHECK puis recréer (impact migration).
-- Option pragmatique V1 : on store la nouvelle valeur 'auto_dino_text'
-- même si le CHECK l'interdit techniquement, en supprimant le CHECK
-- (SQLite tolère, juste plus de garde-fou côté DB).
--
-- Mon vote : utilité du CHECK = faible (l'app contrôle déjà l'enum
-- côté Python). On rebuild la table une fois (script one-shot
-- ml/scripts/migrate_resolution_status_check.py) puis on ajoute
-- 'auto_dino_text' au schema.sql.
```

À discuter au démarrage du chunk : faut-il le rebuild table, ou
relâcher le CHECK ? Le rebuild est propre mais lourd ; le relâche est
pragmatique.

### Idempotence + force

- Idempotence par défaut : si `resolution_status` est déjà
  `auto_dino_text` ou `manual`, le step skip.
- `--force` : recompute même les déjà-décidés (utile pour tester un
  changement de seuils).

## Front (chunk 8.d)

### Badge sur la page Coin

`packages/web/src/features/coins/pages/CoinDetailPage.vue` (ou
équivalent) — la galerie d'images du coin doit montrer pour chaque
image :
- `auto` (badge bleu/indigo) si `resolution_status='auto_dino_text'`
- `manual` (badge gris) si `resolution_status='manual'`
- `auto_phash` / `auto_name` (existants) si applicables

À voir : où vit cette galerie aujourd'hui dans l'admin (probablement
pas encore implémentée ?). Si pas implémentée, le 8.d peut juste
ajouter le filtre review queue (exclure les `auto_dino_text`) +
reporter la galerie à un chunk dédié page Coin.

### Filtre review queue

`/review` ne doit pas afficher les `auto_dino_text`. La query API qui
peuple la queue filtre déjà sur `resolution_status='needs_review'`,
donc rien à faire en théorie — vérifier que les `auto_dino_text` ne
matchent pas accidentellement.

## Tests à écrire

### `ml/tests/test_auto_accept.py` (8.b)

Cas convergent + Dino confirme avec seuils OK :
1. `test_auto_accept_when_all_signals_align` — text=convergent +
   is_lot=False + dino_top1_country=target + spread/sim ≥ seuils →
   `resolution_status='auto_dino_text'`, eurio_id=target.

Cas blockers :
2. `test_no_auto_accept_when_text_partial`
3. `test_no_auto_accept_when_text_absent`
4. `test_no_auto_accept_when_is_lot`
5. `test_no_auto_accept_when_dino_top1_country_mismatch`
6. `test_no_auto_accept_when_country_spread_below_threshold`
7. `test_no_auto_accept_when_country_sim_below_threshold`
8. `test_no_auto_accept_when_no_dino_prediction` — fallback gracieux
   si pas de row dans `image_asset_dino_predictions`.
9. `test_no_auto_accept_when_no_text_signals` — fallback gracieux
   si pas de row dans `listing_text_signals`.

Idempotence :
10. `test_idempotent_skips_already_auto`
11. `test_force_recomputes_already_auto`

Audit trail :
12. `test_resolution_attempts_json_carries_signals_snapshot`

### Test d'intégration pipeline (8.b)

13. `test_pipeline_orchestrator_runs_auto_accept_after_auto_validate`
    — orchestrateur doit appeler le nouveau step au bon endroit.

## Audit visuel attendu

Après backfill 8.c :

```sql
-- Distribution post-décision sur les 524 crops 2€ commémo
SELECT resolution_status, COUNT(*) AS n
  FROM image_assets ia
  JOIN source_images si ON si.id = ia.source_image_id
 WHERE si.target_eurio_id LIKE '%-2eur-%'
 GROUP BY resolution_status ORDER BY n DESC;

-- Échantillon des auto_dino_text pour audit manuel (20)
SELECT ia.id, ia.eurio_id, ia.resolution_confidence,
       si.listing_title, si.target_eurio_id
  FROM image_assets ia
  JOIN source_images si ON si.id = ia.source_image_id
 WHERE ia.resolution_status = 'auto_dino_text'
 ORDER BY RANDOM() LIMIT 20;
```

**Cible attendue** (à confirmer post-calibration) :
- ~30-40 % auto-accept yield si la calibration permet precision ≥ 99 %
  (estimation optimiste : 88 % convergent texte × 34 % R@1 country
  Dino × marge spread/sim ≈ 30 % yield brut).
- ~60-70 % restent en `needs_review` (ce qui est bien — V1 conservatif).

Si yield < 10 % → seuils trop stricts ou règle inadaptée, on
rediscute. Si precision < 99 % sur l'échantillon manuel des 20 →
on remonte δ_min/σ_min.

## Cas border à acter avant code

1. **Target_eurio_id absent sur source_images** (ne devrait quasi pas
   arriver, mais arrive sur mocks) → pas d'auto-accept (rien à
   confirmer).
2. **Dino prediction absente** (encoder out-of-scope ou bank manquante
   au moment du backfill) → pas d'auto-accept, fallback silencieux.
3. **Texte verdict NULL** (target absent de `coins`) → pas
   d'auto-accept (cf. chunk 6.a comportement existant).
4. **Dino top1_country_eurio_id correct mais top1_country_sim très
   bas** (ex. 0.5) → bloqué par σ_min. Bon.
5. **Dino top1_country_eurio_id == target mais
   top1_eurio_id (global) != target** (= un autre pays a une sim plus
   forte qu'AD pour ce crop AD) — la règle utilise la bande country,
   donc ça passe. C'est intentionnel (mesure chunk 3.5). À valider
   en audit visuel.

## Plan d'attaque suggéré (par chunks audit-par-chunk)

1. **8.a** Script de calibration en mémoire seul, lance sur 524
   crops, output CSV + console. **Audit obligatoire** avec Raphaël.
   30-60 min.
2. **STOP. Audit. Go/no-go.**
3. **8.b** Step pipeline + tests. 1.5-2h. Audit unit tests + intégration.
4. **STOP. Audit visuel.**
5. **8.c** Backfill réel sur 524 crops + audit DB + échantillon manuel
   20. 30 min.
6. **STOP. Audit visuel manuel.**
7. **8.d** Front (filtre review queue + badge si page Coin existe).
   30-60 min.

## Hors-scope rappels

- ❌ Pas de modification du Dino — encoder reste fixe.
- ❌ Pas d'auto-accept sur autre chose que 2€ commémo (P4).
- ❌ Pas de spot-check / monitoring (chunk 10).
- ❌ Pas de bouton "rollback" admin (chunk 9).
- ❌ Pas d'utilisation des `theme_tokens` (extracteur V1 ne pose
  pas de comparaison thème — V2 si besoin).

## Mémoires liées

- `feedback_dino_thresholds` — sims tassées euros, percentile-relatif
- `feedback_chunk_audit_flow` — chunks 30min-3h, livrer + attendre
- `feedback_no_debt` — pas de shortcut, on durcit la règle si
  precision < 99 %
- `project_arcface_design_group_label` — labels = design_group au
  niveau training, mais auto-validate écrit `eurio_id` (cohérent avec
  vision §"Glossaire")

## Snippets utiles à coller en début de session

```bash
# Distribution actuelle des verdicts texte sur les crops 2€ commémo
sqlite3 ml/state/training.db "
  SELECT lts.vs_target_verdict, COUNT(*) AS n
    FROM listing_text_signals lts
    JOIN source_images si ON si.id = lts.source_image_id
    JOIN image_assets ia ON ia.source_image_id = si.id
   WHERE si.target_eurio_id LIKE '%-2eur-%'
     AND ia.resolution_status = 'needs_review'
   GROUP BY lts.vs_target_verdict ORDER BY n DESC;"

# Distribution Dino R@1 country
sqlite3 ml/state/training.db "
  SELECT
    SUM(CASE WHEN p.top1_country_eurio_id = si.target_eurio_id
             THEN 1 ELSE 0 END) AS r1_country,
    COUNT(*) AS total
  FROM image_asset_dino_predictions p
  JOIN image_assets ia ON ia.id = p.asset_id
  JOIN source_images si ON si.id = ia.source_image_id
  WHERE si.target_eurio_id IS NOT NULL;"

# Crops triplement éligibles (texte convergent + Dino top1_country == target + non-lot)
sqlite3 ml/state/training.db "
  SELECT COUNT(*) AS n_eligible
    FROM image_assets ia
    JOIN source_images si ON si.id = ia.source_image_id
    JOIN listing_text_signals lts ON lts.source_image_id = si.id
    JOIN image_asset_dino_predictions p ON p.asset_id = ia.id
   WHERE ia.resolution_status = 'needs_review'
     AND lts.vs_target_verdict = 'convergent'
     AND lts.is_lot = 0
     AND p.top1_country_eurio_id = si.target_eurio_id;"
```

Le résultat de la 3e query donne la **borne sup absolue de yield**
avant même d'appliquer δ_min/σ_min. Premier sanity check à lancer en
ouverture de session.
