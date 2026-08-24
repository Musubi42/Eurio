# Chunk 02 — Réconciliation slugs + sync captures 17

> **But** : faire des captures device de `mix-zone-17` le hold-out des 17 classes,
> malgré le mismatch de slugs (pull device pris avant le renommage verbeux).

## Problème

Le pull device `app-android/debug_pull/20260429_214408/` nomme ses dossiers avec
les **anciens slugs** (pré-chantier D). Sur les 17 du CSV/catalogue :
- 5 matchaient exactement, 11 avaient un slug divergent, 1 absente du pull.

Le sync écrit `eval_real_norm/<dir-name>/` (clé = nom du dossier) et résout
`numista_id` via `coin_lookup`. Donc dossiers en anciens slugs → hold-out non
trouvé par `prepare_dataset` (qui cherche `eval_real_norm/<new_eurio_id>/`).

## Solution livrée

1. **Map ancien→nouveau slug** (16 coins, hand-vérifiée, même pays+année+denom,
   thème équivalent) → artefact auditable `slug-reconciliation.json`.
2. **Pull réconcilié** : symlinks `eurio_debug/eval_real/<new_eurio_id>` → dossiers
   raws originaux (non-destructif).
3. **Re-sync** `vision.sync_eval_real --also-write-captures --overwrite` → écrit
   `eval_real_norm/<new_eurio_id>/` (96/96 normalisés) + `datasets/<nid>/captures/`.

## 2ᵉ bug câblage trouvé : `coin_lookup` stale (corrigé)

`api/coin_lookup.py` lisait `ml/datasets/eurio_referential.json` (JSON legacy,
557/2628 mappings) → renvoyait `None` pour les 12 nouveaux slugs verbeux. D'où
l'API `captures/status` qui les affichait « missing » malgré les fichiers présents.
→ **fix** : `coin_lookup` lit `eurio.db` (`coins`, 689 mappings, colonne `theme`
conservée). Même migration SQLite-only que le resolver. `eurio_referential.json`
n'est plus lu par ce module.

## État final

- `captures/status` mix-zone-17 : **fully=16, partial=0, missing=1**.
- Seul manquant : **`fr-2018-...bleuet-de-france`** — absent du pull device, donc
  pas de hold-out. À capturer au téléphone avant le run PC (ou exclure du bench).
- ⚠️ Donnée à vérifier : numista_id de bleuet diverge — CSV `134283` vs eurio.db
  `134685`. Sans impact immédiat (pas de capture), mais à trancher au chunk catalogue.

## Fichiers / artefacts

- `docs/lab-streamline/slug-reconciliation.json` — la map (auditable).
- `ml/serving/coin_lookup.py` — migré sur eurio.db.
- `eval_real_norm/` + `datasets/<nid>/captures/` — peuplés pour les 16.

## Journal

- 2026-06-02 — map construite (16/16 validés), re-sync 96/96, coin_lookup migré,
  status lab = 16/17. Reste bleuet (capture device manquante).
