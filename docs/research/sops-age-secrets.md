# Sécuriser les secrets d'un repo avec SOPS + age

Guide reproductible — basé sur le setup Eurio.

## Principe

Les secrets (clés API, credentials) vivent **chiffrés dans le repo** sous forme d'un fichier `secrets/dev.env`. Chaque machine autorisée a sa propre paire de clés [age](https://github.com/FiloSottile/age) ; n'importe laquelle des clés privées peut déchiffrer le fichier. [SOPS](https://github.com/getsops/sops) gère le chiffrement multi-recipients et l'édition en clair dans `$EDITOR`.

Le `.envrc` ([direnv](https://direnv.net/)) déchiffre automatiquement à chaque `cd` dans le repo et exporte les vars dans le shell.

```
repo/
├── .sops.yaml          # config SOPS : quels fichiers, quels recipients (commité)
├── secrets/
│   ├── dev.env         # fichier chiffré SOPS (commité)
│   └── dev.env.example # template plaintext des clés attendues (commité, sans valeurs)
└── .envrc              # déchiffre + exporte au chargement du shell (commité)
```

---

## Mise en place initiale (une seule fois)

### 1. Dépendances

Via Nix (recommandé) ou Homebrew :

```bash
# Nix — dans flake.nix devShell :
sops age

# Homebrew :
brew install sops age
```

### 2. Générer sa clé age sur la première machine

```bash
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
# Affiche : # public key: age1xxxxxxxxxxxxxxxxxxxx
```

Sauvegarder `~/.config/sops/age/keys.txt` dans le password manager — c'est la seule sauvegarde.

### 3. Créer `.sops.yaml`

```yaml
# .sops.yaml
creation_rules:
  - path_regex: secrets/.*\.env$
    key_groups:
      - age:
          # mac — pubkey générée par `age-keygen` sur le Mac
          - age1xxxxxxxxxxxxxxxxxxxx
```

### 4. Créer `secrets/dev.env.example`

Template committé avec les noms de clés mais sans valeurs :

```dotenv
# Template — la version chiffrée vraie est secrets/dev.env (SOPS+age).

API_KEY=xxxxx
DATABASE_URL=postgres://...
```

### 5. Créer et chiffrer `secrets/dev.env`

```bash
cp secrets/dev.env.example secrets/dev.env
# Remplir avec les vraies valeurs dans l'éditeur
sops -e -i secrets/dev.env       # chiffre in-place
git add secrets/dev.env .sops.yaml
git commit -m "secrets: init SOPS+age encryption"
```

### 6. Câbler le `.envrc`

```bash
# .envrc
if [ -f secrets/dev.env ]; then
  set -a
  . <(sops -d --input-type dotenv --output-type dotenv secrets/dev.env)
  set +a
else
  echo "⚠️  secrets/dev.env absent — voir README §Secrets pour le bootstrap." >&2
fi
```

`set -a` auto-exporte chaque variable du fichier sourcé sans passer par `eval` ni `sed`, ce qui gère proprement les commentaires et les lignes vides.

Puis :

```bash
echo "secrets/dev.env" >> .gitignore   # au cas où on oublierait la version chiffrée
direnv allow
```

---

## Bootstrap d'une nouvelle machine (3 phases, 2 machines)

### Phase A — sur la nouvelle machine

```bash
# 1. Générer la clé age
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
# → noter la pubkey affichée : age1xxxx...

# 2. Sauvegarder keys.txt dans le password manager

# 3. Ajouter la pubkey dans .sops.yaml (sous la liste age:)
#    puis dans .envrc si le hostname n'y est pas encore

# 4. Commit + push
git add .sops.yaml .envrc
git commit -m "secrets: add <machine> age recipient"
git push
```

### Phase B — sur une machine déjà autorisée

```bash
git pull

# Re-chiffre dev.env pour inclure le nouveau recipient
sops updatekeys secrets/dev.env

git add secrets/dev.env
git commit -m "secrets: re-encrypt dev.env for <machine>"
git push
```

`updatekeys` ne peut tourner que sur une machine capable de déchiffrer — d'où le passage obligatoire par une machine existante.

### Phase C — retour sur la nouvelle machine

```bash
git pull
direnv allow
echo $API_KEY   # doit être non-vide
```

---

## Opérations courantes

### Éditer un secret existant

```bash
sops secrets/dev.env
# → s'ouvre dans $EDITOR en clair, re-chiffre à la sauvegarde
git add secrets/dev.env
git commit -m "secrets: update <KEY>"
git push
# Sur les autres machines :
git pull && direnv reload
```

### Ajouter un nouveau secret

```bash
sops secrets/dev.env          # ajouter MA_NOUVELLE_KEY=valeur, sauvegarder
direnv reload                 # propage dans le shell courant
env | grep MA_NOUVELLE_KEY    # sanity check : doit afficher la valeur

git add secrets/dev.env
git commit -m "secrets: add MA_NOUVELLE_KEY"
git push
# Sur les autres machines :
git pull && direnv reload
```

Penser à reporter la clé (avec valeur factice) dans `secrets/dev.env.example` pour que les nouveaux contributeurs sachent ce qui est attendu.

### Secrets indexés (pool de clés)

Pour des secrets consommés via un pool round-robin (ex: plusieurs API keys du même provider) :

```dotenv
# Dans dev.env
API_KEY_00=xxx
API_KEY_01=xxx
API_KEY_02=xxx
```

Toujours ajouter dans l'ordre sans laisser de trou — si le code scanne jusqu'au premier slot manquant, un trou casse le pool silencieusement.

Sanity check après ajout :

```bash
env | grep -c '^API_KEY_'   # doit afficher le bon nombre de slots
```

---

## Rotation / révocation

Machine compromise ou perdue :

```bash
# 1. Retirer sa pubkey de .sops.yaml
# 2. Re-chiffrer sans ce recipient
sops updatekeys secrets/dev.env
# 3. Commit + push
git add .sops.yaml secrets/dev.env
git commit -m "secrets: revoke <machine>"
git push
# 4. Rotater les secrets eux-mêmes côté providers (Supabase, eBay, etc.)
```

La privkey orpheline ne pourra plus déchiffrer les futures versions du fichier.

---

## Première initialisation d'un repo from scratch

```bash
# Sur la première machine, après avoir mis sa pubkey dans .sops.yaml :
cp secrets/dev.env.example secrets/dev.env
# remplir avec les vraies valeurs
sops -e -i secrets/dev.env
git add secrets/dev.env .sops.yaml
git commit -m "secrets: bootstrap SOPS+age"
```

---

## Référence rapide

| Commande | Effet |
|---|---|
| `age-keygen -o ~/.config/sops/age/keys.txt` | Générer sa paire de clés age |
| `sops secrets/dev.env` | Éditer en clair (re-chiffre à la sauvegarde) |
| `sops -e -i secrets/dev.env` | Chiffrer in-place (première fois) |
| `sops -d secrets/dev.env` | Afficher en clair (stdout) |
| `sops updatekeys secrets/dev.env` | Re-chiffrer avec les recipients du `.sops.yaml` courant |
| `direnv reload` | Re-déchiffrer + re-exporter dans le shell courant |
