# Exercice de restauration — le harnais

> Rejoue en une heure ce que l'exercice #1 a fait à la main le 2026-08-16 :
> restaurer depuis pCloud, remonter une stack **isolée** sur la copie, et
> demander à l'application elle-même de servir cette donnée.
>
> C'est le **niveau 4** de
> [`VERIFICATION.md`](../../../docs/work-in-progress/backup-pipeline/VERIFICATION.md)
> §2 — « l'application démarrerait-elle dessus ? ». Les niveaux 1 à 3 tournent
> chaque nuit et ne regardent que des fichiers.

## Isolation — les trois barrières

Aucune commande d'ici ne doit pouvoir toucher la production, même mal tapée :

1. **Projet compose `eurio-drill`**, conteneurs suffixés `-drill`.
2. **Réseau propre**, jamais `traefik` : rien n'est routable depuis l'extérieur,
   aucun `Host()` de production ne peut être capté.
3. **Ports sur `127.0.0.1` et décalés** : `19000` (S3), `18042` (API),
   `18048` (review).

Le répertoire de travail vit **hors du dépôt** ; `prepare-secrets.sh` refuse
d'écrire dans `/opt/eurio`.

## Dérouler — une commande

```bash
go-task backup:drill          # 28 min mesurées, ~14 Go de disque, ne touche pas la production
go-task backup:drill:status   # où en est l'exercice
go-task backup:drill:down     # détruire (à lancer même après un échec)
```

**Il est aussi ordonnancé** — `eurio-backup-drill.timer` (`nix/eurio-vps.nix`),
les 5 janvier / avril / juillet / octobre à 04:00 UTC, après la fenêtre
Duplicati. Un succès acquitte l'anneau 5 puis **détruit** les 14 Go ; un échec
passe l'anneau au rouge (`eurio-backup.sh drill-fail`) et **conserve** la stack
et les journaux. Compter sur la seule absence d'acquittement laisserait 90 j de
période + 30 j de grâce avant le moindre signal.

Chiffres du premier exercice automatisé (2026-08-19) : clone 15 s · images
2 min 30 · choix de version 20 s · index 11 min · restauration **10 min 27**
pour 7,0 Gio · MinIO et stack 3 min · contrôles 10 s. 16/18 invariants,
`/coins` → 658 pièces, un crop servi ≡ octet pour octet.

`run-drill.sh` enchaîne les six étapes et pose un marqueur après chacune : un
échec en étape 5 se reprend **sans re-télécharger 6 Go** (`go-task backup:drill
-- up`). Ce que le harnais du 2026-08-16 laissait à la main et qui est
désormais dedans :

| Étape | Ce qu'elle prouve, et que l'exercice #1 ne prouvait pas |
|---|---|
| 1 `clone` | le dépôt Codeberg **+ la clé age suffisent** — l'exercice partait de `/opt/eurio`, donc supposait la machine perdue |
| 2 `build` | on sait **reconstruire** `eurio-api` et `eurio-review` depuis ce clone. Il réutilisait les `:latest` locales, c'est-à-dire l'artefact que le sinistre emporte |
| 3 `pick` | la version retenue **porte un `manifest.json`** — contrôle automatisé, plus une consigne de README |
| 4 `restore` | `repair` puis `restore` depuis pCloud, secrets jamais dans `argv` |
| 5 `up` | secrets régénérés depuis SOPS, MinIO bootstrapé, objets avant bases |
| 6 `smoke` | l'application sert la donnée, puis les invariants, puis l'anneau 5 |

**Deux préalables, tous les deux non négociables :**

- **Committer et pousser le harnais avant de lancer.** L'exercice tourne depuis
  le clone, pas depuis `/opt/eurio` : c'est tout l'intérêt. Une modification non
  poussée n'est donc pas testée. `run-drill.sh` refuse de continuer si le
  compose du clone ignore `DRILL_API_IMAGE`.
- **`nix shell nixpkgs#duplicati`** est le chemin par défaut, délibérément : le
  conteneur `oim-duplicati` est justement ce que le sinistre emporte. Vérifié le
  2026-08-19 — le 2.3.0.1 de nixpkgs lit les archives écrites par le 2.2.0 du
  conteneur (les 5 `dlist` se déchiffrent et se listent). Pour repasser par le
  conteneur : `DRILL_DUPLICATI_CMD="docker exec oim-duplicati /app/duplicati/duplicati-cli"`,
  à condition que `$WORK` soit sous un bind visible du conteneur.

