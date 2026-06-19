# PAT workflow — `studio-local`

> Comment générer, coller, renouveler, révoquer ton **Personal Access
> Token** pour faire tourner `packages/studio-local/` sur Mac ou PC.

## 0. C'est quoi un PAT, déjà ?

- Token opaque format `eurio_<43 chars base64url>` (cf. `DESIGN.md §5.1`).
- Stocké en base `eurio.db.pat_tokens` (hash + scopes + expiry).
- Lié à **ton** user OIDC. Les scopes effectifs au runtime = intersection
  des scopes du PAT et des scopes de ton rôle actuel. Si ton rôle perd
  un scope, le PAT le perd aussi (pas de privilege escalation gelée).
- **Le clair n'est affiché qu'une seule fois** à la création. Si tu le
  perds, tu révoques + tu en crées un nouveau.

## 1. Workflow complet

### 1.1 Générer un PAT

**Option A — UI `admin-vps`** (à venir) :

1. Connecte-toi sur `https://eurio-admin.musubi.dev` via Authentik.
2. Va dans `Mes tokens` → bouton `Nouveau token`.
3. Donne-lui un nom parlant : `mac-raph`, `pc-training`, etc.
4. Sélectionne les scopes nécessaires (voir §2).
5. (Optionnel) Mets une date d'expiration.
6. Click → modale qui montre le clair **une fois**. Copie-le.

**Option B — CLI break-glass** (depuis le VPS, sans UI) :

```bash
ssh dontpanic@vps
docker exec eurio-api python -m serving.auth create-pat \
    --email <ton-email-authentik> \
    --name mac-raph \
    --scopes coins:read,coins:write,review:read,review:write,training:run
```

