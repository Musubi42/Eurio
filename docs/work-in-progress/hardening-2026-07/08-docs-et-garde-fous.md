# 08 — Docs à jour & garde-fous durables (leçons des sessions passées)

> Fiche de remédiation auto-portée — audit hardening 2026-07. Deux volets : (A) nettoyer le
> drift doc↔code qui trompe les futurs agents ; (B) poser les garde-fous pour que les
> difficultés **récurrentes** des sessions passées ne remordent plus.

## A. Doc-drift à corriger

Certaines corrections urgentes ont **déjà été appliquées** par la session d'audit (marquées ✅).

| Sév. | Doc | Drift | État |
|---|---|---|---|
| high | `docs/operations/secrets-followup.md` | Affirme « secrets caviardés de tout l'historique » — **faux**, re-fuités via `.envrc copy` | ✅ corrigé (bandeau alerte) |
| high | `docs/work-in-progress/model-b/README.md` | « event-log livré/converge » alors qu'abandonné le jour même (Direction A) | ✅ corrigé (bandeau) |
| medium | `docs/work-in-progress/collaborative-review/README.md` | « CONCEPTION, rien n'est implémenté » alors que `ml/review_service/` complet | ✅ corrigé |
| medium | `CLAUDE.md` §Commandes | `android:snapshot` / `snapshot-dry` n'existent plus (→ `ml:build-app-core`) | ✅ corrigé |
| high | `docs/work-in-progress/local-sync/HANDOFF-next-session.md` | Périmé de 5 commits : liste comme « à faire » des gaps déjà fermés (`d0d2fb3`+) | ⏳ à régénérer |
| medium | `docs/work-in-progress/README.md` | Bloc « Focus actuel » (2026-06-30) muet sur Direction A, le chantier le + critique | ⏳ à faire |
| low | `docs/design/_shared/components-parity.md` | Documente ~25 composables `EurioXxx` qui n'existent dans aucun fichier | ⏳ à faire |
| low | `docs/design/_shared/scene-parity.md` | Aucune ligne pour `ProfileHistory.vue` (route livrée) — viole R4 | ⏳ à faire |
| low | `admin/.../confusion/useConfusionMap.ts` | Fonctions nommées `…FromSupabase` alors qu'elles lisent eurio.db (commentaire l'admet) | ⏳ à faire (cf. fiche 02) |

**Chunk A** : régénérer `HANDOFF-next-session.md` depuis l'état réel (`c4-c8-known-gaps.md` +
`replica-auto-sync.md`) ; ajouter `local-sync/` au « Focus actuel » de `docs/work-in-progress/README.md`
tant que Direction A n'est pas close ; corriger les 3 drifts `low` de parité.

## B. Difficultés récurrentes → garde-fous

L'audit des HANDOFF/RESUME/friction-log + `git log` révèle un **même motif** qui a mordu
plusieurs fois : **l'échec silencieux** (le code affiche « succès » alors que rien n'a eu lieu),
et le **doc-handoff périmé** (un fichier « à lire en premier » qui décrit un état obsolète).

### B.1 — Échecs silencieux (le fil rouge)

| Incident passé | Statut aujourd'hui |
|---|---|
| event-log : bulk qui « ne voyage pas », succès affiché | Réglé par abandon (Direction A) |
| `sqlite3_rsync` rc=0 no-op (distant refuse mais rc=0) | Réglé (`1594d30`) — mais heuristique « tout stderr = échec » fragile (cf. fiche 01) |
| `--reload` tue les subprocess détachés | Réglé pour cohort_jobs — **PAS** pour `/export/tflite` ni `/confusion-map/compute` (cf. fiche serving) |
| `isolation_level=None` : `conn.commit()` no-op, écritures partielles | **Ouvert** dans `lab_routes.py` (cf. fiche 07) |
| chemins DB hardcodés lus/écrits en silence sur le mauvais fichier | **Ouvert** (cf. fiche 01) |
| lecture de mock silencieuse quand ML API down (front) | **Ouvert** (cf. fiche 04) |
| `except ImportError: pass` masque un builder cassé en « skipped » | ✅ corrigé (`app_export/run.py`) |