Réglages : `WORK`, `DRILL_REF`, `DRILL_EMAIL`, `DRILL_VERSION`,
`DRILL_DUPLICATI_CMD`.

## Une quatrième barrière d'isolation : le tag des images

Les images de l'exercice sont taguées **`:drill`**, jamais `:latest`. Un
`docker build` qui écrase le tag de production serait un exercice qui casse ce
qu'il prétend savoir remonter — le compose les lit via
`${DRILL_API_IMAGE:-eurio-api:latest}`, le défaut gardant le harnais utilisable
à la main.

## Dérouler à la main, étape par étape

```bash
WORK=/opt/eurio-restore-test          # jetable, hors du dépôt
RESTORED=/chemin/de/la/copie-restaurée # cf. ../README-RESTORE.md §6
cd /opt/eurio

# 1. identifiants d'infra, REGÉNÉRÉS depuis SOPS (RESTAURATION.md §1 étape 2)
sops exec-env secrets/dev.env "bash infra/backup/drill/prepare-secrets.sh $WORK"

# 2. MinIO isolé + buckets + policies du dépôt (étape 3)
sops exec-env secrets/dev.env \
  "docker compose -f infra/backup/drill/compose.yml --project-directory $WORK up -d minio"
MINIO_CONTAINER=eurio-minio-drill MINIO_SECRETS_DIR=$WORK/secrets MINIO_SKIP_COMPOSE=1 \
  ./infra/minio/bootstrap.sh
# `eurio-db` est un bucket legacy que bootstrap.sh ne crée pas (D-20) :
docker exec eurio-minio-drill mc mb --ignore-existing local/eurio-db

# 3. objets d'abord — le store RÉFÉRENCÉ avant le référençant (étape 4)
bash infra/backup/drill/import-objects.sh "$WORK" "$RESTORED/minio"

# 4. les bases ensuite (étape 5). Sans -wal ni -shm : VACUUM INTO produit une
#    base autonome. Les fichiers restaurés sont en lecture seule, l'API écrit.
cp "$RESTORED/eurio.db"  "$WORK/api-data/eurio.db"    && chmod 644 "$WORK/api-data/eurio.db"
cp "$RESTORED/review.db" "$WORK/review-data/review.db" && chmod 644 "$WORK/review-data/review.db"

# 5. les services (étape 6)
sops exec-env secrets/dev.env \
  "docker compose -f infra/backup/drill/compose.yml --project-directory $WORK up -d"

# 6. un PAT « break-glass » : Authentik n'existe pas dans l'exercice
docker exec eurio-api-drill python -m serving.auth create-pat \
  --email <ton-email> --name drill        # imprime le clair UNE fois
export DRILL_PAT=eurio_…

# 7. les contrôles (étape 7)
bash infra/backup/drill/smoke.sh "$RESTORED" "$WORK"
python3 infra/backup/verify_invariants.py "$RESTORED" \
  --baseline "$RESTORED/baseline-manifest.json" --repo-root .

# `smoke.sh` acquitte l'anneau 5 (eurio-drill) lui-même, et seulement si tout
# passe. Rien à pinguer à la main : un exercice raté doit rester silencieux.

# 8. détruire
docker compose -f infra/backup/drill/compose.yml --project-directory $WORK down -v
rm -rf "$WORK" "$RESTORED"
```

## Ce que `smoke.sh` prouve, et ce qu'il ne prouve pas

| Contrôle | Ce qu'il attrape |
|---|---|
| `/healthz` | l'API démarre sur la base restaurée — y compris ses migrations |
| `/coins` | elle **sert** la donnée, pas seulement « la base s'ouvre » |
| crop signé → MinIO → sha256 | la chaîne **DB ↔ MinIO ↔ policy `eurio-app`** est entière, et l'octet servi est l'octet sauvegardé |
| `/admin/flow` | `review.db` restaurée est servie par `eurio-review` |

Il ne prouve **pas** le front, ni Traefik/TLS, ni Authentik : ce sont des
dépendances externes, remontables indépendamment, et aucune ne porte de donnée
que la sauvegarde couvre.

L'exercice écrit avec le compte applicatif `eurio-app`, jamais avec le root
MinIO — sinon il validerait un chemin de permissions que la production n'emprunte
pas (D-30).
