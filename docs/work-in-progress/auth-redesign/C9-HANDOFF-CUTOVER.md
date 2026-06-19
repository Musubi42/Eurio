# C9 — Cutover : déploiement VPS + kill Vercel + kill `review_service` + archive

> **But (1 phrase)** : basculer en production sur le panel self-hosted, tuer
> les surfaces legacy (Vercel, `eurio-review`, `review-admin`, `admin/packages/web`),
> archiver, mettre à jour la doc (CLAUDE.md, README, etc.).
>
> **Ne fait PAS** : nouveau code applicatif. C9 est un cutover ops + nettoyage.

## 0. Pré-requis (durs)

- C6 ✅ — review porté.
- C7a ✅ — editorial core porté.
- C7b ✅ — sets & analytics porté.
- C8 ✅ — users + tokens UI.
- **Sauvegarde Authentik vérifiée** (volumes Postgres + media inclus dans `infra/backup/eurio-backup.sh`, cycle restore testé) — cf. C1 §8. **Bloquant** : si non fait, on ne lance pas C9.
- **Coexistence test ≥ 7 jours** : panel + legacy tournent côte à côte, l'opérateur (et idéalement 1 reviewer) utilise le panel pour les tâches quotidiennes. Aucune régression bloquante recensée. Cette coexistence est la **dernière phase de test avant le cutover one-shot** (cf. DESIGN.md D9 all-in : ce n'est pas un dual-run permanent, c'est une fenêtre de validation).
- DNS : `admin.musubi.dev` créé (pointe vers IP VPS).

## 1. Déploiement du panel sur le VPS

> **Choix déjà figé en C5 §9 : Nginx static.** L'Option B (FastAPI `StaticFiles`) est documentée ci-dessous pour historique mais ne sera pas implémentée.

### Option A — Nginx statique (retenu)

Nouveau dossier `infra/panel/` :

```
infra/panel/
├── docker-compose.yml      ← nginx:alpine, monte dist/ + nginx.conf
├── nginx.conf              ← serve static, SPA fallback, CSP headers
└── README.md
```

Build du panel en CI ou localement → tarball `dist/` → push sur VPS → mount
dans le container nginx via volume.

### Option B — Mount du `dist/` dans le container `eurio-api` (rejeté)

`FastAPI.mount("/", StaticFiles(directory="/srv/panel"))` après les routers
API. Plus simple (1 container de moins), mais couple le déploiement front au
déploiement API et complique la CSP. **Rejeté en C5 §9.**

### Routage Traefik

```yaml
labels:
  - traefik.http.routers.eurio-panel.rule=Host(`admin.musubi.dev`)
  - traefik.http.routers.eurio-panel.entrypoints=websecure
  - traefik.http.routers.eurio-panel.tls=true
  - traefik.http.routers.eurio-panel.tls.certresolver=letsencryptresolver
```

## 2. Kill Vercel

1. Backup final : `git pull` + tag `v-before-vercel-kill-YYYY-MM-DD`.
2. Sur le dashboard Vercel : supprimer le projet `eurio-admin` (ou équivalent).
3. Supprimer les variables d'env Vercel.
4. Si DNS pointait vers Vercel : remettre les enregistrements vers VPS.
5. Dans `CLAUDE.md`, sous "Déploiement admin" : remplacer la section Vercel
   par la nouvelle topologie (panel self-hosted).

## 3. Kill `review_service` / `eurio-review`

```bash
ssh vps
cd /opt/eurio/infra/review
docker compose down
# Backup du volume avant suppression :
tar czf ~/review-legacy-backup-$(date +%F).tar.gz ./data
# Garde le tarball quelques semaines, puis purge.
```

Supprimer le dossier `infra/review/` du repo (commit dédié).
Supprimer `ml/review_service/` du repo (les routes ont été portées en C4).
Supprimer DNS `eurio-review.musubi.dev` (ou CNAME vers `admin.musubi.dev`).

## 4. Kill `admin/packages/web` + `admin/packages/review-admin`

