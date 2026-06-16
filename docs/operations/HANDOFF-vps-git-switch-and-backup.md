# HANDOFF — VPS : backup pCloud d'abord, puis bascule git GitHub → Codeberg

> **Pour qui** : une session Claude Code (ou un humain) qui tourne **sur le VPS**
> (NixOS, là où tournent MinIO + review_service + eurio-api en Docker).
> **But, dans l'ordre strict** :
> 1. **SAUVEGARDER** vers pCloud (la DB **et** toute la data MinIO) — **AVANT de
>    toucher quoi que ce soit**.
> 2. Basculer la source git du VPS de **GitHub → Codeberg** sans rien perdre.
>
> **Tu produis un résumé en fin** (modèle §6) que l'utilisateur ramènera.

---

## 0. Invariants (à respecter absolument)

- ⛔ **Ne jamais écrire/supprimer dans MinIO** (buckets ou `infra/minio/data/`). On
  fait de la **lecture** pour backup, point.
- ⛔ **Pas de git avant que le backup soit vérifié** (§1 entièrement vert).
- 🔁 **L'historique git a été réécrit** côté Codeberg/GitHub (nettoyage + purge de
  secrets). Le clone du VPS a donc un historique **divergent** → un `git pull` simple
  échouera. On fait `fetch` + `reset --hard` (§2).
- 💾 **La data lourde vit DANS le checkout** : `infra/minio/data/` (crops/raws/
  canonical, plusieurs Go) et `infra/eurio-api/data/eurio.db`. Elle est **gitignorée**
  → préservée par `reset --hard` (fichiers untracked). **C'est pourquoi on bascule
  EN PLACE, pas par un re-clone** (un re-clone orphelinerait ces Go).
- ☁️ **pCloud = compte US** → `hostname = api.pcloud.com` (le défaut).
- 🔑 La **DB canonique actuelle = l'objet `eurio-db/eurio.db` dans MinIO** (Modèle A,
  le Mac est writer via lease). Donc backuper les buckets MinIO **inclut la DB**. La
  copie locale `infra/eurio-api/data/eurio.db` (conteneur C4) est une copie jetable.

## 0.bis Prérequis (vérifier, ne pas supposer)

```bash
cd /opt/eurio || { echo "adapter le chemin du repo"; }
git remote -v                                  # origin doit pointer GitHub (l'ancien)
docker ps | grep -iE 'minio|review|eurio-api'  # conteneurs up
ls infra/minio/data/                           # buckets présents (crown jewels)
ls infra/minio/secrets/minio_root_user infra/minio/secrets/minio_root_password
curl -s https://eurio-s3.musubi.dev/minio/health/live -o /dev/null -w "%{http_code}\n"  # 200
nix shell nixpkgs#rclone --command rclone version   # rclone dispo (NixOS)
```

---

## 1. PHASE 1 — Backup vers pCloud (AVANT tout le reste)

> Objectif : une copie off-site de **la DB + tous les buckets MinIO**, vérifiée.
> Outil : `rclone` (lecture MinIO en S3 → écriture pCloud). On utilise `copy`
> (append-only) : **jamais** `sync` (qui propagerait une suppression).

### 1.1 — Remote `minio` (source, lecture seule en pratique)

`rclone` lit la config dans `~/.config/rclone/rclone.conf`. Crée les 2 remotes.
Les creds MinIO = **root** (accès complet aux 4 buckets) :

```bash
RU=$(cat infra/minio/secrets/minio_root_user)
RP=$(cat infra/minio/secrets/minio_root_password)
nix shell nixpkgs#rclone --command rclone config create minio s3 \
  provider=Minio \
  access_key_id="$RU" \
  secret_access_key="$RP" \
  endpoint=https://eurio-s3.musubi.dev \
  region=us-east-1
nix shell nixpkgs#rclone --command rclone lsd minio:   # doit lister les 4 buckets
```

### 1.2 — Remote `pcloud` (destination, US, headless)

Le VPS n'a pas de navigateur → générer le token **sur le Mac** puis le coller ici.

```bash
# ── SUR LE MAC (navigateur) ──
rclone authorize pcloud          # ouvre le navigateur, autorise → imprime un token JSON
# Copier tout le blob {"access_token":...}.

# ── SUR LE VPS ──
nix shell nixpkgs#rclone --command rclone config create pcloud pcloud \
  hostname=api.pcloud.com \
  token='<COLLER_LE_BLOB_TOKEN_DU_MAC>'
nix shell nixpkgs#rclone --command rclone lsd pcloud:   # doit lister la racine pCloud
```

> ⚠️ Le `rclone.conf` contient désormais le token pCloud + les clés MinIO → **fichier
> secret**, ne le committe nulle part. Il reste local au VPS.

### 1.3 — Lancer le backup (les 4 buckets, DB incluse)

```bash
RC() { nix shell nixpkgs#rclone --command rclone "$@"; }
DEST="pcloud:eurio-backup"
for b in eurio-db enrichment-crops enrichment-raws numista-canonical; do
  echo "=== backup $b ==="
  RC copy "minio:$b" "$DEST/$b/" --fast-list --transfers 8 --progress
done
```

