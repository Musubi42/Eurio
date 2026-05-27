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

Le bootstrap se fait en 3 phases sur 2 machines : la nouvelle machine publie sa pubkey, une machine déjà autorisée re-chiffre `secrets/dev.env` pour l'inclure, la nouvelle machine récupère le résultat.

**Phase A — sur la nouvelle machine**

1. **Générer une clé age** :
   ```bash
   mkdir -p ~/.config/sops/age
   age-keygen -o ~/.config/sops/age/keys.txt
   ```
   La commande affiche `# public key: age1...` — copier cette pubkey.

   Si `keys.txt` existe déjà, c'est qu'une identité antérieure traîne. Soit la réutiliser (regarder la ligne `# public key:` du fichier), soit l'archiver ailleurs avant de regénérer (et penser à retirer l'ancienne pubkey de `.sops.yaml` côté rotation).

2. **Backup la privkey dans le password manager** (contenu complet de `~/.config/sops/age/keys.txt`). C'est la seule sauvegarde — si elle est perdue, la machine ne pourra plus déchiffrer.

3. **Ajouter la pubkey à `.sops.yaml`** sous `creation_rules → key_groups → age:`, à côté du commentaire correspondant à la machine.

4. **Câbler le hostname dans `.envrc`** si pas encore présent. Vérifier `hostname -s` et, si absent du `case`, ajouter une ligne :
   ```bash
   <hostname>) use flake .#<profil> ;;
   ```
   où `<profil>` est `mac`, `pc` ou `vps` (voir tableau §Démarrer le projet).

5. **Commit + push** sur la nouvelle machine :
   ```bash
   git add .sops.yaml .envrc
   git commit -m "secrets: add <machine> age recipient"
   git push
   ```

**Phase B — sur une machine déjà autorisée (Mac, VPS, …)**

6. `git pull` pour récupérer la nouvelle pubkey.

7. Re-chiffrer `secrets/dev.env` pour inclure le nouveau recipient :
   ```bash
   sops updatekeys secrets/dev.env
   ```
   `updatekeys` ne peut tourner que sur une machine capable de déchiffrer le fichier — d'où le détour par une machine déjà autorisée.

8. Commit + push :
   ```bash
   git add secrets/dev.env
   git commit -m "secrets: re-encrypt dev.env for <machine>"
   git push
   ```

**Phase C — retour sur la nouvelle machine**

9. `git pull && direnv allow` — les secrets sont déchiffrés et exportés au prochain `cd` dans le repo.

10. Sanity check :
    ```bash
    echo $SUPABASE_URL   # doit être non-vide
    ```

### Éditer un secret

```bash
sops secrets/dev.env
```

Ouvre le fichier en clair dans `$EDITOR`, re-chiffre automatiquement à la sauvegarde. Commit + push, puis sur chaque autre machine `git pull && direnv reload`.

### Ajouter un nouveau secret

Même flow que pour éditer, avec deux nuances : `direnv reload` après sauvegarde pour propager la nouvelle var dans le shell courant, et un sanity check pour confirmer qu'elle est bien là.

```bash
sops secrets/dev.env                    # ajouter MA_NOUVELLE_KEY=valeur, sauvegarder
direnv reload                           # propage dans le shell courant
env | grep -c 'MA_NOUVELLE_KEY'        # sanity check : doit afficher 1
git add secrets/dev.env
git commit -m "secrets: add MA_NOUVELLE_KEY"
git push
```

Pour les secrets **indexés** (ex: `NUMISTA_API_KEY_MUSUBI00`, `MUSUBI01`, …, consommés via un pool round-robin par `ml/referential/numista_keys.py`), `env | grep -c '^NUMISTA_API_KEY_MUSUBI'` compte combien de slots sont remplis. Attention : le scanner s'arrête au premier slot manquant, donc toujours ajouter dans l'ordre sans laisser de trou.

Sur les autres machines : `git pull && direnv reload`. Si la convention est de tenir `secrets/dev.env.example` à jour, y reporter aussi la nouvelle clé avec une valeur factice.

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


ok alors ccproxy est opérationnel et tourne le la petite note en mémoire ce n'est pas un souci mais quand on fera un test on fait un test sur une image on s'assure que parce qu'on fait un test sur une image parce qu'on s'assure que le prompt qu'on donne à ccproxy le gson qu'on va récupérer etc est bien formaté une fois qu'on aura fait ce premier test on pourra le lancer sur cinq images pour voir si on arrive va faire un match parce que ça ne sert à rien de faire un appel cloud code pour une seule image et un format de réponse autant batcher je sais pas combien c'est le la taille idéale pour un match mais je pense que déjà mettre dix images ça sera largement géré maintenant j'ai envie qu'on utilise cloud vision en tant que juge du coup sur la première image on réfléchira à qu'est ce qu'un bon juge on juge sur le fameux DE 2010 sur notre site d'image restreint on va pas tout mètre dedans concernant la sévérité du under crop je te laisse tester mild et pour le modèle on utilise sonnette c'est celui qui est configuré par défaut donc je te laisse checker ccproxy tu peux faire un premier appel pour voir comment ça fonctionne tu peux aussi regarder un peu plus là le code de cc proxy et on discute de l'implémentation