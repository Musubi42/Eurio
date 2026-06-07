# Work in progress — chantiers à reprendre et clore

> Chantiers démarrés selon le workflow « doc d'abord, puis implémentation »,
> mais **pas encore 100 % finis** (arrêtés en cours, évolués, ou idées en suspens).
>
> Delta **doc ↔ code mesuré via graphify le 2026-06-07** (graphe de la codebase).
> Le `%` reflète ce que le code montre réellement, pas ce que la doc prétend.
>
> **Boucle cible** : reprendre → finir le reste listé ci-dessous → déplacer le dossier vers `docs/archive/`.

| Chantier | % réel | En une phrase |
|---|---|---|
| [coin-richness](./coin-richness/) | ~85 % | presque fini, reste run eBay sur cohorte + scale 524 |
| [data-harmonization](./data-harmonization/) | ~85 % | tout livré sauf le Chunk 5 (migration identité) |
| [design-groups-standards](./design-groups-standards/) | ~80 % | pilote BE live, reste le rollout autres pays |
| [crop-forensics](./crop-forensics/) | ~55 % | sujet actif, reste l'auto-rejet (S7) |
| [cohort-pipeline](./cohort-pipeline/) | ~40 % | rebuild cockpit pas commencé, design seulement |

---

## coin-richness — ~85 % ✅ presque fini
Toute la prep (P.*) et V.1-V.2 livrées (9 tables en base, scripts présents, page CoinDetail live).
**Reste :**
- **V.3** : run eBay discovery + `price_aggregate` sur la cohorte 19 (pipeline existe, juste pas lancé)
- **V.4** : tour visuel des 19 pages coin + décision GO/NO-GO sur le scale 524
- **Phase F** : scale à 524 coins (`refetch_numista_2eur.py --all-eurozone`, ~2000 calls Numista, multi-session)
- Archiver 4 scripts legacy de la queue P.9 · 8 fichiers Vue lisent encore Supabase (non bloquant)
- ⚠️ source `wikipedia` *seedée* dans `source_registry` mais **aucun adapter** `ml/sources/wikipedia/` (à construire — cf. branche `sources-jo-wikipedia`)

## data-harmonization — ~85 %
⚠️ **`architecture.md` = design canonique verrouillé** : le consulter même en cours, ne pas le périmer.
Chunks 0-4 livrés (eurio.db, schema canonique, table `eurio_id_migrations` présente).
**Reste (Chunk 5, non démarré) :**
- Écrire le driver de migration d'identité : journal `eurio_id_migrations` → propager les renames vers `image_assets`, `cohort_members`, bench gold
- Re-pin du bench gold après tout rename d'`eurio_id` · replay du gold BE 2017 (~28 entrées `needs_rematch`)
- Re-juger 17 gold / 13 labels 2017 dans le studio bench · i18n des 147 coins générés
- Supprimer `ml/scripts/batch_match_numista.py` · virer `training.db` fantôme (coexiste avec eurio.db)

## design-groups-standards — ~80 %
Doc **fidèle au code** : modèle FK scalaire `coins.design_group_id` (`schema.sql:935`, `ON DELETE SET NULL`),
tooling `ml/bootstrap/obverse_groups.py` + `apply_plan` + tests live. Pilote BE (chunks 1-5) livré.
**Reste :**
- **Chunk 6** : rollout aux autres pays (généraliser `obverse_groups.py` au-delà de BE — apply/audit par pays)
- Gate parseur derive-then-diff avant tout rollout large (§4.6, pas encore en code)
- Validation vision LLM a posteriori par pays (§4.7, différée)

## crop-forensics — ~55 % (sujet actif)
S1-S6 livrés/réfutés (composite score dans `bench_routes.py`, sort buttons, scripts `ml/scripts/crop_exp/`).
**Reste :**
- **S7** : implémenter `auto_reject_reason` (2 seuils : `composite<0.2 + bg_uniformity` / `area_ratio<0.05 + inner_feature_score`) côté backend — aucun commit
- **S8** (optionnel) : promouvoir `score_v2` comme sort par défaut (v1 déjà livré)
- **S9** (pausé) : seuil `area_ratio` adaptatif par catégorie de raw

## cohort-pipeline — ~40 % (rebuild pas commencé)
Tables `cohort_jobs` / `image_state_events` existent en base + `store.py`, endpoint `recrop-zero` live,
mais le rebuild cockpit décrit dans `REBUILD-HANDOFF` **n'a pas démarré** (design pur, UI rejetée par le PO).
**Reste :**
- Audit réel du cycle de vie image en base (reproduire les bugs B1-B4) **avant tout patch**
- Modèle d'état SQLite explicite (la table existe mais n'alimente pas les transitions cockpit)
- Redesign UX cockpit (skill frontend-design : flow en tête, ligne-exemple, hiérarchie des boutons)
- Fixes : B1 (attribution be-2007=0, theme-matcher trop large) · B2 (recrop-zero → 0 crop, observabilité) · B3 (sémantique lanes manual/auto/ccproxy) · B4 (compteurs/boutons illisibles) · B5 (légende/flow absent)
- Valider WS5 (mini-bench ccproxy, commit `66b44ea`) côté PO · câbler en prod le détecteur census `nms_only`
