# Harmonisation images — kickoff

> Sortir le stockage des images du filesystem local pour que Mac, PC et
> Vercel admin voient le même catalogue, et préparer la chaîne prod
> Android via Supabase Storage. Sans pouvoir tout perdre d'un seul coup.

Lis [`vision.md`](vision.md) en premier. Les chunks numérotés sont des
briques implémentables séparément, dans l'ordre indiqué. Aucun chunk ne
doit être attaqué sans que ses pré-requis soient livrés et audités.

## Plan

| # | Chunk | Pré-req | Statut |
|---|---|---|---|
| 1 | [MinIO docker bootstrap (VPS NixOS)](chunk-1-minio-bootstrap.md) | — | À faire |
| 2 | [Schéma DB + format storage_key](chunk-2-image-keys-schema.md) | — | À faire |
| 3 | [Migration scripts (3 inventaires)](chunk-3-migration-script.md) | 1, 2 | À faire |
| 4 | [Cache local read-through (lib commune)](chunk-4-local-cache.md) | 3 | À faire |
| 5 | [Pre-fetch run-scoped training](chunk-5-pc-training-cache.md) | 4 | À faire |
| 6 | [Publication Supabase Storage (chaîne prod)](chunk-6-supabase-publication.md) | 1, 2 | À faire |
| 7 | [Backup pCloud (tar hebdo écrasé)](chunk-7-pcloud-backup.md) | 1 | À faire |
| 8 | [Cleanup + rollback](chunk-8-cleanup-rollback.md) | 3, 4, 5 | À faire |

## Ordre d'implémentation conseillé

```
1 (MinIO docker) ──┐
                   ├──> 3 (migration) ──┬──> 4 (cache lib) ──> 5 (training)
2 (DB schema)    ──┘                    │
                                        │
6 (Supabase publication) ←─ peut partir en parallèle de 3
7 (backup) ←─ dès que 1 est live
8 (cleanup) ←─ ferme la boucle quand 4 et 5 sont stables
```

Les chunks 1, 2, 6, 7 peuvent partir en parallèle (indépendants des données existantes).
3 doit attendre 1 + 2.
4 attend 3. 5 attend 4 (réutilise la lib).
8 ferme la boucle.

## Conventions communes à tous les chunks

- **Pas de fallback silencieux.** Si MinIO est down ou un hash ne matche pas, le code throw — pas de "best-effort skip".
- **Toute clé S3 est dérivable depuis la DB**, pas l'inverse. La DB est canonique, MinIO est dérivé.
- **Aucun chunk n'introduit de feature flag.** On bascule en hard cut (cf. `feedback_no_debt`).
- **Standards uniquement** : boto3, rclone, MinIO docker officiel, Traefik. Pas d'invention exotique.

## Mémoires liées

- `feedback_no_debt` — pas de shortcut, on construit propre
- `feedback_chunk_audit_flow` — chunk-par-chunk avec audit visuel
- `feedback_nix_devshell` — toutes les deps via flake.nix
- `project_eurio_stack` — VPS = dev/scrape, Supabase Storage = images app prod
