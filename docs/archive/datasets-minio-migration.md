# Mission — Migrer `ml/datasets/` vers MinIO (2 buckets) sans casser le local

> **⛔️ ARCHIVÉ (2026-08-14) — CHIFFRES FAUX.** Ce plan parle de « 2,5 Go, ~8895
> fichiers committés » sous `ml/datasets/` : la réalité mesurée est **33 Mo pour
> 3900 fichiers trackés**. Le raisonnement (buckets, `dataset_path()` local-first,
> `git rm --cached` tardif) reste valable et a été repris ; les volumes non.
>
> **Successeur : [ADR-004](../adr/004-artefacts-binaires-hors-git.md)** — et il couvre
> en plus les **modèles**, absents de ce plan.
> Chiffres à jour : [`../architecture/artifacts.md`](../architecture/artifacts.md) §Volumes.

> **Statut : PLAN, pas démarré.** Mission séparée du refacto-ml (chunks 1-8). À faire
> étape par étape, chaque phase validée avant la suivante. **Principe directeur : rien
> de destructif (suppression git/local) tant que la transition n'est pas validée
> bout-en-bout.** Doctrine R0 (zéro dette), [[feedback_chunk_audit_flow]] (chunks audités).

## 1. Contexte & problème

`ml/datasets/` = **2.5 Go, ~8895 fichiers committés** (693 sous-dossiers, un par
`numista_id` : `obverse.jpg`, crops, variantes). C'est aujourd'hui la **synchro
cross-PC** (Mac ↔ PC) : tout passe par git. Deux douleurs :

1. **Poids git** : clones lents, historique lourd, chaque machine porte 2.5 Go binaires
   non-mergeables. Incohérent avec la doctrine **eurio.db → MinIO** (lease, chunk 6).
2. **Bande passante page coins (admin)** : `/coins` affiche toutes les pièces avec
   thumbnail + titre. Elle charge des images **pleine qualité** → transfert lourd au
   chargement. On veut des **vignettes optimisées** (webp ~256-512px) servies à part.

### Comment c'est lu aujourd'hui (à préserver pendant la transition)
- `DATASETS_DIR = ML_DIR / "datasets"` dans ~10 modules (`serving/{server,distance_logic,iteration_runner}.py`,
  `referential/*`, `bootstrap/*`, `training/*`). Accès **filesystem direct**.
- La page coins admin tire les images via l'API ML (`/images/{numista_id}/source`) et
  `firstImageUrl(coin)` (URLs canoniques).
- Une couche MinIO existe déjà : `shared/storage/` — buckets
  `numista-canonical | enrichment-raws | enrichment-crops`, `local_path(bucket, key)`
  (read-through cache), `public_url`/`signed_url`, CDN `eurio-images.musubi.dev`.
  **On réutilise ce pattern**, on ne réinvente rien.

## 2. Cible

### Deux buckets
| Bucket | Contenu | Usage | Format |
|---|---|---|---|
| `datasets-originals` | images sources pleine qualité (= contenu actuel de `datasets/`) | training, crop, bench | tel quel (jpg/png/webp) |
| `datasets-thumbs` | vignettes dérivées | page coins admin, previews | **webp, bord max ~384px, qualité ~80** |

Versioning ON sur `datasets-originals` (récupération). `datasets-thumbs` régénérable
depuis les originals → pas besoin de versioning (ou lifecycle court).

### Accès code = read-through cache (jamais de FS réseau)
Une fonction unique `dataset_path(numista_id, kind="obverse")` qui :
1. cherche en **local** (`ml/datasets/...`) → si présent, le rend (rapide, comportement actuel) ;
2. sinon **pull depuis MinIO** dans un cache local, puis le rend.

→ Pendant toute la transition, le local gagne toujours : **comportement strictement
inchangé** tant que `datasets/` est sur disque. La bascule MinIO-first est un flag de fin.

### Synchro = même modèle que le lease eurio.db (chunk 6)
`go-task ml:datasets:{push,pull,sync,status}` (boto3, mêmes creds `MINIO_*`). Pas de
verrou (les images sont append-only par `numista_id`, pas de write concurrent destructif
— contrairement à la DB). Dédup par checksum.

## 3. Phases (chaque phase = livrable + gate de validation)

### Phase 0 — Inventaire & empreintes (non destructif)
- Manifeste `datasets/` : pour chaque fichier, chemin relatif + sha256 + taille.
- Script `datasets:manifest` → `ml/state/datasets_manifest.json` (gitignored).
- **Gate** : manifeste complet, total cohérent avec `du` (2.5 Go).

### Phase 1 — Provisioning + upload originals + thumbs (additif, git intact)
- Doc VPS (comme `chunk6-vps-minio.md`) : créer `datasets-originals` + `datasets-thumbs`,
  versioning, policy (creds Mac/PC rw), vérifs.
