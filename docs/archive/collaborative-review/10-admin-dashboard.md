# 10 — Régie review : front admin auto-hébergé sur le VPS

> Statut : **conception figée**, prête à implémenter après le 09 (déploiement
> VPS OK). Le service review tourne, on a un CLI `manage` ; on veut maintenant
> piloter la gestion des reviewers depuis une vraie page web plutôt que d'aller
> `docker compose exec` à chaque fois.
>
> **Décision d'architecture (2026-06-08) : Option B — front admin auto-hébergé
> sur le VPS.** La régie ne vit PAS dans la console Vue Vercel
> (`admin/packages/web`). Elle est servie par `review_service` lui-même, sur
> `eurio-review.musubi.dev/admin`, gated par `REVIEW_ADMIN_TOKEN`. Voir
> « Pourquoi cette topologie » plus bas.

## Pourquoi

Aujourd'hui, pour ajouter un ami reviewer :
1. SSH sur le VPS.
2. `cd /opt/eurio/infra/review && docker compose exec review python -m review_service.manage add-reviewer --token Paolo42 --name Paolo`.
3. Recopier à la main `https://eurio-review.musubi.dev/?u=Paolo42` dans WhatsApp.

C'est friable, et surtout je veux **aussi** voir d'un coup d'œil qui review,
combien, à quel rythme, et pouvoir moi-même rentrer dans une session review
en un clic. Le CLI reste utile (bootstrap, disaster-recovery), mais la régie
quotidienne doit vivre dans une page web.

## Pourquoi cette topologie (Option B)

Trois machines sont dans le jeu :

```
Mac (moi)              Vercel                    VPS
─────────              ──────                    ───
admin/packages/web  →  (déployé statique)        review_service + review.db
ml API (local)         PAS de secret ici         /admin/* gated X-Admin-Token
secrets/dev.env                                  eurio-review.musubi.dev
(REVIEW_ADMIN_TOKEN)
```

Le secret `REVIEW_ADMIN_TOKEN` protège les routes `/admin/*`. Il ne doit
**jamais** finir dans un bundle front public (Vercel), sinon n'importe qui le
lit dans les sources du navigateur. Trois designs étaient possibles :

- **A — relais par l'API ml locale (Mac)** : page dans la console Vue, tape
  l'API ml locale qui détient le secret et relaie. Marche seulement quand le
  Mac tourne.
- **B — front admin auto-hébergé sur le VPS** *(retenu)* : `review_service`
  sert lui-même une page `/admin`, gated par le token tapé une fois. Autonome,
  toujours disponible, aucun relais, aucun secret côté front.
- **C — proxy serverless Vercel** : met le secret review dans Vercel et ajoute
  de l'infra qu'on n'a nulle part ailleurs.

**B est retenu** parce que la régie devient toujours disponible (créer une
invite depuis le téléphone un dimanche sans allumer le Mac), self-contained, et
sans exposition de secret : la page `/admin` est du HTML inerte qui demande le
token au chargement ; sans token valide, tous les `/admin/*` répondent 401.

## Forme cible

```
eurio-review.musubi.dev/          → front reviewer (existant, ?u=<token>)
eurio-review.musubi.dev/admin     → NOUVEAU front régie, gated REVIEW_ADMIN_TOKEN
```

`review_service` sert déjà son front reviewer statique sur `/` (mount avec
`html=True`). On ajoute un **second build** monté sur `/admin`, **avant** le
catch-all `/` dans `app.py` (ordre Starlette : sinon la SPA reviewer avale
`/admin`).

### Structure de code

- **Nouveau package** `admin/packages/review-admin/` (Vue 3 + Vite, même stack
  que `admin/packages/review`). Auth admin séparée proprement de l'auth
  reviewer — pas de route bricolée dans le front reviewer existant.
- Le `Dockerfile` (`infra/review/Dockerfile`) build les **deux** fronts ;
  l'entrypoint / `app.py` sert les deux dist (`/` et `/admin`).
