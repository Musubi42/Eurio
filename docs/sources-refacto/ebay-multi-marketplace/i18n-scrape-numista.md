# Chunk — scrape Numista FR + EN via TOR (VPS Hetzner)

> Brief auto-suffisant pour produire les ~1156 rows
> `coin_names_i18n` en `source='numista'` `confidence='canon'`.
> Tourne sur le **VPS Hetzner** (TOR + IPs diversifiées).
> La DB SQLite reste sur le **PC** ; le VPS est stateless ML-wise.
>
> Lire d'abord `i18n-strategy.md` pour le contexte général.
>
> Verrouillé 2026-05-19, pivot vers le worklist/JSONL le même jour.

## Objectif

Fetch `https://fr.numista.com/<id>` et `https://en.numista.com/<id>`
pour les ~578 coins (`face_value=2.0 ∧ numista_id≠NULL`), extraire le
`<h1>`, persister 1 row par (eurio_id, lang) dans `coin_names_i18n`.

= **1156 fetches**, ~58 min via TOR avec 10 circuits parallèles.

## Architecture (3 scripts, 2 machines)

Au lieu d'embarquer la stack DB sur le VPS, on sépare :

| Script | Machine | Rôle |
|---|---|---|
| `scripts/export_i18n_worklist.py` | PC | Lit `coins`, dump `state/i18n_worklist.json` |
| `scripts/bootstrap_coin_names_i18n.py` | VPS | Scrape via TOR, append `state/i18n_{results,failures}.jsonl` |
| `scripts/import_i18n_results.py` | PC | Migration schema + `INSERT OR IGNORE` |

**Bénéfices :**
- VPS reste stateless (pas de `training.db` à synchroniser dans les deux sens).
- Reprise sur crash = gratuite : les JSONL sont append-only et lus au démarrage pour construire le skip-set.
- Audit propre : le JSON résultat est l'artefact transférable et inspectable.
- Migration schema isolée côté PC, où la DB vit.

## Pourquoi TOR

Le probe du 2026-05-19 a montré qu'un scrape direct (UA explicite,
1 req/s) **se fait flag après ~7 requêtes** par Numista (page
`challenge.php`). L'IP VPS Hetzner risque aussi d'être déjà flaggée
(range VPS = bad reputation).

TOR donne 10 circuits = 10 exit nodes IPs distinctes simultanément.
Avec rotation par username SOCKS5 (`IsolateSOCKSAuth`) + throttle 30s
par circuit, l'empreinte ressemble à du trafic légitime.

**Pattern d'isolation** (récupéré de `privateHub/infrastructure/tor-proxy`) :
chaque worker httpx utilise un `socks5h://circuitN:x@127.0.0.1:9050` ;
TOR crée un pool de circuits distinct par username. Pour rotation,
on bumpe le suffixe : `circuit0_b0` → `circuit0_b1` toutes les 20 req.
**Pas de `stem`/`ControlPort`/`NEWNYM` nécessaire.**

## Setup TOR

Fichiers livrés :

- `ml/infrastructure/tor/torrc` — config TOR avec `IsolateSOCKSAuth IsolateDestAddr`
- `ml/infrastructure/tor/docker-compose.yml` — single `osminogin/tor-simple`, port `127.0.0.1:9050`

```bash
go-task ml:tor:up      # docker up + wait bootstrap (jusqu'à 60s) + check exit IP
go-task ml:tor:logs    # tail container logs si besoin
go-task ml:tor:down
```

`tor:up` valide via `https://check.torproject.org/api/ip` → `{"IsTor":true}`.

### Note SocksPolicy

Le port n'est exposé qu'en `127.0.0.1:9050` côté host. Le `torrc`
contient `SocksPolicy accept *` (au lieu de restreindre par range)
parce que selon la machine, Docker peut utiliser des bridges hors
de `172.16.0.0/12` (e.g. `172.80.x.x` sur ce VPS NixOS).

## Workflow complet

### Étape 1 — Export worklist (PC)

```bash
go-task ml:export-i18n-worklist
# → ml/state/i18n_worklist.json
```

Le script :
- Sélectionne `eurio_id, numista_id FROM coins WHERE face_value=2.0 AND numista_id IS NOT NULL`
- **Skip-existing** : exclut les coins dont les 2 langs (fr+en) sont déjà en DB. `--include-done` pour forcer.
- Format de sortie :

```json
{
  "exported_at": "...",
  "filter": "face_value=2.0 AND numista_id IS NOT NULL",
  "langs": ["fr", "en"],
  "n_items": 578,
  "items": [
    {"eurio_id": "fr-1999-2eur-standard", "numista_id": 104, "langs": ["fr", "en"]},
    ...
  ]
}
```

Si la moitié des coins ont déjà la langue `fr` mais pas `en`, le champ `langs` par item ne contiendra que `["en"]` pour ces coins → on ne refetch que le manquant.

### Étape 2 — rsync vers VPS

```bash
rsync ml/state/i18n_worklist.json nixos:/opt/eurio/ml/state/
```

(adapte le host selon ton SSH config)

### Étape 3 — Scrape (VPS)

```bash
# Sur le VPS
go-task ml:tor:up
go-task ml:bootstrap-coin-names-i18n
# → ml/state/i18n_results.jsonl  (append-only)
# → ml/state/i18n_failures.jsonl (append-only)
```

Options utiles : `-- --circuits 10 --per-circuit-sleep 30 --rotate-every 20`.

