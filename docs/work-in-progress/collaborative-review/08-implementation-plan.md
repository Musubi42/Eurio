# 08 — Plan d'implémentation (chunks)

> Découpage en chunks autonomes (30 min – 3 h), livrés un par un avec audit visuel
> entre chaque (cf. `feedback_chunk_audit_flow`). Ne pas enchaîner sans « go ».

## Points à trancher avant de coder

1. **Process séparé vs routeur dans `ml/serving`** pour le backend review.
   Reco : **process séparé** (always-on VPS vs `ml/serving` local-only).
2. **Transport publish/reconcile** : HTTP authentifié vs script sur VPS lisant un
   dump. Reco : HTTP (`/admin/*`) pour rester découplé.
3. **Hébergement du front** : servi par le process FastAPI review, ou statique
   derrière le reverse-proxy.

## Chunks proposés

### C0 — Squelette service review (VPS)
- Process FastAPI séparé, `review.db` (schéma `02`), WAL + busy_timeout.
- systemd unit + reverse-proxy + sous-domaine HTTPS.
- `GET /health`. Seed `reviewers` à la main.
- **Livrable** : service joignable, base créée, un reviewer seedé.

### C1 — Auth
- `POST /auth`, cookie de session, middleware sur routes review.
- Validation token + `last_seen_at`. Cf. `04`.
- **Livrable** : `?u=Paolo42` connecte ; URL nue → 401 propre.

### C2 — Claim & décision (cœur backend)
- `POST /claim` (UPDATE atomique, fenêtre 10, TTL). Cf. `03`.
- `POST /items/{id}/decide`, `POST /items/{id}/skip`, `GET /me/stats`.
- Guards de concurrence (`WHERE claimed_by=?`).
- **Livrable** : flux complet testable au curl, deux tokens → items disjoints.

### C3 — Publish (eurio.db → review.db)
- `go-task review:publish` + `POST /admin/publish`.
- Résolution crop_url MinIO + candidates_json. UPSERT idempotent. Cf. `07`.
- **Livrable** : items open de eurio.db visibles dans review.db.

### C4 — Front reviewer
- Package `admin/packages/review`, carte de review, compteur, félicitation.
- Auth (lien + modale), tokens.css, mobile-first. Cf. `06`.
- **Livrable** : un ami peut reviewer 10 pièces de bout en bout.

### C5 — Reconcile + staging
- `go-task review:reconcile` + `GET /admin/decisions` + `peer_review_decisions`.
- Idempotence par `decisions.id`. Cf. `07`.
- **Livrable** : décisions des amis visibles en staging dans eurio.db.

### C6 — Vue d'arbitrage admin
- Page `/review/peer-arbitration` dans `admin/packages/web`.
- Grille crop + choix + qui + concorde/diverge (filet auto-validate). Approuver /
  rejeter en masse → applique `decide()` au canonique. Cf. `05`.
- Stats qualité par reviewer.
- **Livrable** : Raphaël arbitre le travail des amis et promeut au canonique.

## Évolutions futures (post-v1)

Double-vote, gold items, score de trust auto, classement amical. Cf. `05` §Évolutions.

## Dépendances / ordre

```
C0 ─▶ C1 ─▶ C2 ─▶ C4   (flux ami complet en local)
        └──▶ C3 ──┘
C2/C3 ─▶ C5 ─▶ C6       (boucle admin complète)
```
C4 peut démarrer dès que C2 est stable (mock publish en attendant C3).
