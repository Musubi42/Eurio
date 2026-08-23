# Nettoyage — inventaire du lot 9

> Tenu à jour **au fil des lots**, exécuté à la fin. Découvrir cet inventaire le
> dernier jour, c'est en oublier la moitié (cf. D10).

## À supprimer une fois les lots 1-8 vérifiés

### Code — le tampon et ses deux fronts

| Chemin | Quoi | Remplacé par |
|---|---|---|
| `ml/review_service/` | 9 fichiers (app, auth, db, manage, routes_*) | `serving/review_queue/` sur le canonique |
| `ml/serving/review_routes.py` | claim/publish/decisions/ack/flow (tampon en OIDC) | lot 7 (bail) + écriture directe |
| `ml/serving/review_db.py` | wrapper `review.db` | — |
| `ml/review/publish_cli.py` | pont publish / reconcile | — (D1) |
| `admin/packages/review/` | mini-app reviewer standalone | `studio-local` (D2, D4) |
| `infra/review/` | conteneur `eurio-review.musubi.dev` | `eurio-admin.musubi.dev` |

⚠️ **`infra/review/` est EN SERVICE.** Arrêter le conteneur et retirer les labels
Traefik **avant** de supprimer les fichiers, sinon Traefik garde une route vers un
backend mort.

### Tâches

`ml/tasks.yml:667-690` — les 5 tâches `review:serve`, `review:reviewer:add`,
`review:reviewer:list`, `review:publish`, `review:reconcile`.

### Front — ce que le lot 8 a rendu redondant

| Chemin | Quoi | Remplacé par |
|---|---|---|
| `admin/.../review/pages/PeerArbitrationPage.vue` | arbitrage UNITAIRE (une décision à la fois, + table par reviewer) | `ArbitrageBulkPage.vue` (`/review/arbitrage`) |
| route `review/peer-arbitration` (`app/router.ts`) | — | rediriger vers `/review/arbitrage` |

⚠️ Conservée **délibérément** jusqu'ici (D10 : on ne supprime pas au fil de l'eau,
on supprime quand le remplaçant est prouvé). Sa page d'état vide pointe déjà vers
la vue en lot. Au moment de la retirer, vérifier qu'elle n'est plus le seul accès
à `/peer-arbitration/reviewers` (les onglets de la vue bulk la consomment aussi).

### Références résiduelles

| Fichier | Ligne | Quoi |
|---|---|---|
| `ml/tests/test_verdict_anchors_scope.py` | `:35` | `"review/publish_cli.py"` dans la liste de scope |
| `ml/shared/verdict_scope.py` | `:10` | mention de `review/publish_cli.py` en commentaire |
| `ml/eurio_ml.egg-info/` | — | régénéré au build, rien à faire à la main |

### Documentation

| Chemin | Sort |
|---|---|
| `docs/work-in-progress/collaborative-review/` | 11 fichiers — supprimés, supersédés par ce chantier |
| `docs/work-in-progress/auth-redesign/ROADMAP.md` | K2 passe de ⬜ à ✅, pointe ici |
| `docs/work-in-progress/auth-redesign/ARCHITECTURE.md` | §7 « Spec friends review (à statuer plus tard) » — tranché, à réécrire ou supprimer |
| `CLAUDE.md` | §Secrets — la phrase « `infra/review/` reste **en service** » devient fausse |
| mémoire `project_friends_review_deferred` | plus vraie — à retirer |

### Secrets devenus inutiles

`infra/review/secrets/` (`review_admin_token`, `review_session_secret`, les deux clés
MinIO) — pattern Docker secrets déjà déprécié. Vérifier qu'aucun n'est référencé
ailleurs avant suppression.

## Ce qu'on NE supprime pas

- `ml/review/peer_arbitration_routes.py` — **réutilisé** par le lot 8
- `peer_review_decisions` — la table de quarantaine (D7)
- `ml/review/review_queue_routes.py` — le legacy lourd reste la voie locale du Mac
  (recadrage, auto-crop, détection) tant que `:8042` existe

## Garde-fou

⚠️ **Ne jamais `git clean -xdf`** dans ce dépôt : `infra/backup/staging/` contient
6,6 Go de données gitignorées (sur le VPS).
