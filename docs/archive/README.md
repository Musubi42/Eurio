# Archive docs

Travaux **livrés** (référence figée) ou approches **abandonnées / remplacées**. Conservés
pour la traçabilité du raisonnement, **jamais pour piloter**.

- Le **pourquoi** d'une décision vit dans [`../adr/README.md`](../adr/README.md).
- L'**état du système** vit dans [`../architecture/README.md`](../architecture/README.md).
- Le **reste-à-faire** hérité de ces chantiers vit dans [`../BACKLOG.md`](../BACKLOG.md).
- Ce qui est **en cours** vit dans [`../work-in-progress/`](../work-in-progress/).

> ⚠️ Un doc d'ici peut affirmer une chose que le code contredit depuis. C'est normal :
> c'est une photo, pas une vérité. Ne jamais agir sur un doc archivé sans le recouper.

## Inventaire (revu le 2026-08-24)

### Architecture de la donnée — remplacée par Direction A

| Dossier | Statut | Décision qui l'a remplacé |
|---|---|---|
| `local-sync/` | Abandonné 2026-07-03 | [ADR-009](../adr/009-direction-a-writer-canonique-unique.md). Garde l'event-log **et sa réfutation par la mesure** — le meilleur doc du lot |
| `model-b/` | Clos 2026-06-30 | [ADR-009](../adr/009-direction-a-writer-canonique-unique.md) + [ADR-011](../adr/011-front-admin-unique.md) |
| `data-layer-unification/` | Livré 2026-07-01 | Supabase retiré du front ; tout passe par `eurio-api` |

### Auth et fronts admin

| Dossier | Statut | Décision |
|---|---|---|
| `auth-redesign/` | Livré 2026-06-19 | [ADR-010](../adr/010-authentik-oidc-et-pat.md) + [ADR-011](../adr/011-front-admin-unique.md). `PAT-WORKFLOW.md` reste opératoire |
| `collaborative-review/` | Supersédé 2026-08-23 | [ADR-012](../adr/012-review-collaborative-ecriture-directe.md) |
| `parity/` | Livré | Capture Maestro + proto + viewer `/parity` en place. Screenshots Android périmés depuis avril |
| `review-improvements/` | Consommé | Prompt de session de juin, joué |

### Pipeline d'acquisition et de crop

| Dossier | Statut | À savoir |
|---|---|---|
| `crop-quality-overhaul/` | Algo livré | `detect_bbox_refine`, crop eBay ~92 %. Le doc pointe un chemin périmé (`ml/sources/_base/steps/`) ; le code vit dans `ml/scan/crop_detectors.py` |
| `crop-rim-overfit/` | Résolu | Le sur-ajustement au cercle interne (EMU 2009) est corrigé par l'algo ci-dessus |
| `crop-recovery/` · `crop-forensics/` | Clos | S1-S6 livrés ou **réfutés**. S7 est gelé : ses deux seuils dépendent de signaux morts — l'implémenter serait de la dette garantie |
| `harmonisation-images/` | Livré | Write-through MinIO en place, canoniques servis par CDN. Résiduel dans `BACKLOG.md` |
| `sources/` · `sources-refacto/` | Livré | Pipeline 6 étapes, orchestrateur, eBay. ⚠️ Les statuts « pas démarré » de ces docs ont drifté |
| `data-harmonization/` | 4 chunks sur 5 | `architecture.md` est le design canonique verrouillé. Chunk 5 dans `BACKLOG.md` |

### Lab, cohortes, entraînement

| Dossier | Statut | À savoir |
|---|---|---|
| `cohort-pipeline/` | Cockpit livré | Remplacé comme cible par `work-in-progress/refacto-page-cohorte/` |
| `cohort-capture-flow/` · `cohort-readiness/` | Livré / consommé | Le flow selection→CSV→adb→sync est live |
| `lab-streamline/` | Livré | La **doctrine A** (train/bench split : les captures device ne passent JAMAIS au training) reste vraie et importante |
| `training-pipeline/` | Sprints livrés | Phase 4 (user-harvest in-app) gatée sur l'app Android → `BACKLOG.md` |
| `improvement-loop/` | Journal | Trace d'une boucle diagnostic → nettoyage → réentraînement de juin |
| `dino-suggestions/` | Supersédé | Remplacé par `banque-dino/` puis `peche-dino/` (août) |
| `design-groups-standards/` | Pilote BE livré | Le modèle réel est une **FK scalaire** `coins.design_group_id`, pas une table pivot. Cf. [ADR-013](../adr/013-la-maille-est-la-classe.md) |
| `storage-hardening/` | Fix livré | Retry-backoff borné sur `local_path()` |

### App Android et design

| Dossier | Statut |
|---|---|
| `app-redesign/` · `design/` | Itérations design antérieures. La source de vérité est `admin/packages/proto/` (R1) |
| `best-frame-capture/` | Chunks 1-7 livrés, parité Kotlin↔Python verrouillée. Reste le bench 50 sessions → `BACKLOG.md` |
| `coinsnap-teardown/` | Teardown concurrent, juin 2026 |
| `phases/` · `features/` | Planification ML/data historique, encore liée depuis `research/` et `mission/` |

### Divers

`operations/`, `research/`, `coin-richness/` (kickoffs consommés), `cohort-capture-ablation.md`,
`datasets-minio-migration.md`, `numista-clean-refetch-kickoff.md`.

## Ce qui a été supprimé le 2026-08-24

Douze dossiers et six fichiers sans lecteur ni lien entrant, livrés ou périmés depuis mai :
`augmentation-benchmark/`, `coin-3d-viewer/`, `research-drafts-content/`,
`research-phase-2c/`, `research-yolo-history/`, `scan-normalization-phases/`,
`scan-normalization/`, `sources-lmdlp/`, `referential-bce/`, `referential-fixes/`,
`lab-prod-refacto/`, `refacto/`, plus les handoffs i18n, `NEXT-SESSION.md`,
`open_questions.md` et `numista-clean-refetch-progress.md`.

Ils restent dans l'historique git. Une archive qu'on ne relit jamais n'est pas une
archive, c'est du bruit.
