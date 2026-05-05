# Harmonisation images — kickoff

> Sortir le stockage des images du filesystem local + git pour avoir
> Mac, PC, et VPS qui voient le même catalogue, sans dépendre l'un de
> l'autre, et sans pouvoir tout perdre d'un seul coup.

Lis [`vision.md`](vision.md) en premier. Les chunks numérotés sont des
briques implémentables séparément, dans l'ordre indiqué. Aucun chunk ne
doit être attaqué sans que ses pré-requis soient livrés et audités.

## Plan

| # | Chunk | Pré-req | Statut |
|---|---|---|---|
| 1 | [MinIO bootstrap (VPS)](chunk-1-minio-bootstrap.md) | — | À faire |
| 2 | [Schéma DB clés storage](chunk-2-image-keys-schema.md) | — | À faire |
| 3 | [Script one-shot migration fs→MinIO](chunk-3-migration-script.md) | 1, 2 | À faire |
| 4 | [Mac fetch on-demand + LRU 5 GB](chunk-4-mac-on-demand-fetch.md) | 3 | À faire |
| 5 | [PC training cache run-scoped](chunk-5-pc-training-cache.md) | 3 | À faire |
| 6 | [Numista bucket public + Cloudflare](chunk-6-numista-public-cdn.md) | 1, 2 | À faire |
| 7 | [Backup pCloud (systemd.timer)](chunk-7-pcloud-backup.md) | 1 | À faire |
| 8 | [Cleanup + rollback procedures](chunk-8-cleanup-rollback.md) | 3, 4, 5 | À faire |

## Ordre d'implémentation conseillé

```
1 (MinIO live) ──┐
                 ├──> 3 (migration) ──┬──> 4 (Mac fetch) ──┐
2 (DB schema)  ──┘                    ├──> 5 (PC cache) ───┤
                                      │                    │
6 (Numista bucket) ←─ peut partir en parallèle de 3        │
7 (backup) ←─ dès que 1 est live                           │
                                                           │
                                       8 (cleanup) ←───────┘
```

Les chunks 1, 2, 6, 7 peuvent partir en parallèle (indépendants des données existantes).  
3 doit attendre 1 + 2.  
4 et 5 attendent 3.  
8 ferme la boucle quand 4 et 5 sont stables.

## Conventions communes à tous les chunks

- **Pas de fallback silencieux.** Si MinIO est down ou un hash ne matche pas, le code throw — pas de "best-effort skip".
- **Toute clé S3 est dérivable depuis la DB**, pas l'inverse. La DB est canonique, MinIO est dérivé.
- **Aucun chunk n'introduit de feature flag.** On bascule en hard cut comme demandé (cf. `feedback_no_debt`).

## Mémoires liées

- `feedback_no_debt` — pas de shortcut, on construit propre
- `feedback_chunk_audit_flow` — chunk-par-chunk avec audit visuel
- `feedback_nix_devshell` — toutes les deps via flake.nix
- `project_eurio_stack` — Kotlin natif, Supabase, TFLite, no VPS prod (le VPS ici est dev, pas prod)
