# Kickoff — Chunk 6 : comparateur `vs_target` + filtre `text_contradict_*`

> Brief auto-suffisant pour reprendre le chunk 6 dans une session
> nouvelle. Doit être lisible sans charger la conversation
> précédente.

## Pré-lecture obligatoire

1. [`vision.md`](./vision.md) — surtout §"Découpage du chantier" et
   les principes P1-P5.
2. [`progress.md`](./progress.md) — §"Chunk 4" (extracteur) et
   §"Chunk 5" (persistance + backfill réel).
3. `ml/sources/text_signals/extractor.py` — la dataclass
   `ListingTextSignals` + le contrat de `extract_listing_text_signals`.
4. `ml/sources/_base/steps/text_signal.py` — le step pipeline
   actuel (sans décision).

## Contexte courant (état du code au démarrage)

Les chunks 0-5 sont livrés. Concrètement :

- L'extracteur `ListingTextSignals` est pur, testé, déployé. 783
  source_images backfillés, 70 % en `coverage=rich`.
- La table `listing_text_signals` (PK `source_image_id`) contient
  une row par listing avec `countries`, `years`, `denominations`,
  `theme_tokens`, `rejected_markers`, `is_lot`, `coverage`,
  `matched`.
- Le step pipeline `text_signal` tourne entre `persist` et
  `download`. Position **stratégique** pour le chunk 6 : on peut
  rejeter un listing **avant** son download → économie de quota
  CDN + de cycles de detect_crop.
- Le panel front "Listings rejetés pré-ingestion" affiche déjà les
  rejets `accept_listing` + `theme_mismatch`. Le chunk 6 ajoute des
  `reason='text_contradict_*'` qui s'y intégreront sans nouveau code
  front.
- Le panel review front "Suggestions Dino" existe (chunk 3). Le
  panel "Texte" arrivera au chunk 7 (pas dans ce kickoff).

## Périmètre du chunk 6

**Ce qui est dans le scope** :

1. Une fonction pure `compare_to_target(signals, target)` qui prend
   un `ListingTextSignals` + l'identité du target_eurio_id (country,
   year, face_value, theme tokens), et retourne un verdict typé.
2. Câblage dans le step `text_signal` (ou un nouveau step
   `text_decide` placé juste après) qui, **uniquement** sur
   verdict = `contradict`, écrit dans `discarded_listings` avec
   `reason='text_contradict_<axe>'` et marque le source_image
   comme rejeté.
3. Tests unitaires + intégration sur le backfill 783 (combien de
   `contradict` détectés, échantillon manuel pour audit).
4. Endpoint API enrichi qui retourne le verdict joint (read-only).
5. Update progress.md avec mesures réelles.

**Hors scope** (chunks suivants) :

- Pas de panel front "Texte" dans le drawer review (chunk 7).
- Pas de combinaison Dino × texte (chunk 8).
- Pas d'auto-accept (chunk 8).
- Pas de rollback tooling page Coin (chunk 9).

## Design proposé du comparateur

### Identité du target nécessaire pour la comparaison

`target_eurio_id` permet d'aller chercher dans la table `coins` :
- `country` (ISO2 — `FR`, `DE`, …)
- `year` (entier)
- `face_value` (réel, 2.0 pour les 2€ commémo)
- `theme` (texte Numista canonique, en anglais)
- `numista_id` (référence)

Le slug de l'eurio_id porte aussi des tokens utiles
(`fr-2014-2eur-100-years-since-the-start-of-world-war-i`). On peut
réutiliser `_theme_keywords` de `ml/sources/ebay/queries.py` pour
extraire des tokens canoniques du target.

### Verdict

```python
from typing import Literal

VsTargetVerdict = Literal[
    "convergent",   # tous les signaux présents pointent target
    "partial",      # 1-2 signaux ok, le reste muet
    "absent",       # rien d'exploitable côté texte (≠ contradiction)
    "contradict",   # ≥1 signal ferme contredit target
]

@dataclass(frozen=True)
class VsTargetComparison:
    verdict: VsTargetVerdict
    contradictions: tuple[str, ...]   # axes en désaccord
    convergences: tuple[str, ...]     # axes en accord
    target_country: str
    target_year: int
    target_face_value: float

def compare_to_target(
    signals: ListingTextSignals,
    target: TargetIdentity,
) -> VsTargetComparison:
    ...
```

### Logique par axe

| Axe | Convergent | Contradict | Absent |
|---|---|---|---|
| **Country** | `target.country in signals.countries` | `signals.countries` non vide ET target absent | `signals.countries` vide |
| **Year** | `target.year in signals.years` | `signals.years` non vide ET target absent ET pas de plage englobant target | idem |
| **Face value** | `target.face_value in signals.denominations` | denoms non vide ET target absent | denoms vide |
| **Themes** | (option V2) ≥1 token thème du target présent | (V2) | (V1) |

