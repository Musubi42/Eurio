# eBay API — Recherche, limitations, stratégie pour Eurio

> État : exploration terminée le **2026-04-13**. Stratégie figée, implémentation pipeline à venir en phase 3.
> Scripts de test : `ml/test_ebay.py`, `ml/test_ebay_item.py`, `ml/test_ebay_aggregate.py`

---

## 1. Pourquoi on a besoin d'eBay

Eurio affiche à l'utilisateur la **valeur marché** de sa collection dans le coffre (PRD §3, phase-3-coffre). Le PRD initial prévoyait la **Finding API** pour les "completed listings" (ventes terminées), qui permettait d'obtenir des vrais prix de transaction.

**Problème découvert** : la Finding API et la Shopping API ont été **décommissionnées le 5 février 2025**. Le PRD doit être mis à jour. Le seul endpoint moderne accessible à un développeur standard est la **Browse API**, qui ne renvoie **que des listings actifs** (pas de ventes terminées sauf pour les développeurs haut-niveau via Marketplace Insights API, réservée à Terapeak).

Cette recherche documente ce qu'on peut effectivement récupérer, à quel coût, et comment en tirer une valeur marché crédible malgré la limitation.

---

## 2. État du paysage API eBay (2026)

### 2.1 APIs actives utilisables

| API | Usage pour Eurio | Statut |
|---|---|---|
| **Browse API** (`/buy/browse/v1/`) | Recherche de listings actifs, détails item, groupes de variations | ✓ Active, 5000 calls/jour |
| **Marketplace Insights API** | Prix de ventes terminées | ❌ Réservée aux partenaires Terapeak |
| **Taxonomy API** | IDs de catégories, aspects valides | ✓ Active, utile pour construire des filtres |

### 2.2 APIs décommissionnées (à éviter)

| API | Décommissionnement | Remplacement |
|---|---|---|
| Finding API | 2025-02-05 | Browse API |
| Shopping API | 2025-02-05 | Browse API |
| Trading API (XML, partiellement) | En cours | Sell APIs (REST) |

---

## 3. Authentification — clarifications

eBay a historiquement **trois** systèmes d'auth, ce qui génère une confusion massive dans le portail développeur :

| Type | Usage | User consent requis |
|---|---|---|
| **Auth'n'Auth** | Trading API legacy (XML) | Oui (vieux flow) |
| **OAuth – User token** (Authorization Code) | Données utilisateur (commandes, inventaire) | Oui — consent page, redirect URI, sign-in.ebay.com |
| **OAuth – Application token** (Client Credentials) | **Recherche publique Browse API** | **NON** — juste Client ID + Cert ID |

Pour Eurio, on n'a besoin **que de l'Application token** (flow `client_credentials`). Pas de consent page, pas de redirect. Un simple POST avec `Authorization: Basic base64(client_id:cert_id)` renvoie un token valide 7200s.

**Credentials stockés** : `.env` → `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET` (= Cert ID).

---

## 4. Findings empiriques — ce que Browse API donne vraiment

### 4.1 `item_summary/search` est très maigre

L'endpoint de recherche retourne une réponse légère qui **ne contient PAS** :
- `condition` / `conditionId` — absent
- `estimatedAvailabilities` (donc pas de `estimatedSoldQuantity`) — absent
- `localizedAspects` (métadonnées structurées) — absent
- `primaryItemGroup` (détection des listings multi-variation) — absent

Les `fieldgroups=EXTENDED` et `fieldgroups=FULL` sur le search **n'ajoutent rien** au payload des items — testé empiriquement, les keys sont strictement identiques. Le seul gain de `FULL` est le bloc `refinement` top-level (voir §4.3).

**Implication** : pour avoir la richesse de données, il faut un appel `getItem` par item. Ça coûte 1 appel supplémentaire mais c'est incontournable.

### 4.2 `getItem` est riche

Le endpoint `/buy/browse/v1/item/{item_id}` retourne un payload complet avec :

- `primaryItemGroup.itemGroupType = "SELLER_DEFINED_VARIATIONS"` → détection des listings multi-variation
- `estimatedAvailabilities[0].estimatedSoldQuantity` → compteur de ventes
- `localizedAspects` → **métadonnées structurées** (année, atelier, design, valeur faciale)
- `conditionDescription` → texte libre de condition (les vendeurs de pièces mettent tout ici)
- `itemOriginDate` → date de création du listing actuel (important pour §5.2)
- `additionalImages` → images HD supplémentaires

