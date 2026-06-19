# HANDOFF — auth-redesign : refonte d'une vraie solution d'authentification

> ## ⚠️ SUPERSEDED — design tranché le 2026-06-19
>
> Ce document a servi à **ouvrir** la discussion. Les décisions de design sont
> désormais prises et formalisées ailleurs :
>
> - **Cible architecture (autoritatif)** → [`DESIGN.md`](./DESIGN.md)
> - **Plan d'implémentation en chunks** → [`ROADMAP.md`](./ROADMAP.md)
> - **Handoffs par chunk** → `C1-HANDOFF-AUTHENTIK.md` … `C9-HANDOFF-CUTOVER.md`
>
> Décisions prises (résumé, mis à jour 2026-06-19 après audit cohérence) :
> 1. Plus de Vercel. **Panel admin self-hosted sur le VPS**.
> 2. **Authentik** (déjà déployé) = IDP unique pour humains. OIDC.
> 3. **`eurio-api`** absorbe `review_service` ; **`admin/packages/panel`**
>    (nouveau) absorbe `admin/packages/web` + `admin/packages/review-admin`.
> 4. **Tokens API personnels** (PAT, style GitHub) — format `eurio_<43 base32>`
>    (256 bits) — créés depuis le panel. Remplacent le pattern `add-token` du
>    C4 model-b.
> 5. **RBAC simple** : 3 rôles (`owner`/`admin`/`reviewer`) + scopes fins,
>    mapping via groupes Authentik `eurio-*`.
> 6. **Cookie de session** = JWT signé HS256 (claims `{sub, email, roles, scopes,
>    sid, iat, exp}`), pas de session-store côté serveur. Rotation via re-login
>    OIDC silencieux. Détail : `DESIGN.md` §6.1.
> 7. **All-in, pas V1/V2** : la migration se fait en plusieurs sessions de dev
>    (chunks C1..C9) pour pouvoir tester par briques, mais le résultat final
>    est un basculement complet en une fois après ≥7j de coexistence test.
>    On ne livre pas une moitié.
> 8. **Supabase Auth (magic-link admin) disparaît complètement** à C9. Tous les
>    appels `supabase.from(…)` directs depuis `admin/packages/web` sont migrés
>    vers des endpoints `eurio-api` équivalents en C7 (split en C7a / C7b).
>    Détail : `DESIGN.md` §9.1.
> 9. **DB Supabase intégralement préservée** : aucune migration `supabase/`
>    n'est créée par cette refonte. Les RLS `auth.jwt() role=admin` deviennent
>    inactives mais sont conservées (dead-but-kept).
>
> Le reste du document ci-dessous (origine + inventaire + options §5) est
> conservé comme **contexte historique** — utile pour comprendre la dette
> qu'on rembourse, mais **non normatif**.

---

## (Historique — origine + inventaire)

> **Pour qui** : une session future (Claude Code ou humain) qui s'attaque sereinement
> à la refonte de l'authentification dans Eurio.
> **But** : poser le problème, lister ce qui existe (brique à brac), et préparer une
> discussion de design avant d'implémenter quoi que ce soit.
> **Statut** : ouvert. Aucune ligne de code à écrire dans la session qui ouvre ce doc
> tant que la décision de design n'est pas prise (voir §5).

## 0. Pourquoi on ouvre ce dossier

> Citation du commanditaire (raphaelthi59@gmail.com, 2026-06-17) :
> *"Je suis toujours pas convaincu par ce qu'on est en train de faire. […] j'aimerais
> mettre une vraie solution d'authentification. Et côté admin, côté panel, j'aimerais
> gérer ça correctement. J'en peux plus des solutions brique à braque dans tous les
> sens."*

L'auth dans Eurio est actuellement **fragmentée en plusieurs sous-systèmes
non concertés**, chacun avec son propre mécanisme. On a accumulé des solutions
ponctuelles ("ça marche, on verra plus tard") au fil des chunks (review, model-b,
admin Vercel). Le doc `docs/work-in-progress/model-b/C4-HANDOFF-SERVER.md`
spécifie un `add-token --name mac/pc` qui exige un copier-coller manuel du
token clair entre le VPS et chaque client — l'opérateur a explicitement
qualifié ce flow de "dégueulasse".

Plutôt que de continuer à patcher au cas par cas, on remet le sujet à plat dans
une session dédiée.

## 1. Inventaire des points d'authentification (état au 2026-06-17)

