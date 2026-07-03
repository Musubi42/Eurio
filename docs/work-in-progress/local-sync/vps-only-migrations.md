# Migrations one-shot — VPS-only (Direction A, C7)

> Statut : FAIT (2026-07-04). Complète `migration-direction-a.md` §5 C7.

## Pourquoi

Sous Direction A, `eurio.db` canonique n'existe qu'au VPS (§3 de
`migration-direction-a.md`). Les migrations one-shot ci-dessous mutent des
colonnes canoniques (`face`, `denom`, `quality_score`, schéma, storage) via des
`UPDATE`/`ALTER` **bruts**, hors du transport `/ingest/*` posé par C2b/C3/C4.
Les lancer contre une réplique locale (Mac/PC) écrirait une divergence
**invisible et jamais synchronisée** — exactement le mécanisme de bug qui a
motivé la migration (§1).

**Règle** : ces 5 scripts ne tournent QUE contre le canonique (VPS, ou une
copie explicitement désignée comme telle par l'opérateur).

## Les 5 scripts

| Script | Écrit | Garde-fou | Dépendances |
|---|---|---|---|
| `scripts/backfill_face.py` | `image_assets.face` (+ rejets, `route_reason`) | ✅ auto (`_vps_only_guard`) | torch/DINO (ArcFace) |
| `scripts/backfill_denom.py` | `image_assets.denom`/`denom_2eur_score` (+ rejets `--reject`) | ✅ auto | torch (probe DINO) |
| `scripts/backfill_quality_score.py` | `image_assets.quality_score`/`quality_pipeline_version` | ✅ auto | aucune (CSV + sqlite pur) |
| `scripts/migrate_canonical_schema.py` | `coins` + tables filles, schéma legacy | ⚠️ déjà `DEPRECATED` (docstring), pas de garde auto | aucune |
| `scripts/migrate_to_minio.py` | `storage_path` (image_assets/source_images), fichiers MinIO | ⚠️ déjà `DEPRECATED` (bandeau stderr), pas de garde auto | aucune |

Les 3 `backfill_*` sont les seuls **actifs** aujourd'hui (les 2 `migrate_*`
sont déjà marqués `DEPRECATED` par leurs auteurs et ne sont plus dans le
chemin normal — pas de garde-fou automatique ajouté, le bandeau existant
suffit à dissuader un run accidentel ; à réviser si l'un des deux redevient
actif).

## Garde-fou automatique (`backfill_*`)

`ml/scripts/_vps_only_guard.py::guard_vps_only()` refuse de démarrer
(`sys.exit(1)`, message sur stderr) si l'une de ces conditions est vraie :

- `EURIO_DB_READONLY` est vrai (cette machine est une réplique read-only, C5) ;
- `client.http.sync_enabled()` est vrai, i.e. `EURIO_API_URL` est configuré
  (cette machine est une **cliente** Direction A qui forward vers un VPS
  canonique — donc n'est PAS elle-même le canonique).

Sur le VPS lui-même (ni l'un ni l'autre n'est configuré localement), les
scripts tournent normalement. Bypass explicite :
`--i-know-this-is-canonical` (l'opérateur atteste que `--db` pointe une copie
canonique — voir procédure ci-dessous).

## Point non tranché : `backfill_face`/`backfill_denom` sur machine GPU

Ces deux scripts dépendent de torch/DINO (encodeur ArcFace + banques
d'ancres) — l'image lean VPS (`infra/eurio-api/Dockerfile`) ne les embarque
**pas** (cv2/torch-free par construction, cf. inventaire des modules copiés).
Ils doivent donc tourner sur une machine GPU (Mac/PC), ce qui contredit
« VPS-only » au sens strict.

**Remontée PO (non tranchée à ce chunk)** : deux options possibles pour
concilier « calcul GPU local » et « écriture canonique unique » —

1. Récupérer une copie exacte du canonique VPS (`pull-replica` en écriture,
   pas en lecture), lancer le backfill dessus avec
   `--i-know-this-is-canonical --db <copie>`, puis pousser le résultat au VPS
   (mécanisme à construire — aucune route `/ingest` ne couvre `face`/`denom`
   aujourd'hui, cf. C4d en cours).
2. Exposer un environnement GPU sur le VPS lui-même (hors périmètre coût/infra
   actuel — le VPS est délibérément « no-GPU », cf.
   `docs/operations/deployment-topology.md`).

Aucune des deux n'est implémentée ici : ce chunk pose le garde-fou et
documente le trou, il ne le comble pas.

## Dry-run reproductible (`backfill_quality_score.py`)

Seul des 3 `backfill_*` à ne dépendre que de sqlite pur (pas de torch) — donc
le seul directement exécutable contre une copie canonique sans environnement
GPU :

```bash
# Contre une copie du canonique (jamais la réplique locale) :
.venv/bin/python scripts/backfill_quality_score.py \
    --db <copie-canonique>/eurio.db --i-know-this-is-canonical
#   dry-run par défaut : imprime la distribution quality_score sans écrire.
#   --commit pour persister.
```

## Voir aussi

- `docs/work-in-progress/local-sync/migration-direction-a.md` §4 (inventaire
  des écrivains), §5 C7, §6 (décisions ouvertes).
- `ml/scripts/_vps_only_guard.py` (implémentation du garde-fou).
