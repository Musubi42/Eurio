# Backup off-site des données sensibles → pCloud (rclone)

> À dérouler plus tard. Décisions actées : **rclone**, cadence **toutes les 6 h**,
> **+ backup à chaque modèle entraîné**, **pas de chiffrement**, config **Nix
> dans ce repo** (module NixOS pour le VPS + module nix-darwin pour le Mac).

## 1. Pourquoi

La donnée sensible (crops eBay = labeur de review, `eurio.db` = référentiel, images
canoniques, modèles) vit aujourd'hui **uniquement sur le disque du VPS** : MinIO **et**
le volume `eurio.db` y sont côte à côte. Un incident disque = perte totale. pCloud
(abo lifetime) sert de **copie off-site** → règle **3-2-1** :

- copie 1 = VPS (MinIO + volume eurio.db, writer),
- copie 2 = pCloud (off-site, ce doc),
- copie 3 *(optionnelle)* = pull périodique sur le Mac.

> Rappel archi (cf. `model-b/DESIGN.md`) : après le **cutover C8**, le canonique
> `eurio.db` est le **volume du VPS** (writer = l'API). MinIO `eurio-db/eurio.db`
> n'est alors plus le canonique-sous-lease — mais **« canonique » ≠ « backup »** :
> ne pas supprimer la sauvegarde pour autant. C'est précisément le rôle de ce doc.

## 2. Quoi sauvegarder

| Source | Contenu | Stratégie |
|---|---|---|
| `eurio.db` (volume VPS, ~102 MB) | référentiel + review | snapshot daté cohérent (`.backup`) |
| bucket `enrichment-crops` | crops eBay (crown jewel) | `rclone copy` (jamais `sync` — voir §6) |
| bucket `enrichment-raws` | raws eBay | `rclone copy` |
| bucket `numista-canonical` | images canoniques (1000+) | `rclone copy` |
| `eurio-db/transfers/` | modèles entraînés | inclus + push direct au train (§7) |

## 3. Remote pCloud (destination) — ⚠️ région EU

`rclone config` → `n` (new) → nom **`pcloud`** → type **`pcloud`** →
`client_id`/`client_secret` **vides** → auth.

- **Région : compte pCloud = US** → **`hostname = api.pcloud.com`** (la valeur par
  défaut → tu peux laisser « Edit advanced config » = No). _(Pour mémoire : un compte
  EU exigerait `hostname=eapi.pcloud.com` ; ce n'est PAS notre cas.)_
  ⚠️ Si un jour la donnée était sur un compte EU, mauvais hostname = token invalide.

Auth navigateur : rclone ouvre `http://127.0.0.1:53682/auth`, tu autorises, le token
revient tout seul.

**VPS sans navigateur (headless)** : génère le token sur le Mac puis transfère-le.

```bash
# sur le Mac (avec navigateur) :
rclone authorize pcloud          # → imprime un blob JSON token
# sur le VPS : rclone config → pcloud → coller le token quand demandé,
# et régler le même hostname (eapi.pcloud.com).
```

Le `rclone.conf` (`~/.config/rclone/rclone.conf`) contient le **token pCloud + les
clés MinIO** → **fichier secret, jamais committé** (voir §8).

## 4. Remote MinIO (source) — backend s3

`rclone config` → `n` → nom **`minio`** → type **`s3`** → provider **`Minio`** →
`access_key_id` / `secret_access_key` = les clés MinIO (mêmes que
`infra/review/secrets/*` / `infra/eurio-api/secrets/*`) → `endpoint` =
`https://eurio-s3.musubi.dev` → reste par défaut.

```bash
rclone lsd minio:                # doit lister les 4 buckets
rclone lsd pcloud:               # doit lister la racine pCloud
```

## 5. Script de backup

`scripts/backup_pcloud.sh` (idempotent, sûr, journalisé) :

```bash
#!/usr/bin/env bash
set -euo pipefail

DEST="pcloud:eurio-backup"
DB_PATH="${EURIO_DB_PATH:-/opt/eurio/infra/eurio-api/data/eurio.db}"
STAMP="$(date +%Y%m%d-%H%M)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# 1) Snapshot cohérent de la DB (WAL-safe, lecture concurrente OK)
sqlite3 "file:${DB_PATH}?mode=ro" ".backup '${TMP}/eurio-${STAMP}.db'"
rclone copy "${TMP}/eurio-${STAMP}.db" "${DEST}/db/" --progress
#    Rétention : garder 30 jours de snapshots DB
rclone delete "${DEST}/db/" --min-age 30d

# 2) Images : COPY (append-only) — ne propage JAMAIS une suppression source (§6)
for b in enrichment-crops enrichment-raws numista-canonical; do
  rclone copy "minio:${b}" "${DEST}/${b}/" --fast-list --transfers 8
done

# 3) Modèles déjà dans MinIO
rclone copy "minio:eurio-db/transfers" "${DEST}/transfers/" --fast-list

echo "✅ backup ${STAMP} terminé"
```

`go-task` (racine) pour le lancer/tester à la main :

```yaml
  backup:run:
    desc: "Backup off-site complet (DB + buckets + modèles) vers pCloud"
    cmds:
      - bash scripts/backup_pcloud.sh
  backup:db:
    desc: "Backup off-site de eurio.db uniquement"
    cmds:
      - EURIO_DB_PATH={{.EURIO_DB_PATH}} bash scripts/backup_pcloud.sh
```

## 6. Sécurité : `copy` et pas `sync` pour les images

`rclone sync` **réplique les suppressions** : un crop effacé par erreur dans MinIO
disparaîtrait aussi de pCloud au prochain run. On utilise **`rclone copy`** (la
destination ne fait qu'**accumuler**, jamais perdre). Coût = quelques orphelins sur
pCloud (négligeable vs 2 TB lifetime). En complément :

- Activer le **versioning MinIO** sur les 3 buckets images (protège *à la source*) :
  `mc version enable <alias>/enrichment-crops` (idem raws, numista-canonical).
- pCloud garde aussi un **historique de fichiers** (rewind) côté destination.

## 7. Backup au moment d'un nouvel entraînement

Le pipeline d'entraînement tourne sur Mac/PC (cf. topologie). À la fin d'un run qui
**exporte** un modèle (`.pth` / `.tflite` / `arcface_*.tar.gz`), pousser l'artefact
**directement** vers pCloud (off-site immédiat, sans attendre le cycle 6 h) :

```bash
# scripts/backup_model_pcloud.sh <iteration_id> <artefact...>
rclone copy "$ARTIFACT" "pcloud:eurio-backup/models/${ITER_ID}/" --progress
```

Câblage : ajouter ce push comme **dernière étape** de la tâche d'entraînement
(`ml/Taskfile.yml`, après l'export) ou dans `ml/training/pipeline.py` après l'export
réussi. Les modèles partent aussi vers MinIO `eurio-db/transfers/` (donc repris par
le run 6 h) — ceci est la ceinture+bretelles pour ne jamais perdre un modèle frais.

## 8. Config Nix dans ce repo

Le `flake.nix` actuel n'expose que des `devShells` (via `flake-utils.eachDefaultSystem`).
Les modules système (NixOS/darwin) sont **indépendants du système** → on les ajoute
**à côté** de `eachDefaultSystem`, au niveau racine des outputs :

```nix
# flake.nix
outputs = { self, nixpkgs, flake-utils }:
  (flake-utils.lib.eachDefaultSystem (system: {
    devShells = { /* … inchangé … */ };
  }))
  // {
    nixosModules.eurio-backup  = import ./nix/backup/nixos.nix;
    darwinModules.eurio-backup = import ./nix/backup/darwin.nix;
  };
```

### a) `nix/backup/nixos.nix` — VPS, timer toutes les 6 h

```nix
{ config, lib, pkgs, ... }:
let
  backupScript = pkgs.writeShellScript "eurio-backup" (builtins.readFile ../../scripts/backup_pcloud.sh);
in {
  systemd.services.eurio-backup = {
    description = "Eurio off-site backup → pCloud";
    path = [ pkgs.rclone pkgs.sqlite pkgs.bash ];
    environment = {
      RCLONE_CONFIG = "/var/lib/eurio-backup/rclone.conf";  # secret, hors repo
      EURIO_DB_PATH = "/opt/eurio/infra/eurio-api/data/eurio.db";
    };
    serviceConfig = { Type = "oneshot"; ExecStart = backupScript; };
  };
  systemd.timers.eurio-backup = {
    description = "Eurio backup toutes les 6 h";
    wantedBy = [ "timers.target" ];
    timerConfig = { OnCalendar = "00/6:00:00"; Persistent = true; RandomizedDelaySec = "5m"; };
  };
}
```

### b) `nix/backup/darwin.nix` — Mac (nix-darwin)

Le Mac n'a pas besoin du timer 6 h (rôle = calcul). On y met juste `rclone` + `sqlite`
dispo, et — optionnel — un `launchd` agent pour une **3ᵉ copie** (pull pCloud → disque
local) ou un backup nocturne si le Mac détient des données non encore sur le VPS.

```nix
{ pkgs, ... }: {
  environment.systemPackages = [ pkgs.rclone pkgs.sqlite ];
  # Optionnel : pull périodique pour une 3e copie
  # launchd.user.agents.eurio-backup-pull = {
  #   command = "${pkgs.rclone}/bin/rclone copy pcloud:eurio-backup $HOME/eurio-backup";
  #   serviceConfig.StartCalendarInterval = [ { Hour = 3; Minute = 0; } ];
  # };
}
```

### c) Import depuis la conf machine

Dans le flake **système** de chaque machine (hors de ce repo), ajouter ce repo en
input puis importer le module :

```nix
# NixOS (VPS) :   imports = [ inputs.eurio.nixosModules.eurio-backup ];
# nix-darwin (Mac): imports = [ inputs.eurio.darwinModules.eurio-backup ];
# avec  inputs.eurio.url = "git+https://codeberg.org/Musubi42/Eurio";
```

Le `rclone.conf` (token pCloud + clés MinIO) **n'est pas dans le repo** : le déposer
sur chaque machine (`RCLONE_CONFIG` ci-dessus), ou le rendre depuis SOPS si on veut
le centraliser plus tard (cf. `docs/operations/secrets-followup.md`).

## 9. Restauration (à tester une fois — drill)

```bash
# DB : choisir un snapshot, l'installer dans le volume (API arrêtée)
rclone copy pcloud:eurio-backup/db/eurio-<STAMP>.db ./restore/
docker compose stop eurio-api
cp ./restore/eurio-<STAMP>.db infra/eurio-api/data/eurio.db
docker compose start eurio-api && curl -s …/healthz

# Images : re-pousser un bucket dans MinIO
rclone copy pcloud:eurio-backup/enrichment-crops minio:enrichment-crops
```

> Un backup non testé n'est pas un backup. Faire **un** drill de restauration après
> la première mise en place, puis noter ici que ça marche (date + résultat).

## 10. Checklist de mise en place

- [ ] Vérifier la région du compte pCloud (EU → `hostname=eapi.pcloud.com`).
- [ ] `rclone config` : remotes `pcloud` (headless via Mac) + `minio`.
- [ ] `rclone lsd pcloud:` et `rclone lsd minio:` OK.
- [ ] `scripts/backup_pcloud.sh` + `scripts/backup_model_pcloud.sh` (+ tâches go-task).
- [ ] `nix/backup/{nixos,darwin}.nix` + wiring `flake.nix` + import conf machines.
- [ ] `mc version enable` sur les 3 buckets images.
- [ ] Hook backup-modèle en fin de pipeline d'entraînement.
- [ ] **Drill de restauration** réussi (noter ici).
- [ ] (post-cutover C8) retirer le mécanisme lease/MinIO-canonique — garder le backup.