| # | Surface | Qui s'authentifie | Mécanisme actuel | Où c'est codé | Verdict |
|---|---|---|---|---|---|
| 1 | **`eurio-api` (FastAPI, VPS)** | Mac, PC (clients machine) | Bearer token, hash SHA-256 en base SQLite (`api_tokens.token_sha`), activable par `EURIO_API_AUTH_REQUIRED` | `ml/serving/auth.py` + dépendance `require_token` | Stockage **OK** (sha en base, jamais le clair côté serveur). Flow de **provisioning manuel "dégueulasse"** (`docker compose exec … add-token` → copier-coller dans `secrets/dev.env` côté client). |
| 2 | **`review_service` (FastAPI, VPS)** | Humain (toi) | Cookie HMAC maison `er_session` (signé `REVIEW_SESSION_SECRET`) + `REVIEW_ADMIN_TOKEN` admin token. Client Vue avec `credentials:'include'`. | `ml/review_service/auth.py:11` + `admin/packages/review-admin/src/api.ts` (le dossier `admin/packages/review/` mentionné historiquement n'existe pas/plus — c'est `review-admin/`) | Token unique fixe + cookie HMAC simple. À remplacer par cookie JWT eurio-api + PAT à C4/C6. |
| 3 | **Console admin Vercel** (Vue/Vite + Supabase) | Humain (toi) | **Magic-link Supabase Auth** (`LoginPage.vue` + `AuthCallbackPage.vue`) + `DEV_BYPASS` via service-role en dev local | `admin/packages/web/src/features/auth/` + `admin/packages/web/src/shared/supabase/client.ts:1-39` (la service-role est gated par `import.meta.env.DEV` → tree-shakée hors du bundle prod, **risque clé exposée déjà mitigé**) | Auth utilisateur **existe bien** côté UI (contrairement au "?" historique). À **supprimer entièrement** à C9 (cf. §9.1 DESIGN). |
| 4 | **Console MinIO** (`eurio-s3-console.musubi.dev`) | Humain devops | Creds root statiques dans `infra/minio/secrets/minio_root_*` | docker-compose MinIO | Acceptable pour ops mais à ne pas exposer à des collaborateurs futurs. |
| 5 | **MCP servers** (Asana, Notion, Google Drive, Gmail, etc.) | Claude / l'opérateur | OAuth par-provider, géré par claude.ai côté hosted | (hors repo) | Pas dans le scope de cette refonte. |
| 6 | **pCloud (backup)** | Le script `eurio-backup.sh` | OAuth token rclone + clé Age dédiée pour le chiffrement | `~/.config/rclone/rclone.conf` + `~/.config/eurio-backup/age-key.txt` | Hors scope auth utilisateur — c'est de l'auth machine→cloud. **Ne pas inclure** dans la refonte. |

> ⚠️ Lignes 2 et 3 **sont à scanner précisément** au début de la prochaine session.
> Ce qui est marqué "à auditer" peut révéler des trous plus graves que le bearer
> manuel d'eurio-api.

## 2. Ce qui marche déjà — à NE PAS casser

- **Le stockage hashé d'eurio-api** (sha256 en base, jamais le clair côté serveur)
  est techniquement correct. Garder ce pattern, qu'on construise dessus ou qu'on
  remplace au-dessus.
- **La centralisation SOPS** (`secrets/dev.env` chiffré avec age) est en place
  et fonctionne. Le commit `2d52d5e0` y a déjà mis `MINIO_*`, `EBAY_*`,
  `SUPABASE_*`, `VITE_SUPABASE_*`, `REVIEW_ADMIN_TOKEN`. Les secrets de **machine**
  (creds, tokens API longs-vivants) restent dans SOPS. La refonte ne touche pas
  ce flux.
- **`programs.ssh.startAgent` + keychain.nix** (NixOS) : géré, ssh-agent
  persistant, clé Codeberg chargée auto. Idem MinIO root via SOPS. **Le canal
  SSH est exploitable** comme bootstrap d'auth (cf. §5 option B).

## 3. Ce qui est cassé — la dette qu'on rembourse

1. **Provisioning de tokens manuel et fragile** (eurio-api : surface 1)
   - L'opérateur lance `docker exec add-token`, copie le clair affiché, le colle
     manuellement dans `secrets/dev.env` côté client. Erreur humaine triviale
     (copier-coller imparfait), pas de traçabilité, pas de rotation propre.
