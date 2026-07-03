# local-sync — walkthrough de validation PO (Mac → VPS → PC)

> À dérouler une fois le code tiré sur chaque machine. Le VPS est déjà déployé
> (endpoints `/db/events/push|pull` live, vérifiés au déploiement). Prérequis
> par machine : `direnv` chargé (EURIO_API_URL + EURIO_API_TOKEN exportés).

## Phase 0 — Bootstrap du Mac (une fois, ~10 min)

```bash
cd ml
# 1. Dry-run : qu'est-ce qui diverge entre ma base locale et le canonique ?
go-task ml:db:sync-bootstrap
# → liste {asset: champs}. Sanity-check : ça doit ressembler à ton travail
#   récent (tri mix-zone-17, recrops…). Rien d'aberrant ?

# 2. Sauvegarde + seed du fichier de travail depuis le canonique
cp state/eurio.db "state/eurio.db.pre-sync-$(date +%F)"
go-task ml:db:pull-replica -- --dest state/eurio.db --force   # --force : on vient de sauvegarder

# 3. Rattrapage : ré-émet tes décisions locales par-dessus le seed
#    --from = la SAUVEGARDE (tes décisions) ; --db = le fichier seedé (reçoit
#    les events, et sert de référence canonique puisqu'il sort du seed).
go-task ml:db:sync-bootstrap -- --db state/eurio.db --from "state/eurio.db.pre-sync-$(date +%F)"
```

Relis le dry-run (il doit refléter ton travail local), puis relance la même
commande avec `-- … --apply`.

```bash
# 4. Premier sync : le backfill monte au VPS
go-task ml:db:sync
# → JSON : ok=true, pushed=N (≈ le nombre d'assets du dry-run)
```

**Vérif côté VPS** (le travail Mac est dans le canonique) :

```bash
ssh serverOimNixDontpanic 'docker exec eurio-api python -c "
import sqlite3; c = sqlite3.connect(\"/var/lib/eurio/eurio.db\")
print(c.execute(\"SELECT COUNT(*) FROM image_state_events WHERE reason=\x27bootstrap_backfill\x27\").fetchone()[0], \"events backfill\")
"'
```

## Phase 1 — Sync auto au fil de l'eau (Mac)

1. `go-task ml:api` + front local (`pnpm dev`) → **badge en bas de sidebar**,
   pastille verte « Sync il y a X min » (ou « jamais synchronisé » au début).
2. Dans le Jeu d'entraînement : exclure un crop du train (« Exclure »).
   → le badge passe « 1 en attente » (pastille verte, compteur au popover).
3. Attendre ≤ 10 min (debounce) OU cliquer le bouton du badge.
   → pastille orange « Synchronisation… » puis verte « à l'instant ».
4. **Vérif VPS** — l'event et la matérialisation y sont :

```bash
ssh serverOimNixDontpanic 'docker exec eurio-api python -c "
import sqlite3; c = sqlite3.connect(\"/var/lib/eurio/eurio.db\")
r = c.execute(\"SELECT reason, machine, hlc FROM image_state_events WHERE machine!=\x27vps\x27 AND hlc IS NOT NULL ORDER BY hlc DESC LIMIT 3\").fetchall()
print(*r, sep=chr(10))
"'
```

## Phase 2 — Reprise sur le PC

1. Tirer le repo (`git pull`), puis Phase 0 pour le PC (sa propre divergence,
   probablement plus petite : recrops/bidouilles).
2. `go-task ml:api` → le worker fait un pull-only au premier cycle (ou clic
   badge) → **le crop exclu sur le Mac est exclu ici aussi** (vérifier dans le
   Jeu d'entraînement).
3. Modifier quelque chose côté PC (ex. réassigner un crop), sync, retour Mac,
   sync (ou attendre le pull-only) → la modif PC est sur le Mac.

## Phase 3 — Scénarios de robustesse

- **Offline** : couper le réseau, trier 2-3 crops → badge « N en attente » ;
  raccrocher le réseau → cycle suivant (≤10 min ou bouton) → tout part, badge
  vert. Rien n'est perdu.
- **Conflit (cas 3 du handoff)** : sur le MÊME crop, décider A sur le Mac,
  sync ; puis décider B sur le PC, sync ; re-sync Mac → les DEUX machines et
  le VPS montrent B (dernière décision). L'event A reste visible dans le log
  (`image_state_events`).
- **Recrop manuel** : recadrer un crop sur le Mac (coin-detail ou review),
  sync → sur le PC, après sync, les colonnes (bbox/phash) sont à jour et le
  PNG re-téléchargé depuis MinIO est le nouveau. (v1 : si l'ancien PNG est
  encore dans le cache disque du PC, un recrop/re-scan le rafraîchit — hint
  `cache_invalidate` transporté, purge auto au replay = amélioration v1.1.)
- **Suppression** : supprimer un crop indécidé (Sync crops) sur une machine →
  après sync, il a disparu partout (tombstone terminal).

## Ce qui doit rester vrai (invariants)

- `sync_outbox` locale vide (ou en route) après un cycle vert ; jamais de
  purge d'un op non poussé.
- `image_state_events` ne rétrécit JAMAIS (audit) — seule l'outbox se purge.
- Un `pull-replica` sur un fichier avec pending REFUSE (garde anti-perte).
- Le VPS ne pousse rien (mode hub) : `sync_outbox` du canonique reste vide.

## En cas de pépin

- Badge rouge → popover : l'erreur exacte (réseau ? 401 PAT ? 422 payload).
  Backoff auto 60→900 s ; `POST /sync/trigger` pour forcer.
- API locale down → `go-task ml:db:sync` (même cycle, en CLI).
- Diagnostic : `sqlite3 state/eurio.db "SELECT status, COUNT(*) FROM sync_outbox GROUP BY status"`
  et `SELECT * FROM sync_state`.
