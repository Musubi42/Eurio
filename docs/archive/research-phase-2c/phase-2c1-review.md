# Phase 2C.1 — Review, observations et décisions

> Review post-implémentation du bootstrap du référentiel (2C.1a commémoratives + 2C.1b circulation).
> État au commit `ce9d310`. Date : 2026-04-13.
> Doc parent : [`data-referential-architecture.md`](./data-referential-architecture.md), [`phase-2c-referential.md`](../phases/phase-2c-referential.md).

---

## TL;DR

Le bootstrap produit **2 891 entrées canoniques propres** (517 commémoratives + 2 374 circulation) sans zéro needs_review. L'architecture en 4 couches (identity / cross_refs / observations / provenance) est respectée et le merge idempotent fonctionne.

**Les soi-disant "comptes anormalement bas" ne sont PAS des bugs parser** — ils reflètent fidèlement la sparsité réelle des données Wikipedia (vérifié cellule par cellule sur LV, BE, EE, LT, HR). Seule DE est vraiment lacunaire (s'arrête à 2016) et nécessite une source alternative.

En revanche, la review a identifié **6 problèmes réels** à résoudre, dont 2 bloquants avant les phases suivantes :

| # | Problème | Gravité | Action |
|---|---|---|---|
| 1 | `slugify` détruit Grec/Cyrillique/Maltais | 🔴 Bloquant | Intégrer `unidecode` |
| 2 | Collision policy en contradiction avec spec §3.3 | 🟠 Bloquant | Choisir une direction et aligner code ↔ spec |
| 3 | DE circulation s'arrête à 2016 (source lacune) | 🟡 Data-gap | Ajouter scraper `de.wikipedia` complémentaire |
| 4 | `extract_data_rows` pairing fragile | 🟡 Qualité | Vérifier explicitement `"Description:"` |
| 5 | `parse_volume_cell` ambigu sur `1.234` | 🟢 Fragilité | Heuristique de magnitude |
| 6 | Divers code smells | 🟢 Hygiène | Corrections mécaniques |

---

## 1. Méthodologie de la review

Lecture en priorité :
- `docs/research/data-referential-architecture.md` (spec complète)
- `docs/phases/phase-2c-referential.md`
- `docs/research/referential-bootstrap-research.md`
- `ml/eurio_referential.py` (helpers)
- `ml/bootstrap_referential.py` (2C.1a)
- `ml/bootstrap_circulation.py` (2C.1b)

Vérifications empiriques exécutées :
1. Re-parse de chaque snapshot HTML (25 pages Wikipedia) pour comparer parser output vs contenu brut.
2. Analyse cellule-par-cellule des FV tables pour LV, BE, EE, LT, HR, MT, CY, AT.
3. Comptage des commémoratives par pays et vérification des gaps.
4. Détection des slugs tronqués (`len > 60`) et recherche de collisions post-troncation.
5. Test de `slugify` sur échantillons Grec/Cyrillique/Maltais/Latin-étendu.
6. Recherche de sources alternatives pour DE circulation 2017+.

---

## 2. Ce qui va bien — à conserver

### 2.1 Architecture 4-couches respectée

Chaque entrée produite expose strictement `identity` / `cross_refs` / `observations` / `provenance`. Aucune fuite de donnée mutable dans `identity`, aucun écrasement de cross-refs entre sources. `make_entry` et `make_identity` forcent la discipline.

### 2.2 Merge idempotent fonctionnel

Les deux scripts suivent le même pattern :
1. Parser les sources fraîches
2. Drop les entrées dont `sources_used` est uniquement ce bootstrap (entrées éphémères)
3. Préserver `provenance.first_seen` + enrichissements externes sur les `eurio_id` qui survivent
4. Insérer les entrées fraîches

Vérifié par re-run : pas de duplicates, pas de churn inutile.

### 2.3 Parsing de volumes robuste

`parse_volume_cell` (circulation) et `parse_volume` (commemos) gèrent correctement :
- thin spaces (`\u00a0`, `\u202f`)
- footnote refs (`[5]`)
- formats européens (espaces, virgules)
- formats compacts DE (`60,00` → 60M) et US (`800.0` → 800M)
- tokens spécimens (`s`, `—`, `N/a`)

Une seule fragilité subsiste (§6.5), pas bloquante aujourd'hui.

### 2.4 Truncation de slug au word-boundary

79 slugs commémoratives dépassent 60 chars et sont tronqués. **Zéro collision post-troncation** détectée dans les groupes `(country, year)` multi-commemos. Le `rsplit("-", 1)` fait son travail.

### 2.5 Les soi-disant "gaps" par pays sont légitimes

Le handoff flaguait `BE:90`, `DE:75`, `EE:37`, `LT:23`, `LV:11`, `HR:16` comme suspects. Vérification cellule-par-cellule :

- **HR : 16** = 2 ans (2023, 2024) × 8 dénominations → parfait (HR a rejoint l'euro en 2023).
- **LV : 11** — la FV table LV contient :
  - 2014 : toutes denoms minted (8 entrées)
  - 2015, 2018, 2020, 2021, 2022 : lignes de `'s'` intégrales (specimen-only)
  - 2017, 2023 : lignes de `— N/a`
  - 2016 : seulement €1 (10M)
  - 2019 : seulement €0.05 (15M)
  - 2023 : seulement €0.05 (15M)
  - Total réel : 8+1+1+1 = **11**. Parser correct.
- **LT : 23** — Lituanie n'émet que sporadiquement. 8 années, parse propre.
- **EE : 37** — ratio sparsité standard pour un petit pays, confirmé.
- **BE : 90** — 21 années couvertes mais très nombreuses cellules `s`. Confirmé.
- **AT : 171**, **FR : 208**, **ES : 200** — couverture haute comme attendu.

**Action : retirer ces pays de la liste "à investiguer".** Le parser n'a pas de bug sur ces countries.

### 2.6 Commémoratives — comptes cohérents

| Pays | Commemos | Années couvertes | Commentaire |
|---|---|---|---|
| DE | 30 | 2006-2026 | Série Bundesländer + specials, cohérent |
| FR | 31 | 2008-2026 | ~1.6/an, cohérent |
| IT | 35 | 2004-2026 | Pays qui exploite son quota |
| SM | 35 | 2004-2026 | San Marino actif |
| FI | 34 | 2004-2025 | Actif |
| LU | 34 | 2004-2025 | Actif |
| VA | 34 | 2004-2025 | Vatican actif |
| GR | 26 | 2004-2025 | |
| ES | 24 | 2005-2026 | |
| AD | 23 | 2014-2025 | Depuis adhésion |
| **AT** | **3** | 2005-2018 | **Parser vérifié OK** — AT n'émet qu'exceptionnellement |
| **NL** | **4** | 2011-2014 | **Parser vérifié OK** — Pays-Bas réticents sur commemos |
| **IE** | **3** | 2016-2023 | **Parser vérifié OK** — Irlande rare |
| **CY** | **4** | 2017-2024 | **Parser vérifié OK** — Chypre rare |

Les petits comptes AT/NL/IE/CY reflètent la **politique nationale réelle** (vérifié : AT n'apparaît pas dans les tables Wikipedia 2019-2023, ces années-là AT n'a pas émis). Pas un bug parser.

---

## 3. Problèmes identifiés et décisions proposées

### Problème 1 — `slugify` détruit Grec / Cyrillique / Maltais 🔴

**Constat empirique**

```python
slugify('Ολυμπιακοί Αγώνες Αθήνα 2004')  # → '2004'  (tout le grec perdu)
slugify('Кирилица и глаголица')            # → ''     (tout le cyrillique perdu)
slugify('Hypogée de Ħal-Saflieni')         # → 'hypogee-de-al-saflieni'  (Ħ perdu)
slugify('Élysée Treaty')                   # → 'elysee-treaty'  (OK)
```

La cause est `unicodedata.normalize("NFKD") + encode("ascii", "ignore")` : décompose proprement les diacritiques latins, mais les caractères non-latins (grec, cyrillique) et les caractères latins étendus avec combining-dot comme `Ħ`/`Ġ` sont **purement supprimés**.

**Impact actuel (bootstrap Wikipedia)**

Quasi nul : Wikipedia écrit tous les thèmes en anglais translittéré. Les thèmes grecs sont déjà en anglais (*"2011 Special Olympics World Summer Games"*). Les thèmes maltais authentiques subissent une dégradation partielle :
- `mt-2017-2eur-agar-qim` (devrait être `hagar-qim`) — le `Ħ` est perdu
- `mt-2019-2eur-ta-agrat-temples` (devrait être `ta-hagrat-temples`)
- `mt-2016-2eur-ggantija` (devrait être `gantija`, or `ggantija` car Wikipedia écrit `Gġantija` avec un `g` d'apparat supplémentaire)

**Impact futur (scrapers sources non-Wikipedia)** 🔴

C'est là que ça casse. Dès qu'un scraper attrape une source qui **garde les scripts originaux** :
- Numista en grec : "Αναβίωση των Αγώνων της Μαραθώνας" → slug vide → fallback `unknown`
- Shop bulgare après 2026 : "Първа монета от 2 евро" → slug vide
- Wikipedia grec / bulgare / russe si on enrichit : pareil

Le Stage 3 (fuzzy slug match) **ne peut pas fonctionner** si le slug source est vide.

**Solution retenue**

Installer `unidecode` via `flake.nix` + `uv pip`, et l'appliquer **avant** la normalisation NFKD dans `slugify`.

```python
from unidecode import unidecode

def slugify(text: str, max_len: int = 60) -> str:
    if not text:
        return ""
    text = text.replace("\u2013", " ").replace("\u2014", " ")
    text = unidecode(text)              # ← NEW : translittère avant NFKD
    text = text.lower()
    text = re.sub(r"['\u2019]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    if len(text) > max_len:
        cut = text[:max_len]
        if "-" in cut:
            cut = cut.rsplit("-", 1)[0]
        text = cut.rstrip("-")
    return text
```

Vérifié empiriquement :
```
'Ολυμπιακοί Αγώνες Αθήνα 2004'  → 'olympiakoi-agones-athina-2004'
'Кирилица и глаголица'            → 'kirilitsa-i-glagolitsa'
'Hypogée de Ħal-Saflieni'         → 'hypogee-de-hal-saflieni'
```

**Pourquoi `unidecode` et pas `anyascii` ou `pyicu`** :
- `anyascii` : licence ISC, légèrement plus permissif, performance équivalente. Tie-break, pas de différence pratique.
- `pyicu` : trop lourd (~100 MB), dépendance C native, build via Nix pénible. Overkill pour du kebab-case.
- `unidecode` : licence GPL/Artistic (OK pour usage interne, non redistribué), 400KB, table lookup, battle-tested. **Retenu.**

**Impact re-bootstrap** : les entrées maltaises (`mt-*-2eur-agar-qim`, etc.) vont changer d'`eurio_id`. Le merge idempotent drop/recrée ces 5-10 entrées, `first_seen` reset mais elles n'ont pas encore d'enrichissements → pas de perte. À exécuter **avant** le premier scraper d'enrichissement pour éviter la migration plus tard.

**Action** : ajouter `unidecode` au `flake.nix` Python environment, mettre à jour `slugify`, re-run les deux bootstraps.

---

### Problème 2 — Collision policy en contradiction avec le spec 🟠

**Constat**

`data-referential-architecture.md` §3.3 dit explicitement :

> Ce suffixe **n'est jamais assigné automatiquement** par un scraper : il est décidé lors d'une résolution manuelle dans la `review_queue`.

Mais `bootstrap_referential.py:270` fait :

```python
def _insert_with_collision_handling(entries, new_entry, collision_log):
    eid = new_entry["eurio_id"]
    if eid not in entries:
        entries[eid] = new_entry
        return
    suffix_n = 2
    while f"{eid}-v{suffix_n}" in entries:
        suffix_n += 1
    new_eid = f"{eid}-v{suffix_n}"
    new_entry["eurio_id"] = new_eid
    new_entry["provenance"]["needs_review"] = True
    ...
```

C'est **le pire des deux mondes** : génération automatique d'IDs canoniques tout en les marquant comme suspects. Si un utilisateur commence à référencer `de-2022-2eur-erasmus-v2` dans sa collection, on ne peut plus revenir en arrière sans casser ses données.

Aujourd'hui, **zéro collision détectée** (grâce à la qualité des slugs Wikipedia), donc le code est dormant. Mais dès que le scraper lmdlp ou eBay arrive avec des slugs plus sales, ça va se réveiller.

**Options**

**Option A — Conformité stricte au spec (retenue)**
- Scraper détecte la collision → écrit dans `review_queue.json` avec les deux candidates
- Jamais d'ID canonique auto-suffixé
- Boot échoue bruyamment si la `review_queue` n'est pas vide à la fin du run (ou bloque juste l'insertion du second et continue)

Avantages : contrat strict, pas de dette invisible, les humains tranchent.
Inconvénients : bootstrap peut se bloquer sur une vraie collision → pipeline humain requis.

**Option B — Relaxer le spec**
- Autoriser l'auto-suffix au bootstrap (parce qu'on a confiance dans la source)
- Interdire l'auto-suffix seulement dans les scrapers de sources tierces
- Adapter le spec §3.3 en ajoutant "sauf au bootstrap depuis source canonique"

Avantages : pragmatique, ne bloque pas le pipeline.
Inconvénients : règle à deux niveaux plus confuse, risque de copier/coller la logique dans un futur scraper.

**Décision** : **Option A**. Raisons :
1. Zéro collision aujourd'hui, donc zéro coût immédiat à passer en strict.
2. L'architecture entière repose sur la promesse "identité canonique immuable". Auto-générer un ID reviendrait à casser cette promesse.
3. Mieux vaut découvrir les collisions tôt (humain les tranche à la main) que tard (impact utilisateurs).
4. Le spec est plus facile à respecter que le relaxer puis devoir durcir plus tard.

**Action** : refactorer `_insert_with_collision_handling` en `_insert_or_queue`. Sur collision :
- Laisser l'entrée originale intacte
- Écrire la collision dans `ml/datasets/review_queue.json` avec `reason = "bootstrap_slug_collision"`
- Continuer le bootstrap sans la seconde entrée
- Logger un WARN + compter les collisions
- Le script termine avec exit code 1 si `review_queue` non-vide (stricte) OU juste un WARN (permissive) — **je penche permissive**, pour ne pas bloquer l'itération

---

### Problème 3 — DE circulation s'arrête à 2016 🟡

**Constat**

La page `en.wikipedia.org/wiki/German_euro_coins` a 15 Face Value tables (une par an 2002-2016) et **aucune** pour 2017+. Vérifié : les tables présentes pour des années plus récentes sont :
- `Year × Number × State × Design × Volume` pour les Bundesländer commemos (déjà capturés dans 2C.1a)
- `Year × Subject × Volume × Note` pour les common-issue commemos (capturés aussi)

Pas de table circulation 2017+. C'est une **lacune de la source**, pas un bug parser.

**Alternative identifiée**

`de.wikipedia.org/wiki/Auflagen_der_deutschen_Euromünzen` contient **toutes les données 2002-2024**, avec :
- **Une table par dénomination** (8 tables : 1c, 2c, 5c, 10c, 20c, 50c, 1€, 2€)
- Colonnes : Mint A (Berlin), D (Munich), F (Stuttgart), G (Karlsruhe), J (Hamburg), Σ (total)
- Lignes : années 2002-2024
- `–` = non frappé pour circulation

Structure **transposée** par rapport au format anglais : denom en titre de table, années en lignes, mints en colonnes. Nécessite un parser dédié.

**Bonus** : ce format expose le détail par mint, alors que notre modèle actuel agrège (`mintage_aggregated_across_mints: true`). On peut optionnellement stocker `by_mint: {A: X, D: Y, F: Z, G: W, J: V}` dans `observations.wikipedia.mintage`.

**Décision proposée**

Créer un scraper séparé `ml/bootstrap_circulation_de.py` qui :
1. Fetch `de.wikipedia.org/wiki/Auflagen_der_deutschen_Euromünzen` + snapshot
2. Parse les 8 tables per-denomination
3. Produit les mêmes entrées `de-YYYY-Xc-standard` que `bootstrap_circulation.py`
4. **Remplace** les entrées DE existantes (détecter via `sources_used == ['wikipedia_country']` et `country == 'DE'`)
5. Stocke le détail par mint dans `observations.wikipedia.by_mint`

Tag le `sources_used = ['wikipedia_de_auflagen']` pour différencier.

Alternative à bas coût : patcher `bootstrap_circulation.py` pour détecter `iso2 == 'DE'` et bifurquer. **Pas retenu** — on a déjà un hardcode `iso2 == "DE"` que je veux retirer (Problème 6), ajouter un second aggraverait la situation. Un script dédié est plus propre.

**Action** : implémenter `bootstrap_circulation_de.py` en Phase 2C.1c (nouvelle sous-phase). Effort ~0.3 jour.

---

### Problème 4 — `extract_data_rows` pairing fragile 🟡

**Constat** (`bootstrap_referential.py:59-81`)

```python
while i < len(rows):
    row = rows[i]
    cells = row.find_all(["td", "th"], recursive=False)
    if len(cells) >= 4:
        desc_row = rows[i + 1] if i + 1 < len(rows) else None
        data_rows.append((row, desc_row))
        i += 2
    else:
        i += 1
```

Chaque fois qu'une row a ≥ 4 cellules, elle est considérée comme data row et la row N+1 comme description row. **Aucune vérification que la row N+1 commence par `"Description:"`.**

**Risque** : si une commémo n'a pas de description row (ou si l'HTML Wikipedia a une anomalie de rendu colspan/rowspan), la row suivante — qui est en fait une *autre commémo* — est absorbée comme "description" et donc **perdue silencieusement**.

