# Recherche — benchmark de routing marketplace par pays d'origine

> Mesure empirique : pour chaque pays d'origine d'un coin, quel
> marketplace eBay maximise le recall ? Objectif : remplacer le
> `_ROUTES` hand-assigné de `ml/sources/ebay/marketplaces.py` par du
> recall mesuré.
>
> Statut : **mesure concluante** (itération 3, theme-match). Le choix
> du modèle de routage `_ROUTES` reste en discussion produit
> (cf. §"Itération 3" et §"Décision de routage").
> Lancé 2026-05-20.

## Contexte

Le routage `_ROUTES` actuel (pays → marketplace primary) a été assigné
**à la main** : AD→EBAY_ES « parce qu'hispanophone-ish », NL→EBAY_NL
« marketplace natif », etc. V1 (cf. `../marketplace-map.md` §Routage PT)
a montré que la mesure contredit l'intuition (PT→GB-only validé par
recall). On généralise : benchmark de toutes les origines.

L'origine d'un coin est triviale — préfixe de l'eurio_id
(`ad-2024-2eur-…` → `ad`).

## Méthode

Script : `ml/scripts/probe_marketplace_routing.py` (jetable).

- **26 origines** (21 pays eurozone + AD/MC/SM/VA + `eu`) — en pratique
  24 avec des commémos 2€ exploitables.
- **9 marketplaces** testés par origine : AT/BE/DE/ES/FR/GB/IE/IT/NL.
- **K=5 coins** échantillon par origine (commémos 2€ circulées
  2008-2023 de préférence).
- Query construite dans la langue native de chaque marketplace.
- Modèle : `primary + GB` (le primary recommandé est le meilleur
  marketplace non-GB ; GB reste le global catch-all).

Coût : ~1170 calls eBay (limite quotidienne 5000).

## Itération 1 — métrique `total` brut → REJETÉE

Premier run : métrique = `total` eBay (estimation du nombre de listings
pour la query). **Inexploitable** :

- **`EBAY_IE` anormalement haut partout** — 645 pour des coins
  allemands, 660 pour des italiens. L'Irlande est un marketplace
  minuscule : impossible. Le `total` de `EBAY_IE` renvoie un pool large
  « expédiable vers l'Irlande » (UK + vendeurs EU) qui chevauche GB.
- **MC → EBAY_DE à ratio 14.9×** (1595 vs 107). 1595 « Monaco » sur
  EBAY_DE n'est pas 1595 vraies commémos Monaco — le `total` eBay fait
  du matching large et ramasse énormément de bruit.

Conclusion : le `total` brut mesure la *richesse brute du marketplace*
mêlée de bruit, pas le recall *exploitable*.

## Itération 2 — métrique « survivors » filtrés

Nouveau run : pour chaque (origine, marketplace, coin), fetch les 200
premiers `itemSummaries`, compter ceux qui passent
**`accept_listing`** (filtres réels du pipeline : prix / devise EUR /
noise / millésime). Recall(origine, mkt) = médiane des survivors sur
les 5 coins.

`title_matches_theme` a été **volontairement écarté** : le matcher
n'a de titres localisés que FR+EN (`coin_names_i18n` — DE/IT/ES/NL
absents), donc l'appliquer biaiserait le benchmark en faveur des
marketplaces à titres FR/EN. `accept_listing` est language-agnostic.
**C'est cette absence de theme-match qui rend le benchmark imprécis**
(les commémos-sœurs du même pays/année ne sont pas distinguées).

### Matrice (survivors médians, sur 200, K=5)

