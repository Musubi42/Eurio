# Design groups — STANDARDS par avers (kickoff nouvelle session)

> **Chantier neuf**, à mener dans une session dédiée. Décidé en brainstorm avec
> le PO (2026-06-07). Pilote : **BE 2€ standard**. But : que scraper/entraîner un
> standard fonctionne enfin (aujourd'hui `be-2007` starve à 0 image, cf. §1).
>
> Pré-requis de lecture, dans l'ordre :
> - CE doc
> - `docs/design/_shared/design-groups.md` (le modèle existant — axe A par numista_id + axe B joint issues ; **à ne pas casser**)
> - mémoire : `project_referential_v2_design`, `project_arcface_design_group_label`,
>   `project_joint_issues_design_group`, `project_coin_variants`
> - code : `ml/sources/ebay/standards.py`, `ml/sources/cohort_scope.py`,
>   `ml/sources/ebay/adapter.py` (`_resolve_group`), `ml/bootstrap/bootstrap_design_groups.py`

---

## 0. PROMPT à coller pour démarrer

```
On modélise les design_groups pour les pièces STANDARD par AVERS (pilote BE 2€).
Lis d'abord docs/design-groups-standards/KICKOFF.md + docs/design/_shared/
design-groups.md + la mémoire (project_referential_v2_design,
project_arcface_design_group_label). NE CODE RIEN avant d'avoir : (1) confirmé en
base les Types BE standard + leurs années (coin_mint_releases) + leur design_group_id
actuel, (2) vérifié que le regroupement avers est dérivable du design_description /
slug (monarque + Nème type, IGNORE la carte), (3) cartographié l'impact sur
standards.py / cohort_scope.py. Restitue findings + plan par chunks (audit visuel
PO chunk par chunk, cf. feedback_chunk_audit_flow), demande arbitrages, PUIS code.
Décisions déjà actées : garder les Types + grouper (ne PAS fusionner), ZÉRO vision
LLM (le design est dans les métadonnées Numista), pilote BE bout-en-bout d'abord.
```

---

## 1. Le problème concret (reproduit en base ce jour)

Scraper `be-2007-2eur-standard-albert-ii-2nd-map-1st-type-1st-portrait` sur eBay
**réussit techniquement** (run `777ee4` : 1 appel → ~200 annonces « 2 euro belgique »
→ 11 raws → 4 crops) mais **0 image n'arrive jamais à be-2007** (0 sur toute son
histoire). Cause : be-2007 est un **standard**, donc `EbayAdapter._resolve_group`
le résout vers un groupe **pays-entier `year=None`** (`adapter.py:433`), et
`standards.py` attribue chaque annonce par **plage d'années → ère mono-coin**.
L'ère de be-2007 = **[2007, 2007]** (une seule année), donc elle ne capte presque
rien ; le rendement part sur les cibles à fort volume (Philippe) et les commémos.

## 2. La vérité du référentiel BE 2€ standard

| Type (`eurio_id`) | Avers | Carte (revers) | Années (`coin_mint_releases`) | `design_group_id` |
|---|---|---|---|---|
| be-1999-…-1st-map-1st-type-1st-portrait | Albert II **1er type** | 1ʳᵉ | **1999-2006** | NULL |
| be-2007-…-2nd-map-1st-type-1st-portrait | Albert II **1er type** *(identique)* | 2ᵉ | **2007** | NULL |
| be-2008-…-2nd-map-2nd-type-2nd-portrait | Albert II 2e type | 2ᵉ | 2008 | NULL |
| be-2009-…-2nd-map-2nd-type-1st-portrait | Albert II 2e type | 2ᵉ | **2009-2013** | NULL |
| be-2014-…-philippe | **Philippe** | 2ᵉ | **2014-2026** | NULL |

**Insight clé** : le « Nème **carte** » est le **REVERS** (face commune, partagée
par les 27 pays) → **non pertinent pour identifier la pièce**. C'est lui qui crée
le faux split : be-2007 a un **avers identique à be-1999**, il n'existe comme Type
séparé que parce que la carte a changé en 2007. Numista (et donc l'axe A actuel,
qui groupe par `numista_id`) **sépare sur la carte** → ne fusionne pas be-1999/be-2007.

## 3. La décision (actée PO 2026-06-07)

**Regrouper les standards par AVERS** (plus grossier que Numista) :

