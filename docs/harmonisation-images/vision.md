# Vision — harmonisation du stockage des images

> Cible end-state, principes, scope V1, anti-objectifs.
> Doit être lu avant tout chunk d'implémentation dans ce dossier.

## Cible end-state

Trois lieux distincts, trois rôles non-recouvrants :

| Lieu | Rôle | Contenu |
|---|---|---|
| **Supabase** | Prod Android | Métadonnées coins, sets, audit. **Aucune image.** |
| **Vercel** | Admin web (build statique) | UI seulement. **Aucune image.** |
| **VPS NixOS** | Source de vérité images + compute scrape | MinIO buckets : `numista-canonical` (public), `enrichment` (privé) |
| **pCloud** | Backup hebdo offsite | Snapshots datés du VPS |
| **Mac (dev)** | Admin live + review | Pas de cache permanent — LRU borné 5 GB |
| **PC fixe (dev)** | Entraînement | Cache `run_id`-scoped, sweep des orphelins |

Les images **ne sont plus dans git**. Le repo conserve uniquement le code et les docs.

## Architecture cible

```
┌─ VPS NixOS ─────────────────────────────────────────────┐
│                                                         │
│   MinIO ── bucket: numista-canonical ─── public-read ───┼──► Cloudflare
│        └── bucket: enrichment ────────── signed URLs ───┼──► Mac / PC
│        └── bucket: source-images ─────── signed URLs ───┤    (à la
│                                                         │    demande)
│   /etc/nixos/eurio-backup.nix                           │
│     systemd.timer (hebdo)                               │
│     rclone sync minio: → pcloud:eurio-backup/           │
└─────────────────────────────────────────────────────────┘
                                                            │
                  ┌─────────────────────────────────────────┤
                  │                                         │
            ┌─────┴─────┐                          ┌────────┴────────┐
            │   Mac     │                          │   PC fixe       │
            │  (dev)    │                          │  (entraînement) │
            ├───────────┤                          ├─────────────────┤
            │ Admin web │                          │ Pré-fetch run   │
            │ Review qu │                          │  → cache run_id │
            │ LRU 5 GB  │                          │  → train        │
            │           │                          │  → sweep orph.  │
            └───────────┘                          └─────────────────┘
                  │                                         │
                  │          ┌─ Vercel ─────┐               │
                  └──────────│ admin static │◄──────────────┘
                             │ build        │ (build deploy
                             └──────────────┘  asynchrone)
```

## Principes non négociables

### P1 — Une seule source de vérité par catégorie d'image

- **Numista canonique** → bucket `numista-canonical`, public-read, fronté Cloudflare.
- **Enrichment scrapé** (eBay, etc.) → bucket `enrichment`, privé, accédé par URL signée temporaire.
- **Raw downloads** (photos originales avant crop) → bucket `source-images`, privé.

Pas de duplication entre buckets. La DB porte la clé S3 unique de chaque image. Si l'image existe ailleurs (Vercel, Supabase), c'est un bug.

### P2 — Lecture jamais bloquée par la latence réseau côté entraînement

- **PC en entraînement** : pré-fetch synchrone en début de run vers un cache local, puis lecture filesystem pour tous les batches. Aucune query MinIO pendant la boucle d'entraînement.
- **Mac en review** : LRU disque borné (5 GB par défaut), évince le moins récemment utilisé. Premier hit = download MinIO, hits suivants = filesystem. Si LRU plein → évincer + télécharger.
- **Front (admin)** : `<img src="">` pointe vers MinIO (URL signée pour `enrichment`, URL publique CDN pour `numista-canonical`). Le browser cache HTTP fait son travail, on ne réinvente rien.

Cf. `chunk-4-mac-on-demand-fetch.md` et `chunk-5-pc-training-cache.md`.

### P3 — Backup non-aligné géographiquement