**Garde-fou proposé — une règle CLAUDE.md + un test-lint** :

> **R7 (proposée) — Jamais d'échec silencieux.** Tout chemin qui peut échouer doit soit lever,
> soit logger l'échec réel de façon visible. Interdits explicites : `except …: pass` sur une
> opération I/O/DB (logger l'exception au minimum) ; un `return None`/fallback mock qui masque
> une indisponibilité sans le signaler à l'appelant/l'UI ; un `rc=0` déclaré succès sans vérifier
> l'effet. Un fallback dégradé doit être **observable** (log + indicateur).

Outillage concret (chunk B.1) :
- Un check CI `grep` qui échoue si un `except (ImportError|Exception):` est suivi d'un `pass` nu
  dans `ml/` (allowlist par commentaire `# noqa: silent-ok <raison>`).
- Étendre le fix `app_export` : appliquer le même durcissement aux 2 endpoints subprocess non
  détachés (fiche serving).

### B.2 — Bypass du writer canonique (Direction A)

Plusieurs scripts/routes écrivent encore en direct sur `ml/state/eurio.db` local sans passer par
`/ingest` VPS et sans honorer `EURIO_DB_READONLY` (cf. fiches 01 & 07). Le garde-fou
`_vps_only_guard.py` existe mais ne couvre que 3 scripts sur ~30.

**Garde-fou proposé (chunk B.2)** :
- Un test qui, avec `EURIO_DB_READONLY=1`, importe chaque script de `ml/scripts/` qui écrit et
  assert qu'il refuse (ou passe par `Store`, qui honore le flag). Interdire `sqlite3.connect()`
  direct hors `ml/store/` via un check `grep` allowlisté.
- Coupler `EURIO_DB_PATH`→réplique et `EURIO_DB_READONLY` (refus au boot si la réplique est
  ouverte en écriture — cf. fiche 01).

### B.3 — HANDOFF/doc périmé (« à lire en premier » = piège)

Le pattern a mordu ≥2 fois (`HANDOFF-next-session.md` périmé de 5 commits ; `model-b/README.md`
« seul doc » contredit par `local-sync`). Un fichier auto-déclaré « point d'entrée unique » qui
n'est pas maintenu est pire que pas de doc : il **oriente activement** vers le mauvais état.

**Garde-fou proposé (chunk B.3)** :
- **Convention** : tout chunk qui ferme un gap listé dans un HANDOFF **doit** mettre à jour ou
  archiver ce HANDOFF dans le même commit. Ajouter la règle à `CLAUDE.md` §Conventions.
- Envisager un **skill** `handoff-sync` (ou étendre `graphify`) : au démarrage d'une session,
  détecter les fichiers `HANDOFF*`/`RESUME*` dont le dernier commit est antérieur à N commits
  touchant le même dossier, et les signaler comme « potentiellement périmés » avant de les suivre.
- Dater les HANDOFF avec le **SHA du commit** qu'ils décrivent (pas juste la date) pour rendre le
  décalage détectable mécaniquement.

### B.4 — Collisions d'environnement (connu, déjà documenté)

Serveurs Vite en collision 5173/5174 (`feedback_proto_dev_server_collision`), `launchd`/TCC sur
macOS (réglé par le thread serveur). Pas d'action de code ; garder la doc à jour. Le thread
autopull dans `:8042` reste le mécanisme retenu sur Mac — documenté dans `replica-auto-sync.md`.

## Effort & priorité

1. **B.1 (échec silencieux)** — la règle R7 + le check `except…pass` est le garde-fou à plus fort
   levier (adresse le fil rouge de tous les incidents passés).
2. **B.2 (bypass writer)** — couple avec la fiche 01.
3. **A + B.3 (docs/handoff)** — peu risqué, à faire au fil de l'eau ; le skill `handoff-sync` est
   un investissement optionnel.
4. **B.4** — doc seulement.
