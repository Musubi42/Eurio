# Review collaborative — Vision & index

> **Statut (corrigé 2026-07-04) : IMPLÉMENTÉ localement, testé E2E — reste le déploiement
> VPS.** Le service complet vit dans `ml/review_service/` (app, auth cookie HMAC, db, routes
> reviewer/admin, régie reviewers — chunks 1/2/4 livrés). Ne PAS re-designer/ré-implémenter :
> voir `08-implementation-plan.md` pour les chunks restants (déploiement `09-vps-deploy.md`).
> _(L'ancien statut « CONCEPTION — rien n'est implémenté » du 2026-06-08 était périmé.)_

## Le problème

La review manuelle des pièces (crops eBay → identification) va rester **majoritaire**
même avec l'auto-validation. Seul, Raphaël ne tiendra pas le volume. On veut faire
**reviewer des amis non-techniques, en parallèle, chacun sur son PC**.

Le modèle actuel (`eurio.db` SQLite derrière un lease manuel Mac/PC, un seul
écrivain à la fois) ne le permet pas : il suppose un utilisateur unique et des
sessions alternées. Cf. `docs/refacto-ml/chunk6-vps-minio.md` et la doctrine
SQLite-only.

## Le recadrage

Ce **n'est pas** un problème de débit SQLite. Une décision de review est une
écriture minuscule et rare (un humain clique toutes les ~10-30 s). SQLite en WAL
encaisse 10 reviewers sans transpirer. Les vrais problèmes sont :

1. **Où vit la surface d'écriture collaborative** → pas derrière le lease Mac/PC ;
   il faut un endroit **toujours allumé** : le **VPS**.
2. **Servir des items distincts** sans collision → claim/lease atomique.
3. **Auth + UX ultra-simple** pour des non-techniques.
4. **Qualité des décisions** → arbitrage admin par Raphaël (pas un merge de
   conflits d'écriture, qui n'existeront quasiment pas).

## L'architecture en une image

```
┌─────────────────────────┐         ┌──────────────────────────────┐
│  DEV CANONIQUE           │ publish │  SERVICE REVIEW (VPS)        │
│  eurio.db (Mac/PC)       │────────▶│  review.db (SQLite WAL)      │
│  lease actuel inchangé   │         │  FastAPI + front minimal     │
│  référentiel/training    │◀────────│  toujours allumé             │
└─────────────────────────┘ reconcile└──────────────────────────────┘
                                              ▲   ▲   ▲
                                          Paolo Ana  Théo  (amis, web)
```

- **eurio.db reste canonique.** Le service review est un **tampon de travail**
  transient, exactement comme MinIO est le tampon des images. Doctrine intacte.
- **Pas de Redis, pas de Vercel** pour cette surface, **pas de Postgres.**

## Décisions actées (2026-06-08)

| Sujet | Décision |
|---|---|
| Backend review | **SQLite `review.db` dédié, FastAPI, sur le VPS** |
| Fenêtre de claim | **10 items** par reviewer, avec compteur + gamification, puis « encore 10 ? » |
| Modèle de vote | **1 reviewer par item** (pas de double-vote auto en v1) |
| Qualité | **Arbitrage admin** par Raphaël, vue rapide façon `AutoValidateVerdict` |
| Auth | Token dans l'URL (`?u=Paolo42`) = identité **et** mot de passe ; modale si absent |
| Identité | Chaque décision tracée `decided_by = <token>` pour juger la qualité par reviewer |

## Index des fichiers

| Fichier | Contenu |
|---|---|
| [`01-architecture.md`](01-architecture.md) | Les 3 surfaces, service VPS, stack, déploiement |
| [`02-data-model.md`](02-data-model.md) | Schéma `review.db` + additions côté `eurio.db` |
| [`03-claim-queue-ux.md`](03-claim-queue-ux.md) | Claim atomique, fenêtre de 10, compteur, gamification |
| [`04-auth.md`](04-auth.md) | Token-dans-l'URL, modale, table reviewers |
| [`05-admin-arbitration.md`](05-admin-arbitration.md) | Passe d'arbitrage de Raphaël, qualité, évolutions |
| [`06-frontend.md`](06-frontend.md) | UI reviewer minimale (carte, candidats, célébration) |
| [`07-reconciliation.md`](07-reconciliation.md) | publish / reconcile, idempotence, go-task |
| [`08-implementation-plan.md`](08-implementation-plan.md) | Découpage en chunks |

## Hors périmètre

- ❌ Redis / file de messages externe (le claim atomique suffit).
- ❌ Vercel pour le front reviewer (il vit sur le VPS).
- ❌ Migration vers Postgres / Supabase comme canonique.
- ❌ Double-vote automatique entre amis, gold items, score de trust auto
  (gardés en **évolutions futures**, cf. `05-admin-arbitration.md`).
