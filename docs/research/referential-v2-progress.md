# Référentiel V2 — Progress tracker (handoff)

> État au 2026-05-15 (post-3f). Sert à reprendre la migration référentiel V2
> dans une session future. Le doc canonique est `referential-v2.md` ; ici on
> suit ce qui a été fait et ce qui reste.

---

## 1. Contexte en 30 secondes

Migration du référentiel Eurio V1 (table `coins` mono-niveau) vers V2 à
trois niveaux **TYPE / VARIANT / MINT_RELEASE** + table `coin_source_refs`
pour l'ingestion multi-source (Numista, MdP, BCE, LMDLP, Wikipedia…).

Le déclencheur métier : permettre au scrape eBay de couvrir toutes les
pièces 2€ existantes côté Numista, dont 99 nouveaux Types qu'on a ajoutés
en 3a + 37 mismatchs sémantiques qu'on a corrigés en 3b.

Décisions architecturales actées (D1–D8) : voir `referential-v2.md` §7.

---

## 2. Plan de migration — où on en est

| Chunk | Sous-phase                                              | Statut       | Livrable                                                                  |
| ----- | ------------------------------------------------------- | ------------ | ------------------------------------------------------------------------- |
| 0     | Doc de design                                           | ✅ livré     | `docs/research/referential-v2.md`                                         |
| 1     | Audit JSON exhaustif (684 entrées 2€ classifiées)        | ✅ livré     | `ml/datasets/audit_referential_v2.json`                                   |
| 2a    | Inspection schéma Supabase actuel                        | ✅ livré     | —                                                                          |
| 2b    | Migration SQL referential V2                             | ✅ appliquée | `supabase/migrations/20260515_referential_v2.sql`                          |
| 2c    | Script Python `migrate_to_v2.py`                         | ✅ livré     | `ml/referential/migrate_to_v2.py` + `go-task ml:migrate-v2[-dry]`         |
| 2d    | Apply + verify (4158 source_refs)                        | ✅ appliquée | —                                                                          |
| **3a**| CREATE_NEW_TYPE × 89 + 5 design_groups joint-issues      | ✅ appliquée | `ml/referential/apply_3a_new_types.py` + `go-task ml:apply-3a[-dry]`     |
| **3b**| REMATCH × 37 + unresolved × 21 (needs_review=true)       | ✅ appliquée | `ml/referential/apply_3b_rematch.py` + `go-task ml:apply-3b[-dry]`       |
| **3c**| MOVE_TO_VARIANT × 15 + UNCERTAIN absorbed × 2 (3 buckets) | ✅ appliquée | `ml/referential/apply_3c_move_to_variant.py` + `go-task ml:apply-3c[-dry]` |
| **3d**| ADD_AS_VARIANT × 25 (4 buckets : A/B1/B2/B3)              | ✅ appliquée | `ml/referential/apply_3d_add_as_variant.py` + `go-task ml:apply-3d[-dry]` |
| **3e**| REVIEW QUEUE infra × 32 cas (script + table + API + UI)  | ✅ livré     | `apply_3e_flag_uncertain.py` + `apply_3e_enrich_context.py` + migration `20260516_coins_review_context.sql` + `ml/review/coins_review_routes.py` + UI `admin/.../CoinsNeedsReviewPage.vue` |
| **3f**| Standards orphans × 15 (1st/2nd map, MT/VA portraits)    | ✅ appliquée | `ml/referential/apply_3f_standards.py` + `go-task ml:apply-3f[-dry]`     |
| 4     | **Refetch Numista propre (greenfield 2€)**               | ❌ todo      | Voir `docs/research/numista-clean-refetch-kickoff.md` — annule l'ancien Phase 4 « nouveautés 2025/2026 ». Couvre wipe full 2€ + slug deterministe + prices via /issues/{id}/prices + multi-key quota rotation |
| 5     | Multi-source ingestion (MdP/LMDLP/BCE → Type Candidates) | ❌ todo      | Refactor scrapers + dedup service                                         |
| 6     | Adaptations UI needs-review post-refetch propre          | ❌ todo      | Voir kickoff Phase 6 — ajustements ~100 lignes attendus                   |

---

## 3. État actuel de la base (au 2026-05-15)