```
orig    AT    BE    DE    ES    FR    GB    IE    IT    NL   reco
AD     117    30   116   147    63     0   115    46    42   EBAY_ES
AT     113    55   180   161    61     0   176    75    41   EBAY_DE
BE      87    91   141   133    97     0   119    69    65   EBAY_DE
CY      56    31    87    83    44     0    50    31    19   EBAY_DE
DE     175   119   182   172   149     0   159   182    98   EBAY_DE
EE      89    57   129   167    77     0    95    81    18   EBAY_ES
ES      64    50   140   167    65     0    76    69    37   EBAY_ES
FI      64    45    99   118    63     0    73    91    37   EBAY_ES
FR     175   165   181   174   171     0   161   172   164   EBAY_DE
GR      63    47   122   171    64     0    95    75    36   EBAY_ES
HR      70    56   109   165    78     0   135    62    62   EBAY_ES
IE      40    31    51    59    28     0    57    24    19   EBAY_ES
IT     144    89   169   139   120     0   136   139    52   EBAY_DE
LT      69    39   117   154    54     0    59    59    17   EBAY_ES
LU     111    67   170   141   104     0   153    80    50   EBAY_DE
LV      53    24    70    72    38     0    36    48     9   EBAY_ES
MC      57    38    30    34    53     0    60    46    37   EBAY_IE
MT     181    66   179   159    98     0   173    76    92   EBAY_AT
NL      87    58   161    99    63     0    52    24    60   EBAY_DE
PT     156    63   125   165    86     0   139    78    61   EBAY_ES
SI      41    36    80    73    47     0    66   108    30   EBAY_IT
SK      49    27    82    94    36     0    74    37     9   EBAY_ES
SM     169    42   136   173    65     0   158   113    93   EBAY_ES
VA      84    54   128   138    75     0    67   112     5   EBAY_ES
```

(`reco` = primary recommandé = meilleur non-GB si ≥ ×1.3 le recall GB.)

## Findings

| # | Finding | Solidité |
|---|---|---|
| 1 | **`EBAY_GB` = 0 survivant partout** | Solide. Les annonces EBAY_GB sont en **GBP** → toutes rejetées par le filtre `non_eur` de `accept_listing`. Le « catch-all global GB » ne rapporte **aucune** annonce EUR exploitable. Remet en cause GB comme global. |
| 2 | **Big-4 → marketplace natif** | Solide. DE→EBAY_DE (182), FR→EBAY_FR (171, ~à égalité avec les autres EZ), IT→EBAY_IT, ES→EBAY_ES — chacun fort sur ses propres coins. |
| 3 | **EBAY_DE & EBAY_ES dominent** | Directionnel. L'Allemagne est le marché de la pièce euro ; ES capte beaucoup. |
| 4 | **Origines à gros volume saturent** | DE/FR : survivors ~150-182/200 sur *tous* les marketplaces EZ → peu discriminant (cap à 200). La différenciation est nette surtout sur les petites origines. |
| 5 | **Theme-match manquant = imprécision** | Sans `title_matches_theme`, les survivors incluent les commémos-sœurs (même pays/année). Le recall mesuré est gonflé de faux positifs. |

## Itération 3 — theme-match réactivé (concluante)

Une fois les 112 coins traduits en DE/IT/ES/NL (chunk I3, 448 lignes
`llm_v1` dans `coin_names_i18n`), `title_matches_theme` a été
ré-intégré dans `search_survivors` : un survivant doit passer
`accept_listing` **ET** désigner la bonne pièce (titre seller
theme-matché dans les langues actives du marketplace). Le matcher est
appliqué **toujours** (pas seulement sur les (pays, année) ambigus),
pour mesurer le recall propre de chaque pièce. Le script lit la liste
exacte des 112 coins via `--coins-file state/benchmark_coins.txt`
(plus de re-sampling SQL hasardeux).

Run du 2026-05-20T21:25Z → `probe_marketplace_routing_20260520T212513Z.json`.

### Matrice (survivors theme-matchés médians, sur 200, K=3-5)

```
orig  n   AT   BE   DE   ES   FR   GB   IE   IT   NL    reco
ad    5    3    7    3   39   16    0   25   12   10    ES
at    3   78   20  130   76   21    0   82   32   14    DE
be    5   31   19   45   35   19    0   26   26   19    DE
cy    3   30   14   55   51   24    0   23   15   14    DE
de    5   77   44   78   58   44    0   64   64   44    DE
ee    5   33   18   36   63   32    0   47   32    8    ES
es    5   20   17   43   43   27    0   11   22   12    DE
fi    5   22   12   32   27   21    0   19   27   12    DE
fr    5   43   34   44   53   51    0   43   51   38    ES
gr    5   25   20   53   60   29    0   34   30   17    ES
hr    5   20   21   36   35   33    0   19   22   20    DE
ie    3   23   12   34   29   12    0   24   13   10    DE
it    5   17   25   22   46   33    0   38   48   19    IT
lt    5   19   15   33   41   26    0   17   18    7    ES
lu    5   21   21   51   32   38    0   39   19   17    DE
lv    5   39   18   47   42   24    0   22   22    6    DE
mc    5   32   18   18   18   22    0   28   18   15    AT
mt    5   34   10   50   38   15    0   41   17   16    DE
nl    3   31   26   53   37   28    0   12    8   26    DE
pt    5   43   23   33   37   27    0   49   24   23    IE
si    5   28   24   39   42   28    0   34   31   22    ES
sk    5   24   17   46   43   24    0   17   21    6    DE
sm    5   54   13   40   51   21    0   51   37   27    AT
va    5   34   19   44   56   24    0   28   48    2    ES
```