**Variantes `fieldgroups`** :
- `PRODUCT` (défaut) : full payload
- `COMPACT` : plus léger, **garde `estimatedAvailabilities`** mais perd `primaryItemGroup` et `localizedAspects`. Utile si on veut juste le signal sold.

### 4.3 Le bloc `refinement` — mine d'or gratuite

Avec `fieldgroups=FULL,ASPECT_REFINEMENTS` sur `item_summary/search`, on récupère au top-level un bloc `refinement` qui contient les **distributions agrégées sur tous les items matching**, sans charger aucun item.

Exemple réel sur `q="2 euro commemorative", category_ids=32650` (13 310 items) :

```
aspectDistributions:
  [Année] — 23 valeurs
    2020: 908    2019: 775    2018: 951
    2015: 1066   2014: 807    ...

  [Valeur faciale] — 16 valeurs
    2 Euro: 15723    1 Euro: 36    ...

categoryDistributions:
  France: 4265    Allemagne: 2023    Finlande: 969    Autres: 4483

conditionDistributions: [...]
buyingOptionDistributions: [...]
```

**Valeur pour Eurio** : avant même de récupérer un item, on sait combien il y a de data disponible pour chaque (année, pays, design). On peut arbitrer notre budget d'appels API par pièce en fonction de la profondeur de marché constatée.

### 4.4 Listings multi-variation : détection et dépliage

Un listing peut contenir **plusieurs dizaines de variations** sous un même `itemId` parent (ex : un vendeur liste "2 euro Allemagne 2006 à 2025" avec 45 variations année × atelier).

**Détection** : via `primaryItemGroup.itemGroupType = "SELLER_DEFINED_VARIATIONS"` dans la réponse `getItem`.

**Dépliage** : via l'endpoint `/buy/browse/v1/item/get_items_by_item_group?item_group_id={id}`. Un seul appel retourne **toutes les variations** avec :
- Prix individuel par variation
- `localizedAspects` structurés par variation (année, atelier, design)
- `estimatedSoldQuantity` par variation

**Exemple mesuré** : le listing `358153628831` retourne 45 variations en 1 appel, fourchette 2,80€–8,00€, avec 12/45 variations ayant ≥1 vente. Les aspects contiennent `"2007 A - Traité de Rome"` directement parsables.

**C'est la meilleure source de data qu'on ait trouvée** : un seul appel API peut remplir le prix de dizaines de pièces d'un coup.

### 4.5 Filtres côté serveur

**`aspect_filter` — ✓ fonctionne**. Syntaxe :
```
aspect_filter=categoryId:32650,Année:{2006}
```
Testé empiriquement : retourne 752 items pour "2 euro" en 2006 uniquement. **Filtrage à la source**, économise la bande passante et le calcul client.

**`filter=conditionIds:{3000|4000|5000}` — ❌ retourne 0 résultats**. Les vendeurs de pièces **ne renseignent pas** le champ `condition` eBay standard (ils mettent tout dans le titre ou la description). Donc ce filtre est à abandonner pour notre use case.

**`filter=price:[3..20],priceCurrency:EUR`** — fonctionne, utile pour éviter les aberrations d'entrée.

### 4.6 Rate limits

- **5 000 appels/jour** par défaut pour Browse API (toutes opérations confondues).
- Augmentation possible à 1,5M/jour via une **Application Growth Check** auprès d'eBay (soumission manuelle, processus non automatique).
- **Token** : 7 200 secondes (2h). À cacher et réutiliser, ne pas recréer à chaque appel.

---

## 5. Observations clés sur la qualité des prix

### 5.1 Prix demandés ≠ prix de marché

Sur 200 résultats de "2 euro commemorative" :
- **Fourchette brute** : 2,42€ à 1 484,89€
- **Médiane** : 6,15€
- **Moyenne** : 23,85€ (biaisée par la queue haute)
- **P25 / P75** : 4,50€ / 17,00€

Interprétation : les listings actifs ont un biais fort vers le haut. Les vendeurs maintiennent des listings "zombies" pendant des années en espérant vendre. Un listing peut avoir `itemOriginDate = 2015` et n'avoir jamais vendu — son prix affiché est fictif.

### 5.2 `estimatedSoldQuantity` — signal exploitable mais flou