2. **Mélange auth-humain / auth-machine dans le même mécanisme** (potentiellement
   surfaces 2 et 3) — un humain ne devrait pas s'authentifier avec un token
   bearer machine. Si on garde un seul mécanisme pour les deux, on prend de
   mauvaises décisions UX (pas de session, pas de logout, pas de scopes
   distincts).
3. **Pas de "compte utilisateur"** : aucune notion d'identité durable
   (email + profil + permissions) — chaque token est une machine anonyme dans
   sa propre colonne. Quand on ajoutera un 2e humain (collaborateur, beta-tester
   admin), il n'y a pas d'endroit naturel où le poser.
4. **Pas de single sign-on entre les 4 surfaces UI** (review console, admin
   Vercel, panel futur, console MinIO). Chaque surface aura son propre login —
   anti-UX, anti-sécurité, anti-vieillissement.

## 4. Le besoin (à formaliser dans la prochaine session)

- **Auth-humain unifiée** sur toutes les surfaces UI (review, admin Vercel,
  futur panel). 1 login = accès à tout, selon les scopes.
- **Auth-machine séparée et propre** pour eurio-api (Mac/PC clients) — pas de
  copier-coller, le secret en clair n'existe que sur le client qui en a besoin.
- **Notion d'identité** (email + profil) côté serveur, traçabilité minimale
  (qui a fait quoi, audit log léger), permissions claires.