| Table                | Rows | Notes                                                                   |
| -------------------- | ---: | ----------------------------------------------------------------------- |
| `coins`              | 2736 | 2628 V1 + 89 commémos (3a) + 4 nouveaux parents (3d B2/B3) + 15 standards (3f). Niveau **TYPE** du modèle V2. |
| `coin_variants`      |   40 | 15 (3c) + 25 (3d). Distribution : 18 coloured / 9 classic / 9 hologram / 2 pattern / 2 mule / 1 other. |
| `coin_mint_releases` |    0 | Vide. Sera peuplée plus tard (Phase 5+ ?).                              |
| `coin_source_refs`   | 4274 | 4259 (post-3d) + 15 (3f : 1 par nouveau standard).                      |
| `design_groups`      |  +5  | Bootstrap des 5 joint-issues `eu-{theme}-{year}` en 3a.                 |
| `coins.needs_review` |   25 | 21 commemos 2€ flaggées en 3b (rematch failed) + 4 nouveaux parents 3d (3 NL B2 + 1 LU B3 Guillaume II). 3f : 0 nouveau (standards = clean cases). |

Commémos 2€ : 466 (V1) → **555** (post-3a) avec leur numista_id à jour
(post-3b). 21 ont `numista_id=null` + `needs_review=true`.

---

## 4. Fichiers clés à lire avant de reprendre

| Fichier                                                              | Rôle                                          |
| -------------------------------------------------------------------- | --------------------------------------------- |
| `docs/research/referential-v2.md`                                    | Design canonique, schéma SQL, décisions D1–D8 |
| `ml/datasets/audit_referential_v2.json`                              | Audit source de vérité pour 3c/3d/3e/3f       |
| `ml/referential/audit_apply_common.py`                               | Helpers : cross-match, joint-issue, eurio_id slug, overlap |
| `ml/referential/apply_3a_new_types.py`                               | Template pour 3c/3d/3e (même structure)       |
| `ml/referential/apply_3b_rematch.py`                                 | Template PATCH/DELETE coins + coin_source_refs |
| `supabase/migrations/20260515_referential_v2.sql`                    | Schéma physique des 3 nouvelles tables        |
| `supabase/types/database.ts`                                         | Types TS — à régénérer après 3c/3d via `mcp__supabase__generate_typescript_types` |

---

## 5. Détails techniques à connaître

### 5.1 Cross-matching (helper)

`audit_apply_common.cross_match_wrong_and_new_types(records)` produit :
- `rematches: {eurio_id: new_nid}`            ← 47 cas (37 WRONG + 8 BUT_VARIANT + 2 UNCERTAIN)
- `unresolved_wrong: [eurio_id]`              ← 21 cas
- `create_as_new_types: [audit_record]`       ← 89 commemos + 15 standards (3f)
- `by_source_class: {eurio_id: classification}`
- `old_nids: {eurio_id: old_nid}`
- `rematch_details: {eurio_id: {"old": catalog_name, "new": catalog_name}}`

Le scoring utilise `inter / |cat_tokens|` avec stopwords étendus
(`day`, `year`, `anniversary`, `euro`, `european`, `union`, etc.).
Seuils : 0.4 pour WRONG, 0.5 pour BUT_VARIANT/UNCERTAIN. Marge 0.15
entre best et second.

### 5.2 Pattern PATCH / DELETE via SupabaseClient

Ajouté en 3b : `sb.patch(table, filters={...}, payload={...})` et
`sb.delete(table, filters={...})`. Usage type :

```python
sb.patch(
    "coins",
    filters={"eurio_id": f"eq.{eid}"},
    payload={"cross_refs": {"numista_id": int(nid)}, "last_updated": today},
)
sb.delete(
    "coin_source_refs",
    filters={
        "coin_type_id": f"eq.{eid}",
        "source": "eq.numista",
        "native_id": f"eq.{old_nid}",
    },
)
```

### 5.3 Convention variants

Slug `{parent_eurio_id}/{finish}` (avec `-{seq}` si collision).
Finish ∈ `classic | coloured | hologram | gilded | pattern | mule |
misstrike | other` (cf. CHECK constraint dans la migration SQL).

`coin_variants.notes` est l'escape hatch (justifier `finish='other'`,
détails Numista).

### 5.4 Multi-référentiel additif (D2)

`coin_source_refs` est le pivot pour les sources externes. PK technique
`bigserial`, UNIQUE composite `(coin_type_id, source, native_id)`. Une
même `native_id` peut couvrir plusieurs `coin_type_id` (cas Wikipedia
page-pays = N coins).

