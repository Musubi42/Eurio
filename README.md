# Eurio

App Android de collection de pièces euro. L'acte central de l'app est le **scan** : pointer la caméra sur une pièce, l'identifier (ML on-device), la proposer pour ajout au coffre. Tout l'UX tourne autour de cet acte.

Monorepo :

- `app-android/` — app Kotlin / Jetpack Compose / Material 3
- `admin/packages/web/` — console Vue 3 / Vite (coins, sets, audit) déployée sur Vercel
- `admin/packages/parity/` — tooling QA local (Playwright, Maestro, screenshots proto ↔ Android)
- `ml/` — projet Python standalone (FastAPI, entraînement, scraping sources)
- `supabase/` — migrations SQL + types générés
- `docs/` — design docs, phases d'implémentation, recherche technique

Plan de travail : `docs/app-implem-phases/README.md`.
Règles repo : `CLAUDE.md`.

## Démarrer le projet

Prérequis (par machine) :

- [Nix](https://nixos.org/download.html) avec flakes activés
- [direnv](https://direnv.net/) + [nix-direnv](https://github.com/nix-community/nix-direnv)
- Une clé age perso (voir §Secrets ci-dessous)

Premier lancement :

```bash
git clone <repo> eurio
cd eurio
cp .envrc.example .envrc
direnv allow
```

Le `.envrc` détecte le hostname et charge le bon devShell Nix :

| Hostname | Profil | Contenu |
|---|---|---|
| `Musubi42s-MacBook-Air-Oim` | `mac` | full stack (Android + ML CPU + admin web + maestro) |
| `desktop` | `pc` | full stack + LD_LIBRARY_PATH NVIDIA pour CUDA/OpenCV |
| `nixos` | `vps` | léger : `go-task` + `minio-client` |

Hostname inconnu → `direnv allow` échoue avec un message expliquant comment ajouter la machine.

Après ça, toutes les commandes passent par `go-task` :

```bash
go-task                          # liste les tâches dispo
go-task android:run              # build + install + start app sur device
go-task tokens:generate          # regen tokens design depuis shared/tokens.css
```

## Secrets

Les secrets (clés Supabase, API Numista, MinIO, …) sont **chiffrés dans le repo** via [SOPS](https://github.com/getsops/sops) + [age](https://github.com/FiloSottile/age). Chaque machine perso a sa propre paire de clés age ; n'importe laquelle des privkeys peut déchiffrer `secrets/dev.env`. Le `.envrc` les exporte au chargement du shell.

### Bootstrap d'une nouvelle machine

1. **Générer une clé age** sur la machine :
   ```bash
   mkdir -p ~/.config/sops/age
   age-keygen -o ~/.config/sops/age/keys.txt
   ```
   La commande affiche `# public key: age1...` — copier cette pubkey.

2. **Backup la privkey dans le password manager** (le contenu complet de `~/.config/sops/age/keys.txt`). C'est la seule sauvegarde — si elle est perdue, la machine ne pourra plus déchiffrer.

3. **Ajouter la pubkey à `.sops.yaml`** sous `creation_rules → key_groups → age:`.

4. **Re-chiffrer les secrets pour inclure le nouveau recipient** depuis une machine déjà autorisée :
   ```bash
   sops updatekeys secrets/dev.env
   ```

5. **Commit + push** `.sops.yaml` et `secrets/dev.env`.

6. Sur la nouvelle machine : `git pull && direnv reload`. Les secrets sont déchiffrés et exportés.

### Éditer un secret

```bash
sops secrets/dev.env
```

Ouvre le fichier en clair dans `$EDITOR`, re-chiffre automatiquement à la sauvegarde. Commit + push, puis sur chaque autre machine `git pull && direnv reload`.

### Première initialisation du repo (a déjà été faite)

Si tu rebootes le système de zéro :

```bash
# Sur la première machine, après avoir mis sa pubkey dans .sops.yaml :
cp secrets/dev.env.example secrets/dev.env
# remplir avec les vraies valeurs
sops -e -i secrets/dev.env       # chiffre in-place
git add secrets/dev.env .sops.yaml
```

### Rotation / révocation

Machine compromise ou perdue : retirer sa pubkey de `.sops.yaml`, lancer `sops updatekeys secrets/dev.env`, commit. La privkey orpheline ne pourra plus déchiffrer les futures versions. Pour les secrets eux-mêmes (Supabase keys, etc.), les rotater côté providers.
