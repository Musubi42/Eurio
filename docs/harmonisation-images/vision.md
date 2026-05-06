# Vision — harmonisation du stockage des images

> Cible end-state, principes, scope V1, anti-objectifs.
> Doit être lu avant tout chunk d'implémentation dans ce dossier.

## Problème

Aujourd'hui les images vivent éparpillées sur le filesystem local du Mac :

| Dossier | Contenu | Taille | Lifecycle |
|---|---|---|---|
| `ml/datasets/<numista_id>/{obverse,reverse}.jpg` | Référentiel canonique Numista | ~270 MB / 694 coins | Stable, géré par bootstrap |
| `ml/state/sources/<src>/raw/<shard>/...` | Photos originales scrapées (eBay, etc.) | ~400 MB | Source → un crop |
| `ml/state/sources/<src>/crops/<shard>/...` | Crops normalisés = actif training | (inclus) | Le vrai actif training |
| `ml/cache/augmentation_sources/` | Augmentations transient | variable | Vie = un run training |
| `ml/debug_captures/` | Captures device pour cohort/bench | petit | Local validation |

Conséquences :
- Mac et PC fixe ne voient pas la même donnée.
- Une perte du Mac = perte des crops scrapés (ce qui prendra le plus de temps à reconstituer).
- Pas de chemin clair pour servir les images Numista canoniques à l'app Android.

## Cible end-state

**Trois lieux distincts, trois rôles non-recouvrants.**

| Lieu | Rôle | Contenu |
|---|---|---|
| **MinIO sur VPS perso** | Source de vérité dev (scrape + training + admin) | Buckets `numista-canonical`, `enrichment-raws`, `enrichment-crops` |
| **Supabase Storage** | Images servies à l'app Android prod | Bucket `app-coins-public` (obverses optimisés) |
| **pCloud** | Backup hebdo offsite du VPS | 1 tarball écrasé chaque dimanche |
| **Mac (dev)** | Admin web + review humaine | Cache local read-through, LRU borné |
| **PC fixe (dev)** | Entraînement | Cache run-scoped, sweep des orphelins |

Les images **ne sont plus dans git** ni mélangées au repo après migration.

## Architecture cible

```
┌─ VPS perso NixOS (docker) ──────────────────────────────┐
│                                                         │
│   MinIO ── numista-canonical  (public via CF)           │
│        ── enrichment-raws     (privé, signed URL)       │
│        ── enrichment-crops    (privé, signed URL)       │
│                                                         │
│   rclone (systemd.timer hebdo) ──► pCloud:eurio.tar     │
└────────────────────────┬────────────────────────────────┘
                         │
        ┌────────────────┼─────────────────┐
        │                │                 │
   Mac (admin)      PC (training)    Vercel (admin web)
   read-through     pre-fetch         lit signed URL via API
   LRU 5 GB         run_id-scoped     ML proxy
        │
        │  augmentations transient locales (jamais S3)
        │
        └─ ml/cache/augmentation_sources/ (vit le run, supprimé après)


┌─ Supabase Storage (chaîne app prod, indépendante) ──────┐
│                                                         │
│   Bucket app-coins-public                               │
│   peuplé par script depuis ml/datasets/                 │
│   Servi à l'app Android via SDK Supabase                │
└─────────────────────────────────────────────────────────┘
```

**Deux chaînes indépendantes** : la chaîne dev (MinIO) et la chaîne prod (Supabase). Les deux ne se parlent pas en runtime — seul le script de publication pousse périodiquement de l'un vers l'autre.

## Principes non négociables

### P1 — Trois groupes d'images, trois lifecycles

1. **Canonique** (Numista référentiel) : stable, push une fois, modifié rarement (correction, ajout de coin). Bucket `numista-canonical` (public). **Aussi publié vers Supabase Storage** (chaîne prod).
2. **Enrichment crops** : actif training. Produit par le pipeline scrape, persiste indéfiniment. Bucket `enrichment-crops` (privé).
3. **Enrichment raws** : sources des crops. Persistent V1 (peut servir à un retrain futur), candidat à purge sélective V2. Bucket `enrichment-raws` (privé).

**Hors S3** : augmentations (`ml/cache/augmentation_sources/`) et captures de bench (`ml/debug_captures/`). Ces images sont locales, transient, jamais uploadées.

