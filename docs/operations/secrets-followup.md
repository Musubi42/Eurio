# Secrets — suivi post-centralisation

> Reliquat à traiter plus tard, après la centralisation SOPS (commit `2d52d5e`,
> branche `sources-jo-wikipedia`, poussé sur codeberg + github le 2026-06-16).

## Contexte (déjà fait)

- **Source unique** : tous les secrets vivent dans `secrets/dev.env` (SOPS+age),
  exporté par `.envrc` dans `os.environ`. Le code lit via `ml/shared/env.py`
  (`load_env` / `require` / `numista_api_key`) — plus aucun parsing de `.env`.
- Numista : tout passe par `KeyManager` (8 clés `MUSUBIxx`, rotation + quota).
- Commandes : `go-task secrets:edit` / `secrets:list` / `secrets:check`.
- Historique git nettoyé : les secrets en clair (eBay PROD, Supabase service_role)
  ont été **caviardés** de tout l'historique. Backup intégral hors-ligne :
  `bizz/Eurio-backup-full-a3a7c5b.git`.

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