- **Règle de frontière = changement de monarque OU de « Nème type »** (= refonte
  majeure de l'avers). On **IGNORE** : la carte (revers), le « Nème portrait »
  (micro-variante), l'année. Déterministe depuis `design_description` / slug —
  **AUCUNE vision LLM** (le texte porte déjà l'info : « Albert II (2nd type) »,
  « Philippe », « Juan Carlos I », « Felipe VI »…).
- **On GARDE les Types existants** (`eurio_id`) tels quels — la carte *est* une
  distinction catalogue légitime, et les années restent mappées dans
  `coin_mint_releases`. On **ajoute juste** `design_group_id` au-dessus. On ne
  fusionne pas de Types, on ne crée pas d'eurio_id par an, on ne touche pas au
  système de variantes (`canonical_eurio_id` reste pour pattern/coloured/mule).

**Design_groups BE attendus (3) :**
| id (proposé) | designation | membres | plage |
|---|---|---|---|
| `be-2euro-albert-ii-t1` | BE 2€ Albert II (1er type) | be-1999, be-2007 | 1999-2007 |
| `be-2euro-albert-ii-t2` | BE 2€ Albert II (2e type) | be-2008, be-2009 | 2008-2013 |
| `be-2euro-philippe` | BE 2€ Philippe | be-2014 | 2014+ |

## 4. Impact technique (à cartographier avant de coder)

1. **Bootstrap** : `bootstrap_design_groups.py` ne couvre PAS ce cas (il groupe par
   `numista_id`, qui sépare sur la carte). → nouvelle étape « avers standard » :
   parse les standards par `(country, denom)`, dérive les groupes par
   `(monarque, Nème type)` depuis le slug/`design_description`, INSERT design_groups
   + UPDATE `coins.design_group_id`. **Propose → PO valide** (réversible, additif).
2. **eBay attribution** (`standards.py`) : remplacer l'ère mono-année par
   **l'appartenance à la plage du design_group** (`year_min..year_max` dérivés des
   `coin_mint_releases` des membres). Une annonce 2007 → groupe `…-t1` (1999-2007)
   → **be-2007 cesse de starve** : le groupe absorbe tout son intervalle.
3. **`cohort_scope.py`** : `v_ebay_standard_groups` raisonne aujourd'hui par Type
   canonique ; vérifier qu'il s'aligne sur le design_group (1 recherche pays = N
   groupes avers, pas N Types).
4. **Label ML** : déjà `COALESCE(design_group_id, eurio_id)` (cf. design-groups.md
   §6.1) → les standards groupés deviennent automatiquement des classes ArcFace
   avers (be-1999+be-2007 = 1 classe, cohérent visuellement).
5. **Scan 2e passe** : un standard se résout en `(design_group, année)` ; l'année
   vient de l'OCR du millésime (l'avers seul ne la donne pas). Cohérent avec le
   modèle 2-passes de design-groups.md §6.2.

## 5. Invariants (ne PAS casser)

- L'**axe A** (4 groupes par numista_id) et l'**axe B** (5 joint issues) existants.
- Les `eurio_id` des Types et les `coin_mint_releases` (mapping année complet).
- Additif : `design_group_id` est nullable, rollback = détacher (cf. design-groups.md §7.3).
- eBay **user-owned** : ne JAMAIS auto-déclencher de scrape pour « tester » (quota PO).
- Doctrine `feedback_chunk_audit_flow` : livrer par chunks, audit PO chunk par chunk.

## 6. Critère de succès du pilote BE

Après bootstrap + patch attribution : **un scrape BE produit des images attribuées
au groupe `…-t1`** (donc à l'intervalle ≤2007, ex be-2007), visible en base et dans
le cockpit. Puis seulement : généraliser aux 24 autres pays (même règle de slug —
échantillon vérifié : FR/DE/ES/NL/IT/GR/PT encodent le design pareil ; ES = Juan
Carlos 1er type / 2e type / Felipe VI, NL = Beatrix / Willem-Alexander, etc.).

## 7. Reste de la session cockpit (loose ends à ne pas perdre)

Travaux livrés cette session (branche `sources-jo-wikipedia`, **pas encore commités**) :
- BUG-1 recrop subprocess + reaper PID (livré, vérifié).
- BUG-2 libellés be-2007 cohérents (livré).
- BUG-3 cœur : scrape→cohort_jobs réconcilié + trace in-row + runs failed (livré).
- **À faire** : BUG-3 sub-part **logs scrape** (`source_runs.log_path` vide + endpoint tail) ;
  corriger la note BUG-3 « dispersés sur les sœurs » → « réparti sur le groupe pays »
  (imprécise pour un standard, cf. ce chantier). Décider commit/PR de la branche.