### P2 — Chaîne dev MinIO, chaîne prod Supabase

- **MinIO** = backend dev, training, admin. Egress gratuit côté VPS, coûte rien.
- **Supabase Storage** = backend app Android prod. Plan Pro $25/mois (250 GB egress, 100 GB storage). Couvre largement 270 MB de canonique + thumbnails.
- **Vercel admin** lit MinIO (signed URL via API ML), **jamais Supabase**, pour ne pas brûler l'egress Supabase prod.
- **App Android** lit Supabase, jamais MinIO. Le VPS n'est pas dans le chemin prod — pas de SLA à tenir, pas de monitoring 24/7 nécessaire.

### P3 — Read-through cache local partout

Le code applicatif n'appelle jamais MinIO directement pour lire un fichier. Il appelle une fonction `local_path(asset)` qui :

1. Cherche dans le cache local. Si présent → retourne le path.
2. Sinon download depuis MinIO vers le cache, puis retourne le path.

Conséquences :
- **PyTorch DataLoader** lit du fs local. Aucune latence réseau pendant la boucle training.
- **Scripts admin Python** marchent transparent.
- **Mac admin** : LRU 5 GB par défaut, évince le moins récemment utilisé.
- **PC training** : cache run-scoped, pre-fetch en début de run, sweep des runs morts.

### P4 — `storage_key` est une clé S3 relative au bucket

Aujourd'hui `image_assets.storage_path` = chemin filesystem absolu, machine-spécifique.

Demain : **clé S3** type :

| Type | Format | Bucket |
|---|---|---|
| Canonique | `numista/<numista_id>/<face>.jpg` | `numista-canonical` |
| Crop | `<source>/<run_id>/<asset_id>.png` | `enrichment-crops` |
| Raw | `<source>/<run_id>/<source_image_id>.<ext>` | `enrichment-raws` |

Le path local cache est dérivé : `~/.cache/eurio/<bucket>/<storage_key>`. Aucune table de mapping additionnelle.

La colonne reste nommée `storage_path` dans le schéma DB (cosmétique, on évite un rename qui touche 17 fichiers Python). Sa **sémantique change** : au lieu d'un chemin fs absolu, elle porte une clé S3 relative au bucket. Le bucket est dérivé de la sémantique de la ligne (cf. chunk 2), pas une colonne séparée.

### P5 — Augmentations restent locales

Les augmentations sont produites à la volée dans `ml/cache/augmentation_sources/<run_id>/` pendant l'entraînement, lues une fois, jetées à la fin du run. Elles ne sont **jamais** uploadées vers S3. Un nouveau run = nouvelles augmentations (le générateur est déterministe par seed).

### P6 — Hard cut sur la migration

On ne maintient pas filesystem + MinIO en parallèle. Le jour J :

1. Plus de pipelines actives sur le Mac.
2. Script de migration upload tout, vérifie sha256, met à jour la DB.
3. Le filesystem local devient lecture seule pendant 7 jours (sécurité).
4. Le code lit MinIO via cache local read-through dès J+1.
5. À J+7 audit OK → suppression définitive du filesystem local.

Pas de feature flag `STORAGE_BACKEND=s3|fs`. Le code parle `local_path(asset)`, point — l'impl appelle MinIO derrière.

## Décisions actées

1. **MinIO dockerisé sur le VPS perso NixOS** (pas Hetzner, pas AWS, pas R2). Container `minio/minio` géré via `docker-compose`, Traefik côté host fait le TLS et le routing.
2. **Domaines** : `s3.eurio.musubi.dev` (signed URL endpoints) + `images.eurio.musubi.dev` (CDN public Cloudflare). Sous-domaines de `musubi.dev`, déjà sur Cloudflare. Pas d'achat de `eurio.com` en V1.
3. **3 buckets MinIO** : `numista-canonical` (public), `enrichment-raws` (privé), `enrichment-crops` (privé).
4. **Pas de FUSE mount**. Le code parle directement à `boto3` (lib standard).
5. **Cache LRU Mac** : 5 GB, eviction par `os.atime`, pas de DB sidecar.
6. **Cache training PC** : scoped par `run_id` sous `~/.cache/eurio/runs/<run_id>/`. Sweep au démarrage du run suivant.
7. **Backup hebdo pCloud** : 1 tarball complet écrasé chaque dimanche. Pas de versioning, pas de rétention multi-semaine. Simple.
8. **Pas de versioning S3** sur les buckets MinIO. La protection vient du backup pCloud.
9. **Chaîne app prod = Supabase Storage** ($25/mois Pro plan). Peuplée par un script de publication depuis `ml/datasets/`. Vercel admin et VPS ne touchent jamais à Supabase Storage en runtime.
10. **Signed URL TTL** : 6 h (compromis entre rotation et cacheabilité du browser HTTP).

