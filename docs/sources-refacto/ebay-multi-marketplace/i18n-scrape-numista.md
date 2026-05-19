# Chunk — scrape Numista FR + EN via TOR (VPS Hetzner)

> Brief auto-suffisant pour produire les ~1156 rows
> `coin_names_i18n` en `source='numista'` `confidence='canon'`.
> Tourne sur le **VPS Hetzner** (TOR + IPs diversifiées).
>
> Lire d'abord `i18n-strategy.md` pour le contexte général.
>
> Verrouillé 2026-05-19.

## Objectif

Fetch `https://fr.numista.com/<id>` et `https://en.numista.com/<id>`
pour les ~578 coins (`face_value=2.0 ∧ numista_id≠NULL`), extraire le
`<h1>`, persister 1 row par (eurio_id, lang) dans `coin_names_i18n`.

= **1156 fetches**, ~58 min via TOR avec 10 circuits parallèles.

## Pourquoi TOR

Le probe du 2026-05-19 a montré qu'un scrape direct (UA explicite,
1 req/s) **se fait flag après ~7 requêtes** par Numista (page
`challenge.php`). Notre IP VPS Hetzner risque même d'être déjà
flaggée (range VPS = bad reputation).

TOR donne 10 circuits = 10 exit nodes IPs distinctes simultanément.
Avec rotation `NEWNYM` toutes les ~5 requêtes par circuit + throttle
30s par circuit, l'empreinte ressemble à du trafic légitime.

## Setup VPS

### 1. TOR + control port

Sur la VPS (NixOS) :

```nix
# /etc/nixos/configuration.nix (ou module dédié)
services.tor = {
  enable = true;
  client.enable = true;
  controlSocket.enable = true;
  settings = {
    ControlPort = 9051;
    CookieAuthentication = true;
    # 10 circuits ouverts en parallèle (par défaut TOR ouvre à la
    # demande, mais on peut prébuilder)
    NumEntryGuards = 10;
    MaxCircuitDirtiness = 600;  # forcer rotation toutes les 10 min
  };
};
```

Alternative non-Nix (Docker) : `dperson/torproxy` exposé sur
`9050` (SOCKS5) + `9051` (control).

### 2. Vérification

```bash
# Sur la VPS
curl --socks5-hostname 127.0.0.1:9050 https://check.torproject.org/api/ip
# → {"IsTor":true,"IP":"..."}
```

### 3. Dependencies Python

Ajouter à `ml/pyproject.toml` (ou flake.nix VPS profile) :

- `httpx[socks]` (déjà installé probablement, sinon `httpx-socks`)
- `stem` (control port TOR, pour `NEWNYM`)

## Script `bootstrap_coin_names_i18n.py`

Emplacement : `ml/scripts/bootstrap_coin_names_i18n.py`.

```python
"""Scrape Numista FR + EN titles via TOR, persist coin_names_i18n.

Run on VPS Hetzner with tor service enabled.

Usage:
    python -m scripts.bootstrap_coin_names_i18n
    python -m scripts.bootstrap_coin_names_i18n --refresh
    python -m scripts.bootstrap_coin_names_i18n --refresh-lang fr
    python -m scripts.bootstrap_coin_names_i18n --only-eurio <id1>,<id2>
    python -m scripts.bootstrap_coin_names_i18n --circuits 10 --per-circuit-sleep 30
"""
```

### Comportement

- **Cible** : `SELECT eurio_id, numista_id FROM coins WHERE
  face_value=2.0 AND numista_id IS NOT NULL`
