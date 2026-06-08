# 10 — Régie review depuis le dashboard admin (suite du 09)

> Statut : **intention produit**, à implémenter après le 09 (déploiement VPS
> OK). Le service review tourne, on a un CLI `manage` ; on veut maintenant
> piloter tout ça depuis la console admin Vue plutôt que d'aller `docker
> compose exec` à chaque fois.

## Pourquoi

Aujourd'hui, pour ajouter un ami reviewer :
1. SSH sur le VPS.
2. `cd /opt/eurio/infra/review && docker compose exec review python -m review_service.manage add-reviewer --token Paolo42 --name Paolo`.
3. Recopier à la main `https://eurio-review.musubi.dev/?u=Paolo42` dans WhatsApp.

C'est friable, et surtout je veux **aussi** voir d'un coup d'œil qui review,
combien, à quel rythme, et pouvoir moi-même rentrer dans une session review
en un clic depuis l'admin. Le CLI reste utile (bootstrap, debug), mais la
régie quotidienne doit vivre dans `admin/packages/web`.

## Surface fonctionnelle visée

Une page admin `/review/reviewers` (à câbler dans la nav existante) avec :

### a) Émettre un nouveau code

Formulaire :
- champ **Nom** (libre, ex. « Paolo »),
- champ **Code** (par défaut auto-généré court & mémorable type
  `Paolo42` / `mathis-coins-7q` ; éditable manuellement),
- bouton **Créer** → POST `/admin/reviewers` sur `review_service`,
- une fois créé, afficher en grand l'**URL complète prête à partager** avec
  bouton **Copier** :

  ```
  https://eurio-review.musubi.dev/?u=Paolo42
  ```

  Idéalement aussi un bouton **Partager via WhatsApp** (lien
  `https://wa.me/?text=…` URL-encodé) pour envoyer en un tap depuis le tel.

> Le query param `?u=<code>` est **déjà supporté** par le front review (la
> modale code n'apparaît que si le param est absent ou invalide) — rien à
> changer côté front review.

### b) Voir qui review et combien

Tableau des reviewers avec, par ligne :
- Nom, code (masqué style `Pao•••42`, hover/clic = révéler + copier),
- **Reviews totales** (compte des décisions enregistrées),
- **Reviews 7 derniers jours** (cadence),
- **Dernière activité** (timestamp relatif : "il y a 3h"),
- **Items en cours de lease** par ce reviewer (ceux claim mais pas encore
  décidés — utile pour détecter un ami qui a abandonné un batch).

Trier par défaut sur "dernière activité" desc — les actifs en haut, les
fantômes en bas.

### c) Vue agrégée du flux

Un petit bloc en haut de page :
- nombre d'items **en attente de review** (claim_window plein vs vide),
- nombre d'items **reviewés mais pas encore reconcile** (= en attente d'un
  `go-task ml:review:reconcile` côté Mac),
- date du dernier `publish` et du dernier `reconcile`.

Ça me dit en un coup d'œil "j'ai besoin de relancer un publish" ou "j'ai du
travail d'arbitration côté Mac".

### d) Entrer en mode reviewer depuis l'admin

Bouton **Reviewer moi-même → ouvre `https://eurio-review.musubi.dev/?u=<mon-code>`**
dans un nouvel onglet. Pour ça, me créer un reviewer dédié (ex. `raph`)
au bootstrap, et stocker mon code dans l'admin (ou dans `localStorage` du
navigateur — peu importe, c'est juste mon poste).

## Implémentation côté `review_service`

Routes admin à ajouter (toutes gated par `REVIEW_ADMIN_TOKEN`, comme
publish/reconcile) :

| Méthode | Route | Body / réponse |
|---|---|---|
| `GET`  | `/admin/reviewers`            | liste reviewers + stats agrégées (count, last_seen, in_flight) |
| `POST` | `/admin/reviewers`            | `{token, name}` → crée, renvoie l'URL complète |
| `DELETE` | `/admin/reviewers/{token}`  | révoque (= suppression simple : le pote ne peut plus se logger) |
| `GET`  | `/admin/flow`                 | `{pending, awaiting_reconcile, last_publish_at, last_reconcile_at}` |

`last_publish_at` / `last_reconcile_at` : à stocker dans une mini-table
`meta` (`key TEXT PRIMARY KEY, value TEXT`) dans `review.db`, posée par les
endpoints `publish` / `reconcile` quand le Mac les appelle.

## Implémentation côté `admin/packages/web`

Nouvelle page Vue `ReviewersAdmin.vue`, sous la même nav que l'arbitration
existante (`/review/peer-arbitration`). Pattern proxy local-only pour le
backend review : ajouter `VITE_REVIEW_SERVICE_URL` (default
`https://eurio-review.musubi.dev`) et lire `REVIEW_ADMIN_TOKEN` côté
backend uniquement (jamais exposé au front Vercel) — donc les appels
admin passent par un endpoint relais sur le serveur de dev ou via un
proxy Vercel serverless qui injecte le header.

> ⚠️ **Pas de token admin dans le bundle front.** Le front Vercel n'a pas
> de secret. Soit l'admin tourne en local seulement (déjà le cas pour
> training & parity), soit on ajoute une route Vercel server-side qui
> détient le token et relaie. À trancher au moment de l'implémentation.

## Hors scope (à NE PAS faire)

- ❌ Auth utilisateur sur l'admin lui-même — déjà discuté ailleurs, le
  dashboard reste local-only ou gated par BasicAuth côté Vercel, mais
  pas de système de comptes.
- ❌ Permettre à un reviewer de se créer un code lui-même — l'invite est
  toujours une action explicite de ma part (sinon n'importe qui peut
  s'inscrire).
- ❌ Stats temps-réel (websocket / polling agressif) — un refresh page ou
  un bouton "rafraîchir" suffit largement.

## Suite

Une fois cette page en place, le 09 perd son CLI `manage` comme chemin
principal : on garde la doc CLI comme procédure de bootstrap / disaster
recovery (si l'admin est cassé), pas comme usage courant.