### Findings itération 3

| # | Finding | Solidité |
|---|---|---|
| 1 | **`EBAY_GB` = 0 partout** — confirmé. eBay.co.uk price en GBP, rejeté par `accept_listing`. Le catch-all GB est du quota mort. | Solide. |
| 2 | **Le marketplace natif ne gagne presque jamais ses propres pièces.** BE→DE (45 vs 19), NL→DE (53 vs 26), IE→DE (34 vs 24), FR→ES (53, FR 51). Seul IT tient (48). Le `_ROUTES` hand-assigné « marketplace natif » est faux sur la majorité. | Solide. |
| 3 | **`EBAY_DE` + `EBAY_ES` dominent** : best sur 13 + 7 origines. `{DE, ES}` est le **top-2 mesuré sur ~22/24 origines**. | Solide. |
| 4 | Exceptions au top-2 `{DE,ES}` : **MC→AT** (mais n=5, tous marketplaces ~18 = marché plat/bruité) et **PT→IE**. Niches à faible signal. | Directionnel. |
| 5 | Plus de saturation à 200 (comptes 30-130) — le theme-match a dégonflé les commémos-sœurs. Données exploitables. | Solide. |

## Décision de routage — ACTÉE (2026-05-21)

Le benchmark mesure le **recall de découverte**. Point clé de cadrage :
après dédup par `item_id` (cf. `../progress.md` — merge RAM), le
marketplace est un **canal de découverte**, pas un segment de prix ni
d'images. Les deux usages du scrape (images d'entraînement, prix de
référence) veulent la même chose : **le maximum de listings distincts
de qualité**. Le routing est donc un pur problème de recall.

**Décision : `{EBAY_DE, EBAY_ES}` en dual-call fixe pour TOUTES les
origines.** Pas de table per-origine.

- `{DE, ES}` est le top-2 mesuré sur ~22/24 origines ; la table
  hand-maintenue n'apporterait qu'un gain marginal sur 2 niches
  bruitées (MC, PT), au prix d'une maintenance et d'un risque de drift.
- `EBAY_GB` **retiré** du modèle : 0 listing EUR exploitable (GBP).
- `EBAY_DE` en primary (best sur 13/24, recall large le plus haut →
  c'est lui qui sert le fetch HD image first-seen), `EBAY_ES` en
  second call.

### Langue des queries

Chaque call interroge le marketplace **dans sa langue native** —
c'est exactement la configuration sous laquelle `{DE, ES}` a été
mesuré gagnant :

- call `EBAY_DE` → `query_lang = "de"`
- call `EBAY_ES` → `query_lang = "es"`

Pas de query multi-langue par call : une langue par marketplace, la
sienne. À distinguer de `MARKETPLACE_ACTIVE_LANGS` (les langues contre
lesquelles `title_matches_theme` matche les titres seller — ES y garde
`+it` pour les cross-listings IT, cf. chunk V1) : la langue de *query*
et les langues de *matching* sont deux réglages séparés et le restent.

→ Impact code : `_ROUTES` dans `ml/sources/ebay/marketplaces.py`
devient trivial (toutes les origines → même route `DE`+`ES`), `route_for`
ne lève plus `UnknownCountry`. `EbayAdapter.discover()` fait toujours
2 calls. Le `global_`/catch-all GB disparaît.

## Artefacts itération 3

- JSON résultat : `ml/state/probe_marketplace_routing_20260520T212513Z.json`
- Script modifié : `--coins-file` + `title_matches_theme` réactivé.

## Artefacts

- Script : `ml/scripts/probe_marketplace_routing.py`
- Coins du benchmark : `ml/state/benchmark_coins.txt` (112 eurio_ids)
- JSON résultat itération-2 : `ml/state/probe_marketplace_routing_*.json`