**Doc eBay officielle** : littéralement une phrase, *"The estimated number of this item that have been sold"*. Aucune mention de fenêtre temporelle, aucune mention de comportement au relist.

**Consensus forums devs (non-officiel)** : le compteur est **par listing** et **se remet à zéro quand le vendeur relist**.

**Hypothèse de travail Eurio** : on assume ce comportement et on combine avec `itemOriginDate` :
```
sales_per_year ≈ estimatedSoldQuantity / (now - itemOriginDate).years
```

Ça nous donne une **vitesse d'écoulement** bien plus utile qu'un compteur brut. Une variation à 3€ vendue 5× en 2 ans = prix crédible (signal fort). Une à 8€ vendue 0× sur 10 ans = prix fantôme (à pénaliser ou filtrer).

**À valider empiriquement** : tracker quelques listings sur plusieurs semaines pour confirmer le comportement au relist.

### 5.3 France et Allemagne dominent le marché

Constat chiffré sur `category_ids=32650` (Pièces euro) :

| Pays | Items actifs |
|---|---|
| France | 4 265 |
| Allemagne | 2 023 |
| Autres (catégorie fourre-tout) | 4 483 |
| Finlande | 969 |

**Implication produit** : les pièces FR/DE bénéficient d'un marché liquide → prix estimés plus fiables. Pour les pièces d'autres pays, il faudra un fallback (Numista cote) ou une marge d'incertitude plus large à afficher dans l'UI.

---

## 6. Stratégie de pipeline pour Eurio

### 6.1 Architecture du pipeline

Pour chaque pièce du catalogue Numista, lors d'un cron hebdomadaire (Supabase Edge Function) :

```
1. Recherche ciblée
   GET /item_summary/search
     q = "{denomination} euro {country} {year} {design_keywords}"
     category_ids = 32650
     aspect_filter = categoryId:32650,Année:{year},Pays:{country}
     filter = price:[{min}..{max}],priceCurrency:EUR
     limit = 50

2. Filtrage anti-bruit (client-side)
   - Rejeter les titres contenant : "lot", "coffret", "set", "BU", "proof", "épreuve"
   - Rejeter les prix < P5 ou > P95 du cluster
   - Trier par seller.feedbackScore décroissant

3. Enrichissement sélectif
   - Pour les top-10 listings filtrés : GET /item/{item_id}?fieldgroups=PRODUCT
   - Récupérer : estimatedSoldQuantity, itemOriginDate, aspects structurés
   - Si primaryItemGroup présent : GET /item/get_items_by_item_group pour déplier

4. Pondération et calcul
   sales_per_year = soldQuantity / max(age_years, 0.5)
   weight = log(1 + sales_per_year) × (seller_feedback_pct / 100)
   → P25 / P50 / P75 pondérés
   → stocker dans price_history avec source='ebay' et confidence=N/50
```

### 6.2 Budget API

| Étape | Appels par pièce |
|---|---|
| Search ciblé | 1 |
| getItem top-10 | 10 |
| Expand groups (moyenne) | ~2 |
| **Total** | **~13** |

Sur 5 000 appels/jour :
- Catalogue POC (10 pièces) → 130 appels → rafraîchissable **38× par jour** (largement suffisant)
- Catalogue phase 3 (200 pièces) → 2 600 appels → rafraîchissable **~2× par jour**
- Catalogue cible long terme (2000+ pièces) → saturation → demander l'Application Growth Check

### 6.3 Filtres anti-bruit — liste détaillée

**Patterns de titre à rejeter** (collector editions polluent le prix circulant standard) :
- `lot`, `coffret`, `set`, `série`, `collection complète`
- `BU` (Brilliant Uncirculated), `proof`, `épreuve`, `BE` (Belle Épreuve)
- `argent`, `or`, `silver` (versions métal précieux)
- `colorisée`, `color`
- `erreur de frappe`, `fauté`

**Filtres numériques** :
- P5 / P95 sur la distribution du cluster
- Prix < valeur faciale × 0.8 → rejet (pas réaliste)
- Prix > valeur faciale × 500 → rejet automatique (queue extrême)

---

## 7. Ce qu'on peut afficher dans Eurio

### 7.1 Coffre utilisateur — MVP

Pour chaque pièce dans la collection :

- **Prix de marché actuel** : médiane pondérée du cluster (P50)
- **Fourchette** : P25 – P75 affichée en secondaire
- **Indicateur de confiance** : nombre de samples + présence de ventes confirmées
- **Source et date** : "eBay, MAJ 2026-04-13"