- `VITE_REVIEW_API` du front régie pointe sur la même origine (`''` en prod
  puisque servi par le même service ; `http://localhost:8048` en dev).

### Login `/admin`

- Au chargement, si pas de token en `localStorage` → écran « colle ton
  `REVIEW_ADMIN_TOKEN` ».
- Token stocké en `localStorage`, envoyé en header `X-Admin-Token` sur chaque
  appel `/admin/*`. Un 401 vide le localStorage et re-demande.
- **Pas de couche supplémentaire** (pas de BasicAuth Traefik) : le token *est*
  déjà le secret, et je suis seul admin. Suffisant.

## Surface fonctionnelle

### a) Émettre un nouveau code

Formulaire :
- champ **Nom** (libre, ex. « Paolo »),
- champ **Code** (auto-généré court & mémorable type `Paolo42` /
  `mathis-coins-7q` ; éditable manuellement),
- bouton **Créer** → `POST /admin/reviewers {token, name}`.

`POST` **rejette un code déjà pris** (le token est PK) → message clair, pas de
silent overwrite.

Une fois créé, afficher en grand l'**URL complète prête à partager** + bouton
**Copier** + bouton **Partager via WhatsApp** (`https://wa.me/?text=…`
URL-encodé) :

```
https://eurio-review.musubi.dev/?u=Paolo42
```

> Le query param `?u=<code>` est **déjà supporté** par le front reviewer (la
> modale code n'apparaît que si le param est absent ou invalide) — rien à
> changer côté front reviewer.

### b) Voir qui review et combien

Tableau des reviewers, une ligne par reviewer :
- Nom, code masqué style `Pao•••42` (clic = révéler + copier),
- **Reviews totales** (compte `decisions`),
- **Reviews 7 derniers jours** (cadence),
- **Dernière activité** (timestamp relatif : « il y a 3 h », depuis
  `reviewers.last_seen_at`),
- **Items en cours de lease** (`review_items` `status='claimed'` &
  `claimed_by = token`) — pour repérer un ami qui a abandonné un batch,
- bouton **Révoquer** / **Réactiver**.

Tri par défaut sur « dernière activité » desc — actifs en haut, fantômes en
bas. Tout vient d'un seul `GET /admin/reviewers` qui agrège `review.db`.

**Révocation = soft-delete** (`is_active=0`), **jamais** hard-delete : les
`decisions` référencent `reviewer_token` en FK. Un reviewer révoqué ne peut
plus se logger ; il reste réactivable (`is_active=1`) depuis le tableau.

### c) Vue agrégée du flux

Bloc en haut de page :
- nombre d'items **en attente de review** (`review_items` `status IN
  ('open','claimed')`),
- nombre d'items **reviewés mais pas encore reconcile** (`decisions`
  `reconciled_at IS NULL`) = en attente d'un `go-task ml:review:reconcile`
  côté Mac,
- date du dernier `publish` et du dernier `reconcile`.

> `last_publish_at` / `last_reconcile_at` n'existent nulle part aujourd'hui.
> Ajouter une mini-table `meta (key TEXT PRIMARY KEY, value TEXT)` dans
> `review.db`, tamponnée par les endpoints `/admin/publish` et
> `/admin/decisions/ack` quand le Mac les appelle. C'est le seul morceau qui
> touche le chemin publish/reconcile existant.

### d) Entrer en mode reviewer depuis l'admin

Bouton **Reviewer moi-même** → ouvre `https://eurio-review.musubi.dev/?u=<mon-code>`
dans un nouvel onglet. Un reviewer dédié (ex. `raph`) créé au bootstrap ; le
front régie le liste déjà (table reviewers), donc rien à stocker en plus.

## Implémentation côté `review_service`

Routes admin à ajouter (toutes gated par `require_admin` = header
`X-Admin-Token` vs `REVIEW_ADMIN_TOKEN`, qui existe déjà pour
publish/reconcile) :

| Méthode | Route | Body / réponse |
|---|---|---|
| `GET`    | `/admin/reviewers`          | liste reviewers + stats agrégées (total, 7j, last_seen, in_flight, is_active) |
| `POST`   | `/admin/reviewers`          | `{token, name}` → crée (409 si token pris), renvoie `{token, name, url}` |
| `DELETE` | `/admin/reviewers/{token}`  | soft-revoke (`is_active=0`) |
| `POST`   | `/admin/reviewers/{token}/reactivate` | `is_active=1` |
| `GET`    | `/admin/flow`               | `{pending, awaiting_reconcile, last_publish_at, last_reconcile_at}` |

**Factorisation** : la logique create / revoke / list vit aujourd'hui dans
`manage.py`. L'extraire dans un module partagé (ex.
`review_service/reviewers.py`) appelé à la fois par le CLI et par les routes
HTTP — pas de duplication. Le CLI reste comme bootstrap / disaster-recovery.