- `datasets:push` : upload tout `datasets/` → `datasets-originals` (idempotent, skip si
  sha identique côté distant).
- `datasets:build-thumbs` : génère les webp (Pillow, bord 384 q80) → `datasets-thumbs`.
- `datasets/` **reste en git, code inchangé**.
- **Gate** : `datasets:status` montre 100 % des originals présents+cohérents (sha) sur
  MinIO ; thumbs générés pour toutes les pièces ; rien de supprimé.

### Phase 2 — Couche d'accès read-through (comportement inchangé)
- Introduire `shared/storage/datasets.py::dataset_path(...)` (local-first → MinIO cache).
- Migrer les ~10 sites `DATASETS_DIR / ...` vers `dataset_path(...)` **un par un**, tests
  à chaque fois. Le local étant toujours présent, **aucun changement de comportement**.
- `datasets:pull` (récupère depuis MinIO vers cache/local) pour une nouvelle machine.
- **Gate** : suite de tests verte ; un run training/bench tourne à l'identique ; sur une
  machine où on **renomme temporairement** `datasets/` → le pull MinIO reconstitue et
  tout marche (preuve que la couche fonctionne) → puis on restaure le local.

### Phase 3 — Page coins sur thumbnails optimisées (gain bande passante)
- API ML : endpoint vignette (`/coins/{eurio_id}/thumb` ou champ `thumb_url` signé vers
  `datasets-thumbs`).
- Admin web : la liste `/coins` consomme la vignette (pas l'original).
- **Gate** : mesurer le poids transféré au chargement de `/coins` avant/après (DevTools
  Network) ; viser une réduction nette (objectif : < quelques centaines de Ko pour la liste).

### Phase 4 — Validation cross-PC réelle
- Sur le **2e PC** : `datasets:pull` depuis MinIO, lancer un cycle complet
  (prép → training/bench → review) **sans** dépendre du git pour les images.
- **Gate** : cycle complet OK des deux côtés ; sha manifest identique local ↔ MinIO ;
  page coins OK. Laisser tourner quelques jours en conditions réelles.

### Phase 5 — Sortir `datasets/` du tracking git (réversible)
- Seulement après Phase 4 validée et stable.
- `git rm --cached -r ml/datasets` (garde le local) + `.gitignore` ajoute `ml/datasets/`
  (avec exceptions éventuelles si quelques seeds doivent rester).
- **Gate** : nouveau clone + `datasets:pull` reconstitue tout ; rien de perdu. La DB git
  ne grossit plus, mais l'historique porte encore les 2.5 Go (voir Phase 6).

### Phase 6 — Purge de l'historique git (irréversible — en dernier, avec backup)
- Seulement quand tout le monde est à l'aise et qu'un **backup complet** du repo existe.
- `git filter-repo --path ml/datasets --invert-paths` (ou BFG) pour retirer `datasets/`
  de **tout l'historique** → réduit la taille réelle du `.git`.
- ⚠️ **Réécrit l'historique** : nécessite un force-push coordonné + re-clone sur chaque
  machine. À faire hors fenêtre de travail, une fois, proprement.
- **Gate** : backup vérifié ; toutes les machines re-clonent ; `datasets:pull` OK partout.

## 4. Garde-fous (R0)
- **Aucune suppression** (`git rm --cached`, purge local, filter-repo) **avant** la
  Phase 4 validée. L'ordre des phases est l'invariant de sécurité.
- Le local reste **source de vérité de fait** jusqu'à Phase 5 ; MinIO est d'abord une
  **copie**, pas un remplacement.
- Réutiliser `shared/storage` (boto3, creds, cache) — pas de nouvelle stack.
- Pas de SQLite/FS réseau ; uniquement client-serveur MinIO (cf. ADR D4 révisé).
- Thumbs **dérivées** (jamais éditées à la main) — régénérables depuis originals.

## 5. Tâches go-task à créer (Phase 1-2)
```
ml:datasets:manifest      # sha256 + tailles → datasets_manifest.json
ml:datasets:push          # local → datasets-originals (idempotent, sha-skip)
ml:datasets:build-thumbs  # webp 384/q80 → datasets-thumbs
ml:datasets:pull          # MinIO → local/cache (nouvelle machine)
ml:datasets:status        # local vs originals vs thumbs (counts + sha drift)
```

## 6. Questions ouvertes à trancher au démarrage
- Taille/qualité exacte des thumbs (384 q80 ? 256 ? AVIF vs WebP ?).
- `datasets-thumbs` servi via CDN public (comme `numista-canonical`) ou URL signée ?
- Garde-t-on un petit sous-ensemble seed dans git (ex. fixtures de test) ou tout sort ?
- Cache local des pulls : `ml/.dataset_cache/` (déjà gitignored) ou dans `datasets/` ?