- **Pas de SaaS lourd** (Eurio reste un projet perso, l'auth doit pouvoir tourner
  sans dépendre d'un fournisseur payant).
- **Pas de réinventer la roue cryptographique** — on prend une lib éprouvée.

## 5. Pistes à évaluer (matrix pour la prochaine session)

### Auth humaine

| Option | Force | Faiblesse | Coût |
|---|---|---|---|
| **Supabase Auth** (déjà dans le stack — surface 3 utilise Supabase comme DB) | Magic links, OAuth providers, JWT, RLS native côté DB. Zéro infra à host. | Lock-in Supabase (mais on en dépend déjà pour la DB du référentiel). Adoption à pousser jusqu'aux surfaces FastAPI (vérif JWT signé). | Free tier généreux. |
| **Authelia / Authentik (self-hosted)** | OIDC complet, MFA, granulaire, sous notre contrôle. | 1 conteneur de plus à maintenir, configuration non triviale. | Gratuit (compute VPS). |
| **Magic links maison + JWT** | Minimaliste, contrôle total. | Réinvente la roue, no MFA, gestion mots de passe = piège. | Gratuit mais dette tech. |
| **Clerk / Auth0** | UX dev excellente, MFA, dashboards. | Coût > 0 dès qu'on grossit. Lock-in. | Free tier limité. |

**Suggestion pour la décision** : Supabase Auth, **si** un audit de
`admin/packages/web/` confirme qu'on utilise déjà Supabase pour la donnée
admin. Ça donne JWT standard, providers OAuth (Google), magic links, et un
endpoint `verify` pour les FastAPI (eurio-api, review_service) → un seul JWT
peut authentifier l'humain partout.

### Auth machine (Mac/PC → eurio-api)

| Option | Force | Faiblesse |
|---|---|---|
| **A — Token côté client, hash via SSH** (proposé en session ce jour) | Secret n'existe que sur le client. Provisioning idempotent via `ssh + add-token-hash`. | Demande une commande `add-token-hash` dans `serving.auth` (~10 lignes). |
| **B — Bootstrap via SSH + scp** (l'opérateur fait tourner un script local qui SSH au VPS, génère secret + sha, scp le secret en SOPS local) | Plus simple à coder, même garantie. | Demande de chaîner SSH + édition SOPS locale. |
| **C — JWT signé par Supabase, vérifié par eurio-api** (si on prend Supabase Auth pour les humains) | Un seul mécanisme pour humains et machines. Le "client machine" est un human-account avec un long-lived JWT. | Sémantiquement bizarre (le Mac est un humain ?), JWT longue durée = risque si fuite. |

**Suggestion pour la décision** : A pour eurio-api (clients machine), avec une
porte de sortie vers C si on décide que Mac/PC sont des "comptes app" gérés par
Supabase Auth.

## 6. Questions ouvertes à trancher à l'ouverture de la session

1. **Audit `admin/packages/web/`** : Supabase est-il utilisé pour la donnée
   uniquement (clé service role server-side) ou y a-t-il déjà un flow user-side ?
   La réponse oriente entre Supabase Auth (option naturelle si oui) et autres
   options.
2. **Audit `admin/packages/review/`** : le `REVIEW_ADMIN_TOKEN` actuel est-il
   suffisant pour V1 (1 humain) ou on bascule directement vers le SSO ?
3. **Combien d'humains à terme** ? (toi seul / toi + 1-2 reviewers / plus) —
   ça change la complexité acceptable.
4. **Quels providers OAuth** ? (Google suffit ? GitHub ? Apple ?)
5. **MFA imposé** ou optionnel pour le panel admin ?
6. **Rotation des tokens machine** : durée de vie cible (jamais ? 90j ?), flow
   de rotation, alerte d'expiration.
7. **Audit log** : pour V1, on logge dans la même DB SQLite ou ailleurs ?
8. **Migration des tokens existants** : on garde les tokens `mac` / `pc`
   actuels et on ajoute le nouveau mécanisme à côté, ou on bascule en hard cut ?

## 7. Ce qui ne doit PAS faire partie du scope

- L'auth de **pCloud** (rclone OAuth + clé Age backup) — c'est de la machine-cloud,
  c'est résolu, ça reste hors scope.
- L'auth des **MCP servers** Claude (Asana, Notion, etc.) — hors repo, géré par
  claude.ai.
- L'auth **SSH** (Codeberg, GitHub legacy, ServerOim) — c'est de la machine-machine,
  géré par les clés et `keychain.nix`. Ne pas mélanger.
- La **rotation des creds MinIO root** — c'est un secret machine dans SOPS, à
  rotater opérationnellement, pas un sujet de design.

## 8. Impact sur le chunk C4 (model-b deploy d'eurio-api)

Le chunk C4 (déploiement `eurio-api` sur le VPS, doc :
`docs/work-in-progress/model-b/C4-HANDOFF-SERVER.md`) est **mis en pause** jusqu'à
ce que la refonte auth tranche le pattern de provisioning des tokens Mac/PC.

Ce qu'on peut faire avant la session auth :
- Conserver le pattern `add-token` actuel et déployer eurio-api avec lui, en
  acceptant la dette du copier-coller pour la V1 — **éviter** : ça enracine
  le pattern qu'on veut justement refondre.
- Différer le déploiement jusqu'à ce que `add-token-hash` (option A) ou le
  flow Supabase JWT (option C) soient décidés et codés — **recommandé**.

Le VPS continue à servir MinIO + review_service via le Modèle A (Mac writer
sous lease) en attendant. Aucune urgence opérationnelle.

## 9. Pointers vers les docs et le code

- `ml/serving/auth.py` — module token actuel (génère, hash, lookup).
- `ml/serving/server_serve.py` — câblage `require_token` dans FastAPI.
- `infra/eurio-api/` — Dockerfile, compose, entrypoint, secrets — pas encore
  déployé (cf. C4).
- `admin/packages/review-admin/src/api.ts` — client review (cookie-based). (le dossier `admin/packages/review/` n'existe pas — c'est `review-admin/`.)
- `admin/packages/web/` — console admin Vercel. Auth = magic-link Supabase Auth, à killer à C9.
- `docs/work-in-progress/model-b/DESIGN.md` — décision #5 ligne 125 :
  "Auth = bearer token app-level". Décision à **réviser** dans cette refonte.
- `docs/work-in-progress/model-b/C4-HANDOFF-SERVER.md` — déploiement eurio-api,
  bloqué par cette refonte.
- `secrets/dev.env(.example)` — vars actuelles dans SOPS, incluant
  `REVIEW_ADMIN_TOKEN`.
- `CLAUDE.md` §"Secrets (SOPS + age)" — pattern de gestion des secrets,
  inchangé par cette refonte.

## 10. À produire au démarrage de la prochaine session

1. **Audit** des 2 zones grises : `admin/packages/web/` et `admin/packages/review/`.
2. **Choix** parmi les pistes du §5, avec justification courte.
3. **Plan d'implémentation** en chunks (provisioning machine, migration admin,
   migration review, mini-panel admin, audit log) — pas tout d'un coup.
4. **Mise à jour** de `DESIGN.md` model-b décision #5 si la nouvelle direction
   contredit le bearer-token-app-level.
5. **Reprise** de C4 (déploiement eurio-api) une fois le pattern de provisioning
   tranché.
