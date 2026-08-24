# C1 — Provisioning Authentik (OIDC + groups)

> **But (1 phrase)** : configurer Authentik (déjà déployé par l'opérateur) pour
> qu'il serve d'IDP unique au stack Eurio — une application OIDC "Eurio Panel",
> 3 groupes (`eurio-owner`, `eurio-admin`, `eurio-reviewer`), claims propres.
>
> **Ne fait PAS** : écrire le code de vérif JWT côté `eurio-api` (c'est C2), ni
> coder le panel front (C5). Ce chunk est *config Authentik + doc d'intégration*.

## 0. Pré-requis

- `DESIGN.md` lu et validé.
- Accès admin à l'instance Authentik (URL + creds dans le password manager perso
  de l'opérateur ; demander si l'agent ne les a pas — pas dans SOPS).
- Authentik à jour (≥ 2024.x recommandé pour la stabilité OIDC + JWKS).

> **OQ1 (cf. DESIGN.md §11)** — Authentik tourne où exactement ? Si dans un
> docker-compose hors-repo : noter le chemin du fichier dans le résumé. Si on
> veut le rapatrier dans `infra/authentik/` : à discuter en fin de chunk, **pas
> le faire ici**.

## 1. Application OIDC "Eurio Panel"

Dans l'UI Authentik (Applications → Create) :

| Champ | Valeur |
|---|---|
| Name | `Eurio Panel` |
| Slug | `eurio-panel` |
| Provider | (créé à l'étape 2) |
| Launch URL | `https://eurio-admin.musubi.dev/` |
| Open in new tab | non |

## 2. Provider OIDC

Provider type : **OAuth2/OpenID Provider**.

| Champ | Valeur | Note |
|---|---|---|
| Name | `eurio-panel-oidc` | |
| Client Type | `Confidential` | Le `client_secret` sera stocké côté `eurio-api` (chunk C2). |
| Client ID | auto-généré, **noter dans le résumé** | |
| Client Secret | auto-généré, **NE PAS coller dans le résumé** | À transmettre à l'opérateur pour SOPS. |
| Redirect URIs | `https://eurio-api.musubi.dev/auth/oidc/callback`<br>`http://localhost:8042/auth/oidc/callback` (dev) | Le callback est côté API, pas côté panel — le browser est juste redirigé. |
| Signing Key | clé RS256 par défaut d'Authentik | RS256 obligatoire (pas HS256) → JWKS public exploitable. |
| Subject mode | `Based on the User's hashed ID` | `sub` stable même si l'email change. |
| Include claims in id_token | ✅ | |
| Issuer mode | `Each provider has a different issuer` | |
| Scopes | `openid`, `email`, `profile`, **+ scope custom `eurio_groups`** (étape 4) | |
| Access code validity | 60 sec (default) | |
| Token validity | `minutes=60` (id_token + access_token) | |
| Refresh token validity | `days=30` | Cookie de session côté panel. |

## 3. Groups

Dans Directory → Groups, créer :

- `eurio-owner` — toi (raphaelthi59@gmail.com).
- `eurio-admin` — pour les autres admins futurs.
- `eurio-reviewer` — pour les reviewers (amis).

Ajouter ton propre user au moins dans `eurio-owner` (et `eurio-admin` + `eurio-reviewer` aussi, pour pouvoir tester tous les flows).

## 4. Custom scope mapping `eurio_groups`

Customization → Property Mappings → Create → **Scope Mapping** :

| Champ | Valeur |
|---|---|
| Name | `eurio-groups` |
| Scope name | `eurio_groups` |
| Description | `Eurio app groups (owner/admin/reviewer)` |
| Expression | (cf. ci-dessous) |

Expression Python :

```python
return {
    "groups": [
        group.name for group in user.ak_groups.all()
        if group.name.startswith("eurio-")
    ],
}
```

Puis : retourner sur le provider `eurio-panel-oidc`, ajouter `eurio-groups` aux scopes.

## 5. Vérification côté Authentik (sans `eurio-api`)

Récupérer le discovery doc :

```bash
curl -s https://authentik.musubi.dev/application/o/eurio-panel/.well-known/openid-configuration | jq .
```

Vérifier les champs présents :
- `issuer` (à noter dans le résumé)
- `authorization_endpoint`
- `token_endpoint`
- `userinfo_endpoint`
- `jwks_uri` (à noter dans le résumé)
- `id_token_signing_alg_values_supported` contient `RS256`
- `scopes_supported` contient `eurio_groups`

Puis JWKS direct :

```bash
curl -s $(curl -s https://authentik.musubi.dev/application/o/eurio-panel/.well-known/openid-configuration | jq -r .jwks_uri) | jq .
```

Doit renvoyer au moins une clé publique RSA. C'est ce que `eurio-api` consommera en C2.

## 6. Test du flow (manuel, browser)

Construire l'URL d'authorize à la main :

```
https://authentik.musubi.dev/application/o/authorize/?
  client_id=<CLIENT_ID>&
  response_type=code&
  scope=openid+profile+email+eurio_groups&
  redirect_uri=https://eurio-api.musubi.dev/auth/oidc/callback&
  state=test123
```

Ouvrir dans le browser. Tu dois être prompté pour t'authentifier (ou être déjà
loggué), puis être redirigé vers `eurio-api.musubi.dev/auth/oidc/callback?code=…`
**avec un 404** (normal : C2 pas encore implémenté). L'important = la redirection
arrive avec un `code` dans la query.

## 7. Documentation des claims pour C2

Valeurs captées le 2026-06-19 (consommées par C2) :

- `issuer` : `https://authentik.musubi.dev/application/o/eurio-panel/`
- `authorization_endpoint` : `https://authentik.musubi.dev/application/o/authorize/`
- `token_endpoint` : `https://authentik.musubi.dev/application/o/token/`
- `userinfo_endpoint` : `https://authentik.musubi.dev/application/o/userinfo/`
- `jwks_uri` : `https://authentik.musubi.dev/application/o/eurio-panel/jwks/`
- `end_session_endpoint` : `https://authentik.musubi.dev/application/o/eurio-panel/end-session/`
- `id_token_signing_alg` : `RS256` (kid actuel `77ad99d54ae56c4cc81c57cde8492853` — sujet à rotation, **ne pas durcir** en code, lire toujours depuis JWKS)
- `client_id` : `8nFCZsZV0Pryxcjse0pOq2YQvLbdWXP8gmwYbh82` (public, OK en clair dans `infra/eurio-api/docker-compose.yml`)
- `client_secret` : transmis hors-bande à l'opérateur, à mettre en SOPS sous `EURIO_OIDC_CLIENT_SECRET`

Format attendu du token décodé :

```json
{
  "iss": "https://authentik.musubi.dev/application/o/eurio-panel/",
  "sub": "<hashed user id, stable>",
  "aud": "<client_id>",
  "exp": 1750000000,
  "iat": 1749996400,
  "email": "raphaelthi59@gmail.com",
  "email_verified": true,
  "name": "Raphaël",
  "groups": ["eurio-owner", "eurio-admin", "eurio-reviewer"]
}
```

## 8. Garde-fous

- **Ne pas supprimer** ni renommer les groupes `eurio-*` une fois créés — leur
  nom est durci dans le mapping rôles côté `eurio-api`. Changement = migration.
- **Ne pas régénérer** le `client_secret` sans prévenir l'opérateur (il est
  référencé dans SOPS côté API).
