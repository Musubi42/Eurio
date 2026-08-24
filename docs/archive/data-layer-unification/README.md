> 🗄️ **Archivé le 2026-08-24.** Livré. Le résiduel — retrait du bucket `eurio-db` — est dans [`docs/BACKLOG.md`](../../BACKLOG.md).

# data-layer-unification

> Chantier en cours depuis le 2026-06-19 : unifier toute la donnée Eurio
> derrière `eurio-api.musubi.dev` (SQLite source de vérité). Décommissionner
> les chemins legacy (Supabase direct frontend, MinIO `eurio-db` bucket,
> lease workflow).

## Vision en 3 lignes

> Une seule porte d'entrée data (`eurio-api`), heavy compute reste local
> mais écrit via HTTP, architecture layered propre (model/repository/
> service/router). L'app Android continue à lire Supabase comme aujourd'hui
> (mirror).

Détail : [`VISION.md`](./VISION.md).

## Statut

| Phase | Description | Statut |
|---|---|---|
| 0 | État initial vérifié (VPS = source de vérité) | ✅ 2026-06-19 |
| 1 | Orphan tables Supabase (confusion_map + sets_audit) | ✅ 2026-06-19 |
| 2a | Endpoints `/coins/*` + refactor coins composables | ✅ 2026-06-19 |
| **2b** | **Endpoints `/sources/*` (READ) — pattern layered inaugural** | **⬜ next** |
| 2c | Endpoints `/review-queue/*` (READ) | ⬜ |
| 2d | Endpoints `/training-runs/*` (READ) | ⬜ |
| 2e | Mints / referential / cohorts / bench / augmentation | ⬜ |
| 3 | Refactor composables studio-local restants | ⬜ |
| 4 | Drop `@supabase/supabase-js` | ⬜ |
| 5 | Kill MinIO `eurio-db` + lease workflow | ⬜ |
| 6 | ML compute local en client HTTP de eurio-api | ⬜ |

Détail : [`ROADMAP.md`](./ROADMAP.md).

## Documents

| Doc | Rôle | Quand le lire |
|---|---|---|
| [`VISION.md`](./VISION.md) | Pourquoi + cible architecturale + 3 principes | En premier — pour saisir la direction |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | Pattern layered backend, conventions de code, exemple complet | Avant d'écrire un endpoint |
| [`ROADMAP.md`](./ROADMAP.md) | Phases avec statut + tracking composables | Pour situer le travail courant |
| [`DECISIONS.md`](./DECISIONS.md) | Log chronologique D-01 → D-NN | Pour comprendre l'historique |
| [`HANDOFF-NEXT-SESSION.md`](./HANDOFF-NEXT-SESSION.md) | Plan d'exécution prochaine session | En début de session pour reprendre |

## Mises à jour

- **ROADMAP.md** : MAJ à la fin de chaque phase / sous-chunk
- **DECISIONS.md** : append-only, ID `D-NN-YYYY-MM-DD` quand décision
  structurelle
- **HANDOFF-NEXT-SESSION.md** : **réécrit** à la fin de chaque session
  par celui qui pose la session (pas append-only)
- **VISION.md** et **ARCHITECTURE.md** : modifiables si pivot ou
  raffinement du pattern, sinon stables

## Lien avec autres chantiers

- [`../auth-redesign/`](../auth-redesign/) — refonte auth (C1 → C5 done,
  pivot frontend dual fait). C'est le prédécesseur direct de ce chantier.
  Cf. `auth-redesign/ARCHITECTURE.md` pour le contexte dual studio-local
  + admin-vps.
- [`../auth-redesign/PAT-WORKFLOW.md`](../auth-redesign/PAT-WORKFLOW.md) —
  comment générer / coller le PAT côté Mac/PC pour que studio-local taper
  `eurio-api`.
- CLAUDE.md racine — règles repo (R0 pas de dette, R0bis frontend dual)

## Mémoires persistantes Claude

- `project_data_unification` (à créer côté memory si pas déjà)
- `project_frontend_dual` (déjà existant)
- `project_auth_redesign_status` (déjà existant)