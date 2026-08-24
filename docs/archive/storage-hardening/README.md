# Stabilisation storage / lab — backlog

> Créé le 2026-06-30, après le fix du 403 transitoire MinIO qui bloquait
> readiness/bake/training sur le PC (cache froid). Commit du fix : `b26dcab2`
> (`fix(storage): retry-backoff borné sur local_path()`).
>
> Contexte run : `docs/work-in-progress/HANDOFF-pc-full-training.md` +
> `RUNBOOK-pc-training.md`. Archi storage : `docs/work-in-progress/model-b/README.md`.

## Ce qui a été fait (ne pas refaire)

- **Fix livré** : `ml/shared/storage/local_cache.py::local_path()` a désormais un
  retry-backoff borné `(0.2, 0.5, 1, 2, 4)s`. Ne retente QUE le transitoire
  (réseau, 5xx, **403**) ; un vrai 404/`NoSuchKey` part toujours direct vers
  `cascade.mark_missing_in_storage` sans retry. Aligné sur le pattern existant de
  `upload_through`. 45 tests storage verts, readiness HTTP 200 bout-en-bout.

## Vérif e2e du pipeline lab sur le PC (2026-06-30)

Chaîne de blocages découverte en déroulant create→bake→train via l'API sur le PC.
**4 corrigés + commités**, 1 ouvert (#5) :

| # | Blocage | État |
|---|---|---|
| 1 | `ModuleNotFoundError: jose` (venv périmée) | ✅ `go-task ml:setup` |
| 2 | MinIO 403 transitoire sur fetch crops (cache froid) | ✅ retry `local_path` (`b26dcab2`) |
| 3 | bake/train « Iteration not found » : `run_*.py` hardcodent `state/eurio.db` | ✅ `resolve_db_path` (`57532072`) |
| 4 | launch-training bloque sur membre design_group sans crops propres (be-2007) | ✅ validation par classe (`b1f8ffcf`) |
| 5 | `prepare_dataset` : « No source images found » | ❌ **OUVERT — décision data-flow** |

### #5 — `prepare_dataset` veut des images source canoniques en local (OUVERT)
Le bake stage correctement les augmentations (`datasets/iterations/<iid>/<class>/…__sample_NNN.jpg`
→ symlinks vers `datasets/<nid>/augmentations/<iid>/`). MAIS `pipeline._prepare` lance
`prepare_dataset.py` sur le **raw `datasets/`** (défaut), où `_source_images` ne compte que
les fichiers `^(obverse|real_)` **au top-level** de `datasets/<nid>/` (`_SOURCE_NAME_RE`).
Sur le PC ces images canoniques Numista sont **absentes** (Model B : elles vivent dans MinIO
`numista-canonical`, pas matérialisées en local ; `n_numista=0` partout). Le smoke Mac passait
car le Mac les avait en local.

**Décision à prendre (domaine PO / data-flow) :**
- **(a)** Matérialiser les obverses canoniques depuis MinIO vers `datasets/<nid>/obverse.jpg`
  sur le compute (step de sync manquant ?), OU
- **(b)** Faire lire à `prepare_dataset` le **staging prebaked** (`datasets/iterations/<iid>/`,
  déjà par-classe) au lieu du raw `datasets/<nid>/` quand `prebaked_augmentations=True`.

## Backlog — par priorité

### P1 — Cause racine MinIO 403 (infra VPS) ⚠️ seul vrai défaut
Le retry client est de la résilience, mais il **masque** le bug : MinIO/Traefik
(`eurio-s3.musubi.dev`) rejette en **403 sur la 1ʳᵉ requête** sous rafale de clés
**distinctes** (mesuré : 400/400 clés → 403 au 1ᵉʳ essai, 400/400 OK au retry ;
la **même** clé répétée 10× ne 403 jamais → déclencheur = volume de clés
distinctes, pas la clé). Pas de middleware rate-limit dans
`infra/minio/docker-compose.yml` (uniquement `buffering` upload + `addprefix`
images).

**À investiguer** : logs MinIO côté VPS, `MINIO_API_REQUESTS_MAX` / throttling
interne MinIO, keep-alive / conntrack du proxy Traefik, éventuel SigV4 sous
connexions neuves. Objectif : supprimer le 403 à la source → le retry redevient
un filet, pas une béquille.

### P2 — Readiness fait un *download* complet juste pour *compter*
`serving/lab_routes.py::cohort_training_readiness` → `preflight_classes` →
`real_training_sources` → `_ebay_training_sources` appelle `local_path()` (GET du
binaire) alors qu'il ne fait que **compter** les sources réelles. Sur cache froid
= lent + c'était le point de fragilité. Mieux : compter via `head_object` /
`list_objects` (ou directement la DB) sans GET du binaire. Gain perf + robustesse.

### P3 — Le front avale les 500 en « Failed to fetch »
Sur erreur serveur non gérée, Starlette renvoie le 500 **sans** headers CORS → le
navigateur bloque la réponse → message opaque « Failed to fetch » côté front.
Ajouter un exception-handler global (`serving/server.py`) qui renvoie un JSON 500
**avec** CORS rendrait toute future erreur serveur lisible dans le front. Pur
diagnosticabilité (aurait fait gagner du temps sur ce bug).

### P4 — Surveiller l'OOM `batch_size=256` sur 1080 Ti (11 GB)
Défaut canonique `training/pipeline.py` (`batch_size=256`, `m_per_class=4`).
Sur 11 GB selon backbone + résolution ça peut serrer. Si OOM au lancement →
baisser à 128 ; sinon documenter que 256 tient sur la 1080 Ti. À confirmer
empiriquement au 1ᵉʳ run complet.

### P5 — Étape de pré-chauffe cache explicite (optionnel)
Un `prefetch` des crops de la cohorte avant bake/train (réutilisant `local_path`
+ retry) front-loaderait les fetch réseau : la run ne ralentirait plus par
à-coups, et un échec dur sortirait tout de suite au lieu d'en plein training.

### P3bis — `/augmentation/preview` (§I1 « Aperçu ») cassé : chemin legacy Supabase
Le bouton « Aperçu » du configurateur de recette appelle `POST /augmentation/preview`
(`serving/augmentation_routes.py::post_preview`), qui résout l'image source via
`_resolve_source_url()` → `_supabase_fetcher` (= `None` sous Model B) → HTTPException
« Supabase non disponible » → 500 → « Failed to fetch » côté front. Puis
`_download_image()` fait un GET httpx sur une URL `coins.images`, pas du MinIO.

C'est un vestige **non migré** vers Model B : le training, lui, passe par
`real_training_sources → _ebay_training_sources → local_path` (MinIO) — chemin sain.
**Non-bloquant pour la run** (le preview est un outil de réglage de recette).
**À décider** : rewirer `post_preview` vers MinIO/`local_path` (mêmes crops que le
training) OU retirer l'aperçu du §I1. Tant que non fait, l'aperçu affichera
« Failed to fetch » sous Model B.

### P6 — `ml/eurio_ml.egg-info/` tracké (mineur cosmétique)
Ces artefacts de build créent du churn à chaque `uv pip install` (vu après
`ml:setup` qui a tiré `python-jose`). Soit les gitignorer, soit committer la
régen une bonne fois.