**Important — plages d'années** : un titre type `2005-2025` est
courant. Si `target.year=2014`, ce n'est pas une contradiction
(l'année cible est dans la plage). Heuristique : extraire les bornes
min/max de `signals.years` ; si `target.year` est entre les deux,
c'est convergent (faible) plutôt que contradict.

**Multi-country** : si `signals.countries = {FR, IT}` et
`target.country = FR`, ce n'est pas contradict — c'est convergent
faible (le target est mentionné, c'est juste un lot transfrontalier).
On laisse `is_lot` séparer ces cas.

### Verdict global (matrice)

```python
n_convergent = len(convergences)
n_contradict = len(contradictions)
total_signals_present = sum([
    bool(signals.countries),
    bool(signals.years),
    bool(signals.denominations),
])

if n_contradict >= 1:
    verdict = "contradict"
elif total_signals_present == 0:
    verdict = "absent"
elif n_convergent == total_signals_present:
    verdict = "convergent"
else:
    verdict = "partial"
```

Soft : un seul axe en contradict suffit pour basculer en
"contradict". C'est strict mais cohérent avec P3 (auto-accept seulement
quand FP rare ET réversible).

### Cas border à tester explicitement

1. Target `fr-2014-2eur-...`, titre `2 euros France 2014` →
   convergent (3/3).
2. Target `fr-2014-2eur-...`, titre `BELGIQUE 2 EURO 2014
   commémorative` → contradict (country).
3. Target `fr-2014-2eur-...`, titre `2 euros 2014 commémorative
   guerre` → partial (country absent, year+denom OK).
4. Target `fr-2014-2eur-...`, titre `BELGIQUE - 2 EUROS 2005-2025
   Toutes Années` → 2014 dans la plage → convergent faible
   country=FALSE → contradict (BE détecté).
5. Target `at-2018-2eur-100-years-republic`, titre `Lot 3 pièces
   AUTRICHE 2018 100 ans République` → convergent + is_lot. Pas
   contradict, mais le chunk 8 ne devra **pas** auto-accepter à cause
   du is_lot.
6. Titre vide ou super court (`belle pièce`) → absent.

### Filtre dur dans la pipeline

Dans le step `text_signal` (ou nouveau `text_decide`), après
extraction et persistance des signaux :

```python
target = load_target_identity(conn, source_image.target_eurio_id)
if target is None:
    # Pas de target_eurio_id sur ce source_image : on ne peut pas
    # comparer. On laisse passer.
    continue

cmp = compare_to_target(signals, target)
if cmp.verdict == "contradict":
    record_discarded_listing(
        conn,
        run_id=run.run_id,
        source=source_id,
        source_ref=source_image.source_ref,
        target_eurio_id=source_image.target_eurio_id,
        reason=f"text_contradict_{cmp.contradictions[0]}",  # ou agrégé
        title=source_image.listing_title,
        raw_payload={
            "contradictions": list(cmp.contradictions),
            "convergences": list(cmp.convergences),
            "signals": signals.matched,
            "target": {
                "country": target.country,
                "year": target.year,
                "face_value": target.face_value,
            },
        },
    )
    # Marquer le source_image comme rejeté pour qu'il ne descende
    # pas dans la pipeline (ne pas download)
    set_source_image_rejected(conn, source_image.id, reason=...)
```

**Question ouverte** : faut-il un nouveau status sur `source_images`
(`crop_status='text_rejected'` ?) ou retirer du
`source_image_ids` map qui descend dans `download` ? Mon vote :
ajouter `route_decision='rejected_text'` sur source_images +
filtrer dans `run_download` les sources_images avec
`route_decision='rejected_text'`. Cohérent avec le pattern existant.

### Persistance du verdict (additif sur listing_text_signals)

Soit on stocke le verdict dans `listing_text_signals` directement
(nouvelles colonnes `vs_target_verdict`, `contradictions_json`,
`convergences_json`), soit on le recalcule à la volée à chaque fois
qu'on a besoin (front, debug). Avantage de stocker : on peut filtrer
en SQL (`WHERE vs_target_verdict='contradict'`) sans recharger la
target. **Mon vote** : stocker, via `_ensure_column` migration. Trois
colonnes additives, pas cher.

## API

Étendre `TextSignalsResponse` du chunk 5 avec :

```python
class TextSignalsResponse(BaseModel):
    # ... champs existants
    vs_target: VsTargetVerdict | None = None
    contradictions: list[str] = []
    convergences: list[str] = []
```

Pas de nouvel endpoint nécessaire — c'est juste plus de données
dans la réponse existante.

## Tests à écrire

`ml/tests/test_text_comparator.py` :

1. `test_convergent_when_all_signals_match` — target fr/2014/2.0,
   signals fr/2014/2.0 → convergent.
2. `test_contradict_on_country_mismatch`
3. `test_contradict_on_year_mismatch`
4. `test_contradict_on_face_value_mismatch`
5. `test_partial_when_country_absent_but_others_match`
6. `test_absent_on_empty_signals`
7. `test_year_range_envelops_target_is_not_contradict` — titre
   "2005-2025", target=2014 → year axe convergent.
8. `test_multi_country_with_target_present_not_contradict`
9. `test_lot_with_target_country_is_convergent_not_contradict`

`ml/tests/test_text_signal_step.py` étendu :

10. `test_step_writes_discarded_on_contradict` — feed un titre BE
    avec target FR → vérifier la row dans discarded_listings avec
    reason="text_contradict_country".
11. `test_step_does_not_discard_on_convergent`
12. `test_step_idempotent_on_already_discarded`

## Audit visuel attendu

Après backfill V2 (re-tourner le step avec décision activée) :

```bash
# Distribution des verdicts sur 783 listings
sqlite3 ml/state/training.db "
  SELECT vs_target_verdict, COUNT(*) AS n
    FROM listing_text_signals
   GROUP BY vs_target_verdict ORDER BY n DESC;"

# Combien rejetés en text_contradict_*
sqlite3 ml/state/training.db "
  SELECT reason, COUNT(*) AS n
    FROM discarded_listings
   WHERE reason LIKE 'text_contradict_%'
   GROUP BY reason ORDER BY n DESC;"

# Échantillon manuel : 20 contradictions pour audit
sqlite3 ml/state/training.db "
  SELECT lts.contradictions_json, si.listing_title, si.target_eurio_id
    FROM listing_text_signals lts
    JOIN source_images si ON si.id = lts.source_image_id
   WHERE lts.vs_target_verdict = 'contradict'
   ORDER BY RANDOM() LIMIT 20;"
```

Cible attendue (intuition à confirmer) :
- ~70 % `convergent` (les listings dont l'extraction confirme le
  target, candidats prime pour auto-accept au chunk 8)
- ~10 % `partial` (2 axes sur 3, restent en review humaine)
- ~10 % `absent` (titre trop pauvre, restent en review humaine)
- ~10 % `contradict` (vrais mismatches, rejetés pré-download)

Si on dépasse 20 % `contradict`, c'est probablement qu'on est trop
strict — relire les contradictions échantillonnées et envisager une
règle plus tolérante (ex. ne contradict que sur 2 axes simultanés).

## Plan d'attaque suggéré (par chunks audit-par-chunk)

1. **6.a** Comparateur pur (`compare_to_target` + tests unitaires
   sans I/O). Audit : on tape la fonction sur les 783 listings
   backfillés en mémoire et on regarde la distribution.
2. **6.b** Persistance du verdict (3 colonnes additives) +
   re-backfill avec verdict. Audit : queries SQL sur la
   distribution.
3. **6.c** Câblage filtre dur dans le step pipeline +
   `discarded_listings(reason='text_contradict_*')` +
   `route_decision='rejected_text'` sur source_images. Audit : panel
   front "Listings rejetés" doit afficher les nouvelles raisons,
   tests pipeline.
4. **6.d** Endpoint API enrichi avec verdict.

Soit on fait 6.a + 6.b en un seul chunk (recommandé, c'est lié), soit
on les sépare. 6.c et 6.d devraient rester séparés (audit visuel
front nécessaire pour 6.c).

## Hors-scope rappels

- ❌ Pas de modification du Dino — le verifier reste indépendant.
- ❌ Pas d'auto-accept — chunk 8.
- ❌ Pas d'utilisation des `theme_tokens` (V1) — reportée à V2 si
  nécessaire après calibration.
- ❌ Pas de feedback sur le filter `accept_listing` amont — laisser
  les filtres existants en place.

## Mémoires liées

- `feedback_dino_thresholds` — Dino inflate sur euros (informationnel,
  ne s'applique pas directement au texte).
- `feedback_chunk_audit_flow` — chunks 30min-3h, livrer + attendre
  rétro. **Important** : ne pas enchaîner les sous-chunks 6.a-6.d
  sans audit visuel intermédiaire.
- `feedback_no_debt` — pas de shortcut. Si le verdict semble trop
  strict, on ajuste explicitement les règles plutôt que d'ajouter
  des cas spéciaux.
