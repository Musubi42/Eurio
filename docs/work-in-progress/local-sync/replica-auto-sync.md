# Réplique auto-sync — fraîcheur transparente de `eurio.replica.db`

> Livré le 2026-07-04 (session « transparence de sync », suite du durcissement
> C4–C8). Objectif : plus JAMAIS de `pull-replica` manuel — la réplique locale
> se rafraîchit seule, en secondes, pendant que tu travailles.

## Le modèle (rappel Direction A)

- **Écritures** : toujours des POST directs au VPS (`/ingest/*`, funnel/lot).
  Elles ne dépendent d'AUCUN pull — rien à perdre, jamais.
- **Lectures partagées front** (Jeu d'entraînement, review) : lisent le VPS
  directement → toujours fraîches, aucun pull requis.
- **Réplique locale** (`ml/state/eurio.replica.db`) : cache de lecture pour le
  compute (scripts `--push`, bench, cohorte). C'est SA fraîcheur que ce
  dispositif automatise.

## Transport : `sqlite3_rsync` incrémental (fallback API)

`go-task ml:db:pull-replica` choisit automatiquement (`--mode auto`) :

1. **rsync** — `sqlite3_rsync` (officiel SQLite ≥ 3.50, fourni par le devShell,
   `flake.nix` baseInputs) synchronise au **niveau page** depuis le canonique
   VPS, bases vivantes des deux côtés. Mesuré : **~3 s / ~4 Ko** transférés
   quand rien n'a changé (vs 106 Mo / ~18 s en pull complet). La réplique reste
   en WAL — ne JAMAIS supprimer ses sidecars `-wal`/`-shm`.
2. **api** — `GET /db/replica` complet + vérif sha. Fallback machine non
   provisionnée ou échec rsync.

`--status` affiche la fraîcheur sans puller. Overrides env :
`EURIO_REPLICA_SSH_HOST` (défaut `serverOimNixDontpanic`),
`EURIO_REPLICA_ORIGIN`, `EURIO_REPLICA_SSH_KEY`.

### Provisionnement d'une machine (fait pour Mac + PC le 2026-07-04)

1. Clé dédiée SANS passphrase (les timers ne peuvent pas répondre à un prompt) :
   `ssh-keygen -t ed25519 -N "" -C "eurio-replica-<machine>" -f ~/.ssh/eurio_replica`
2. Côté VPS, autoriser la clé **restreinte** dans
   `/home/dontpanic/.ssh/authorized_keys` :
   `restrict,command="/home/dontpanic/bin/eurio-replica-cmd" ssh-ed25519 …`
   Le forced command (`~/bin/eurio-replica-cmd`) ne laisse passer QUE
   `sqlite3_rsync` sur le SEUL `/opt/eurio/infra/eurio-api/data/eurio.db` —
   cette clé ne donne ni shell ni autre fichier.
3. Binaire côté VPS : `nix profile install nixpkgs#sqlite-rsync`
   (→ `~/.nix-profile/bin/sqlite3_rsync`). ⚠️ Imperatif — à migrer dans
   `environment.systemPackages` de la config NixOS du VPS à l'occasion.

## Automatisation

### Toutes machines — thread du serveur ML local (`serving/server.py`)

Au démarrage du serveur :8042, `client.replica.start_autopull_thread()` pull
en boucle (défaut 120 s, `EURIO_REPLICA_AUTOPULL_INTERVAL`). Tant que tu
bosses, c'est frais. Gates : `EURIO_REPLICA_AUTOPULL=0` désactive ; sans
transport rsync provisionné le thread ne démarre pas (pas de spam API).

**Pourquoi pas launchd sur le Mac ?** Testé et abandonné : TCC interdit à un
agent launchd de LIRE le contenu de `~/Documents` (le repo, la réplique) —
sonde : `cat` → `Operation not permitted`, exit 126 — alors que le serveur
lancé depuis ton terminal hérite des droits. Alternative si un jour nécessaire :
accorder Full Disk Access à `/bin/sh` (Réglages → Confidentialité), non retenu.

### PC (NixOS) — timer systemd user (couvre serveur éteint)

Unités imperatives dans `~/.config/systemd/user/` (installées le 2026-07-04) :
`eurio-replica-pull.service` (oneshot → `ml/scripts/replica_autopull.sh`) +
`eurio-replica-pull.timer` (2 min, Persistent). Logs : `journalctl --user -u
eurio-replica-pull`. Équivalent déclaratif home-manager à migrer à l'occasion :

```nix
systemd.user.services.eurio-replica-pull = {
  Unit.Description = "Eurio - auto-pull replique eurio.db";
  Service = {
    Type = "oneshot";
    ExecStart = "/bin/sh /home/raphael/Documents/Musubi42/Eurio/ml/scripts/replica_autopull.sh";
  };
};
systemd.user.timers.eurio-replica-pull = {
  Timer = { OnBootSec = "2min"; OnUnitActiveSec = "2min"; Persistent = true; };
  Install.WantedBy = [ "timers.target" ];
};
```

## Limite connue (chantier suivant, décision PO)

La réplique fraîche n'est consommée que par les chemins qui la LISENT.
`EURIO_DB_PATH` n'est posé ni sur Mac ni sur PC → le serveur local :8042 et
les scripts compute lisent encore `ml/state/eurio.db` (fichier legacy, périmé
par construction sous Direction A). Les vues front partagées ne sont PAS
affectées (elles lisent le VPS). Pour fermer complètement :
**split local-state** — séparer l'état local légitime (cohort_jobs, runs
d'entraînement, overlay dismiss) de la donnée partagée, puis pointer les
lectures partagées sur `eurio.replica.db` (et activer `EURIO_DB_READONLY`).
Cf. `c4-c8-known-gaps.md` §MAJOR 2 (limite assumée).
