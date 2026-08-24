# ADR-015 — Secrets : SOPS + age, une source unique, y compris sur le VPS

- **Statut** : ✅ Acceptée
- **Date** : 2026-06-16 (centralisation) · étendu au VPS en juin 2026

## Contexte

Les secrets d'Eurio vivaient dans quatre endroits à la fois : un `.env` racine en
clair, des variables collées dans le dashboard Vercel, des fichiers `infra/*/secrets/<name>`
lus par des variables `*_FILE` (pattern Docker secrets), et des valeurs en dur dans
des scripts. Aucun inventaire, aucune rotation, et rien qui empêche un fichier en clair
de se faire committer.

Ce dernier risque s'est réalisé : un fichier **`.envrc copy`** (693 octets) contenant
`SUPABASE_SERVICE_ROLE_KEY`, les identifiants eBay **PROD** et les clés Numista en clair
était **tracké à HEAD et poussé sur les deux remotes**. Il a été trouvé par un audit,
pas par une garde.

## Décision

**`secrets/dev.env`, chiffré SOPS + age et committé, est la source unique de tous les
secrets.** Pas de `.env` en clair, pas de second store.

- Chaque machine a sa **propre paire de clés age** ; les pubkeys sont listées dans
  `.sops.yaml`, la clé privée vit dans `~/.config/sops/age/keys.txt` et n'est **jamais**
  committée (sauvegarde : le password manager).
- `.envrc` (committé) déchiffre au chargement du shell via `sops -d` et **exporte** les
  variables dans l'environnement. Éditer = `go-task secrets:edit` ; vérifier =
  `secrets:check`.
- **Côté code, on lit `os.environ`, jamais un fichier.** `ml/shared/env.py`
  (`load_env` / `require` / `numista_api_key`). Aucun parsing de `.env` à la main.
  Les clés Numista (8, en rotation) passent par `referential.numista_keys.KeyManager` —
  il n'existe **pas** de `NUMISTA_API_KEY` au singulier.
- **Sur le VPS, même pattern, pas un autre.** Le `.envrc` racine déchiffre au
  `cd /opt/eurio` ; `docker compose` forwarde au conteneur via
  `environment: { VAR: ${VAR:?missing} }`. Aucun fichier secret en clair sur disque.
  Pour les contextes scriptés (cron, systemd), fallback explicite :
  `sops exec-env /opt/eurio/secrets/dev.env "docker compose up …"`.
- Le pattern **Docker secrets (`infra/*/secrets/<name>` + `*_FILE`) est déprécié.**
  `infra/eurio-api/` a migré.
- **Frontière assumée** : les runtimes distants qu'on ne contrôle pas. `loan/`, extrait
  dans son propre dépôt ([ADR-006](./006-extraction-loan.md)), gère ses secrets via le
  dashboard Vercel.

## Alternatives considérées

| Option | Verdict |
|---|---|
| `.env` gitignorés par machine | ❌ Aucune source de vérité, rien de partagé entre Mac/PC/VPS, et c'est exactement l'état d'où l'on vient — le fichier en clair finit committé |
| Docker secrets (`*_FILE`) sur le VPS | ❌ Un second store, avec ses propres fichiers en clair sur le disque du serveur, et une syntaxe qui ne ressemble à rien de ce que le code lit ailleurs |
| Un gestionnaire de secrets (Vault, Infisical…) | ❌ Un service de plus à héberger, sauvegarder et surveiller, pour un dépôt à un opérateur. SOPS n'a pas de runtime |
| `git-crypt` | ❌ Chiffre par fichier sans multi-recipient lisible. SOPS édite en clair dans `$EDITOR` et re-chiffre à la sauvegarde, ce qui est le geste quotidien |
| Chiffrer avec une clé unique partagée | ❌ Une clé par machine se révoque en retirant une ligne de `.sops.yaml` |

## Conséquences

**Bonnes.** Un seul fichier à sauvegarder, une seule commande pour éditer, et le
secret voyage avec le dépôt sans jamais être lisible. Ajouter une machine = ajouter
une pubkey. Le VPS suit exactement la même doctrine que les postes de dev.

**Mauvaises, et assumées.**

- **Perdre `~/.config/sops/age/keys.txt` sur toutes les machines, c'est perdre tous
  les secrets.** La sauvegarde de cette clé est hors bande, dans le password manager,
  et c'est un point unique de défaillance humaine.
- Le déchiffrement se fait au chargement du shell : **hors direnv, on n'a rien**. C'est
  la même racine que le piège n°1 du dépôt (un shell hors `nix develop` lit la mauvaise
  base et n'a pas les bons secrets).
- **L'historique git des remotes a contenu des secrets en clair.** Le `git rm --cached`
  du 2026-07-04 n'a pas purgé l'historique ; la position retenue par
  [ADR-005](./005-remaster-historique-git.md) est que le remaster sur base propre et
  l'archivage hors ligne de l'ancien historique remplacent un `git-filter-repo`. **Ce
  remaster n'est pas encore fait** — jusque-là, les clés qui ont fuité doivent être
  considérées comme ayant été publiques, révocation ou pas.

## Voir aussi

- Guide reproductible de mise en place : [`../research/sops-age-secrets.md`](../research/sops-age-secrets.md)
- Bootstrap d'une nouvelle machine : `README.md` §Secrets
- Remaster de l'historique : [ADR-005](./005-remaster-historique-git.md)
