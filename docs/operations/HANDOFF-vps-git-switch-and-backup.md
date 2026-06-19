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

> **Priorité absolue de ce handoff** : la data MinIO (crops, raws, canonical, **et
> l'objet `eurio-db/eurio.db`**) **ne doit jamais être supprimée ni écrasée** par
> cette procédure. Tout le reste (bascule git, sparse-checkout, etc.) est
> subordonné à cette garantie. En cas de doute → STOP.

- ⛔ **Ne jamais écrire/supprimer dans MinIO** (buckets ou `infra/minio/data/`). On
  fait de la **lecture** pour backup, point.
- ⛔ **Pas de git avant que le backup soit vérifié** (§1.4 entièrement vert) **et que
  le pre-flight §2.0 soit passé**.
- 🛟 **Snapshot local belt-and-braces obligatoire AVANT TOUT** (§1.0) : hardlinks
  instantanés de `infra/minio/data/` (+ `infra/eurio-api/data/` si présent) vers
  `/opt/eurio-snapshot-<date>/`. Coût disque ≈ 0, filet local indépendant de pCloud.
- 🔁 **L'historique git a été réécrit** côté Codeberg/GitHub (nettoyage + purge de
  secrets). On **ne suppose pas** que local ≡ Codeberg : on **vérifie** d'abord
  (§2.1) puis on choisit la stratégie minimale qui préserve la data :
  no-op si égal, `merge --ff-only` si fast-forward possible, `reset --hard`
  **seulement** si divergence avérée et après pre-flight §2.0 vert.
- 💾 **La data lourde vit DANS le checkout** : `infra/minio/data/` (crops/raws/
  canonical, plusieurs Go) et — si déployé — `infra/eurio-api/data/eurio.db`. Elle
  est **gitignorée** → préservée par toute opération git qui ne touche pas aux
  fichiers untracked. **C'est pourquoi on bascule EN PLACE, pas par un re-clone**
  (un re-clone orphelinerait ces Go).
- ☁️ **pCloud = compte US** → `hostname = api.pcloud.com` (le défaut).
- 🔑 La **DB canonique actuelle = l'objet `eurio-db/eurio.db` dans MinIO** (Modèle A,
  le Mac est writer via lease). Donc backuper les buckets MinIO **inclut la DB**. La
  copie locale `infra/eurio-api/data/eurio.db` (conteneur C4) est une copie jetable
  **si elle existe** — on la backupe quand même par précaution (§1.3.bis).

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

### 1.0 — Snapshot local belt-and-braces (OBLIGATOIRE, en premier)

