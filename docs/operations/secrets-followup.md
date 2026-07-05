# Secrets — suivi post-centralisation

> Reliquat à traiter plus tard, après la centralisation SOPS (commit `2d52d5e`,
> branche `sources-jo-wikipedia`, poussé sur codeberg + github le 2026-06-16).

> ⚠️ **ALERTE (audit hardening 2026-07-04) — l'affirmation « caviardé de tout l'historique »
> ci-dessous est FAUSSE.** Un fichier `.envrc copy` (693 o) contenait **les mêmes secrets en
> clair** (`SUPABASE_SERVICE_ROLE_KEY`, `EBAY_CLIENT_ID/SECRET` PROD, clés Numista, anon keys)
> et était **tracké à HEAD, poussé sur codeberg + github**. Il a été **retiré du tracking git**
> (`git rm --cached`) + ajouté au `.gitignore` le 2026-07-04, MAIS :
> - **les clés ne sont TOUJOURS PAS révoquées** (cf. §2, cases `[ ]`) — elles restent actives ;
> - **l'historique des 2 remotes contient encore les secrets** (le `git rm` ne purge pas
>   l'historique). Une purge (`git-filter-repo`) + force-push reste à faire.
>
> **Action P0 : révoquer/rotater d'abord (§2), purger l'historique ensuite.** Tant que ce n'est
> pas fait, considérer `service_role` / eBay PROD / Numista comme **compromis publiquement**.

## Contexte (déjà fait)

- **Source unique** : tous les secrets vivent dans `secrets/dev.env` (SOPS+age),
  exporté par `.envrc` dans `os.environ`. Le code lit via `ml/shared/env.py`
  (`load_env` / `require` / `numista_api_key`) — plus aucun parsing de `.env`.
- Numista : tout passe par `KeyManager` (8 clés `MUSUBIxx`, rotation + quota).
- Commandes : `go-task secrets:edit` / `secrets:list` / `secrets:check`.
- Historique git nettoyé une première fois (commit `2d52d5e`) — **MAIS re-fuité ensuite**
  via `.envrc copy` (cf. alerte en tête). Le caviardage initial ne couvre donc PAS l'état
  actuel des remotes. Backup intégral hors-ligne : `bizz/Eurio-backup-full-a3a7c5b.git`.

## À faire

### 1. Supprimer le `./.env` racine (orphelin)

Plus lu par aucun code depuis `2d52d5e`. Dernier store de secrets en clair en double.

```bash
# Vérifier une dernière fois qu'il n'est plus référencé :
git grep -nE '/ "\.env"' -- '*.py'    # doit être vide
rm .env                                # gitignoré, donc juste le disque
```

### 2. Révoquer les clés exposées (IMPORTANT)

Elles ont vécu en clair dans l'ancien historique git → compromises même après caviardage.

- [ ] **eBay PROD** : régénérer Client ID + Cert ID sur le eBay developer portal.
- [ ] **Supabase `service_role`** : régénérer dans Supabase (Settings → API).
      Pense aussi à `VITE_SUPABASE_SERVICE_KEY` / anon si tu les rotates.
- [ ] Mettre les nouvelles valeurs : `go-task secrets:edit` puis `direnv reload`.

### 3. Supprimer le mirror backup

Quand tu es serein que codeberg + github te conviennent :

```bash
rm -rf bizz/Eurio-backup-full-a3a7c5b.git   # 1.2 G
```

## Optionnel (durcissement)

### 4. `VITE_SUPABASE_SERVICE_KEY` — supprimer le chemin `DEV_BYPASS`

Une clé `service_role` derrière un préfixe `VITE_` = risque théorique d'embarquement
dans le bundle front (aujourd'hui tree-shaké hors prod via `DEV_BYPASS`).

- Fichiers : `admin/packages/web/src/shared/supabase/client.ts` (`DEV_BYPASS`,
  `serviceKey`) + `admin/packages/web/vite.config.ts` (inject `VITE_SUPABASE_SERVICE_KEY`).
- Objectif : ne jamais servir la `service_role` au front, même en dev.
- Garde existante : `go-task loan:env-check` vérifie déjà côté `loan/`.
