# 01 — Architecture

## Trois surfaces d'écriture, trois maisons

| Surface | Maison | Accès | Possède |
|---|---|---|---|
| **Dev canonique** `eurio.db` | Mac/PC (lease actuel) | 1 writer alterné (Raphaël) | référentiel, sources, training, exports |
| **Service review** (NOUVEAU) | VPS, toujours allumé | N writers (amis) — trivial en WAL | queue live, décisions, claims, identité reviewer |
| **Pont de réconciliation** | scripts go-task | batch push/pull | synchro entre les deux |

Le **service review** est le seul composant always-on nouveau. Tout le reste est
inchangé.

## Pourquoi ce découpage

- Les amis reviewent en concurrence sur un service allumé → **zéro conflit** avec
  le lease dev de Raphaël.
- La review **sort de l'équation du lease** : pendant un training PC, Raphaël peut
  continuer à bosser sur Mac (référentiel, cohortes) sans que la review n'entre en
  compétition pour `eurio.db`.
- **SQLite partout.** `eurio.db` reste canonique ; `review.db` est un tampon
  transient. Pas de migration de base.

## Stack du service review

- **Backend** : FastAPI + `sqlite3` standard (mêmes patterns que `ml/store/` :
  WAL, `busy_timeout`, transactions courtes `BEGIN IMMEDIATE`). Pas besoin des
  UDFs phash ici (le service ne fait pas de dédup d'images).
- **Base** : `review.db` (SQLite WAL) sur le disque du VPS. Voir `02-data-model.md`.
- **Front** : app web minimale, mobile-first, servie par le même process (ou en
  statique à côté). Voir `06-frontend.md`.
- **Images** : les crops sont déjà sur **MinIO** ; le front les charge via URL
  présignée / publique-lecture. Le service ne stocke pas d'images, juste des URLs.

## Concurrence SQLite — pourquoi ça tient

- WAL = 1 writer + N readers simultanés sans contention.
- Le writer/writer se règle avec `busy_timeout` (≥ 5 s) + transactions courtes.
- Volume réel : ~10 reviewers cliquant toutes les 10-30 s = quelques écritures de
  quelques octets par seconde. SQLite ne transpire pas.

Références : `sqlite.org/wal`, pattern claim/lease type `FOR UPDATE SKIP LOCKED`
émulé par un `UPDATE` atomique (cf. `03-claim-queue-ux.md`).

## Déploiement VPS

- Process géré par **systemd** (auto-restart, survie au reboot). Le VPS fait déjà
  tourner MinIO ; le service review vit à côté.
- Reverse-proxy (Caddy/nginx déjà en place ?) → sous-domaine type
  `review.<domaine>` en HTTPS.
- **Pas de Vercel** : Vercel est statique/serverless sans état long ; on a besoin
  d'un service stateful always-on.

## Où vit le code dans le monorepo

Proposition (à confirmer au moment de l'implémentation) :

```
admin/packages/review/        # nouveau package : front reviewer minimal
ml/review_service/            # ou un petit service FastAPI dédié (à trancher :
                              # réutilise-t-on ml/serving ou un process séparé ?)
```

> **Point ouvert** : le backend review tourne-t-il dans un process FastAPI
> **séparé** (recommandé — isolé du dev local, déployable seul sur VPS) ou
> est-il un routeur de plus dans `ml/serving/server.py` ? Le service review étant
> always-on sur VPS alors que `ml/serving` est local-only, un **process séparé**
> semble plus propre. À acter en `08-implementation-plan.md`.
