# 04 — Authentification

## Principe (décision actée)

Auth **volontairement minimale**. On ne protège pas des secrets d'État : on évite
juste que n'importe qui tombe sur l'outil et pollue les données. Raphaël transmet
le lien lui-même en chat privé.

Le **token est à la fois l'identité et le mot de passe**. Exemple : l'ami Paolo a
le token `Paolo42`.

## Deux portes d'entrée

1. **Lien direct (cas nominal)** : Raphaël envoie
   `https://review.<domaine>/?u=Paolo42`. Le front lit le query param `u`, valide
   le token côté serveur, pose un cookie de session, et **nettoie l'URL** (retire
   `?u=` de la barre d'adresse pour éviter qu'il traîne).

2. **URL nue + modale** : si l'ami arrive sur `https://review.<domaine>/` sans
   query param, une petite modale demande « Ton code ? » → il tape `Paolo42` →
   même validation.

## Validation côté serveur

```
POST /auth   { token: "Paolo42" }
  → SELECT * FROM reviewers WHERE token=? AND is_active=1
  → si ok : set-cookie session (signé), UPDATE last_seen_at
  → si ko : 401, modale affiche "Code inconnu"
```

- Session = cookie httpOnly signé contenant le token (ou un id de session mappé).
  Durée longue (ex. 30 j) — c'est du confort, pas de la sécurité forte.
- Toutes les routes review exigent un cookie valide.

## Table `reviewers`

Seedée à la main par Raphaël (un INSERT par ami). Cf. `02-data-model.md`.

```sql
INSERT INTO reviewers (token, display_name, created_at)
VALUES ('Paolo42', 'Paolo', :now);
```

## Identité tracée partout

Chaque décision porte `reviewer_token` (cf. `decisions` dans `02`). Au moment de la
réconciliation, ça devient `decided_by` côté `eurio.db` + `reviewer_name` dans le
staging `peer_review_decisions`. Conséquence :

- Côté admin, Raphaël **sait qui a décidé quoi** (« c'est Paolo42 qui a fait ces
  20 reviews »).
- Ça permet de **juger la qualité par reviewer** et de repérer les bêtises (cf.
  `05-admin-arbitration.md`).

## Non-objectifs

- ❌ OAuth / magic-link / mot de passe fort.
- ❌ Auto-inscription : on ne crée un reviewer que par INSERT manuel.
- ❌ Rôles fins : tous les amis ont le même rôle (reviewer). Raphaël arbitre via le
  console admin séparé, pas via ce front.