---

## 5.5 Re-fetch contract (durci en 3f, 2026-05-15)

Quand on re-call l'API Numista (Phase 4 ou plus tard pour catch-up des
nouveautés), on doit pouvoir reproduire exactement le même mapping
`numista_id → eurio_id` qu'on a aujourd'hui en DB. Sinon les imports
déterministes deviennent flaky → orphans → workflow cassé.

La règle est à **deux étages** :

### Tier 1 — BINDING (autoritaire, immutable)

```
Pour chaque numista_id du payload re-fetché :
  1. SELECT coin_type_id FROM coin_source_refs
       WHERE source = 'numista' AND native_id = $nid
  2. Si trouvé → c'est CE coin_type_id. On update les métadonnées
                  (theme, design_description, last_updated…) mais
                  ON NE TOUCHE JAMAIS au slug eurio_id.
  3. Si non trouvé → nouveau nid, passer à Tier 2.
```

Conséquence : un `eurio_id` est gelé à la création. Si Numista renomme
le `catalog_name` plus tard, on update les métadonnées mais l'eurio_id
reste celui d'origine. Le binding survit aux renames.

### Tier 2 — SLUG GENERATION (fonction pure du payload API)

Pour les nids inconnus, le slug DOIT être dérivable du payload API
**uniquement** — pas de domain knowledge externe, pas de "je sais que
VA 2017 = 2nd map", pas d'invention. Sinon le re-fetch produit un slug
différent du tien et tu te retrouves avec deux eurio_ids pour la même
pièce.

Les fonctions concernées :
- `apply_3f_standards.standard_slug(catalog_name)` pour les standards
- `audit_apply_common.eurio_id_from_catalog(...)` pour les commémos

### Manual overrides (escape hatch)

Quand on a une source autoritaire externe (BCE, Wikipedia, MdP…) qui
enrichit le slug au-delà de ce que Numista expose, on peut ajouter un
override **keyé sur numista_id** dans `MANUAL_NID_SLUG_OVERRIDES` du
script concerné. Le keying par nid garantit la déterminisme au re-fetch.

