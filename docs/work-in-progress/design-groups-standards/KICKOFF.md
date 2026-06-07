# Design groups — STANDARDS par avers (kickoff nouvelle session)

> **Chantier neuf**, à mener dans une session dédiée. Décidé en brainstorm avec
> le PO (2026-06-07). Pilote : **BE 2€ standard**. But : que scraper/entraîner un
> standard fonctionne enfin (aujourd'hui `be-2007` starve à 0 image, cf. §1).
>
> Pré-requis de lecture, dans l'ordre :
> - CE doc
> - `docs/design/_shared/design-groups.md` (le modèle existant — groupage par numista_id + joint issues ; **à ne pas casser**)
>
> **⚠️ Modèle réel à intégrer avant de coder** : `coins.design_group_id` est une **FK
> scalaire** (`schema.sql:935`, `ON DELETE SET NULL`) → *une pièce appartient à AU
> PLUS UN design_group*. Ce n'est **pas** une table pivot (la note mémoire
> « table pivot live » est périmée). Il n'y a donc pas « 3 axes qui coexistent » :
> il y a **une seule colonne, plusieurs stratégies de groupage sur des sous-ensembles
> disjoints de pièces**. Cf. invariant §5.1.
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
ATTENTION modèle : design_group_id est une FK SCALAIRE (1 pièce = 1 groupe), PAS un
pivot — ne grouper QUE les pièces où design_group_id IS NULL (invariant §5.1).
Décisions déjà actées : garder les Types + grouper (ne PAS fusionner), ZÉRO vision
LLM POUR DÉRIVER le groupage (déterministe depuis métadonnées), mais review vision
LLM A POSTERIORI par pays pour VALIDER (§4.7), pilote BE bout-en-bout d'abord puis
on évalue/itère avant d'élargir. Gate parseur derive-then-diff avant tout rollout (§4.6).
```

---

## 1. Le problème concret (reproduit en base ce jour)

Scraper `be-2007-2eur-standard-albert-ii-2nd-map-1st-type-1st-portrait` sur eBay
**réussit techniquement** (run `777ee4` : 1 appel → ~200 annonces « 2 euro belgique »
→ 11 raws → 4 crops) mais **0 image n'arrive jamais à be-2007** (0 sur toute son
histoire). Mécanique : be-2007 est un **standard**, donc `EbayAdapter._resolve_group`
le résout vers un groupe **pays-entier `year=None`** (`adapter.py:433`), et
`standards.py` attribue chaque annonce par **plage d'années → ère mono-coin**
(`standards.py` docstring l.11-14 : `[début_ère, début_ère_suivante−1]`).
L'ère de be-2007 = **[2007, 2007]** (une seule année).

> **⚠️ Distinguer câblage vs volume (à trancher en (1) du prompt).** L'attribution
> par plage **fonctionne déjà** : une annonce *2007 authentique* atteindrait be-2007.
> Donc le « 0 » est très probablement un **fait de volume** (marché eBay BE dominé par
> Philippe + commémos ; quasi aucun standard 1999-2007 en vente), pas un bug de
> wiring. **Preuve à expliciter** : où sont allés les 4 crops du run `777ee4` ? Si
> Philippe/commémos → diagnostic volume confirmé.
>
> **Conséquence sur l'attente** : regrouper be-1999+be-2007 corrige la **topologie de
> classes** (plus de singleton mono-année qui starve) mais **ne garantit pas le feed** :
> si le marché 1999-2007 est réellement maigre, `…-t1` restera sous-alimenté et devra
> être enrichi par d'autres sources (cf. `project_cohort_training_pipeline`). C'est
> pourquoi le critère de succès §6 vise un **volume cible**, pas « une image attribuée ».

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
| id (proposé) | designation | membres | plage (dérivée, *non stockée en dur*) |
|---|---|---|---|
| `be-2euro-albert-ii-t1` | BE 2€ Albert II (1er type) | be-1999, be-2007 | 1999-2007 |
| `be-2euro-albert-ii-t2` | BE 2€ Albert II (2e type) | be-2008, be-2009 | 2008-2013 |
| `be-2euro-philippe` | BE 2€ Philippe | be-2014 | 2014-… (`_ERA_OPEN_END`) |

> **Plages = dérivées à la volée** depuis `coin_mint_releases` des membres, **jamais
> figées dans la ligne `design_groups`** (sinon désync au prochain millésime). La borne
> haute de l'ère la plus récente réutilise `_ERA_OPEN_END` (= 9999, `standards.py:46`),
> pas un « 2014+ » en dur.

## 4. Impact technique (à cartographier avant de coder)

1. **Bootstrap** : `bootstrap_design_groups.py` ne couvre PAS ce cas (il groupe par
   `numista_id`, qui sépare sur la carte). → nouvelle étape « avers standard » :
   parse les standards par `(country, denom)`, dérive les groupes par
   `(monarque, Nème type)` depuis le slug/`design_description`, INSERT design_groups
   + UPDATE `coins.design_group_id`. **Propose → PO valide** (réversible, additif).
   - **Idempotent obligatoire** : ré-exécutable sans doublon. `INSERT … ON CONFLICT
     DO NOTHING` sur `design_groups.id` ; `UPDATE coins … WHERE design_group_id IS
     NULL` **uniquement** (cf. invariant §5.1 — ne jamais écraser un groupe existant).
   - **Le parseur est LE risque**, pas la SQL (cf. §4.6). Lignes non-parsables →
     **review**, jamais un groupe deviné en silence.
2. **eBay attribution** (`standards.py`) : remplacer l'ère mono-année par
   **l'appartenance à la plage du design_group** (`year_min..year_max` dérivés des
   `coin_mint_releases` des membres). Une annonce 2007 → groupe `…-t1` (1999-2007)
   → **be-2007 cesse de starve en tant que classe** : le groupe absorbe tout son
   intervalle (sous réserve qu'il y ait du volume, cf. §1).
   - **⚠️ Collision commémo élargie** : `standards.py` exclut les commémos par
     theme-match négatif (docstring l.15-18). En passant l'ère à la plage groupe
     (`…-t1` = **1999-2007**), la fenêtre 2007 recouvre désormais l'année du
     **Traité de Rome 2007** (commémo eurozone-wide). **Vérifier que l'exclusion
     négative s'applique AVANT l'attribution-par-plage**, sinon les commémos 2007
     fuient dans `…-t1`.
3. **`cohort_scope.py`** : `v_ebay_standard_groups` raisonne aujourd'hui par Type
   canonique ; vérifier qu'il s'aligne sur le design_group (1 recherche pays = N
   groupes avers, pas N Types).
4. **Label ML** : déjà `COALESCE(design_group_id, eurio_id)` (cf. design-groups.md
   §6.1) → les standards groupés deviennent automatiquement des classes ArcFace
   avers (be-1999+be-2007 = 1 classe, cohérent visuellement).
5. **Scan 2e passe** : un standard se résout en `(design_group, année)` ; l'année
   vient de l'OCR du millésime (l'avers seul ne la donne pas). Cohérent avec le
   modèle 2-passes de design-groups.md §6.2.
6. **Gate parseur (bloquant avant rollout)** : « déterministe depuis slug /
   `design_description`, zéro vision » repose sur un parseur de `(monarque, Nème type)`
   qui doit tenir sur **24 pays × langues** (slugs EN probables, `design_description`
   parfois localisé). Avant de généraliser : produire un **audit derive-then-diff**
   (groupes parsés vs table validée à la main) comme *gate*, pas un eyeball. Toute
   ligne non-parsable → file de review (pas de mis-group silencieux, cf. doctrine
   SQLite « aucun fallback silencieux »).
7. **Review vision a posteriori (QA, pas dérivation)** : une fois les design_groups
   d'un pays bootstrappés, lancer une **passe vision LLM par pays** qui regarde les
   avers groupés et confirme la cohérence visuelle (un groupe = un avers ; pas de
   pièce visuellement étrangère). C'est compatible avec « zéro vision » : la **vision
   ne dérive jamais le groupage** (déterministe depuis les métadonnées), elle ne fait
   que **valider** le résultat. Sortie = liste d'anomalies → review PO, pas un
   re-groupage automatique.

## 5. Invariants (ne PAS casser)

- **5.1 — `design_group_id` est SCALAIRE (une pièce = un seul groupe).** Le groupage
  avers ne touche QUE les pièces `WHERE design_group_id IS NULL`. **Assert avant
  UPDATE** : si une pièce visée a déjà un groupe (numista_id / joint issue), STOP et
  remonter — ne JAMAIS écraser. Les « axes » ne coexistent pas sur une même pièce :
  ce sont des stratégies disjointes sur la même colonne.
- Le groupage par **numista_id** et les **joint issues** existants restent intacts.
- Les `eurio_id` des Types et les `coin_mint_releases` (mapping année complet).
- Additif : `design_group_id` est nullable, rollback = détacher (cf. design-groups.md §7.3).
- eBay **user-owned** : ne JAMAIS auto-déclencher de scrape pour « tester » (quota PO).
- Doctrine `feedback_chunk_audit_flow` : livrer par chunks, audit PO chunk par chunk.

## 6. Critère de succès du pilote BE

**Pilote = BE 2€ bout-en-bout, on évalue ensemble, on itère, PUIS on élargit.**
Déroulé acté (PO 2026-06-07) :

1. Bootstrap des 3 design_groups BE + attribution patchée (chunks, audit PO).
2. **Review vision LLM BE** (§4.7) : confirme que les avers groupés sont cohérents.
3. Un scrape BE produit des images **attribuées au groupe `…-t1`**, visibles en base
   et dans le cockpit. ⚠️ **« une image » ne suffit pas** : viser un **volume cible**
   (~100/classe, cf. `project_cohort_training_pipeline`) — si le marché 1999-2007 est
   maigre (cf. §1), documenter le déficit et prévoir l'enrichissement, ne pas déclarer
   victoire sur 4 crops.
4. On évalue ensemble la qualité → on améliore → **une fois que ça marche bien**, on
   élargit aux autres pays.

**Scope réel de la généralisation** : pas « 24 autres pays » mais **pays ×
dénominations** — chaque dénomination à face nationale (1€, 50c…) a aussi un avers
monarque qui peut changer, à sa propre cadence. Le pilote reste **BE-2€** ; la règle
de slug semble transposable (échantillon eyeball : FR/DE/ES/NL/IT/GR/PT encodent le
design pareil — ES = Juan Carlos 1er/2e type / Felipe VI, NL = Beatrix /
Willem-Alexander…), **mais à valider par le gate parseur §4.6 + review vision §4.7
pays par pays**, pas par extrapolation.

## 7. Loose ends cockpit

Déplacés vers `docs/cohort-pipeline/COCKPIT-DEBUG-HANDOFF.md §6` (n'avaient pas leur
place dans ce kickoff). Y figurent : BUG-3 logs scrape restant, correction de la note
« dispersés sur les sœurs » → « réparti sur le groupe pays », et la décision commit/PR
de la branche `sources-jo-wikipedia`.