**Total collection** : somme des P50 + fourchette totale P25/P75.

### 7.2 Courbe d'évolution par année

Grâce au `aspect_filter=Année:{...}`, on peut interroger l'API pour **chaque année historique d'une même pièce** et tracer une courbe de prix temps. Pour les pièces du catalogue qui existent dans plusieurs millésimes, ou pour tracker l'évolution d'une pièce unique via re-sampling hebdomadaire, on construit progressivement un historique.

**Visualisation** : graphique sparkline dans la page détail d'une pièce.

### 7.3 Indicateurs de demande marché

Exploitation directe des `categoryDistributions` et `aspectDistributions` du bloc `refinement` :

- **"Pièce recherchée"** : badge si le nombre de listings actifs dépasse un seuil (ex : >500)
- **"Marché liquide"** : badge pour les pièces FR/DE avec >1000 items actifs
- **"Marché étroit"** : warning pour les pièces avec <10 items actifs (incertitude sur le prix)

### 7.4 Projection à moyen terme — feature différenciante

**Hypothèse** : en accumulant l'historique mensuel des prix sur plusieurs mois, on peut calculer une tendance (régression linéaire simple) et projeter une valeur estimée dans 5–10 ans.

**Affichage utilisateur** :
> *"Ta collection vaut **218€** aujourd'hui. Basée sur l'évolution des prix et la demande constatée sur les marchés FR/DE, valeur estimée dans 10 ans : **~275€**."*

Cette feature dépend de :
1. Un historique accumulé (au moins 6–12 mois de snapshots hebdomadaires)
2. Un modèle simple et honnête (pas de promesses, afficher une marge d'incertitude)
3. Une clause UI explicite que c'est une **projection indicative, pas une garantie**

**Risque** : si on se trompe et que les prix baissent, effet déceptif. Mitigation : afficher toujours une fourchette pessimiste/optimiste et pas un chiffre unique.

---

## 8. Limitations et hypothèses à valider

| Limitation | Mitigation |
|---|---|
| Pas de prix de ventes terminées via l'API publique | Signal `estimatedSoldQuantity` + vitesse d'écoulement (hypothèse) |
| `estimatedSoldQuantity` non-documenté sur le comportement au relist | Hypothèse "reset au relist" + validation empirique sur 2-3 mois |
| `condition` quasi jamais renseigné par les vendeurs de pièces | Parser `conditionDescription` (texte libre) ou ignorer ce filtre |
| Pays autres que FR/DE ont un marché étroit | Fallback Numista cote + warning UI "faible liquidité" |
| Rate limit 5 000/jour non scalable au catalogue cible | Application Growth Check à demander avant phase 5 |
| Listings zombies (origine 2015, jamais vendus) pollution haute | Filtrage via `itemOriginDate` + `sales_per_year = 0` |

---

## 9. Scripts de test et artefacts

Tous les scripts de test sont dans `ml/` et lisent les credentials depuis `.env` :

| Script | Usage |
|---|---|
| `ml/test_ebay.py` | OAuth + recherche simple, 5 résultats affichés |
| `ml/test_ebay_item.py` | Détails d'un item spécifique par `itemId` |
| `ml/test_ebay_aggregate.py` | Agrégation paginée + rapport statistique |

Les réponses brutes de référence sont sauvegardées dans `ml/output/` (gitignored) et peuvent être régénérées à tout moment pour re-vérifier le comportement de l'API.

**Commande d'exemple** :
```bash
source ml/.venv/bin/activate
python ml/test_ebay_aggregate.py "2 euro commemorative" 200
```

---

## 10. Prochaines étapes

1. **Valider l'hypothèse `estimatedSoldQuantity`** — tracker 5 listings sur 2 semaines, observer le comportement du compteur au fil des relists.
2. **Construire le prototype de pipeline** (phase 3) sous forme de script Python one-shot qui prend une pièce du catalogue Numista et produit un P25/P50/P75 complet.
3. **Porter le pipeline en Supabase Edge Function** une fois la logique validée.
4. **Mettre à jour le PRD** pour remplacer toutes les mentions de "Finding API" par "Browse API + stratégie pondérée".
5. **Demander l'Application Growth Check** eBay avant d'atteindre 400 pièces actives au catalogue.
