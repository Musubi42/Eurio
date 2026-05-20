# Marketplace map — correspondance pays → marketplace + langue

> Table de routage canonique. Source de vérité pour `EbayAdapter` au
> moment du discover : pour chaque coin, on regarde le pays d'origine et
> on en déduit (1) le marketplace primaire à interroger en plus de
> EBAY_GB et (2) la langue de la query à construire.
>
> Toute modif de cette table doit être justifiée par un probe (cf.
> `language-probe.md`) — pas d'instinct, pas d'à-peu-près.

## Marketplaces eBay disponibles (filtrés pour la zone euro)

| Marketplace ID | Langue native | Cat. coins (id 32650) | Statut |
|---|---|---|---|
| `EBAY_AT` | de | ok | dédié zone DACH |
| `EBAY_BE` | fr / nl | ok | dédié bilingue |
| `EBAY_DE` | de | ok | gros catalogue numismatique |
| `EBAY_ES` | es | ok | dédié |
| `EBAY_FR` | fr | ok | dédié, baseline historique |
| `EBAY_GB` | en | ok | **catch-all global V1** |
| `EBAY_IE` | en | ok | dédié, recouvre largement GB |
| `EBAY_IT` | it | ok | dédié, fort sur micro-États |
| `EBAY_NL` | nl | ok | dédié |

Pas d'EBAY_GR, EBAY_PT, EBAY_PL ciblé V1. EBAY_US exclu (cf. vision §"Anti-objectifs").

## Table de routage : `country` ISO2 → marketplaces appelés

### Pays avec marketplace eBay natif (8)

| `coins.country` | Marketplace natif | Langue query | Marketplaces appelés (V1) |
|---|---|---|---|
| `AT` | `EBAY_AT` | de | `AT` + `GB` |
| `BE` | `EBAY_BE` | fr (primaire, voir note) | `BE` + `GB` |
| `DE` | `EBAY_DE` | de | `DE` + `GB` |
| `ES` | `EBAY_ES` | es | `ES` + `GB` |
| `FR` | `EBAY_FR` | fr | `FR` + `GB` |
| `IE` | `EBAY_IE` | en | `IE` + `GB` (overlap fort attendu) |
| `IT` | `EBAY_IT` | it | `IT` + `GB` |
| `NL` | `EBAY_NL` | nl | `NL` + `GB` |

Note BE : EBAY_BE est bilingue FR/NL. **Décision V1 actée** : query en FR
uniquement (plus gros segment vendeur côté Wallonie/Bruxelles), matcher
theme tokens en FR+NL (aliases bilingues côté `MARKETPLACE_ACTIVE_LANGS`).

Alternative considérée et rejetée pour V1 : faire BE-FR + BE-NL (sacrifier
GB pour BE) — gain marginal estimé (la diaspora BE achète peu hors-BE),
casse l'invariant "GB toujours" (P1). À revisiter en V2 si KPI BE plafonne.

### Pays sans marketplace natif → fallback par langue principale (6)

| `coins.country` | Langue principale | Fallback marketplace | Justification |
|---|---|---|---|
| `AD` | ca / es (fr secondaire) | `EBAY_ES` | catalan ≈ espagnol pour le token-matching ; Andorre listé en ES sur les marketplaces ibériques |
| `LU` | fr / de / lb (admin = fr) | `EBAY_FR` | langue de travail dominante chez les sellers |
| `MC` | fr | `EBAY_FR` | enclave francophone |
| `PT` | pt | `EBAY_ES` *(provisoire)* | pas d'EBAY_PT, proximité linguistique ibérique > anglais — **à confirmer V1 probe**, défaut GB-only si non confirmé |
| `SM` | it | `EBAY_IT` | enclave italophone |
| `VA` | it (latin officiel) | `EBAY_IT` | enclave italophone |

### Pays sans marketplace natif ET sans langue couverte → GB only (11)

| `coins.country` | Langue principale | Marketplaces appelés |
|---|---|---|
| `BG` | bg | `GB` seul |
| `CY` | el / tr | `GB` seul |
| `EE` | et | `GB` seul |
| `FI` | fi | `GB` seul |
| `GR` | el | `GB` seul |
| `HR` | hr | `GB` seul |
| `LT` | lt | `GB` seul |
| `LV` | lv | `GB` seul |
| `MT` | mt / en | `GB` seul (en déjà couvert) |
| `SI` | sl | `GB` seul |
| `SK` | sk | `GB` seul |