- **VPS** = source de vérité (Hetzner / OVH / autre).
- **pCloud** = backup hebdomadaire (data center tiers, autre juridiction).
- Aucun chemin où la perte d'un seul lieu = la perte de la donnée.
- Rétention : `latest/` (synced) + `snapshots/<YYYY-MM-DD>/` hebdo, gardés 4 semaines.

### P4 — `storage_path` n'est plus un chemin filesystem

Aujourd'hui `image_assets.storage_path` = `/Users/musubi42/.../crop.png`. Bug par construction sur 2 machines.

Demain : **clé S3** type `enrichment/ebay/run-abc/asset-123.png`. Machine-agnostique. Le code construit l'URL absolue à la demande (URL signée pour privé, URL publique pour Numista).

Migration : un script one-shot (`chunk-3-migration-script.md`), hard cut, sans phase de coexistence (cf. `feedback_no_debt`).

### P5 — La pipeline d'entraînement ne sait pas qu'on est en S3

Le code training PyTorch lit toujours des fichiers locaux. Le DataLoader ne change pas. Ce qui change : l'étape de pré-requis du runner instancie le cache, télécharge, écrit sous `~/.cache/eurio/runs/<run_id>/`, puis appelle l'entraînement avec ce path local.

Si jamais on swap MinIO → AWS S3 ou Backblaze B2, **rien ne bouge dans la pipeline d'entraînement**. Le seul code qui change est la fonction de pré-fetch (un client S3 qui parle au nouvel endpoint).

### P6 — Hard cut, jamais de double écriture

On ne maintient pas filesystem + MinIO en parallèle "le temps de la migration". Le jour J :

1. Plus de pipelines actives sur les machines locales.
2. Script de migration upload tout, vérifie sha256, met à jour la DB.
3. Le filesystem local devient lecture seule pour 7 jours (sécurité), puis supprimé.
4. À partir du jour J+1, toute nouvelle image écrit directement en MinIO.

Pas de `try local then S3 fallback`. Pas de feature flag `STORAGE_BACKEND=s3|fs`. Le code parle MinIO, point.

## Décisions actées

1. **MinIO sur VPS** (pas AWS S3, pas Cloudflare R2, pas Backblaze B2). Tu le maîtrises déjà, gratuit, ré-versible.
2. **Cloudflare CDN devant le bucket public Numista** (pas Vercel).
3. **Pas de FUSE mount** (pas de `rclone mount`). Trop d'effets de bord, debug pénible. Code Python parle directement à `boto3` ou `minio-py`.
4. **Cache LRU 5 GB sur Mac** via `diskcache` ou impl maison simple (1 fichier `~/.cache/eurio/lru/index.json` + dossier `objects/`).
5. **Cache training scoped par `run_id`** sous `~/.cache/eurio/runs/<run_id>/`. Sweep au démarrage du run suivant.
6. **Backup hebdo pCloud** via `rclone` + systemd.timer (NixOS module ou user-level selon la nature du VPS — à confirmer).
7. **Pas de versioning S3 actif sur les buckets**. Versioning = explose la facture stockage et complique la restauration. La protection vient des snapshots pCloud datés.
8. **Naming des clés S3** : voir `chunk-2-image-keys-schema.md`. Format `<bucket>/<source>/<run_id ou stable_key>/<asset_id ou face>.<ext>`.

## Décisions à confirmer

1. **Nature du VPS** : NixOS (`nixos-rebuild switch`-managé) ou Linux générique avec flake user-level via direnv ? Influence chunks 1 et 7.
2. **Domaine Cloudflare** : `images.eurio.com` ou autre ? Doit être enregistré avant chunk 6.
3. **Nettoyage filesystem post-migration** : J+7 ou J+30 avant `rm -rf ml/datasets/` local ?
4. **Stratégie thumbnail** : on génère des thumbs (256, 512px) à la persistence dans MinIO, ou on sert l'original et on laisse Cloudflare faire l'image-resizing (payant) ? Default V1 : pas de thumbs, on sert l'original 1:1.

