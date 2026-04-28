# Build & deploy — local-first, pas de sync

Principe directeur : **la clé Supabase service role ne quitte jamais
ma machine**. Vercel ne parle qu'à Vercel KV. Le catalogue et les
images sont figés au build local et uploadés via `vercel deploy
--prebuilt`.

Pas de script de sync KV → Supabase (cf. `data-model.md` §4).

## Pré-requis

- Node 22 LTS + pnpm (déjà dans le devShell Nix du monorepo)
- `vercel` CLI : via flake ou `pnpm add -g vercel`
- `SUPABASE_SERVICE_ROLE_KEY` exporté via direnv (`.envrc` racine)

## Variables d'environnement

| Var | Où | Usage |
|---|---|---|
| `SUPABASE_SERVICE_ROLE_KEY` | `.envrc` racine (local only) | Build local : fetch coins + download images |
| `SUPABASE_URL` | `.envrc` racine | Idem |
| `KV_REST_API_URL` | Vercel auto-injection | API routes runtime |
| `KV_REST_API_TOKEN` | Vercel auto-injection | Idem |
| `LOAN_ADMIN_USERNAME` | Vercel env (prod) | Basic auth `/admin/*` |
| `LOAN_ADMIN_PASSWORD` | Vercel env (prod) | Idem |

Aucune var Supabase n'est définie côté Vercel. Garde-fou anti-fuite
ci-dessous.

## Workflow build & deploy

### 1. Build du catalog + images (local)

```bash
go-task loan:build-catalog
```

Ce que ça fait (`loan/scripts/build-catalog.ts`) :

1. Lit `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` depuis l'env.
2. Fetch toutes les pièces 2€ curated (filtre dans `data-model.md`).
3. Fetch les `coin_market_prices` correspondantes, garde la plus
   récente par `eurio_id`.
4. **Pour chaque image** : download depuis Supabase Storage, resize
   max 800 px (sharp), écrit dans
   `loan/public/coins/{eurio_id}/{idx}.jpg`.
5. Sérialise `loan/public/catalog.json` avec les chemins relatifs
   `/coins/{eurio_id}/{idx}.jpg`.
6. Affiche un résumé : `508 coins, 78 personal_owned, 1024 images,
   83 MB, generated_at=…`.

Idempotent : si l'image existe déjà avec le bon hash, skip.

### 2. Build Next + deploy

```bash
go-task loan:deploy
```

Sous le capot :

```bash
cd loan
vercel build --prod
vercel deploy --prebuilt --prod
```

`--prebuilt` est la clé : Vercel ne re-build rien, il sert exactement
ce que j'ai compilé localement. `catalog.json` et `public/coins/*` y
sont embarqués.

### 3. Re-build après changement (`personal_owned`, nouvelle pièce, image)

Identique à 1 + 2. Pas d'ISR ni de webhook : c'est une action
explicite quand je curate. Cible : ≤ 1× / semaine.

## Garde-fous sécurité

### Avant chaque deploy

```bash
go-task loan:env-check
```

Grep `service_role` dans le build :

```bash
! grep -r "service_role" .next .vercel/output 2>/dev/null
! grep -r "SUPABASE_SERVICE_ROLE_KEY" .next .vercel/output 2>/dev/null
```

Échoue si une de ces strings apparaît, bloque le deploy.

### Architecture

- `loan/scripts/build-catalog.ts` lit `SUPABASE_*` depuis `process.env`,
  jamais en dur.
- Le code dans `loan/src/` (Next runtime) **n'importe jamais** rien
  qui touche Supabase.
- Les vars Supabase ne sont **pas** dans Vercel env. Elles ne peuvent
  pas fuir au runtime.

## Repo & git

- `loan/public/coins/` → **gitignored** (volumineux, régénéré au
  build).
- `loan/public/catalog.json` → gitignored aussi.
- `loan/.next`, `loan/.vercel` → gitignored.
- Le source du site (`loan/src/`, `loan/scripts/`, configs) → versionné.

## go-task entries (à ajouter dans `Taskfile.yml` racine)

```yaml
loan:build-catalog:
  desc: "Génère catalog.json + télécharge images dans public/coins/ (local only)"
  dir: loan
  cmds:
    - pnpm tsx scripts/build-catalog.ts

loan:dev:
  desc: "Dev server Next sur loan/"
  dir: loan
  cmds:
    - pnpm dev

loan:env-check:
  desc: "Vérifie que les secrets Supabase ne sont pas dans le build"
  dir: loan
  cmds:
    - "! grep -r 'service_role' .next .vercel/output 2>/dev/null"
    - "! grep -r 'SUPABASE_SERVICE_ROLE_KEY' .next .vercel/output 2>/dev/null"

loan:deploy:
  desc: "Build local + env-check + deploy --prebuilt vers Vercel prod"
  dir: loan
  cmds:
    - go-task loan:build-catalog
    - vercel build --prod
    - go-task loan:env-check
    - vercel deploy --prebuilt --prod
```

## Risques & mitigations

| Risque | Mitigation |
|---|---|
| Fuite `SUPABASE_SERVICE_ROLE_KEY` dans le bundle | `loan:env-check` post-build, vars jamais lues côté Next runtime |
| Spam claims (API publique sans auth) | Rate limit Upstash naturel, pas de stakes : j'ignore le bruit en discutant IRL |
| `public/coins/` devient lourd (>100 MB) | Resize 800 px sharp + JPEG quality 80 ; alerting manuel si > 200 MB |
| Catalog obsolète après ajout d'une pièce | Doc explicite : `loan:deploy` fait partie du workflow d'ajout 2€ |
| Brute-force basic auth `/admin` | Mot de passe long aléatoire ; rate limit Vercel Edge |