Le script :
1. Vérifie l'exit IP TOR
2. Lit le worklist + les 2 JSONL existants → construit le skip-set `(eurio_id, lang)`
3. Distribue le travail restant round-robin sur N circuits
4. Chaque worker : throttle, bump username toutes les 20 reqs, append result/failure ligne par ligne
5. Logue le progress toutes les 20 reqs (`ok=X fail=Y, X.X req/s, ETA Y min`)

Pour run en background long :

```bash
nohup go-task ml:bootstrap-coin-names-i18n > state/bootstrap.log 2>&1 &
```

### Étape 4 — rsync retour vers PC

```bash
rsync nixos:/opt/eurio/ml/state/i18n_results.jsonl ml/state/
rsync nixos:/opt/eurio/ml/state/i18n_failures.jsonl ml/state/
```

### Étape 5 — Import en DB (PC)

```bash
go-task ml:import-i18n-results
```

Le script :
- Lit `i18n_results.jsonl` (1 ligne par succès)
- Trigger `Store(...)` → `_bootstrap` ajoute les colonnes `confidence` + `model` si manquantes (via `_ensure_column`, pas de recreate-and-copy)
- `INSERT OR IGNORE` par défaut. `--replace` pour forcer le refresh.
- Affiche un summary avec la couverture par langue

## Mode POC (validation pré-prod)

Avant tout scrape massif, lance le POC sur 5 coins pour valider la
stack TOR + extraction de titres :

```bash
go-task ml:tor:up
go-task ml:bootstrap-coin-names-i18n:poc
# → ml/state/bootstrap_coin_names_i18n_poc_<ts>.json
```

5 workers en parallèle, 1 circuit chacun. Le summary console affiche
les titres FR/EN extraits → review manuelle. Aucune écriture DB.

Validé 2026-05-19 sur :
- `fr-1999-2eur-standard` → `2 euros 1re carte` / `2 Euros 1st map`
- `de-2020-2eur-…` → FR 403 (1 échec WAF observé, EN OK)
- `ad-2025-2eur-bearded-vulture` → `2 euros Gypaète barbu` / `2 Euros Bearded vulture`
- `mc-2007-2eur-…grace-kelly` → `2 euros - Grace Kelly` / `2 Euros - Albert II Grace Kelly`
- `sm-2005-2eur-…physics` → `2 euros Année de la physique` / `2 Euros Physics`

## Schéma cible

`coin_names_i18n` après migration (additive via `_ensure_column`) :

```sql
CREATE TABLE coin_names_i18n (
  eurio_id   TEXT NOT NULL REFERENCES coins(eurio_id) ON DELETE CASCADE,
  lang       TEXT NOT NULL CHECK (lang IN ('fr','en','de','it','es','nl')),
  title      TEXT NOT NULL,
  source     TEXT NOT NULL DEFAULT 'numista',
  confidence TEXT NOT NULL DEFAULT 'canon',  -- 'canon' (scraped) | 'llm' | 'manual'
  model      TEXT,                            -- LLM model id, NULL pour canon
  fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (eurio_id, lang)
);
```

Le `CHECK` sur `lang` reste `(fr,en,de,it,es,nl)` pour l'instant.
Quand la phase LLM 9-langs arrivera, on l'enlèvera via recreate-and-copy.

## Format des JSONL artifacts

### `i18n_results.jsonl`

```json
{"eurio_id":"fr-1999-2eur-standard","lang":"fr","title":"2 euros 1re carte","source":"numista","confidence":"canon","fetched_at":"2026-05-19T20:29:48Z","circuit":"circuit0_b0","elapsed_ms":482}
```

Champs requis par `import_i18n_results.py` : `eurio_id`, `lang`, `title`.
Les autres sont propagés en DB tels quels.

### `i18n_failures.jsonl`

```json
{"eurio_id":"de-2020-2eur-…","lang":"fr","numista_id":226447,"http_status":403,"final_url":"https://fr.numista.com/226447","challenge_detected":false,"redirected_to_other_lang":false,"error":null,"circuit":"circuit1_b0","attempt_at":"2026-05-19T20:29:48Z"}
```

Pas de retry dans le run principal. "Autre méthode" plus tard :
- LLM EN→FR pour les pièces qui ont l'EN mais pas le FR (cas typique du 403 récurrent)
- Re-scrape ciblé avec nouveau pool d'exit nodes après quelques heures
- Saisie manuelle pour le reliquat

## Anti-objectifs

- ❌ Pas de fetch des 9 langues (kickoff périmé) — FR + EN uniquement pour ce chunk
- ❌ Pas de parallélisation au-delà de 10 circuits — TOR n'aime pas
- ❌ Pas de fallback API Numista (quota précieux, voir `i18n-strategy.md`)
- ❌ Pas de scrape direct sans TOR sur la VPS — IP déjà potentiellement flaggée
- ❌ Pas de DB sur le VPS — pivot worklist/JSONL
- ❌ Pas de `stem`/`ControlPort`/`NEWNYM` — `IsolateSOCKSAuth` suffit, rotation par bump du username

## Définition de "done"

- [x] Service TOR opérationnel (Docker compose + torrc local + check exit IP)
- [x] POC validé sur 5 coins FR+EN, titres cohérents
- [x] Schéma `coin_names_i18n` étendu (`confidence`, `model`)
- [x] Scripts livrés : `export_i18n_worklist`, `bootstrap_coin_names_i18n` (full+poc), `import_i18n_results`
- [x] Tasks `ml:export-i18n-worklist`, `ml:bootstrap-coin-names-i18n`, `ml:import-i18n-results`
- [ ] Worklist exporté côté PC, rsync'd vers VPS
- [ ] Run full terminé sur VPS, couverture FR ≥ 95 %, EN ≥ 95 %
- [ ] Results importé côté PC
- [ ] `progress.md` à jour
