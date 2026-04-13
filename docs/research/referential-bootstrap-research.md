# Recherche — Sources canoniques pour bootstrap du référentiel Eurio

> Recherche préparatoire à l'implémentation de la Phase 2C.1.
> Date : 2026-04-13.
> Consommateur : `ml/bootstrap_referential.py` (à coder).
> Doc parent : [`data-referential-architecture.md`](./data-referential-architecture.md), [`phase-2c-referential.md`](../phases/phase-2c-referential.md).

---

## Résumé exécutif

Trois décisions principales issues de cette recherche :

1. **Wikipedia est la source primaire de bootstrap**, pas la BCE. Wikipedia est plus complet (intègre micro-états), plus à jour (couvre 2026), et ses wikitables s'ingèrent en une ligne via `pandas.read_html`. La BCE reste en **validation autoritaire** + descriptions officielles + URLs images canoniques.

2. **Le référentiel final contiendra ~3 600 entrées, pas 500.** Les 2€ commémoratives ne représentent que ~520 entrées (~15% du total). Le gros volume est la **circulation standard** (~3 000 entrées = 8 dénominations × 21 pays × ~20 ans). Cette révision implique de **splitter la Phase 2C.1** en deux sous-étapes distinctes.

3. **Aucune émission commune 2025/2026.** Les 5 émissions communes connues restent définitives : 2007 Traité de Rome, 2009 UEM, 2012 euro 10 ans, 2015 drapeau, 2022 Erasmus.

---

## 1. Source BCE — commémoratives 2€

**URL index :** `https://www.ecb.europa.eu/euro/coins/comm/html/index.en.html`

Page-passerelle. Liens vers des sous-pages annuelles :
**`https://www.ecb.europa.eu/euro/coins/comm/html/comm_{YYYY}.en.html`** pour 2004 à 2025.

**2026 non disponible** en avril 2026 — la traduction BCE en 23 langues prend plusieurs mois après publication JOUE.

**Structure sous-page annuelle** (exemple `comm_2024`) : HTML statique, aucun JavaScript, ~25 entrées/an, format :

```html
<h3>Lithuania</h3>
<p><strong>Feature:</strong> Lithuanian tradition of straw gardens...</p>
<p><strong>Description:</strong> The design features a stylised straw garden...</p>
<p><strong>Issuing volume:</strong> 500 000 coins</p>
<p><strong>Issuing date:</strong> Fourth quarter of 2024</p>
```

- Champs : pays (h3), feature, description, issuing volume, issuing date, image (path relatif `comm_2024/<Country>.jpg`)
- Code JOUE non-systématique dans le corps
- Scrape via `BeautifulSoup4` + `lxml`, `read_html` ne marche pas (non tabulaire)

**Verdict** : structure régulière prévisible, mais couverture 2026 absente → inutilisable seul pour bootstrap.

---

## 2. Source Wikipedia — commémoratives 2€ + micro-états + communes

**URL principale :** `https://en.wikipedia.org/wiki/2_euro_commemorative_coins`

**Structure** :
- Une **grande matrice pays × années** (24 pays/micro-états × 2004-2026) avec marqueurs « Y » (émis) / « S » (scheduled)
- **Une section par année** (2004 → 2026), chacune avec une wikitable détaillée
- Sections dédiées aux émissions communes (« 2007 commonly issued coin », etc.)
- Micro-états (Vatican, Monaco, SM, Andorre) intégrés dans la même table

**Champs par entrée** : drapeau/image, pays, thème, **volume d'émission** (systématique), **date de mise en circulation**, description du design.

**Total répertorié** : ~585 variations, incluant les 2026 programmées.

**Outillage** : `pandas.read_html` ingère les wikitables en une ligne. Fallback si cellules fusionnées (colspan/rowspan) → API MediaWiki + `mwparserfromhell` pour parser le wikitext brut.

---

## 3. BCE vs Wikipedia — verdict

| Critère | BCE | Wikipedia |
|---|---|---|
| Couverture 2026 | ❌ Non | ✅ Oui (programmées) |
| Volumes | ✅ | ✅ |
| Micro-états | ⚠ Dispersé | ✅ Intégré |
| Structure scrapable | HTML régulier (BS4) | wikitables via `read_html` |
| Fraîcheur | Lag de plusieurs mois | Continue |
| Autorité juridique | ✅ | ❌ (sourcé BCE) |
| Descriptions officielles | ✅ Oui | ⚠ Paraphrasé |
| Images canoniques | ✅ | ⚠ |

**Décision** : Wikipedia comme **source primaire**, BCE comme **validation** + **enrichissement** (images, descriptions officielles, cross-check des volumes).

---

## 4. Pièces de circulation standard

**BCE** : `https://www.ecb.europa.eu/euro/coins/2euro/html/index.en.html` (et équivalents par dénomination). Couvre 28 entités (21 zone euro + Andorre, Monaco, SM, Vatican) mais **un seul design représentatif par pays** — pas tous les millésimes. **Peu utile pour un référentiel année par année.**

