# Kickoff — Pipeline référentiel apply-fix (prochaine session)

> Doc de reprise froide. Lecture en 3 min pour redémarrer là où on s'est
> arrêté le 2026-05-25.

## Où on en est

**Chantier** : résoudre 9 cas de mauvais liens `coins ↔ numista_id`
identifiés par `scripts.audit_referential`. Cause racine : bootstrap
initial qui a créé 1 row par (country, year) au lieu de N quand il y a
plusieurs commémo 2 € pour ce couple.

**Déjà livré (session du 2026-05-25)** :
- Investigation cas LV 2018 Zemgale → diagnostic + fix manuel reverté
- Doc roadmap : `docs/operations/referential-fixes-pipeline.md`
- Script discovery : `ml/scripts/discover_referential_fixes.py`
- Output discovery : `ml/state/referential_fix_proposals.json`
  - 9 cas tous en **Shape B** (swap + new row)
  - 7 high confidence, 2 medium
  - 5 cas déclenchent un `design_group` joint (4 existent, 1 à créer)
- Endpoints exploratoires : `/referential/zero-canon`, `/referential/divergences` + pages admin

**État DB après revert** : eurio.db intacte, 13 count_mismatch + 9 catalog_unlinked + 4 numista_orphan (les 4 cas 2026 hors scope).

## Ce qu'on attaque cette session

### Chunk 2 ✅ livré (session 2026-05-25 suite) — Apply endpoint backend (cascade 8 étapes)

`POST /referential/fix-proposals/{case_id}/apply` → cascade en
`ml/api/referential_fix_apply.py`. Smoke-test preflight ok sur
``lv-2018-100th-anniversary-of-the-baltic-states``.

Cascade :
1. Pre-flight checks (case_id existe dans `referential_fix_proposals.json`, état DB compatible)
2. Backup `eurio.db` → `state/eurio.db.bak-fix-{case_id}-{ts}`
3. Mutations eurio.db en transaction :
   - INSERT new row `coins`
   - UPDATE existing row (swap numista_id, rebuild raw_payload_json)
   - INSERT/UPDATE design_group si applicable
4. Move FS sidecars BCE selon `source_attributions` (si target='new')
5. Fetch image Numista pour les rows ayant un nouveau numista_id (existing post-swap + new row)
   - Appel Numista API `/types/{id}/source`, écrit dans `ml/canonical_images/{eurio_id}/obverse_numista.webp`
   - INSERT `coin_canonical_images` (source='numista', role='obverse')
6. Push Supabase Storage : upload nouveaux fichiers + DELETE paths orphelins
7. Push Supabase coins/observations via `sync_to_supabase` (filtré aux 2 eurio_ids)
8. Vérif : re-run audit + divergences, retourner les diffs

Retour de l'endpoint : objet avec `success`, `steps: [...]` (chaque étape avec status + diagnostic), `audit_after`, lien vers le backup.

**Pré-requis** ✅ livrés (session 2026-05-25 suite) :
- `GET /referential/fix-proposals` — liste résumée (case_id, shape, confidence, swap, new_row eurio_id)
- `GET /referential/fix-proposals/{case_id}` — détail brut (swap, new_row, source_attributions, warnings, reasoning)
- `POST /referential/fix-proposals/refresh` — re-run `scripts.discover_referential_fixes`, renvoie méta

### Chunk 3 ✅ livré (session 2026-05-25 suite) — Page admin `/referential/fixes`

Layout : liste à gauche (9 cas, badges shape/confidence), panneau détail à droite avec :
- Section "Swap" : existing eurio_id, sa current vs new numista_id, similarités, titres Numista
- Section "New row" : preview du eurio_id auto-généré, theme, design_description, lien design_group si applicable
- Section "Images avant/après" : 4 images côte à côte (existing row avant/après, new row prévisualisée si possible)
- Section "Source attributions" : pour chaque BCE/LMDLP, où ça va aller avec score
- Bouton **Apply this fix** (rouge, confirmation)
- Bouton "Refresh discovery" en haut

### Chunk 4 — Test pilote LV 2018

Pipeline complet sur le cas Zemgale. Vérif visuelle :
- `/coins/lv-2018-2eur-zemgale` affiche bien l'image Zemgale (depuis Numista 143883 fetched)
- `/coins/lv-2018-2eur-100th-anniversary-of-the-baltic-states` existe et affiche l'image BCE Baltic States
- `audit_referential` : LV 2018 disparaît de count_mismatch
- `/referential/divergences` : zemgale clean, baltic-states soft légitime

Si KO → diagnostic + fix backend. Si OK → enchaîner les 8 autres cas.

## Décisions actées (ne pas re-questionner)

| | |
|---|---|
| Image fetch | Numista API directe, idempotent (skip si déjà fetched) |
| Slug generation | Auto depuis titre Numista (`slugify()` dans discovery) |
| Workflow apply | UI admin one-by-one, pas de bulk auto |
| Backup avant chaque fix | Oui, `state/eurio.db.bak-fix-{case_id}-{ts}` |
| Storage cleanup orphan | Oui, DELETE explicite au step 6 |
| Atomicité push fail | Pas de revert eurio.db. Steps 1-6 restent appliqués, réponse contient `push_failed`, opérateur relance `POST /referential/push` séparément (acté 2026-05-25) |
| Design_groups | Apply ne touche **rien** aux design_groups. Rattachement 100% manuel post-apply via UI existante (acté 2026-05-25) |

## Suspens à trancher quand on touchera la cascade

1. **Idempotence du fetch Numista** : si l'image existe déjà sur disque ET en DB, skip. Si elle existe sur disque mais pas en DB, re-INSERT seulement. Cas tordu : fichier existe mais corrompu.
2. **2 numista_ids same (country, year)** : et s'il y a un 3ème non détecté ? L'audit ne le verrait pas. Tests à faire post-apply : re-run audit sur les 9 cas pour vérifier zero régression.

## Commandes utiles pour reprendre

```bash
# Voir l'état actuel
cd ml && python -m scripts.audit_referential | head -40

# Re-run discovery
python -m scripts.discover_referential_fixes -v

# Voir les propositions JSON
cat ml/state/referential_fix_proposals.json | jq '.proposals[0]'

# Voir une row coin précise
sqlite3 ml/state/eurio.db "SELECT * FROM coins WHERE eurio_id='lv-2018-2eur-zemgale';"

# Voir le contenu BCE sidecar
cat ml/canonical_images/lv-2018-2eur-zemgale/obverse_bce.json | jq

# API FastAPI live (uvicorn reload sur ml/api/server.py port 8042)
curl http://localhost:8042/referential/divergences | jq '.n_hard, .n_soft'
```

## Backups disponibles

- `ml/state/eurio.db.bak-prebalticfix-20260525-144049` — pré-fix LV 2018 (état "stable" actuel)
- Autres backups antérieurs dans `ml/state/eurio.db.bak-*`

## Liens

- Doc roadmap : `docs/operations/referential-fixes-pipeline.md`
- Audit script : `ml/scripts/audit_referential.py`
- Discovery script : `ml/scripts/discover_referential_fixes.py`
- Push existant : `ml/scripts/push_to_supabase.py`
- Endpoints admin référentiel : `ml/api/referential_routes.py`
- Page admin : `admin/packages/web/src/features/referential/pages/ReferentialPage.vue` + `DivergencesPage.vue`