**Schéma** : ajouter la table `meta` à `schema.sql` (idempotent,
`CREATE TABLE IF NOT EXISTS`). Wirer le tampon dans `routes_admin.py`
(`publish` → `meta['last_publish_at']`, `decisions/ack` →
`meta['last_reconcile_at']`).

## Hors scope (à NE PAS faire)

- ❌ Auth utilisateur sur l'admin lui-même au-delà du `REVIEW_ADMIN_TOKEN` —
  pas de système de comptes, le token suffit.
- ❌ Permettre à un reviewer de se créer un code lui-même — l'invite est
  toujours une action explicite de ma part (sinon n'importe qui s'inscrit).
- ❌ Stats temps-réel (websocket / polling agressif) — un bouton
  « rafraîchir » suffit.
- ❌ Régie dans la console Vue Vercel (`admin/packages/web`) — annulé par
  l'Option B.

## Suite

Une fois cette page en place, le 09 perd son CLI `manage` comme chemin
principal : on garde la doc CLI comme procédure de bootstrap / disaster
recovery (si le service est cassé), pas comme usage courant.

### Chunks d'implémentation

1. ✅ **Backend reviewers** — module `reviewers.py` (extrait de `manage.py`) +
   routes `GET/POST/DELETE/reactivate /admin/reviewers`, CLI re-câblé dessus.
2. ✅ **Backend flow** — table `meta`, route `/admin/flow`, tampon
   publish/reconcile.
3. ✅ **Front régie** — package `admin/packages/review-admin`, login token,
   sections a/b/c/d.
4. ✅ **Câblage déploiement** — Dockerfile build 2 fronts + copie des 2 dist,
   `app.py` mount `/admin` avant le catch-all `/`. Reste l'exécution du rebuild
   sur le VPS (ci-dessous).

### Procédure de déploiement (VPS)

```bash
# 1. Récupérer le code à jour sur le VPS
cd /opt/eurio && git pull

# 2. Rebuild + redémarrer le service (recompile les 2 fronts dans l'image)
cd /opt/eurio/infra/review
docker compose up -d --build

# 3. Créer mon reviewer perso (pour le bouton « ouvrir ↗ » / reviewer moi-même)
docker compose exec review python -m review_service.manage \
  add-reviewer --token raph --name Raphael

# 4. Vérifier
curl -s https://eurio-review.musubi.dev/admin/ | head -c 40   # doit servir le HTML régie
```

La page est alors sur **`https://eurio-review.musubi.dev/admin`**. Au premier
chargement, coller le `REVIEW_ADMIN_TOKEN` (celui de
`infra/review/secrets/review_admin_token`, le même que `publish`/`reconcile`).

> Audit visuel local avant de déployer :
> `pnpm --filter eurio-review-admin-front dev` (sur :5181, tape l'API
> `go-task ml:review:serve` sur :8048).
</content>
</invoke>