**Wikipedia** : **une page par pays**, pattern `https://en.wikipedia.org/wiki/{Country}_euro_coins`. Exemples :
- `Bulgarian_euro_coins`
- `French_euro_coins`
- `German_euro_coins`
- `Vatican_euro_coins`

Chaque page contient :
- Une wikitable des 8 dénominations avec design
- **Une table « Circulating mintage quantities »** (volumes par année + dénomination) → exactement ce qu'il nous faut
- Les changements de design (ex : France a deux séries 1€/2€)

**Ordre de grandeur** :
- 8 dénominations × 21 pays × ~20 ans moyens ≈ **~3 000 entrées**
- Sans distinguer variantes d'ateliers (Allemagne A/D/F/G/J × 5, ou France Pessac × 1)
- Avec ateliers distingués : multiplication possible, à arbitrer

**Attention** : certains pays n'émettent pas toutes les dénominations chaque année (Vatican en particulier → sets de collection uniquement depuis 2010, seule la 50c est frappée en volume ~1,5-2M/an). **Pas de produit cartésien mécanique**, s'appuyer sur la table mintage réelle.

---

## 5. Émissions communes zone euro

Liste exhaustive (Wikipedia + BCE) :

| Année | Thème | Participants |
|---|---|---|
| 2007 | 50 ans Traité de Rome | 13 pays |
| 2009 | 10 ans UEM | 16 pays |
| 2012 | 10 ans euro fiduciaire | 17 pays |
| 2015 | 30 ans drapeau européen | 19 pays |
| 2022 | 35 ans Erasmus | 19 pays |

**Aucune émission commune programmée pour 2025 ou 2026** (vérifié en avril 2026).

**Chaque pays émet bien sa propre variante** avec sa face nationale — l'avers (le design commun) est identique, le revers est national. Ces variantes **comptent en plus** du quota annuel de 2 pièces commémoratives (3ème exceptionnelle autorisée).

**Volume total** : ~90-100 variantes sur les 5 émissions communes (avec ajustement pour les adhésions tardives).

**Modélisation Eurio** : 5 entrées canoniques `eu-YYYY-2eur-{slug}` avec sous-champ `national_variants` listant tous les pays participants. Ou : 5 entrées canoniques + 90 entrées filles si on préfère des entrées par pays. **Décision à prendre** : préférer la 1ère option (plus compact, plus cohérent).

---

## 6. États tiers

**Cadence d'émission 2€ commémoratives** :

| Pays | Depuis | Cadence |
|---|---|---|
| Saint-Marin | 2004 | 1-2/an |
| Vatican | 2004 | 1-2/an (dont Sede Vacante exceptionnelle) |
| Monaco | 2007 | 0-1/an (très rare, volumes faibles ~15k) |
| Andorre | 2014 | 1-2/an |

**Sources** :
- Wikipedia : `Vatican_euro_coins`, `Monegasque_euro_coins`, `Sammarinese_euro_coins`, `Andorran_euro_coins`
- BCE : intégrés dans pages annuelles commémoratives

**Spécificité** : volumes circulation très faibles côté Vatican/Monaco, souvent uniquement en sets numismatiques. Flag à prévoir dans le schéma : `collector_only: true`.

**Wikipedia `2_euro_commemorative_coins` intègre déjà ces 4 états**, pas de source additionnelle nécessaire pour le bootstrap des commémoratives.

---

## 7. Recommandation technique

### 7.1 Stack Python

```
httpx                 # async + backoff + User-Agent propre (Wikipedia politeness)
pandas                # read_html sur wikitables → DataFrame direct
beautifulsoup4 + lxml # BCE structure h3/p plate
mwparserfromhell      # OPTIONNEL — wikitext brut via MediaWiki API
pydantic              # validation + normalisation schema Coin
```

### 7.2 Priorité des sources

1. **Wikipedia `2_euro_commemorative_coins`** → source primaire commémoratives + communes + états tiers
2. **Wikipedia `{country}_euro_coins`** (×25 pages) → circulation standard (tables mintage)
3. **BCE `comm_{year}.en.html`** (2004-2025) → cross-validation + descriptions officielles + URLs images

### 7.3 Écueils à gérer

- **Volumes hétérogènes** : `"50 million"`, `"2,481,800 coins"`, `"500 000"`, `"500.000"` → regex + normalisation explicite vers int
- **Dates imprécises** : BCE donne `"Fourth quarter of 2024"`, Wikipedia donne parfois date précise. Stocker `issue_date_raw` + `issue_year` + `issue_quarter` optionnel
- **Cellules fusionnées** Wikipedia : `colspan`/`rowspan` → `pandas.read_html` gère mais post-traitement à prévoir, fallback API MediaWiki
- **Unicode** : cyrillique bulgare (БЪЛГАРИЯ), grec, diacritiques slovènes → UTF-8 partout, `ensure_ascii=False` dans les dumps JSON
- **Images BCE** : chemins relatifs, résoudre contre base BCE
- **2026 BCE manquant** : tolérer gracieusement l'absence de `comm_2026.en.html`, se rabattre Wikipedia
- **Micro-états circulation** : ne **pas** générer un produit cartésien (pays × dénomination × année), s'appuyer sur table mintage réelle
- **Politesse Wikipedia** : User-Agent identifié (`Eurio/0.1 (https://eurio.app; contact@eurio.app) python-httpx/0.x`), `time.sleep(0.5)` entre requêtes