## Anti-objectifs

- ❌ **Pas de Supabase Storage** pour les images training. Supabase reste réservé prod Android (1 GB free, 5 GB egress free → grillé instantanément avec 100k images training).
- ❌ **Pas de versioning git** des images (`ml/datasets/` ne doit plus contenir de `.png` après migration).
- ❌ **Pas de Syncthing** ou autre P2P. Pas de "source de vérité" claire = catastrophe à 100k fichiers.
- ❌ **Pas de cache permanent sur Mac** (le LRU est borné, pas un mirror).
- ❌ **Pas de `rclone mount`** (FUSE). On appelle l'API S3 directement.
- ❌ **Pas de double écriture** (fs + MinIO). Hard cut.
- ❌ **Pas de feature flag** `STORAGE_BACKEND`. Une seule implémentation, qui parle MinIO.
- ❌ **Pas d'image-resizing on-the-fly côté serveur ML**. Si besoin de thumbs, on les génère à l'écriture (chunk futur, pas V1).
- ❌ **Pas d'écriture concurrente Mac+PC sur le même bucket**. Seul le code de scrape écrit (sur la machine où il tourne, qui upload vers MinIO). La review humaine ne crée pas d'images, elle reclasse des images existantes.

## Glossaire

| Terme | Définition |
|---|---|
| **Bucket** | Espace de stockage MinIO indépendant, avec ses propres ACL. Trois buckets V1 : `numista-canonical`, `enrichment`, `source-images`. |
| **Storage key** | Clé S3, équivalent d'un chemin relatif dans un bucket. Format défini dans chunk 2. |
| **Signed URL** | URL S3 temporaire (~1h) qui donne un accès direct à un objet privé sans exposer les credentials. |
| **Public bucket** | Bucket en lecture publique sans signature. Réservé à Numista canonique (catalogue, OK d'être public). |
| **LRU disk cache** | Cache local qui garde les N derniers Go d'objets accédés, évince le moins récemment utilisé quand plein. |
| **Run-scoped cache** | Cache dont la durée de vie est égale à la durée d'un run d'entraînement, identifié par son `run_id`. |
| **Hard cut** | Migration sans phase de coexistence : à un instant T, on bascule, pas de retour arrière simple. |
| **Sweep** | Nettoyage automatique des caches orphelins (runs cancelled / failed) au démarrage du run suivant. |

## Ce qui peut faire pivoter le plan

1. **Coût bande passante VPS** : si le PC en entraînement download 100 GB par run et que le VPS est limité (Hetzner 20 TB/mois OK, OVH attention), faut mesurer après chunk 5.
2. **Latence MinIO sur Mac en review** : si > 500 ms par image en cold cache, il faudra peut-être pré-fetch les premiers crops de la review queue côté MinIO (background prefetch).
3. **Cloudflare gratuit suffit** ? Il a un cap "non-HTML files via free plan" théoriquement, en pratique c'est OK si on reste sous quelques TB/mois de bande passante. Si jamais on dépasse → Backblaze B2 + Cloudflare bandwidth alliance (free egress).
4. **NixOS module vs flake user** : la décision sur le VPS conditionne la propreté du chunk 7.

## Mémoires liées

- `feedback_no_debt` — pas de shortcut, hard cut sur la migration
- `feedback_nix_devshell` — toutes les deps via flake.nix (côté Mac/PC dev, MinIO côté VPS)
- `feedback_chunk_audit_flow` — chunk-par-chunk, audit visuel avant d'avancer
- `project_eurio_stack` — Kotlin natif Android, no VPS prod (le VPS ici est dev/scrape, pas prod)
- `project_monorepo_structure` — secrets via direnv
- `reference_supabase_free_tier` — pourquoi pas Supabase Storage (1 GB DB, 1 GB Storage, 5 GB egress)
