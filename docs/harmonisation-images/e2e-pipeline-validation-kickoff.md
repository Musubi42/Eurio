# E2E pipeline validation — kickoff (handover)

> Destiné à la prochaine session Claude Code. Self-contained : contexte,
> objectifs, plan d'attaque, références. Rédigé 2026-05-18 post
> commit `12843bd` (MinIO MCP installé + SS-3+SS-4 validés).

---

## 1. Mission

Valider de bout en bout la pipeline **scrape eBay → filtres → review → save** :

1. **Filtres** : comprendre quels filtres tournent sur quels signaux,
   les voir appliqués dans une UI debug, savoir lire les rejets.
2. **Review queue** : les items rescapés des filtres apparaissent bien
   dans `admin /review` avec les bonnes métadonnées (image, prix,
   coin cible, top-K suggestions Dino, etc.).
3. **Decide + save** : appliquer une décision (manual eurio_id, lot
   split, reject) → écrit ce qu'il faut dans Supabase / MinIO et
   ferme la ligne `review_queue` proprement.

Cible : un parcours de bout en bout réussi sur un mini batch eBay
(2-3 pièces ciblées) où on peut tracer chaque artefact à chaque
étape.

## 2. État au démarrage

| Élément | État | Note |
|---|---|---|
| Write-through MinIO | **✅ live** | SS-1+SS-2 (commit `b8977b9`), SS-3+SS-4 validés (commit `ba136d8`). Run `e2e58d8` a produit 9 crops dans `enrichment-crops/ebay/`. |
| MinIO MCP | **✅ installé** | `minio-eurio` server (commit `12843bd`). Read-only, tools `list_buckets/list_objects/head/get/...`. |
| .venv ml/ | **✅ propre** | Reconstruit avec `uv venv --system-site-packages`. `ultralytics` ajouté à `pyproject.toml`. `staleVenvCheckHook` dans `flake.nix` détecte les drifts. |
| .envrc | **✅ auto-active venv** | `source ml/.venv/bin/activate` ajouté → plus de désync `(.venv)` prompt ↔ PATH. |
| eBay quota | OK | Mais à respecter — `/sources/ebay/quota-status` avant chaque batch. |
| Référentiel coins | Post-refetch 2€ | 656 coins / 25 pays, voir `docs/research/numista-clean-refetch-progress.md`. |

## 3. Plan en 3 phases

### V-1 : filter visibility (~1h)

**Objectif** : voir et comprendre chaque filtre appliqué à un scrape.

Code à connaître (`ml/sources/ebay/` + `_base/steps/`) :