Si `--scopes` omis : le PAT reçoit **tous** les scopes effectifs de l'user
(= union des scopes des rôles qu'il a, sauf `audit:write` toujours interdit).
Avec `--expires-days 90` pour une expiration optionnelle.

Affiche le clair `eurio_...` dans la sortie. Idem : copier maintenant ou jamais.

### 1.2 Coller le PAT côté machine dev

Sur ton Mac (et idem sur PC) :

```bash
cd /chemin/vers/eurio/admin/packages/studio-local
cp .env.example .env.local
# édite .env.local et remplace les placeholders
$EDITOR .env.local
```

Contenu attendu :

```ini
# .env.local — ignoré par git (cf. admin/.gitignore). Source unique du PAT
# pour cette machine. Si .env.local est wipé, il faut re-renseigner depuis
# password manager ou re-générer + révoquer l'ancien.
VITE_EURIO_API_BASE=https://eurio-api.musubi.dev
VITE_EURIO_PAT=eurio_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Puis :

```bash
pnpm dev   # ou go-task admin:studio-dev (alias à venir)
```

Le panel ouvre `http://localhost:5173`. Si le PAT est invalide / expiré,
tu vois un bandeau "PAT invalide — vérifie .env.local et relance".

### 1.3 Sauvegarder le PAT hors machine

`.env.local` est local-machine. Si le disque crash ou si tu reformates,
le PAT est perdu. Recommandations :

- **Stocker dans ton password manager** (1Password, Bitwarden, etc.) — un
  entrée par machine. Note le nom du PAT (= ce que tu lui as donné en §1.1)
  pour pouvoir le révoquer ciblé si besoin.
- **Ne JAMAIS** mettre `.env.local` en clair dans Drive/iCloud/Dropbox.

### 1.4 Ajouter une nouvelle machine

Workflow standard :

1. Crée un PAT dédié à cette machine (`mac-raph-2`, `mac-collab-paolo`, …).
   Un PAT distinct par machine permet de révoquer ciblé en cas de perte.
2. Sur la nouvelle machine : clone le repo + `cp .env.example .env.local`
   + colle le PAT + `pnpm dev`.
3. Mets le PAT dans ton password manager partagé avec la machine si
   c'est la même personne, ou perso si c'est un collaborateur.

### 1.5 Révoquer un PAT

Si tu perds ton Mac, si un PAT fuite, si tu rends une machine :

**Via UI `admin-vps`** (à venir) :

1. `Mes tokens` → ligne du PAT à révoquer → bouton `Révoquer`.

**Via CLI** :

Pour l'instant pas de CLI de révocation côté `pat_tokens` — passer par
l'API (cookie OIDC requis) :

```bash
# Lister tes PAT
curl -sS -b "eurio_session=<cookie>" https://eurio-api.musubi.dev/me/tokens

# Révoquer par id
curl -sS -X DELETE -b "eurio_session=<cookie>" \
    https://eurio-api.musubi.dev/me/tokens/<id>
```

Ou en SQL direct (break-glass) sur le VPS :

```bash
docker exec eurio-api sqlite3 /var/lib/eurio/eurio.db \
    "UPDATE pat_tokens SET revoked_at = strftime('%s','now')*1000 WHERE name = 'mac-raph';"
```

La révocation est immédiate (soft-delete) — le PAT ne sera plus accepté
par `require_principal`.

### 1.6 Renouveler (rotation périodique)

Si tu mets une expiration sur tes PAT (recommandé : 90 jours) :

1. À l'approche de l'expiration, génère un nouveau PAT (§1.1).
2. Remplace `VITE_EURIO_PAT` dans `.env.local`.
3. Relance `pnpm dev`.
4. Révoque l'ancien.

## 2. Scopes recommandés par usage

Le PAT hérite des scopes effectifs de ton rôle (intersection). Donne au
PAT le **minimum** nécessaire à son usage :

| Usage | Scopes minimum |
|---|---|
| Tout (rôle `owner`) | tous ceux de `owner` (cf. `auth_principal.ROLE_SCOPES`) |
| Reviewer fast-iter | `review:read review:write coins:read` |
| Training launcher (PC) | `training:run coins:read` |
| Scrape sources | `sources:read sources:write coins:write` |
| Read-only consult | `coins:read sources:read audit:read` |

Si tu hésites : demande tous les scopes de ton rôle. C'est ce que fait
l'UI par défaut (le PAT ne peut **pas** dépasser ton rôle de toute façon).

## 3. Sécurité — règles non-négociables

- **Jamais** committer `.env.local`. Le `.gitignore` de `admin/` l'exclut
  déjà — vérifie avec `git status` avant chaque commit.
- **Jamais** logger `VITE_EURIO_PAT` dans la console ni dans un fichier
  de debug.
- **Jamais** partager un PAT entre deux personnes ; un PAT = une machine
  = une personne identifiable. Plus facile à révoquer.
- **Jamais** générer un PAT avec `audit:write` ou `users:manage` "au cas
  où" — donne le scope strict.

## 4. Multi-machine — modèle mental

Une analogie : un PAT = clé physique de bureau. Tu en as **une par
trousseau** (= machine), tu peux la révoquer indépendamment, et les
collaborateurs ont chacun la leur. La serrure (= eurio-api) regarde
seulement si la clé est valide, pas qui la porte.

```
owner=raph
├── PAT mac-raph        → Mac perso, full scopes
├── PAT pc-training     → PC à la maison, scopes training+read
├── PAT mac-meeting     → MacBook taf, scopes read-only

reviewer=paolo
├── PAT laptop-paolo    → MacBook Paolo, scopes review uniquement
```

## 5. FAQ

**Q : Et si je veux taper `eurio-api.musubi.dev` depuis curl ou un autre
client (pas le frontend) ?**
R : Crée un PAT avec un nom dédié (ex: `curl-debug`) et fais
`curl -H "Authorization: Bearer eurio_…" https://eurio-api.musubi.dev/me`.
Même mécanisme.

**Q : Pourquoi pas un seul PAT partagé entre toutes mes machines ?**
R : Si une machine est compromise, tu dois révoquer + re-générer partout.
Un PAT par machine = un blast radius limité.

**Q : Le PAT est en clair dans `.env.local`, c'est sûr ?**
R : C'est un trade-off accepté. Le PAT est limité (scopes intersection
rôle, révocable, expiration possible). En contrepartie : pas de prompt
à chaque démarrage, pas de gestion de session locale complexe. Si tu
veux plus strict : passe à un secret manager local (1P CLI op read par
exemple) qui peut peupler `.env.local` à chaque session.

**Q : Mon `.env.local` a été wipé (formatage, nouveau clone). Que faire ?**
R : Récupère le PAT depuis ton password manager ; colle-le. Si tu ne
l'as plus, révoque l'ancien (au cas où il traîne quelque part) et
crée-en un nouveau.