Toujours citer la source dans le commentaire au-dessus de l'override.
Vide pour 3f (aucun override nécessaire — VA Francis 2014/2017 partagent
le slug `francis`, l'année désambigue, on est honnêtes sur l'absence
d'info map dans Numista).

### Tiebreaker pour collisions inter-batch

Si deux nids différents produisent le même `(country, year, slug)`,
il faut un tiebreaker. Convention : suffix `-{numista_id}` + flag
`needs_review=true`. À implémenter quand un cas réel apparaît (aucun
en 3f, à surveiller en Phase 4).

---

## 6. Choses ouvertes à décider quand on reprend

1. **3c — décisions actées 2026-05-15 (3c.0)** :
   - **D-3c-1** Bucket A (BUT_VARIANT absorbé) → switch `cross_refs.numista_id`
     vers le classic_nid. Bucket B (non-absorbé) → garder le variant_nid
     en place. Bucket C (UNCERTAIN absorbé) → switch vers rematch_nid.
   - **D-3c-2** Le variant_nid Numista vit comme 2e `coin_source_refs` row
     sous le même `coin_type_id` (option a — additif sans schema change).
     Le lien variant_nid ↔ slug variant est tracé dans `coin_variants.notes`
     (`Numista nid={nid} — {catalog_name}`).
   - **D-3c-3** Bucket B vérifié via SELECT live : les 7 cas ont bien V1.cross_refs
     == audit variant_nid. Pas de drift. Cohérent avec la reco "garder variant_nid".

2. **3d — décisions actées 2026-05-15 (3d.0)** :
   - **D-3d-1** Si finish='classic' et parent.cross_refs pointe ailleurs,
     bascule vers le classic_nid (4 cas appliqués : Prince Charles, Chamber
     of Deputies, Admission Henri, Feierstëppler).
   - **D-3d-2** Pour les vrais ORPHAN_VARIANT sans parent classic Numista
     (3 NL collector coloured-only) : création de parent abstrait avec
     needs_review=true.
   - **D-3d-3** `variant_label='color-variant'` → finish=`other` + notes
     `[variant_label=color-variant]` (escape hatch documenté).
   - **D-3d-4** Source_refs : 1 row par (parent, source, native_id), même
     granularité qu'en 3c (variant_nid co-localisé sous le parent Type).
   - **Découverte non prévue** : audit's `likely_parent_eurio_id` avait des
     erreurs (4 DRIFT cases corrigés via re-matching `overlap_score` +
     1 cas LU Guillaume II nécessitant manual override → bucket B3).
     `audit_apply_common.cross_match_wrong_and_new_types` n'est pas utilisé
     pour 3d ; à la place, re-match local contre tous les coins du même
     `(country, year, is_commemorative)` bucket.

3. **3e (review queue)** — ✅ infra livrée 2026-05-16 :
   - `apply_3e_flag_uncertain.py` a flaggé les 7 IN_REF_UNCERTAIN non-absorbés
     → 32 coins needs_review=true (21 du 3b + 4 du 3d B2/B3 + 7 du 3e.1).
   - Migration `20260516_coins_review_context.sql` ajoute `coins.review_action_hint TEXT`
     (CHECK: rebind|verify_parent|confirm_or_rematch_uncertain) + `coins.review_payload JSONB`
     + index partiels.
   - `apply_3e_enrich_context.py` a backfillé ces 2 colonnes pour les 32 cas
     (distribution : 21 rebind / 4 verify_parent / 7 confirm_or_rematch_uncertain).
   - `ml/review/coins_review_routes.py` expose 5 endpoints `/coins-review/*` :
     `GET /queue`, `GET /search-numista` (local catalog + Numista live API
     fallback avec ASCII fold), `POST /{eid}/rebind`, `POST /{eid}/no-coverage`,
     `POST /{eid}/delete-redirect`.
   - UI Vue `/coins/needs-review` dans `admin/packages/web/src/features/coins/`
     avec composable `useCoinsReview.ts`. 2-pane, panneaux adaptés au hint,
     keyboard `j/k 1-9 c r n d`. Tokens.css canonical.
   - **Résolution des 32 cas reportée** : voir
     `docs/research/numista-clean-refetch-kickoff.md`. L'analyse pendant la
     session 3e a montré que la plupart des cas viennent d'un script V1
     bancal de génération d'eurio_id. Plutôt que de patcher 32 cas, on repart
     d'un refetch Numista propre (greenfield 2€). Ces 32 coins seront wipés
     dans Phase 1 du kickoff (chunk dédié, confirmation utilisateur requise).

4. **3f — décisions actées 2026-05-15 (3f.0)** :
   - **D-3f-1** Approche = nouveaux TYPE entries (Option A, comme 3a
     mais pour standards non-commémos). Pas de variants ni mint_releases
     (mauvais fit pour les redesigns de portrait/carte).
   - **D-3f-2** eurio_id format `{country}-{year}-2eur-standard-{slug}`
     avec slug **toujours descriptif** (consistance interne 3f).
     Algorithme `standard_slug()` dans `apply_3f_standards.py` — pure
     function du `catalog_name` Numista, fallback `1st-type` si vide.
   - **D-3f-3** `theme` + `design_description` extraits du catalog_name
     (lisibles humainement).
   - **D-3f-4** `is_commemorative=false`, `needs_review=false`. Standards
     = clean cases, Numista fait autorité sur le design.
   - **D-3f-5** `coin_variants` / `coin_mint_releases` non touchés.
     `series_id` (grouping ères de design) reporté à une session future.
   - **Re-fetch contract durci** : voir §5.5 (deux étages binding +
     slug generation, plus stub `MANUAL_NID_SLUG_OVERRIDES`). Garantit
     que les 15 eurio_ids sont reproductibles à partir de l'API Numista
     seule, sans connaissance externe.

5. **post-3** : Phase 4 (refetch Numista pour 2025/2026 nouveautés).
   Quota Numista mai 2026 : 0/1800 calls, frais. Budget estimé : ~100
   calls pour catch-up. **Doit respecter le contract §5.5**.

---

## 7. Memory persistance

Décisions sauvées dans :
- `~/.claude/projects/.../memory/project_referential_v2_design.md`
  (les 8 décisions D1–D8)
- `~/.claude/projects/.../memory/MEMORY.md` (index)

Ces mémoires sont chargées automatiquement par Claude Code dans le
projet. Pas besoin de les répéter dans le prompt.