**Vérification empirique** : re-parsing avec un check strict n'a révélé aucun gap inexpliqué sur le snapshot actuel. Mais c'est une bombe à retardement : si un jour Wikipedia change un format, des entrées peuvent disparaître silencieusement sans erreur.

**Solution**

```python
while i < len(rows):
    row = rows[i]
    cells = row.find_all(["td", "th"], recursive=False)
    if len(cells) >= 5:              # aligne sur parse_data_row
        desc_row = None
        if i + 1 < len(rows):
            peek = rows[i + 1]
            peek_cells = peek.find_all(["td"], recursive=False)
            if peek_cells:
                peek_text = peek_cells[0].get_text(" ", strip=True).lower()
                if peek_text.startswith("description:"):
                    desc_row = peek
        data_rows.append((row, desc_row))
        i += 2 if desc_row else 1   # ne "consume" N+1 que si c'est vraiment une desc
    else:
        i += 1
```

Également : unifier le seuil `>= 5` entre `extract_data_rows` et `parse_data_row` (actuellement 4 vs 5, incohérent).

**Action** : patch `bootstrap_referential.py`, ajouter un test sur un cas forgé (row data sans desc row suivi d'une autre row data).

---

### Problème 5 — `parse_volume_cell` ambigu sur `1.234` 🟢

**Constat** (`bootstrap_circulation.py:76-117`)

```python
COMPACT_DECIMAL_RX = re.compile(r"^\d+\.\d{1,3}$")  # '800.0' or '1.234'
...
if COMPACT_DECIMAL_RX.match(text):
    value = float(text)
    return int(value * 1_000_000)
```

`800.0` = 800 millions (US-compact format, DE English Wikipedia). Correct.
`1.234` → match aussi. Actuel : 1.234 × 1M = **1 234 000**.

Si jamais une source utilise le format DE thousands `1.234` pour signifier **1 234** (pas 1.234 millions), on obtient 1 000× l'erreur.

**Contexte actuel** : la page DE Wikipedia anglaise utilise exclusivement `,` comme séparateur décimal sur les tables FV (`60,00`, `124,3`). Pas de conflit aujourd'hui. Mais :
- `de.wikipedia.org` (si on l'utilise pour Problème 3) pourrait mixer les conventions
- Un scraper de shop allemand (Hoffmann, MA-Shops) pourrait avoir `1.234` = 1234

**Décision** : appliquer une heuristique de garde à bas coût, sans complexifier.

```python
if COMPACT_DECIMAL_RX.match(text):
    value = float(text)
    # Millions compact : valeurs plausibles entre 0.001 et 10000 (0.001M à 10G)
    # Si valeur > 10000 c'est clairement pas millions
    # Si valeur < 1 et forme N.NNN (ex '0.001') c'est probablement pas un volume
    if value > 10000:
        return None  # suspect, let the caller handle
    return int(value * 1_000_000)
```

Plus fondamentalement, **documenter par-source** quelle convention est attendue. Un comment en tête de `parse_volume_cell` qui énumère les sources connues et leur convention est plus efficace que n'importe quelle heuristique.

**Action** : ajouter la garde `value > 10000 → None`, ajouter un docstring avec la table des conventions connues. Non-bloquant, à faire en passant.

---

### Problème 6 — Code smells divers 🟢

| Fichier | Ligne | Problème | Fix |
|---|---|---|---|
| `bootstrap_referential.py` | 14 | `import sys` inutilisé | supprimer |
| `bootstrap_circulation.py` | 19 | `import sys` inutilisé | supprimer |
| `eurio_referential.py` | 235 | `datetime.utcnow()` deprecated Py 3.12+ | `datetime.now(timezone.utc)` |
| `bootstrap_circulation.py` | 220 | `iso2 == "DE"` hardcodé dans `mintage_aggregated_across_mints` | détecter au parse time (count de tables distinctes contribuant à une même key) |
| `eurio_referential.py` | 187 | `joue_reference` dans identity + `joue_code` dans cross_refs → duplication | **décision : retirer `joue_reference` de `make_identity`**, ne garder que `cross_refs.joue_code` (canonical selon la spec §4.2). Mettre à jour le schema SQL (§4.3 ne l'a pas de toute façon). |
| `bootstrap_referential.py` | 74 | `extract_data_rows` seuil `>= 4` incohérent avec `parse_data_row` seuil `>= 5` | aligner sur `>= 5` partout |
| `eurio_referential.py` | 112 | `parse_volume` vs `parse_volume_cell` — 2 fonctions redondantes | garder les deux (scope différent) mais documenter. `parse_volume` ne sert qu'aux commémoratives, `parse_volume_cell` à la circulation. OK. |

**Action** : patch unique de hygiène, ~10 min.

---

## 4. Points discutés mais NON retenus comme problèmes

### 4.1 Truncation à 60 chars

Le word-boundary rsplit fonctionne : zéro collision post-troncation. Certains slugs perdent l'indicateur "joint-issue" à la fin (ex: `fr-2013-2eur-50th-anniversary-of-the-signing-of-the-elysee-treaty-joint`) mais ça n'a pas d'impact sur l'ID canonique, juste sur la lisibilité. `max_len=60` est un bon tradeoff.

### 4.2 Émissions communes Option A

Le spec §3.4 figent ce choix : une entrée canonique `eu-*` avec `national_variants`, pas d'entrées filles. La review confirme que ce choix est cohérent avec les 5 entrées `eu-*` produites par le bootstrap. Pas de question ouverte.

### 4.3 Variantes de design France 1€/2€

Deux séries historiques française (Sempé 1999 → Serre 2022 pour les 1€/2€). Le bootstrap actuel les agrège sous `fr-YYYY-2eur-standard` sans distinguer. **Acceptable pour le POC** — la distinction est visuelle et sera gérée par Stage 4 (visual matching) quand ArcFace sera prêt. Noter dans TODOs mais pas bloquant.

### 4.4 Variantes mints allemands

Le bootstrap actuel agrège A/D/F/G/J en un seul volume par année. La solution au Problème 3 (scraper de.wikipedia) exposera le détail par mint dans `observations.wikipedia.by_mint`. Les consommateurs (app, scoring) peuvent continuer d'ignorer le détail s'ils veulent.

### 4.5 Vatican : ères de design (2002-2005, 2006-2013, ...)

Chaque pape a sa propre effigie. Pour le POC on garde `va-YYYY-2eur-standard` sans distinguer. La distinction sera faite par Stage 4 ou par review manuelle quand on rencontrera une pièce Vatican concrète. Non-bloquant.

### 4.6 Bulgarie 2026

Wikipedia n'a qu'une ligne placeholder vide pour BG 2026 (BG a rejoint l'eurozone le 2026-01-01, première frappe prévue S2 2026). Rien à faire avant que BG n'émette réellement. Re-run du bootstrap automatiquement régulièrement couvrira.

---

## 5. Plan d'exécution proposé

Ordre optimal pour ne pas re-migrer deux fois :

### 5.1 Batch "fix slugify et hygiène" — ~1 heure

1. Installer `unidecode` via `flake.nix` + `uv pip install unidecode`
2. Patch `slugify` dans `eurio_referential.py`
3. Hygiène (§ Problème 6 tableau) :
   - Retirer imports `sys` inutilisés
   - `datetime.utcnow` → `datetime.now(timezone.utc)`
   - Aligner seuil `>= 5` dans `extract_data_rows`
   - Retirer `identity.joue_reference` (garder `cross_refs.joue_code`)
   - Remplacer `iso2 == "DE"` par détection dynamique dans `parse_country_page`
4. Fix `extract_data_rows` pairing (Problème 4)
5. Ajouter garde `value > 10000` dans `parse_volume_cell` (Problème 5)
6. Re-run bootstrap commémoratives + circulation

**Vérifications post-run** :
- Nombre d'entrées stable (±10) → pas de régression massive
- Pas de nouveaux `needs_review`
- Les slugs MT changent pour `hagar-qim`, `ta-hagrat-temples`, `gantija` (vérifier manuellement)

### 5.2 Batch "collision policy" — ~45 min

1. Refactor `_insert_with_collision_handling` → `_insert_or_queue`
2. Créer `ml/datasets/review_queue.json` initial `[]`
3. Le bootstrap log WARN sur collision, écrit dans `review_queue.json`, **ne bloque pas** le run
4. Tester en forgeant une collision artificielle (deux thèmes identiques après slug)
5. Mettre à jour le spec §3.3 si nécessaire (il est déjà correct, devrait juste marcher)

### 5.3 Batch "DE circulation 2017+" — ~3 heures

1. Créer `ml/bootstrap_circulation_de.py`
2. Fetch + snapshot `de.wikipedia.org/wiki/Auflagen_der_deutschen_Euromünzen`
3. Parser les 8 tables per-denomination
4. Écrire dans le référentiel avec `sources_used = ['wikipedia_de_auflagen']`
5. Remplacer les entrées DE existantes (actuellement taggées `wikipedia_country`)
6. Vérifier : DE passe de 75 à ~200 entrées couvrant 2002-2024

### 5.4 Mise à jour de la doc

- `docs/research/data-referential-architecture.md` §4.1 : retirer `joue_reference` de l'exemple identity
- `docs/phases/phase-2c-referential.md` : ajouter 2C.1c (Allemagne) après 2C.1b
- `docs/research/referential-bootstrap-research.md` : ajouter note sur `de.wikipedia.org/wiki/Auflagen...` comme source DE canonique

### 5.5 Tests smoke

Au-delà de l'inspection visuelle, ajouter `ml/test_eurio_referential.py` avec :
- `test_slugify_greek` : doit produire `olympiakoi-agones-athina-2004`
- `test_slugify_cyrillic` : doit produire `kirilitsa-i-glagolitsa`
- `test_slugify_maltese` : doit produire `hagar-qim` (non-régression)
- `test_slugify_truncation_word_boundary` : slug long doit couper sur `-`
- `test_compute_eurio_id_basic` : couvre 1c..2eur
- `test_parse_volume_formats` : matrice de formats (EU, US, DE, thin-space, footnote)

Effort : ~30 min.

---

## 6. Ce qu'on livre à la fin

- [ ] `slugify` gère Grec/Cyrillique/Maltais
- [ ] Collision policy cohérente avec spec (pas d'auto-suffix)
- [ ] DE circulation étendue à 2024 via source alternative
- [ ] Code hygiénisé (imports, deprecated APIs, hardcodes)
- [ ] Tests smoke de base sur les helpers critiques
- [ ] Doc à jour (architecture, phase, research)
- [ ] Référentiel toujours à ~2 900-3 000 entrées propres (gain marginal sur DE, pas de régression ailleurs)

Après ça, **Phase 2C.2 (scraper lmdlp)** peut démarrer sur une base saine.

---

## 7. Décisions tranchées (2026-04-13)

1. **Collision policy** : permissive → WARN + écriture dans `review_queue.json`, le bootstrap continue (pas de exit 1).
2. **Ordre d'exécution** : §5.1 → §5.2 → §5.3 → §5.4 → §5.5 validé.
3. **Phase 2C.1c (DE)** : sous-phase formelle ajoutée à `phase-2c-referential.md`.
4. **Licence translittération** : `anyascii` (ISC) retenu plutôt qu'`unidecode` (GPL/Artistic) → compatible commercial.
5. **Tests** : stdlib `unittest`, fichier unique `ml/test_eurio_referential.py`, pas de pytest.

---

## 8. Résultat de l'implémentation

Tous les batches §5.1–§5.5 ont été exécutés.

### Référentiel après fixes

| Métrique | Avant (commit ce9d310) | Après |
|---|---|---|
| Total entrées | 2 891 | **2 938** |
| Commémoratives | 517 | 517 |
| Circulation (hors DE) | 2 299 | 2 299 |
| Circulation DE | 75 (2002-2016) | **122 (2002-2024)** |
| `needs_review` | 0 | 0 |
| Slugs Maltais corrects | non (`agar-qim`) | oui (`hagar-qim`) |
| `joue_reference` doublonné | présent | retiré |
| Hardcode `iso2 == "DE"` | présent | détection dynamique |

### Fichiers livrés

- `ml/eurio_referential.py` — slugify via `anyascii`, `joue_reference` retiré, `datetime.now(timezone.utc)`
- `ml/bootstrap_referential.py` — `extract_data_rows` strict sur `"Description:"`, `_insert_or_queue` → `review_queue.json`, no auto-suffix
- `ml/bootstrap_circulation.py` — garde `parse_volume_cell` > 10000, détection dynamique de `aggregated_across_tables`
- `ml/bootstrap_circulation_de.py` — **NEW** Phase 2C.1c, parse `de.wikipedia` Auflagen page
- `ml/test_eurio_referential.py` — **NEW** 29 tests stdlib `unittest`, tous verts
- `flake.nix` — ajout `httpx`, `beautifulsoup4`, `lxml`, `anyascii`
- `ml/datasets/sources/wikipedia_de_auflagen_2026-04-13.html` — snapshot immuable

### Docs mises à jour

- `docs/research/data-referential-architecture.md` §4.1, §4.3 — `joue_reference` retiré, `collector_only` ajouté au schema SQL
- `docs/phases/phase-2c-referential.md` — sous-phase 2C.1c ajoutée, table d'effort actualisée
- `docs/research/referential-bootstrap-research.md` — note sur source DE alternative

### Tests

```
$ python ml/test_eurio_referential.py
Ran 29 tests in 0.003s
OK
```

Couverture : `slugify` (8 cas dont Grec/Cyrillique/Maltais/troncation), `compute_eurio_id` (5 cas), `format_face_value` (matrice 8 denoms), `parse_volume` (4 cas), `parse_volume_cell` (7 cas dont garde compact-millions), `parse_de_value` (3 cas).