> Filet de sécurité **local** indépendant de pCloud. Les hardlinks sont instantanés
> et ne coûtent ~rien en disque (mêmes inodes que les fichiers d'origine). Si une
> opération ultérieure malmenait `infra/minio/data/`, on peut rétablir depuis le
> snapshot sans même toucher pCloud.

```bash
SNAP="/opt/eurio-snapshot-$(date +%F-%H%M)"
mkdir -p "$SNAP"
# MinIO data : hardlinks récursifs (rapide, ~0 disque, même filesystem requis).
cp -al infra/minio/data "$SNAP/minio-data"
# Copie locale eurio.db (peut être absente si conteneur eurio-api pas déployé).
if [ -e infra/eurio-api/data ]; then
  cp -a infra/eurio-api/data "$SNAP/eurio-api-data"
fi
echo "$SNAP" > /tmp/eurio-snapshot-path   # mémorisé pour les vérifs §1.4/§2.0/§2.2
ls -la "$SNAP" && du -sh "$SNAP"
# Sanity : compter les fichiers côté source vs snapshot.
echo "source files: $(find infra/minio/data -type f | wc -l)"
echo "snap   files: $(find "$SNAP/minio-data" -type f | wc -l)"
```

> ⚠️ Si `cp -al` échoue (filesystems différents, ou data sur un volume Docker hors
> `/opt/eurio/infra/minio/data/`), tomber sur `cp -a` (copie réelle, prend la place
> disque). Ne pas continuer sans snapshot.

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
  region=us-east-1 \
  force_path_style=true \
  v2_auth=true
nix shell nixpkgs#rclone --command rclone lsd minio:   # doit lister les 4 buckets
```

> ⚠️ **`v2_auth=true` est requis** parce que `eurio-s3.musubi.dev` est derrière
> Cloudflare. Le WAF/proxy CF altère ou supprime les en-têtes `Amz-Sdk-*` que le
> SDK Go v2 (utilisé par rclone ≥ 1.70) signe en SigV4 → `SignatureDoesNotMatch`.
> SigV2 signe moins d'en-têtes et passe sans souci. `mc` n'est pas touché car il
> utilise minio-go avec une stratégie de signature compatible avec les proxies.

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

### 1.3.bis — Backup conditionnel de la copie locale `eurio.db` (filet)

> Si le conteneur `eurio-api` est déployé sur ce VPS, sa copie locale de la DB
> existe sous `infra/eurio-api/data/eurio.db`. Le doc la qualifie de « jetable »
> (la canonique est dans MinIO), mais on la backupe quand même comme filet — coût
> ~100 Mo sur pCloud, gain : indépendance de bug MinIO.

```bash
RC() { nix shell nixpkgs#rclone --command rclone "$@"; }
if [ -f infra/eurio-api/data/eurio.db ]; then
  TS=$(date +%F)
  RC copyto infra/eurio-api/data/eurio.db \
    "pcloud:eurio-backup/local-db/eurio-${TS}.db" --progress
  RC ls "pcloud:eurio-backup/local-db/" | grep "eurio-${TS}.db"
else
  echo "ℹ️  infra/eurio-api/data/eurio.db absent — pas de copie locale à backuper."
fi
```

### 1.4 — VÉRIFIER (bloquant : tout doit être vert avant la Phase 2)

```bash
RC() { nix shell nixpkgs#rclone --command rclone "$@"; }
for b in eurio-db enrichment-crops enrichment-raws numista-canonical; do
  echo "=== $b ==="
  echo -n "source : "; RC size "minio:$b"
  echo -n "backup : "; RC size "pcloud:eurio-backup/$b"
  RC check "minio:$b" "pcloud:eurio-backup/$b" --one-way   # 0 différence attendue
done
# Sanity DB (taille) :
RC ls pcloud:eurio-backup/eurio-db | grep eurio.db    # taille ~102 MB

# Sanity DB (intégrité) : hash MinIO source vs pCloud destination.
# Méthode : on télécharge l'objet DB depuis les deux sources et on compare les sha256.
TMP=$(mktemp -d)
RC copyto minio:eurio-db/eurio.db                "$TMP/db-from-minio.db"
RC copyto pcloud:eurio-backup/eurio-db/eurio.db  "$TMP/db-from-pcloud.db"
sha256sum "$TMP/db-from-minio.db" "$TMP/db-from-pcloud.db"   # les 2 hash doivent être identiques
rm -rf "$TMP"

# Sanity snapshot local : doit exister et avoir le même # de fichiers que source.
# IMPORTANT : on EXCLUT `.minio.sys/` (metacache + trash interne en rotation
# constante, sans impact sur les objets utilisateur).
SNAP=$(cat /tmp/eurio-snapshot-path 2>/dev/null || true)
if [ -z "$SNAP" ] || [ ! -d "$SNAP/minio-data" ]; then
  echo "❌ Snapshot local §1.0 introuvable — STOP, refaire §1.0."; exit 1
fi
SRC_N=$(find infra/minio/data -type f -not -path '*/.minio.sys/*' | wc -l)
SNP_N=$(find "$SNAP/minio-data"   -type f -not -path '*/.minio.sys/*' | wc -l)
echo "Objets utilisateur (hors .minio.sys) : source=$SRC_N  snap=$SNP_N"
test "$SRC_N" = "$SNP_N" \
  && echo "✅ snapshot local cohérent avec la source (data utilisateur)" \
  || { echo "❌ # fichiers utilisateur diffère — STOP, investiguer."; exit 1; }
```

`rclone check --one-way` doit reporter **0 fichier manquant / différent** ET les
deux `sha256sum` de la DB doivent être **identiques**. Sinon, **STOP**, ne passe
pas en Phase 2, et note l'erreur dans le résumé.

> _(Optionnel, secondaire)_ Tar du volume brut comme filet supplémentaire — **non
> requis** (la config MinIO est reproductible via `bootstrap.sh` + `policies/`, donc
> le backup objet ci-dessus suffit). Si tu y tiens : `docker compose -f
> infra/minio/docker-compose.yml stop minio` puis `tar -C infra/minio -czpf
> /tmp/minio-data.tgz data` puis redémarrer + `rclone copy /tmp/minio-data.tgz
> pcloud:eurio-backup/volume-snapshots/`. Le `stop` garantit la cohérence ; `-p`
> préserve les permissions dans le tar.

---

## 2. PHASE 2 — Bascule git GitHub → Codeberg (EN PLACE, Codeberg devient canonique)

> Seulement **après** §1.4 vert. On garde le dossier `/opt/eurio` en place pour ne pas
> déplacer les Go de `infra/*/data/`.
>
> **Stratégie** : Codeberg devient la source canonique. On **ne suppose pas** que
> local ≡ Codeberg : on **mesure** d'abord, puis on choisit la voie minimale qui
> préserve la data.

### 2.0 — Pre-flight bloquant (rien ne touche le working tree avant ce check)

```bash
cd /opt/eurio

# (a) Aucun fichier critique ne doit être tracké par git (sinon reset --hard les écraserait).
#     Whitelist : `.do-not-delete`, `.gitkeep`, `*.example` sont des sentinels/templates
#     qui DOIVENT être trackés. Tout le reste sous data/secrets serait un drift à corriger.
LEAKED=$(git ls-files infra/minio/data infra/eurio-api/data infra/minio/secrets infra/eurio-api/secrets 2>/dev/null \
  | grep -vE '/\.do-not-delete$|/\.gitkeep$|\.example$')
if [ -n "$LEAKED" ]; then
  echo "❌ Des fichiers critiques sont TRACKÉS — STOP. Liste :"; echo "$LEAKED"
  echo "   → ne pas faire reset --hard, investiguer le .gitignore d'abord."
  exit 1
else
  echo "✅ Aucun vrai fichier de data/secret tracké (seuls les sentinels safe le sont)."
fi

# (b) Aucun fichier tracké sous infra/ ne doit être modifié localement (sinon reset --hard l'écraserait).
DIRTY=$(git status --porcelain infra/ | grep -v '^??' || true)
if [ -n "$DIRTY" ]; then
  echo "❌ Fichiers trackés modifiés sous infra/ — STOP. Liste :"; echo "$DIRTY"
  echo "   → décider : stash, commit, ou revert AVANT bascule. Ne pas écraser à l'aveugle."
  exit 1
else
  echo "✅ infra/ propre côté trackés."
fi

# (c) Le snapshot local §1.0 doit exister.
SNAP=$(cat /tmp/eurio-snapshot-path 2>/dev/null || true)
if [ -z "$SNAP" ] || [ ! -d "$SNAP/minio-data" ]; then
  echo "❌ Snapshot local §1.0 introuvable — STOP."
  exit 1
else
  echo "✅ Snapshot local présent : $SNAP"
fi
```

**Les 3 checks doivent être verts. Sinon STOP, on ne touche pas à git.**

### 2.1 — Ajouter Codeberg, mesurer la divergence, choisir la stratégie

```bash
cd /opt/eurio
git remote -v                                    # constate origin = github (avant)
git remote add codeberg https://codeberg.org/Musubi42/Eurio.git 2>/dev/null || \
  git remote set-url codeberg https://codeberg.org/Musubi42/Eurio.git
git fetch codeberg sources-jo-wikipedia

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse codeberg/sources-jo-wikipedia)
echo "LOCAL  = $LOCAL"
echo "CODEBERG = $REMOTE"

if [ "$LOCAL" = "$REMOTE" ]; then
  STRATEGY="noop"
  echo "✅ Local ≡ Codeberg → simple bascule du remote, AUCUN reset."
elif git merge-base --is-ancestor "$LOCAL" "$REMOTE"; then
  STRATEGY="ff"
  echo "↗ Local est en arrière de Codeberg → fast-forward (préserve la data)."
elif git merge-base --is-ancestor "$REMOTE" "$LOCAL"; then
  STRATEGY="ahead"
  echo "⚠ Local est EN AVANCE de Codeberg → ne pas reset --hard (perte de commits)."
  echo "  → DEMANDER À L'UTILISATEUR : push local→Codeberg, ou reset volontaire ?"
else
  STRATEGY="diverged"
  echo "⚠ Historiques DIVERGENTS — reset --hard requis pour basculer sur Codeberg."
  echo "  → DEMANDER CONFIRMATION EXPLICITE avant reset."
fi
echo "STRATEGY=$STRATEGY"
```

### 2.2 — Appliquer la stratégie choisie

#### Cas A — `noop` (local ≡ Codeberg)

```bash
# Aucun changement de working tree. On bascule juste l'URL de origin.
git remote set-url origin https://codeberg.org/Musubi42/Eurio.git
git remote remove codeberg               # on peut retirer le remote temporaire
git remote -v                            # origin = codeberg ✅
git branch --set-upstream-to=origin/sources-jo-wikipedia sources-jo-wikipedia
```

#### Cas B — `ff` (fast-forward possible)

```bash
git merge --ff-only codeberg/sources-jo-wikipedia
git remote set-url origin https://codeberg.org/Musubi42/Eurio.git
git remote remove codeberg
git branch --set-upstream-to=origin/sources-jo-wikipedia sources-jo-wikipedia
```

#### Cas C — `ahead` ou `diverged` (NE PAS exécuter sans confirmation utilisateur)

```bash
# STOP : reporter à l'utilisateur, attendre une décision explicite avant ce qui suit.
# Si décision = "reset --hard sur Codeberg, on accepte de perdre les commits locaux non poussés" :
git reset --hard codeberg/sources-jo-wikipedia
git remote set-url origin https://codeberg.org/Musubi42/Eurio.git
git remote remove codeberg
git branch --set-upstream-to=origin/sources-jo-wikipedia sources-jo-wikipedia
```

> `reset --hard` ne touche **pas** les fichiers **untracked/gitignorés** →
> `infra/minio/data/`, `infra/minio/secrets/`, `infra/eurio-api/data/`,
> `infra/eurio-api/secrets/`, `rclone.conf` sont **préservés**. Le pre-flight §2.0
> a déjà vérifié qu'aucun fichier critique n'était tracké.

### 2.3 — (Optionnel) Alléger le checkout

Le VPS n'a besoin que de `infra/` + `ml/`. Pour retirer le superflu tracké
(app-android, admin, docs…) **sans toucher la data untracked** :

```bash
git sparse-checkout init --cone
git sparse-checkout set infra ml
git checkout sources-jo-wikipedia
ls                       # ne reste que infra/ ml/ (+ data/secrets untracked sous infra/*)
```

### 2.4 — Vérifier que la data et les services sont intacts

```bash
# (a) Data untracked toujours là.
ls infra/minio/data/                         # 4 buckets toujours là
ls infra/minio/secrets/                      # creds toujours là
[ -d infra/eurio-api/data ] && ls infra/eurio-api/data/   # si conteneur déployé

# (b) # de fichiers MinIO inchangé par rapport au snapshot §1.0 (data utilisateur seulement).
SNAP=$(cat /tmp/eurio-snapshot-path)
SRC_N=$(find infra/minio/data -type f -not -path '*/.minio.sys/*' | wc -l)
SNP_N=$(find "$SNAP/minio-data"   -type f -not -path '*/.minio.sys/*' | wc -l)
echo "minio/data files (hors .minio.sys) : actuel=$SRC_N  snapshot=$SNP_N"
test "$SRC_N" = "$SNP_N" && echo "✅ data utilisateur MinIO intacte" || echo "❌ écart — investiguer"

# (c) Conteneurs toujours up (git ne les redémarre pas).
docker ps --format '{{.Names}}\t{{.Status}}' | grep -iE 'minio|review|eurio-api'
curl -s https://eurio-s3.musubi.dev/minio/health/live -o /dev/null -w "%{http_code}\n"  # 200
# eurio-api : seulement si déployé sur ce VPS
curl -s https://eurio-api.musubi.dev/healthz 2>/dev/null ; echo
```

> Les conteneurs tournent sur leurs volumes/secrets, **indépendamment de git**. La
> bascule git ne les redémarre pas. Ne rebuild `eurio-api` que si tu veux déployer le
> nouveau code (centralisation secrets) — et seulement après accord (hors scope ici).

### 2.5 — Snapshot local : conserver ou nettoyer

Une fois §2.4 vert **et** §1.4 vert, le snapshot local de §1.0 a fait son job. Tu
peux le garder quelques jours (sécurité supplémentaire — il ne coûte rien grâce
aux hardlinks tant que rien n'est modifié dans `infra/minio/data/`) ou le
supprimer : `rm -rf "$SNAP"` (ça ne touche pas la source, juste les hardlinks).

---

## 3. Ce qu'on NE fait PAS dans ce handoff

- ❌ Supprimer quoi que ce soit dans MinIO ou le `eurio-db` bucket.
- ❌ Supprimer ou écraser un fichier sous `infra/*/data/` ou `infra/*/secrets/`.
- ❌ Faire un `git reset --hard` sans pre-flight §2.0 vert ET stratégie §2.1 calculée.
- ❌ Re-cloner le repo (orphelinerait les Go de data untracked).
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

- Snapshot local §1.0 :
    - chemin : <…>  / # fichiers source vs snap : <…> = <…>
- Backup pCloud :
    - eurio-db          : source <taille/objets> / backup <…> / check --one-way : <0 diff ?>
    - enrichment-crops  : <…> / <…> / <…>
    - enrichment-raws   : <…> / <…> / <…>
    - numista-canonical : <…> / <…> / <…>
    - eurio.db dans le bucket (sha256 source ≡ pCloud ?) : <oui/non>
    - copie locale eurio.db backupée (§1.3.bis) : <oui/non/absente>
    - tar volume (si fait) : <oui/non>
- Git (Codeberg canonique) :
    - origin avant : github → après : codeberg (set-url OK ?)
    - stratégie §2.1 : <noop | ff | ahead | diverged>
    - HEAD avant : <sha local>  HEAD après : <sha> (== Codeberg ?)
    - sparse-checkout appliqué : <oui/non> (contenu : infra ml)
- Données préservées (post-bascule) :
    - infra/minio/data : # fichiers <actuel> vs snapshot <snap> = <ok/écart>
    - infra/minio/secrets : <ok>
    - infra/eurio-api/data : <ok/absent>
- Services après bascule : minio <200?>, eurio-api /healthz <…>, review <…>
- Déviations / blocages : <…>
- Questions ouvertes : <…>
```