Archiver sous `docs/archive/admin-web/` et `docs/archive/admin-review-admin/`
(pattern existant — cf. `docs/archive/design/prototype/`). Supprimer du
workspace pnpm.

Mettre à jour `admin/pnpm-workspace.yaml`.

## 5. Invalidation des anciens tokens & suppression Supabase Auth

### 5.1 Anciens tokens machine (C4 model-b legacy)

- Anciens tokens `mac` / `pc` (model-b C4 legacy) : **soft-delete** via `UPDATE api_tokens SET revoked_at = strftime('%s','now')*1000 WHERE revoked_at IS NULL AND name IN ('mac','pc')`. Pas de `DELETE` — on garde la trace pour l'audit (cohérence avec C3 §2).
- L'opérateur re-crée 2 tokens propres (`mac-cli`, `pc-cli`) depuis `/me/tokens`.
- Mettre à jour `secrets/dev.env` côté Mac + PC avec les nouveaux tokens via `go-task secrets:edit`.

### 5.2 Suppression complète Supabase Auth (admin)

Décision DESIGN §9.1 : Supabase Auth disparaît entièrement.

1. **Avant suppression** : export d'audit léger des comptes (email + dernière connexion + provider) — `psql … -c "select email, last_sign_in_at, raw_app_meta_data from auth.users" > docs/archive/supabase-auth-users-$(date +%F).csv` (commit ou chiffrement local selon sensibilité).
2. **Supabase dashboard → Authentication → Providers** : désactiver "Email" (magic link), désactiver tous les providers OAuth si activés.
3. **Purge** : `delete from auth.users;` (suppression des comptes — toutes les `auth.identities` cascade). **Pas de DROP de la table `auth.users`** : c'est une table système Supabase, on vide juste son contenu.
4. **RLS** : les policies `auth.jwt() ->> 'role' = 'admin'` (≥8 occurrences dans `supabase/migrations/*`) **restent en place** mais deviennent inactives (`auth.jwt()` retourne NULL côté service-role). Documenté dans le commit C9 comme dead-but-kept. Pas de migration de suppression.
5. **Côté code** : la dépendance `@supabase/supabase-js` reste utilisée côté `eurio-api` (`ml/serving/supabase_client.py`), mais est **supprimée** de `admin/packages/panel/package.json` (vérifier qu'elle n'a jamais été ajoutée). Côté `admin/packages/web/` legacy : archivé sous `docs/archive/admin-web/` (cf. §4) — le code reste lisible mais hors workspace.
6. **Secrets** : `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `VITE_SUPABASE_*` sont **conservés** dans `secrets/dev.env` (toujours utilisés par `eurio-api` pour la donnée). Seul `SUPABASE_SERVICE_ROLE_KEY` reste actif côté VPS. La variable `VITE_SUPABASE_SERVICE_KEY` (dev only) est retirée puisque le panel n'a plus de chemin `import.meta.env.DEV` qui l'utilise.

### 5.3 Garantie DB Supabase préservée

À ce stade, on a :
- Vidé `auth.users` (logique applicative) ;
- Conservé l'intégralité des tables métier (`coins`, `sources`, `sets`, `audit_*`, RLS comprises) ;
- Aucun `DROP TABLE`, aucun `TRUNCATE` côté schéma métier ;
- Aucune nouvelle migration `supabase/migrations/*.sql` créée par cette refonte.

Le risque DB est nul. Vérification : `git diff main supabase/` ne montre aucun nouveau fichier.

## 6. Mise à jour de la doc

- `CLAUDE.md` :
  - Section "Déploiement admin" → réécrire pour refléter le panel self-hosted.
  - Section "Secrets" → ajouter `EURIO_OIDC_*`, retirer `REVIEW_ADMIN_TOKEN`,
    `REVIEW_SESSION_SECRET`.
  - Section "Stack technique" → mentionner le panel + Authentik.
- `README.md` racine : nouveau diagramme topologie si présent.
- `docs/work-in-progress/auth-redesign/ROADMAP.md` : marquer C9 ✅, déplacer
  le dossier sous `docs/decisions/auth-redesign/` ou similaire (doc devient
  historique).
- `docs/work-in-progress/model-b/C4-HANDOFF-SERVER.md` : mettre à jour avec
  une note "auth flow now via Authentik + personal API tokens" si C4 model-b
  est déployé après C9.

## 7. RUNBOOK break-glass

Créer `docs/operations/RUNBOOK-auth.md` (court). Doit documenter au minimum :

### 7.1 Authentik down — re-grant owner

```bash
ssh vps
cd /opt/eurio/infra/eurio-api/
docker compose exec eurio-api python -m serving.auth grant-owner --email raphaelthi59@gmail.com
# Vérifie auth_audit
docker compose exec eurio-api sqlite3 /data/eurio.db \
  "SELECT * FROM auth_audit WHERE event='grant_owner.cli' ORDER BY ts DESC LIMIT 5;"
```

### 7.2 Invalidation de masse des sessions (rotation `EURIO_SESSION_SECRET`)

Le cookie `eurio_session` étant un JWT HS256 signé par cette clé, sa rotation
invalide instantanément **tous** les cookies en circulation. Procédure :

```bash
# 1. Générer une nouvelle clé
python -c 'import secrets; print(secrets.token_hex(32))'

# 2. La mettre dans secrets/dev.env via go-task secrets:edit
go-task secrets:edit
# (remplacer EURIO_SESSION_SECRET=...)

# 3. Redéployer eurio-api pour qu'il charge la nouvelle valeur
ssh vps "cd /opt/eurio/infra/eurio-api && docker compose up -d --force-recreate"

# 4. Tous les utilisateurs sont déconnectés. Ils refont login OIDC normal.
```

À utiliser uniquement en cas de suspicion de fuite de la clé ou de session
admin compromise.

### 7.3 Suspicion de fuite d'un PAT

```bash
# Lister les tokens actifs d'un user (depuis le panel /me/tokens, ou via SQL)
docker compose exec eurio-api sqlite3 /data/eurio.db \
  "SELECT id, name, created_at, last_used_at FROM api_tokens
   WHERE user_id=? AND revoked_at IS NULL;"

# Révoquer un PAT spécifique (soft-delete)
docker compose exec eurio-api sqlite3 /data/eurio.db \
  "UPDATE api_tokens SET revoked_at = strftime('%s','now')*1000 WHERE id=?;"

# Auditer l'usage
docker compose exec eurio-api sqlite3 /data/eurio.db \
  "SELECT * FROM auth_audit WHERE target=? ORDER BY ts DESC LIMIT 50;"
```

### 7.4 Restore Authentik depuis backup (catastrophe)

Cf. backup pCloud (`infra/backup/eurio-backup.sh`) — restore du volume Postgres
d'Authentik à partir du dernier dump. Procédure détaillée à écrire en C1 lors
de l'ajout du backup.

## 8. Critères d'acceptation

- `admin.musubi.dev` répond avec le panel, certifié TLS, login Authentik OK.
- `eurio-review.musubi.dev` ne répond plus (ou redirige).
- `dashboard.vercel.com` ne montre plus le projet eurio-admin.
- `docker ps` sur le VPS ne montre plus `eurio-review`.
- `secrets/dev.env` ne contient plus `REVIEW_ADMIN_TOKEN` ni les anciens
  tokens machine.
- L'opérateur et au moins 1 reviewer ont fait leur quotidien dans le panel
  pendant 1 semaine sans bug bloquant.

## 9. Résumé

```
## C9 — résumé cutover

- Date du cutover : YYYY-MM-DD
- Panel déployé sur admin.musubi.dev : OK
- Vercel project supprimé : OK
- eurio-review container stoppé + volume backupé : OK
- review.db migré / fusionné / conservé : <…>
- admin/packages/web archivé : OK
- admin/packages/review-admin archivé : OK
- ml/review_service archivé : OK
- Tokens mac/pc legacy invalidés, nouveaux créés via panel : OK
- CLAUDE.md mis à jour : OK
- RUNBOOK auth créé : OK
- Régressions rencontrées : <…>
- Tâches résiduelles : <…>
```
