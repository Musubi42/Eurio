# 🗑️ EPHEMERal — Seed `coin_series` sur la DB VPS (D2)

> **Fichier jetable.** Une fois la séquence exécutée et vérifiée, **supprime ce
> fichier** (`git rm VPS-SEED-COIN-SERIES.md && git commit -m "chore: drop ephemeral VPS seed handoff"`).
> Destiné à une session Claude Code **sur le VPS** (`/opt/eurio`).

## Objectif

Peupler la table `coin_series` (+ `coins.series_id`) dans le **canonique VPS**
`/var/lib/eurio/eurio.db`. Ces données n'existaient qu'en Supabase ; le commit
`1c19931` (`feat(coin-series): D2`) a rapatrié le seed côté SQLite + ajouté
l'endpoint `GET /coin-series`, mais **seule la DB de dev locale a été seedée**.
Tant que la DB VPS ne l'est pas, le futur picker série de studio-local (qui tape
`eurio-api.musubi.dev`) serait vide.

## Preuves / état attendu AVANT

```bash
# Sur le VPS — la table existe (bootstrap schema.sql) mais est vide :
docker exec eurio-api python -c \
  "import sqlite3,os; c=sqlite3.connect(os.environ['EURIO_DB_PATH']); \
   print('coin_series:', c.execute('select count(*) from coin_series').fetchone()[0]); \
   print('coins.series_id:', c.execute('select count(series_id) from coins').fetchone()[0])"
# Attendu : coin_series: 0   (et series_id: 0 ou faible)
```

## Pré-requis IMPORTANTS

1. **Le conteneur tourne une image antérieure au commit `1c19931`** → il faut
   **rebuild** pour embarquer le nouveau code (`referential/enrich_coins_metadata.py`
   avec `--target sqlite`, ET le module `serving/coin_series/` qui sert
   l'endpoint). Le rebuild **déploie aussi l'endpoint** — c'est voulu.
2. **L'image ne copie PAS `ml/data/`** (cf. `infra/eurio-api/Dockerfile`, liste
   COPY explicite) → le fichier seed `ml/data/coin_series_seed.json` **n'est pas
   dans le conteneur**. On le `docker cp` à la main (étape 3).
3. La DB est en WAL : le script peut tourner **pendant que l'API est up** (1 seul
   writer court, `BEGIN IMMEDIATE`). Pas besoin d'arrêter le service.

## Séquence

```bash
cd /opt/eurio

# 1. Récupérer le code (commit 1c19931 doit être présent)
git pull
git log --oneline -1   # vérifier qu'on a bien feat(coin-series): D2 …

# 2. Rebuild + restart l'API (déploie l'endpoint /coin-series)
cd infra/eurio-api
docker compose up -d --build
docker compose ps      # confirmer le nom du service/conteneur (supposé: eurio-api)

# 3. Copier le seed dans le conteneur (data/ absent de l'image)
docker cp /opt/eurio/ml/data/coin_series_seed.json eurio-api:/srv/ml/data/coin_series_seed.json

# 4. DRY-RUN d'abord (n'écrit rien — vérifie le matching)
docker exec -w /srv/ml eurio-api python -m referential.enrich_coins_metadata
#   Attendu : "Loaded 32 series", "✓ All N circulation coins matched a series"
#   (cible sqlite par défaut, EURIO_DB_PATH=/var/lib/eurio/eurio.db est déjà dans l'env du conteneur)

# 5. APPLY
docker exec -w /srv/ml eurio-api python -m referential.enrich_coins_metadata --apply
#   Attendu : "coin_series count after upsert: 32" + "✓ wrote N coins.series_id update(s)"
```

> `-w /srv/ml` positionne le cwd ; `PYTHONPATH=/srv/ml` est déjà dans l'image, donc
> `-m referential.enrich_coins_metadata` résout. Le chemin sqlite n'importe **pas**
> `python-jose` ni `export.sync_to_supabase` (import paresseux côté supabase only).

## Vérification APRÈS

```bash
# A. Données peuplées
docker exec eurio-api python -c \
  "import sqlite3,os; c=sqlite3.connect(os.environ['EURIO_DB_PATH']); \
   print('coin_series:', c.execute('select count(*) from coin_series').fetchone()[0]); \
   print('coins.series_id:', c.execute('select count(series_id) from coins').fetchone()[0])"
# Attendu : coin_series: 32   (series_id > 0)

# B. Endpoint monté (sans auth → on attend 401/403, PAS 404)
curl -s -o /dev/null -w "%{http_code}\n" https://eurio-api.musubi.dev/coin-series
# 401 ou 403 = route montée ✅   |   404 = pas déployée (rebuild raté)

# C. (optionnel) Avec un PAT valide portant le scope coins:read :
curl -s -H "Authorization: Bearer eurio_XXX" https://eurio-api.musubi.dev/coin-series | head -c 400
# Attendu : tableau JSON de 32 séries
```

**Idempotent** : re-lancer l'étape 5 écrit 0 update et laisse le count à 32.

## Cleanup (obligatoire)

```bash
cd /opt/eurio
git rm VPS-SEED-COIN-SERIES.md
git commit -m "chore: drop ephemeral VPS seed handoff (coin_series seeded)"
# (push selon le workflow dual-remote habituel)
```

## Si ça casse

- **404 sur `/coin-series`** → l'image n'a pas le module ; revérifier `git log`
  (commit `1c19931` présent ?) puis `docker compose up -d --build --no-cache`.
- **`No such file … coin_series_seed.json`** → l'étape 3 (`docker cp`) n'a pas été
  faite ou le nom de conteneur diffère (`docker compose ps`).
- **`No module named 'store'`** → lancer avec `-w /srv/ml` (cwd) ou
  `-e PYTHONPATH=/srv/ml`.
- **Lock SQLite** → réessayer ; si persistant, `docker compose stop` l'API,
  relancer l'étape 5 via un one-off `docker compose run --rm eurio-api …`, puis
  `docker compose start`.

---
Renvoie à la session locale : counts obtenus (A) + code HTTP (B), pour débloquer
le Chunk 3 (swap `useCoinSeries.ts` → `eurioApi.get('/coin-series')`).