### 7.4 Cross-validation BCE ↔ Wikipedia

Pipeline :
1. Parser les deux sources indépendamment vers un schéma `Coin` pydantic normalisé
2. Clé de jointure : `(country, year, theme_normalized)` ou `(country, year, commemorative_index)` selon structure
3. Pour chaque divergence, logger `{bce_value, wiki_value, field}` dans `ml/datasets/sources/divergences_YYYY-MM-DD.jsonl`
4. Règles de résolution par défaut :
   - Volumes → BCE (autorité officielle)
   - Descriptions → BCE (phrasing officiel)
   - Couverture 2026 → Wikipedia (BCE manquant)
   - Thèmes → Wikipedia (plus standardisé)
5. Validation humaine manuelle sur l'échantillon de divergences → repérer coquilles Wikipedia + retards BCE

### 7.5 URLs à hardcoder dans `bootstrap_referential.py`

```python
WIKIPEDIA_COMMEMO = "https://en.wikipedia.org/wiki/2_euro_commemorative_coins"
WIKIPEDIA_COUNTRY = "https://en.wikipedia.org/wiki/{country_adjective}_euro_coins"
ECB_COMMEMO_YEAR  = "https://www.ecb.europa.eu/euro/coins/comm/html/comm_{year}.en.html"
ECB_NATIONAL      = "https://www.ecb.europa.eu/euro/coins/2euro/html/index.en.html"
```

Et un mapping statique `country_mapping.json` :
```json
{
  "BG": {"adjective": "Bulgarian",   "name": "Bulgaria"},
  "DE": {"adjective": "German",      "name": "Germany"},
  "FR": {"adjective": "French",      "name": "France"},
  "VA": {"adjective": "Vatican",     "name": "Vatican City"},
  ...
}
```

### 7.6 Estimation du nombre d'entrées

| Catégorie | Entrées |
|---|---|
| 2€ commémoratives (2004-2026, 21 pays + 4 états tiers) | **~520** |
| Émissions communes (5 × ~19 variantes, ou 5 canoniques) | **~90 ou 5** |
| Circulation standard (8 × 21 × ~20 ans) | **~2 800** |
| Circulation micro-états (volumes réduits) | **~200** |
| **Total brut** | **~3 600** |

Après déduplication des communes (elles peuvent apparaître dans Wikipedia comme entrées par pays) : **~3 400-3 500 entrées canoniques**.

---

## 8. Implication pour le plan de la Phase 2C

La phase 2C.1 initiale prévoyait ~500 entrées en bootstrap. La recherche révèle un scope réel **7× plus grand**. Recommandation : splitter 2C.1 en deux sous-étapes distinctes pour garder des livrables atomiques.

- **Phase 2C.1a — Bootstrap 2€ commémoratives + communes + états tiers**
  - Source : Wikipedia `2_euro_commemorative_coins`
  - ~610 entrées
  - Une seule page à fetcher, une seule table à parser
  - Effort : 0,5-1 jour

- **Phase 2C.1b — Bootstrap circulation standard**
  - Sources : 25 pages Wikipedia `{country}_euro_coins`
  - ~3 000 entrées
  - 25 fetches + 25 parsings de tables mintage
  - Effort : 1-2 jours

La mise à jour de `phase-2c-referential.md` avec ces deux sous-étapes est recommandée avant de commencer l'implémentation.

---

## Sources citées

- [BCE — €2 commemorative coins index](https://www.ecb.europa.eu/euro/coins/comm/html/index.en.html)
- [BCE — €2 commemorative coins 2024](https://www.ecb.europa.eu/euro/coins/comm/html/comm_2024.en.html)
- [BCE — National sides](https://www.ecb.europa.eu/euro/coins/2euro/html/index.en.html)
- [Wikipedia — 2 euro commemorative coins](https://en.wikipedia.org/wiki/2_euro_commemorative_coins)
- [Wikipedia — Euro coins](https://en.wikipedia.org/wiki/Euro_coins)
- [Wikipedia — Bulgarian euro coins](https://en.wikipedia.org/wiki/Bulgarian_euro_coins)
- [Wikipedia — Vatican euro coins](https://en.wikipedia.org/wiki/Vatican_euro_coins)
- [EUR-Lex OJ C/2025/6380 — new national sides](https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=OJ:C_202506380)