- **Langues** : `('fr', 'en')` hardcodé (les autres passent par LLM)
- **Réseau** :
  - 1 client httpx **par circuit TOR** (10 clients), chacun via SOCKS5
    `127.0.0.1:9050` mais avec `SOCKS5_AUTH` différent (ce qui force
    TOR à utiliser un circuit distinct par couple user:pass — pattern
    "stream isolation")
  - User-Agent navigateur classique : `Mozilla/5.0 (X11; Linux x86_64)
    AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36`
  - Cookies de session conservés **par circuit** (`httpx.Client` retient)
  - Throttle : 30s **par circuit** entre 2 requêtes (donc effectif ~3s
    entre 2 requêtes au global)
  - Rotation `NEWNYM` via `stem` toutes les **20 requêtes par circuit**
    (~600s d'usage avant rotation)
- **Détection challenge.php** :
  - Si `response.url` contient `challenge.php` → marquer le circuit
    comme "burnt", forcer `NEWNYM`, retry sur autre circuit
  - Si 3 circuits burnt consécutivement → abort + alerte
- **Idempotence** :
  - Par défaut : `INSERT OR IGNORE` (skip si row existe)
  - `--refresh` : `INSERT OR REPLACE` global
  - `--refresh-lang fr` : `INSERT OR REPLACE` filtré
- **Parsing** : recyclé de `probe_coin_names_i18n.py` →
  `extract_title_from_html()` (fonction pure, à factoriser dans
  `sources/numista/parse.py` ou similaire)
- **Persistence** : 1 commit par batch de 50 rows pour ne pas perdre
  l'avancement en cas d'interruption
- **Progress** : tqdm avec ETA, log par lang en fin de run

### Structure du run

```
[setup]      Build 10 TOR circuits, verify each exit IP via check.torproject.org
[fetch]      Distribute coins across circuits (round-robin)
             Each circuit: fetch coin → parse → persist → sleep 30s → next
[shutdown]   Close all circuits, print coverage stats
```

### Distribution coins ⇄ circuits

578 coins × 2 langues = 1156 fetches → 116 fetches/circuit.
À 30s/fetch/circuit = ~58 min. Tient en background nohup.

Pseudo-code :

```python
circuits = build_tor_circuits(n=10, control_port=9051)
work = [(coin, lang) for coin in coins for lang in ('fr', 'en')]
queues = distribute_round_robin(work, n_circuits=10)
with ThreadPoolExecutor(max_workers=10) as pool:
    futures = [pool.submit(run_circuit, c, q) for c, q in zip(circuits, queues)]
    wait(futures)
```

### Schema migration (Chunk pré-requis)

Avant le scrape, étendre `coin_names_i18n` selon
`i18n-strategy.md` §"Schéma cible" :

```sql
-- Recreate-and-copy car SQLite ne supporte pas ALTER pour CHECK/cols
CREATE TABLE coin_names_i18n_new (
  eurio_id    TEXT NOT NULL,
  lang        TEXT NOT NULL,
  title       TEXT NOT NULL,
  source      TEXT NOT NULL,
  confidence  TEXT NOT NULL,
  model       TEXT,
  fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (eurio_id, lang)
);
-- Pas de CHECK lang : on valide côté Python (cf. i18n-strategy §D-i18n-3)

INSERT INTO coin_names_i18n_new (eurio_id, lang, title, source, confidence, fetched_at)
SELECT eurio_id, lang, title, 'numista', 'canon', fetched_at
FROM coin_names_i18n;  -- migration des rows existantes (si présentes)

DROP TABLE coin_names_i18n;
ALTER TABLE coin_names_i18n_new RENAME TO coin_names_i18n;
```

À faire dans `store.py._bootstrap` avec détection de l'ancien schéma.

## Tests

`ml/tests/test_bootstrap_coin_names_i18n.py` :

- Mock 1 page Numista (fixture HTML statique), vérifier extraction
- Test idempotence (2 runs → pas de duplicats)
- Test `--refresh-lang fr` (seules `lang='fr'` touchées)
- Test challenge.php detection → row absente, log warning
- Test rotation TOR : mock `stem.Controller` → vérifier que `NEWNYM`
  est appelé au seuil configuré

Pas de test e2e contre vraie Numista en CI (flaky + WAF).

## Run

### Préparation

```bash
# Sur VPS
go-task ml:install         # via flake.nix profile vps
sudo systemctl status tor  # vérifier service actif
nc -z 127.0.0.1 9050       # SOCKS5 ouvert
nc -z 127.0.0.1 9051       # control ouvert
```

### Lancement

```bash
# Nouvelle task à ajouter au Taskfile.yml
go-task ml:bootstrap-coin-names-i18n

# Équivalent direct
cd ml/
.venv/bin/python -m scripts.bootstrap_coin_names_i18n \
  --circuits 10 \
  --per-circuit-sleep 30 \
  2>&1 | tee state/bootstrap_coin_names_i18n.log
```

Lancer en `nohup` + `&` pour run de 58 min en background.

### Validation post-run

```sql
-- Couverture par langue (attendu ≥ 95 %)
SELECT lang, count(*) FROM coin_names_i18n
WHERE source='numista' GROUP BY lang;

-- Coins manqués (challenge.php / 404 / 5xx)
SELECT c.eurio_id, c.numista_id
FROM coins c
LEFT JOIN coin_names_i18n n ON n.eurio_id=c.eurio_id AND n.lang='fr'
WHERE c.face_value=2.0 AND c.numista_id IS NOT NULL AND n.eurio_id IS NULL;
```

Si > 5 % de coins manqués → relancer avec `--only-eurio <ids>` sur
les manquants (TOR aura rebuilt ses circuits entre-temps).

### Spot-check manuel

5 coins au hasard, vérifier que le titre FR est cohérent (ex.
`fr-1999-2eur-standard` doit donner `2 euros 1re carte` et pas
`2 Euros 1st map`).

## Récupération du DB depuis le VPS vers PC

Une fois le scrape OK, ramener la table sur PC pour la suite (LLM
batch) :

```bash
# Option simple : rsync du .db entier
rsync vps:Eurio/ml/state/training.db ml/state/training.db.from-vps
# puis swap, ou diff/merge ciblé sur coin_names_i18n
```

Ou : SQL dump filtré sur `coin_names_i18n`, transfer, import sur PC.
À voir au moment du run selon état du `training.db` de chaque côté.

## Anti-objectifs

- ❌ Pas de fetch des 9 langues (kickoff périmé) — FR + EN uniquement
- ❌ Pas de parallélisation au-delà de 10 circuits — TOR n'aime pas
- ❌ Pas de fallback API Numista (quota précieux, voir
  `i18n-strategy.md`)
- ❌ Pas de scrape direct sans TOR sur la VPS — IP déjà potentiellement
  flaggée

## Définition de "done"

- [ ] Service TOR opérationnel sur la VPS (control + SOCKS)
- [ ] Schema `coin_names_i18n` migré (cols `source`, `confidence`,
  `model`)
- [ ] Script `bootstrap_coin_names_i18n.py` livré + tests
- [ ] Task `ml:bootstrap-coin-names-i18n` dans `Taskfile.yml`
- [ ] Run terminé, couverture FR ≥ 95 %, EN ≥ 95 %
- [ ] DB transférée sur PC pour la phase LLM
- [ ] `progress.md` à jour