## Décisions à confirmer

1. **Optimisation des canoniques avant push Supabase** : Numista actuel = 270 MB. Avec WebP + resize 1024 max, on descend probablement à <80 MB. À tester au chunk de publication.
2. **Délai filesystem lock-fs post-migration** : 7 jours par défaut, configurable. Plus long = plus safe, coût marginal nul.
3. **Embarquement des coins les plus communs dans l'APK** : V2. V1 = tout fetch via Supabase Storage.

## Anti-objectifs

- ❌ Pas de Supabase Storage pour scrape / training / admin. Trop coûteux en egress vu le volume scrape.
- ❌ Pas de versioning git des images. Le repo conserve uniquement code + docs + 1 manifest de migration.
- ❌ Pas de Syncthing / P2P. Pas de "source de vérité" claire = catastrophe.
- ❌ Pas de cache permanent sur Mac (LRU borné).
- ❌ Pas de FUSE mount.
- ❌ Pas de double écriture fs+MinIO. Hard cut.
- ❌ Pas de feature flag `STORAGE_BACKEND`.
- ❌ Pas d'image-resizing on-the-fly côté serveur dev. Si besoin de thumbs, on les génère à l'écriture (chunk publication Supabase).
- ❌ Pas d'écriture concurrente Mac+PC sur le même bucket. Seul le code de scrape écrit (sur la machine où il tourne).
- ❌ Pas d'augmentation uploadée en S3. Local et transient, point.
- ❌ Pas de Hetzner ni autre VPS managé. VPS perso uniquement.

## Glossaire

| Terme | Définition |
|---|---|
| **Bucket** | Espace de stockage MinIO indépendant, avec ses propres ACL. |
| **Storage key** | Chemin relatif dans un bucket. Format défini en P4. |
| **Signed URL** | URL S3 temporaire (TTL 6h) qui donne accès à un objet privé sans exposer les credentials. |
| **Public bucket** | Bucket en lecture publique sans signature. Réservé à `numista-canonical`. |
| **Read-through cache** | Cache qui télécharge à la demande au premier accès, puis sert depuis le local. |
| **Run-scoped cache** | Cache dont la durée de vie est égale à la durée d'un run d'entraînement. |
| **Hard cut** | Migration sans phase de coexistence. |
| **Sweep** | Nettoyage automatique des caches orphelins au démarrage du run suivant. |
| **Chaîne dev** | MinIO + Vercel admin + Mac/PC. |
| **Chaîne prod** | Supabase Storage + app Android. |

## Ce qui peut faire pivoter le plan

1. **Volume crops scrapés** : si on dépasse 100 GB, vérifier que le disque VPS suit + que le tarball pCloud reste viable.
2. **Supabase egress** : si le plan Pro 250 GB ne suffit plus (Android prod scale), passer à Backblaze B2 + Cloudflare bandwidth alliance pour la chaîne prod. La chaîne dev reste MinIO.
3. **Latence MinIO sur Mac** : si > 500 ms par image en cold cache, prefetch en background les premiers items de la review queue.

## Mémoires liées

- `feedback_no_debt` — pas de shortcut, hard cut sur la migration
- `feedback_nix_devshell` — toutes les deps via flake.nix (côté Mac/PC dev)
- `feedback_chunk_audit_flow` — chunk-par-chunk, audit visuel avant d'avancer
- `project_eurio_stack` — VPS = dev/scrape, **Supabase Storage = images app prod**
- `project_monorepo_structure` — secrets via direnv
- `feedback_training_source_obverse_only` — training = obverse uniquement, dimensionner les caches en conséquence
