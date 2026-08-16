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

## Dérouler

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