### Cas spécial : `eu` (joint issues)

| `coins.country` | Marketplaces appelés |
|---|---|
| `eu` | `GB` seul |

Les commémos communes (eu) sont émises par les 21 pays en simultané. Tirer
sur 21 marketplaces n'est pas tenable côté quota. EBAY_GB catch-all suffit
pour les retrouver — ces pièces sont sur-représentées partout vu leur tirage.

## Récapitulatif — coût quota par batch

Pour un batch standard de 10 eurio_ids (D-21) :

| Profil pays | Discovery calls | Si presque toujours 2 |
|---|---:|---:|
| Best case (10 × GB-only, batch full joint+small countries) | 10 × 1 = 10 | — |
| Average (mix pays) | ~10 × 1.7 = 17 | — |
| Worst case (10 × pays avec natif) | 10 × 2 = 20 | 20 |

Plus les `item/{id}` HD : ~8 par eurio_id × 10 = 80 calls fixes. Total
discovery+HD pour 1 batch : **~100 calls** (cap 200 si on remplit). Le
budget 5000/jour permet 25-50 batches/jour. Convergence freshness en
quelques semaines pour ~466 commémos cibles.

## Implémentation — emplacement et signature

Cible : `ml/sources/ebay/marketplaces.py` (nouveau fichier).

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class MarketplaceRoute:
    """Marketplaces eBay à interroger pour un pays donné.

    `primary` = marketplace natif si applicable, sinon fallback langue.
    `global_` = EBAY_GB toujours présent (catch-all V1).
    Les deux sont distincts ; si primary == global_, primary vaut None
    (= 1 seul call au lieu de 2).
    """
    primary: str | None    # ex: "EBAY_DE", ou None si GB-only
    global_: str = "EBAY_GB"
    query_lang: str = "en"  # langue de la query primary; "en" si GB-only

def route_for(country: str) -> MarketplaceRoute:
    """Renvoie le couple (primary, global) pour le pays ISO2.

    `country` = `coins.country` (ISO2 majuscule ou 'eu' pour joint).
    Toujours non-None — `global_` au minimum.
    """
    ...
```

Le dict de routage est explicité dans le module, **pas une vue SQL** —
c'est de la config produit qui appartient au code, pas au schéma. On
veut la pouvoir grepper et modifier en review code.

### Routage PT — tranché V1 (2026-05-20)

`route_for("PT")` renvoie `MarketplaceRoute(primary=None)` → **GB-only**.

Le probe V1 (`scripts/probe_marketplace_languages.py`, sous-probe PT
recall) a mesuré, sur le coin `pt-2021-2eur-portuguese-presidency…`,
le `total` eBay : **EBAY_ES = 608, EBAY_GB = 362**, soit un ratio
**1.68×** (stable sur 5 runs consécutifs). Le critère documenté
exigeait ≥ ×2 pour justifier le 2ᵉ call EBAY_ES. 1.68 < 2.0 → PT
repasse en GB-only : un seul call discovery, pas de doublement du
coût quota pour un gain de recall modéré.

Décision réversible : si une mesure ultérieure (autre coin PT, autre
période) montre ≥ ×2, ré-router `PT` vers `EBAY_ES`.

### Convention `endpoint` vs colonne `marketplace`

Pour les rows `discovery_searches`, le champ `endpoint` reste générique
(`ebay.browse.search`) — il décrit **l'API appelée**, pas la cible. Le
marketplace vit dans **la colonne dédiée** `marketplace`. Pas de
duplication (`ebay.browse.search.de` est explicitement banni — sinon
double source de vérité et drift garanti dès qu'un refacto bouge l'un
sans l'autre).

## Évolution future

- **Probe trimestriel** : run `language-probe.md` une fois par trimestre
  pour repérer un changement de mix (eBay ferme/ouvre des marketplaces,
  les vendeurs changent de canal).
- **Ajout marketplaces V2** : si KPI recall plafonne après bascule,
  on peut ajouter EBAY_PL pour les listings d'Europe centrale, ou
  EBAY_US pour les commémos collector-grade exportées USA.
- **Personnalisation par seller** : pas dans ce chantier mais pourrait
  alimenter une heuristique "seller pro EU avec catalogue large → call
  son marketplace de listing principal".