- **Sauvegarde Authentik (BLOQUANT pour C9)** :

  **Infos Authentik VPS capturées le 2026-06-19** (instance `oim-authentik`, version 2025.10.0) :

  | Cible | Type | Chemin/nom |
  |---|---|---|
  | Postgres data | volume Docker nommé | `oim-authentik_database` |
  | Media (clés de signature OIDC, branding) | bind mount | `/opt/stacks/oim-authentik/media/` |
  | Certs TLS Authentik | bind mount | `/opt/stacks/oim-authentik/certs/` |
  | Templates custom | bind mount | `/opt/stacks/oim-authentik/custom-templates/` |
  | Compose + .env | bind | `/opt/stacks/oim-authentik/docker-compose.yaml` + `.env` |

  Étapes :
  1. Ouvrir `infra/backup/eurio-backup.sh` et ajouter ces sources s'il ne les couvre pas déjà.
  2. **Postgres** : utiliser `docker exec authentik_postgresql pg_dump -U authentik authentik | gzip > /tmp/authentik-pg-$(date +%F).sql.gz` (cohérence transactionnelle) — **pas** un tar du volume live.
  3. **Bind mounts** : tar standard suffit (`media/`, `certs/`, `custom-templates/`, `docker-compose.yaml`, `.env`).
  4. Tester un cycle backup → restore sur un Authentik throw-away (compose local jetable) avant de marquer le chunk validé.
  5. Si l'étape 1, 2 ou 4 échoue ou n'est pas faite, **C9 est bloqué** : noter explicitement dans le résumé et ouvrir un ticket de suivi.

## 9. Résumé à produire

```
## C1 — résumé Authentik

- Authentik version : <…>
- Compose / hébergement : <chemin du docker-compose ou note "hors repo">
- Application "Eurio Panel" créée : OUI/NON
- Provider OIDC "eurio-panel-oidc" :
  - issuer : <…>
  - jwks_uri : <…>
  - client_id : <…>
  - client_secret : transmis à l'opérateur via <canal sécurisé>
- Groups créés : [eurio-owner, eurio-admin, eurio-reviewer]
- Scope mapping `eurio_groups` créé : OUI/NON
- User raphael ajouté dans : <liste>
- Test discovery doc : OK / KO (+ erreur)
- Test JWKS : OK / KO
- Test flow browser : redirection avec ?code= reçue OUI/NON
- Backup Authentik couvert par eurio-backup.sh : OUI / NON / À vérifier
- Déviations : <…>
- Questions pour la session de design : <…>
```