`eurio-db/eurio.db` est un **objet complet** (uploadé d'un bloc par le Mac sous lease)
→ la copie est cohérente, pas besoin de `sqlite .backup` ici.

### 1.4 — VÉRIFIER (bloquant : tout doit être vert avant la Phase 2)

```bash
RC() { nix shell nixpkgs#rclone --command rclone "$@"; }
for b in eurio-db enrichment-crops enrichment-raws numista-canonical; do
  echo "=== $b ==="
  echo -n "source : "; RC size "minio:$b"
  echo -n "backup : "; RC size "pcloud:eurio-backup/$b"
  RC check "minio:$b" "pcloud:eurio-backup/$b" --one-way   # 0 différence attendue
done
# Sanity DB :
RC ls pcloud:eurio-backup/eurio-db | grep eurio.db    # taille ~102 MB
```

`rclone check --one-way` doit reporter **0 fichier manquant / différent**. Sinon,
**STOP**, ne passe pas en Phase 2, et note l'erreur dans le résumé.

> _(Optionnel, secondaire)_ Tar du volume brut comme filet supplémentaire — **non
> requis** (la config MinIO est reproductible via `bootstrap.sh` + `policies/`, donc
> le backup objet ci-dessus suffit). Si tu y tiens : `docker compose -f
> infra/minio/docker-compose.yml stop minio` puis `tar -C infra/minio -czpf
> /tmp/minio-data.tgz data` puis redémarrer + `rclone copy /tmp/minio-data.tgz
> pcloud:eurio-backup/volume-snapshots/`. Le `stop` garantit la cohérence ; `-p`
> préserve les permissions dans le tar.

---

## 2. PHASE 2 — Bascule git GitHub → Codeberg (EN PLACE)

> Seulement **après** §1.4 vert. On garde le dossier `/opt/eurio` en place pour ne pas
> déplacer les Go de `infra/*/data/`.

```bash
cd /opt/eurio
git remote -v                                   # constate origin = github
git remote set-url origin https://codeberg.org/Musubi42/Eurio.git
git fetch origin
git checkout sources-jo-wikipedia 2>/dev/null || git switch sources-jo-wikipedia
git reset --hard origin/sources-jo-wikipedia    # bascule sur l'historique réécrit
git log --oneline -3
```

`reset --hard` met le working tree au niveau de Codeberg. Il **ne touche pas** les
fichiers **untracked/gitignorés** → `infra/minio/data/`, `infra/minio/secrets/`,
`infra/eurio-api/data/`, `infra/eurio-api/secrets/`, `rclone.conf` sont **préservés**.

### 2.1 — (Optionnel) Alléger le checkout

Le VPS n'a besoin que de `infra/` + `ml/`. Pour retirer le superflu tracké
(app-android, admin, docs…) **sans toucher la data untracked** :

```bash
git sparse-checkout init --cone
git sparse-checkout set infra ml
git checkout sources-jo-wikipedia
ls                       # ne reste que infra/ ml/ (+ data/secrets untracked sous infra/*)
```

### 2.2 — Vérifier que rien n'a bougé côté données / services

```bash
ls infra/minio/data/                         # buckets toujours là
ls infra/minio/secrets/                      # creds toujours là
docker ps | grep -iE 'minio|review|eurio-api'  # conteneurs toujours up (git ne les redémarre pas)
curl -s https://eurio-s3.musubi.dev/minio/health/live -o /dev/null -w "%{http_code}\n"  # 200
curl -s https://eurio-api.musubi.dev/healthz ; echo                                      # {"ok":true,...}
```

> Les conteneurs tournent sur leurs volumes/secrets, **indépendamment de git**. La
> bascule git ne les redémarre pas. Ne rebuild `eurio-api` que si tu veux déployer le
> nouveau code (centralisation secrets) — et seulement après accord (hors scope ici).

---

## 3. Ce qu'on NE fait PAS dans ce handoff

- ❌ Supprimer quoi que ce soit dans MinIO ou le `eurio-db` bucket.
- ❌ Toucher au lease / au cutover Modèle B (c'est C8, séparé).
- ❌ Rebuild/redéployer les conteneurs (sauf demande explicite).
- ❌ Committer `rclone.conf` ou un secret.

## 4. Restauration (pour info — drill à faire plus tard, pas maintenant)

- **MinIO** : fresh MinIO → `infra/minio/bootstrap.sh` (recrée buckets + app-user +
  policy depuis git) → `rclone copy pcloud:eurio-backup/<bucket> minio:<bucket>`.
  Pas de souci d'ownership (restauration niveau-objet).
- **DB** : `rclone copy pcloud:eurio-backup/eurio-db/eurio.db ./` puis ré-injection
  (volume eurio-api, ou re-upload dans MinIO selon le modèle en vigueur).

## 5. Dépannage

- `rclone lsd minio:` échoue → vérifier endpoint (`https://eurio-s3.musubi.dev`) et que
  les creds lus sont bien les **root** (pas l'app-user, qui n'a pas accès à `eurio-db`).
- `rclone lsd pcloud:` échoue → token mal collé, ou `hostname` ≠ `api.pcloud.com`.
- `git reset --hard` se plaint d'un fichier tracké modifié localement sur le VPS →
  noter lequel (modif locale non commitée ?), `git stash` ou copier de côté, puis
  reprendre. Ne jamais forcer si ça touche un `secrets/` ou `data/`.

## 6. Résumé à produire (handoff retour)

```
## VPS — bascule git + backup pCloud

- Backup pCloud :
    - eurio-db    : source <taille/objets> / backup <…> / check --one-way : <0 diff ?>
    - crops       : <…> / <…> / <…>
    - raws        : <…> / <…> / <…>
    - numista-canonical : <…> / <…> / <…>
    - eurio.db présent dans le backup (taille) : <…>
    - tar volume (si fait) : <oui/non>
- Git :
    - origin avant : github  → après : codeberg (set-url OK ?)
    - HEAD après reset : <sha> (== Codeberg ?)
    - sparse-checkout appliqué : <oui/non> (contenu : infra ml)
- Données préservées : infra/minio/data <ok>, secrets <ok>, eurio-api/data <ok>
- Services après bascule : minio <200?>, eurio-api /healthz <…>, review <…>
- Déviations / blocages : <…>
- Questions ouvertes : <…>
```
```
```