| Étape | Fichier | Que fait ce filtre |
|---|---|---|
| Discover | `ebay/queries.py` | `build_query()` : compose la requête eBay depuis `coins.country/year/theme`. `theme_tokens` = mots-clés cherchés dans le titre du listing. |
| Discover | `ebay/filters.py` | `accept_listing()` : prix > face, < extreme, currency EUR, pas "PROOF"/"argent". Year-in-title check pour commémos. |
| Discover | `ebay/filters.py` | `is_lot_suspected()` : flag "lot/coffret/série/rouleau/set" sur le titre → pas reject mais marqué. |
| Persist | `_base/steps/persist.py` | Dédup par `source_ref` (= `ebay_v1\|<itemId>\|<groupId>_img<N>`). |
| Text signal | `_base/steps/text_signal.py` | Vérifie cohérence titre eBay ↔ coin cible. Verdict `match` / `contradict` / `inconclusive` → si `contradict` la row est marquée `route_decision='rejected_text'` et **skip** au download. |
| Download | `_base/steps/download.py` | Pas un filtre — mais skip les rows `rejected_text`. |
| Detect/crop | `_base/steps/detect_crop.py` | YOLO + Hough → 0 crops = `crop_status='zero_crops'` (= rejet implicite, la row n'arrive pas dans la review). |

**Tâches V-1** :

- [ ] Lancer un scrape ciblé 1-2 coins (ex : `fr-2015-2eur-paix` +
      `de-2018-2eur-helmut-schmidt` — deux thèmes très distincts pour
      voir le filtre theme_tokens en action).
- [ ] Inspecter `/sources/ebay/runs/<id>/searches?eurio_id=...` et
      `/sources/ebay/runs/<id>/discarded?eurio_id=...` côté admin.
      Vérifier que l'UI montre pourquoi chaque listing a été drop.
- [ ] Si un filtre n'est pas visible dans l'UI → décider : (a) ajouter
      l'info aux endpoints `/runs/<id>/discarded`, ou (b) doc dans
      `ml/sources/ebay/README.md`.
- [ ] Via le MCP MinIO : confirmer que `n_raws_added` = nombre
      d'objects dans `enrichment-raws/ebay/<run_id>/` et idem pour
      `enrichment-crops`.

### V-2 : review queue (~30min)

**Objectif** : les rescapés de detect_crop arrivent dans la review
avec toutes les infos nécessaires.

- [ ] Ouvrir `admin /review` après le scrape V-1.
- [ ] Pour chaque item dans la queue, vérifier :
  - Image crop affichée (servie via `/sources/ebay/.../assets/.../file`
    qui passe par `local_path(enrichment-crops, key)` → lit MinIO).
  - Métadonnées listing : titre, prix, URL eBay, `is_lot_suspected`.
  - Top-K Dino suggestions (si `dino_predictions` ont tourné).
  - Verdict text_signal visible.
- [ ] Endpoint utilisé : `GET /review-queue?source=ebay&status=open`
      (cf. `ml/api/review_queue_routes.py:186`).
- [ ] Vérifier le compte : `n_review_enqueued` (sur le run) ==
      nombre de lignes `review_queue.status='open'` pour ce run.

### V-3 : decide + save (~1h)

**Objectif** : tester les 3 chemins de décision, vérifier les effets
en DB **et** dans MinIO.

| Action | Endpoint | Effet attendu DB | Effet attendu MinIO |
|---|---|---|---|
| Manual match (eurio_id correct) | `POST /review-queue/{id}/decide` body `{ eurio_id }` | `image_assets.resolution_status='manual', eurio_id=X`. `review_queue.status='resolved'`. | **À clarifier** — le crop reste-t-il dans `enrichment-crops` ou est-il promu vers `numista-canonical` ? Voir vision.md §"buckets". |
| Reject (mauvaise pièce / pas de pièce) | `POST /review-queue/{id}/reject` body `{ reason }` | `image_assets.resolution_status='rejected'`. `review_queue.status='rejected'`. | Crop reste en place ; cascade_sync décidera plus tard si on peut le delete. |
| Skip (à revoir plus tard) | `POST /review-queue/{id}/skip` | `review_queue.status='skipped'`. | Rien. |
| Lot split | `POST /review-queue/lots/{key}/decide` | Crée N rows `image_assets` filles, une par pièce. | Crops déjà présents (1 par image listing) — pas de nouveau push. |

**Tâches V-3** :

- [ ] Lister les 4 cas ci-dessus dans un mini script de test
      (ou via curl). Pour chacun :
  1. Capturer l'état DB avant.
  2. Capturer l'état MinIO avant (via MCP `list_objects`).
  3. Faire l'appel POST.
  4. Re-capturer DB + MinIO.
  5. Comparer aux attendus.
- [ ] Documenter dans `docs/harmonisation-images/vision.md` ce qui se
      passe (ou doit se passer) pour la promotion eurio_id → bucket
      canonical, si applicable.
- [ ] Si une promotion auto crop → numista-canonical est attendue
      mais pas implémentée : créer un ADR ou une issue.

## 4. Outils MCP disponibles

Le MCP `minio-eurio` (commit `12843bd`) expose en read-only :

```
list_buckets          → 3 buckets (numista-canonical, enrichment-raws, enrichment-crops)
list_objects          → liste objets par prefix (ex. ebay/<run_id>/)
head_object           → métadonnées (size, content-type, etag)
get_object            → télécharge bytes (utile pour comparer un crop à un listing eBay)
get_object_metadata   → tags + user-metadata
get_presigned_url     → URL signée 6h pour download HTTP
cluster_info          → bucket count, total objects
bucket_info           → policy + lifecycle
```

Pas de `--allow-write/delete/admin` dans la config docker. Pour des
opérations destructives, ré-ajouter le flag dans `.mcp.json`.

## 5. Critères de fin

- [ ] V-1 : doc écrite répondant à "Quels filtres tournent et où les voir"
- [ ] V-2 : screenshot admin /review avec une review complète + counts
      validés contre la DB
- [ ] V-3 : 4 décisions testées, état post-action vérifié en DB **et**
      MinIO, divergences documentées
- [ ] Si bug trouvé : commit qui fix ou ADR qui le tracke

## 6. Points de vigilance

- **eBay quota** : 5 000 appels/jour gratuit. Chaque scrape consomme
  `n_search` + `n_get_item`. Pour V-1, target 1-2 coins max.
- **Idempotence** : relancer un scrape sur les mêmes target_eurio_ids
  n'ajoute pas de raws (skip storage_status='present'). C'est OK pour
  itérer sur detect/review sans cramer du quota.
- **Two clients** : boto3 (côté Python, code Eurio) ↔ MinIO Go client
  (côté MCP). Si un test passe via boto3 mais pas via MCP, vérifier
  d'abord les credentials/endpoint.
- **Cache local read-through** : `~/.cache/eurio/` est peuplé par tout
  appel à `local_path()`. Pour tester "MinIO seul source de vérité",
  `rm -rf ~/.cache/eurio` avant un re-run.

## 7. Référentiel — où chercher quoi

| Question | Fichier / dir |
|---|---|
| Filtres eBay (titre, prix, theme) | `ml/sources/ebay/filters.py`, `queries.py` |
| Pipeline orchestrateur | `ml/sources/_base/orchestrator.py` |
| Text signal (titre ↔ coin) | `ml/sources/_base/steps/text_signal.py` |
| Crop detection + dispatch studio/listing | `ml/sources/_base/steps/detect_crop.py` + `ml/scan/normalize_snap.py` |
| Review endpoints | `ml/api/review_queue_routes.py` |
| Review UI | `admin/packages/web/src/features/review/` |
| MinIO write-through helpers | `ml/storage/local_cache.py`, `ml/sources/_base/storage.py` |
| Vision buckets (canonical vs enrichment) | `docs/harmonisation-images/vision.md` |
| Cascade DB ↔ MinIO sync | `docs/harmonisation-images/chunk-9-cascade-sync.md` |

## 8. Commit-history hooks

| Commit | Quoi |
|---|---|
| `b8977b9` | SS-0/1/2 — write-through scrape→MinIO live |
| `ba136d8` | SS-3+SS-4 — tests verts + ultralytics + env hardening |
| `12843bd` | MCP minio-eurio ajouté |

## 8.5 V-1 status au 2026-05-18 — done

V-1 a tourné sur `ad-2017-2eur-100-years-of-the-anthem-of-andorra` +
`ad-2019-2eur-2019-fis-alpine-ski-world-cup-final`. Deux bugs filtres
identifiés et fixés ; trois anomalies aval (A1/A2 cascade-résolues, A3/A4
ouvertes). **Run de référence pour V-2 : `5a166018a19c4e50b4cc383b4342f298`
— 70 reviews ouvertes sur ebay.** Détail complet : `v1-filters-fix-and-anomalies.md`.

## 9. Quick-start (à exécuter au début de la prochaine session)

```bash
# 1. Vérifier l'env
direnv allow   # si banner stale venv → go-task ml:venv-rebuild
python -c "import boto3; print(boto3.__version__)"

# 2. Vérifier que le serveur tourne (sinon le relancer)
curl -s http://localhost:8042/healthz || \
  (cd ml && nohup .venv/bin/python -m uvicorn api.server:app --port 8042 --reload > /tmp/eurio-uvicorn.log 2>&1 &)

# 3. Vérifier le MCP MinIO (depuis Claude Code)
# → demander : "Liste les buckets MinIO et combien d'objets dans chacun"

# 4. Démarrer V-1 — choisir 2 coins target
# → admin web : http://localhost:5173/sources/ebay
```

---

*Si quelque chose dans ce doc s'avère faux pendant la session,
**mettre à jour ce fichier en priorité** — il sera relu par les
sessions suivantes.*
