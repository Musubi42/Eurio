# Probe — scrape Numista i18n (journal d'investigation)

> ✅ **PROBE EXÉCUTÉ — 2026-05-19** ✅
>
> Cette probe a livré deux findings majeurs qui ont fait pivoter
> toute la stratégie i18n :
>
> 1. **WAF Numista** kick après ~7 requêtes (challenge.php) → bypass
>    nécessaire (TOR).
> 2. **Numista non-canon hors FR/EN** — les sous-domaines `de.`, `it.`,
>    `es.`, etc. conservent le titre EN du coin (seuls FR et EN sont
>    vraiment traduits humainement).
>
> → Stratégie refondue, voir **`i18n-strategy.md`** + chunks
> exécutables (`i18n-scrape-numista.md`, `i18n-llm-translation.md`).
>
> Cette doc reste comme **journal d'investigation** (traçabilité du
> "pourquoi on a pivoté"). Le script `ml/scripts/probe_coin_names_i18n.py`
> et le JSON résultat `ml/state/probe_coin_names_i18n_20260519T164712Z.json`
> restent en place comme preuves empiriques.
>
> ---
>
> Phase de validation **avant** d'écrire le script de bootstrap final
> (`i18n-bootstrap-kickoff.md` §Chunk I1-B). Objectif : valider sur 5
> coins que le parser HTML extrait correctement les titres multilingues,
> sans toucher la DB ni la prod.
>
> Une fois cette probe verte → on lance l'implémentation I1 complète
> (DB writes, hook bootstrap, run 1h27 sur ~578 coins).
>
> Créé le 2026-05-19.

## Objectif

Spotter les PBs de parsing **avant** de payer 1h27 de scrape + une
écriture massive en DB. On veut répondre à :

1. Le `<h1>` est-il toujours présent et bien formé sur les 9 langues ?
2. Le `<span>` (sous-titre / thème) doit-il être inclus dans le titre,
   exclu, ou stocké séparément ? (kickoff dit "tout le h1" — confirmer
   sur cas réels)
3. Que se passe-t-il quand Numista n'a **pas traduit** un coin dans une
   langue donnée ? (Saint-Marin / Vatican en EL / RU notamment)
4. Les caractères non-latins (γυπαετός, бородач) sont-ils bien décodés
   UTF-8 ? Pas d'entités HTML résiduelles (`&amp;`, `&#x...`) ?
5. Les noms propres (Grace Kelly, Warschau, Schwerin) sont-ils traduits
   ou conservés tels quels ? (impact direct sur le matcher I2)

## Coins de test

| # | eurio_id | numista_id | Cas testé |
|---|---|---|---|
| 1 | `fr-1999-2eur-standard` | 104 | Trivial — titre court, pas de thème |
| 2 | `de-2020-2eur-50-years-since-the-kniefall-von-warschau` | 226447 | `<span>` complexe + thème historique. Probe manuel EN déjà OK. |
| 3 | `ad-2025-2eur-bearded-vulture` | 482937 | Translit non-triviale (DE=Bartgeier, EL=γυπαετός) — valide UTF-8 + traduction réelle |
| 4 | `mc-2007-2eur-25th-anniversary-of-the-death-of-grace-kelly` | 5036 | Proper noun — Numista traduit "Grace Kelly" ou pas ? Impact matcher |
| 5 | `sm-2005-2eur-world-year-of-physics-2005` | 5076 | Saint-Marin — test couverture incomplète (probable miss sur EL / RU / PT) |

5 coins × 9 langues = **45 fetches**. À 1 req/s = ~45 secondes de
probe. Suffisant pour itérer plusieurs fois si le parser a besoin
d'être patché.

## Script

Emplacement : `ml/scripts/probe_coin_names_i18n.py`

**Jetable** — supprimé après validation I1. Pas de tests unitaires, pas
d'intégration au `Taskfile.yml`, pas de hook. Le seul livrable utile
est le **JSON d'output** + les leçons qu'on en tire pour le parser
final.

### Args

```
python ml/scripts/probe_coin_names_i18n.py
    # → fetch les 5 coins hardcodés ci-dessus sur les 9 langues
    # → écrit ml/state/_probe/i18n-probe-<timestamp>.json
    # → log progress sur stdout

python ml/scripts/probe_coin_names_i18n.py --eurio <id1>,<id2>
    # → override la liste hardcodée (pour ré-tester un coin précis
    #   après un patch parser)

python ml/scripts/probe_coin_names_i18n.py --lang fr,en
    # → ne fetch que ces langues (utile pour debug ciblé)
```

### Comportement

- Throttle 1 req/s (même contrat que le script final, on valide aussi
  ça).
- User-Agent : `"Eurio probe (https://github.com/Musubi42/Eurio)"`.
- Follow redirects (301 court → canonique).
- Parse via `bs4` (`html.parser`, pas `lxml` — éviter une dep).
- **Aucune écriture DB**. Output JSON uniquement.
- 4xx (incl. 404 = coin pas traduit dans cette langue) → on enregistre
  `http_status: 404, raw_h1: null` dans le JSON, on continue.
- 5xx → backoff 2× / 4× / 8× puis abandon avec `error: "5xx after 3
  retries"`.

### Format de l'output JSON

```json
{
  "probed_at": "2026-05-19T14:30:00Z",
  "throttle_seconds": 1.0,
  "results": [
    {
      "eurio_id": "fr-1999-2eur-standard",
      "numista_id": 104,
      "langs": {
        "fr": {
          "url": "https://fr.numista.com/104",
          "http_status": 200,
          "elapsed_ms": 312,
          "raw_h1_html": "<h1>2 Euros</h1>",
          "h1_text": "2 Euros",
          "h1_span_text": null,
          "h1_main_text": "2 Euros"
        },
        "en": { ... },
        "de": { ... }
      }
    },
    ...
  ]
}
```

3 champs distincts pour le titre, c'est volontaire :

- `h1_text` : tout le texte du `<h1>` concaténé (= ce que le kickoff
  propose de stocker).
- `h1_main_text` : texte du `<h1>` **sans** le `<span>` (= "2 Euros"
  pour Warsaw).
- `h1_span_text` : contenu du `<span>` seul (= "Kneeling to Warsaw"
  pour Warsaw, `null` pour les coins sans thème).

On capture les 3 dans la probe pour décider après coup lequel garder
en DB. **Le choix est encore ouvert.** Le kickoff penche pour
`h1_text`, mais voir cas Warsaw on pourrait préférer stocker `main` +
`span` séparément (utile aussi pour la page coin details admin :
afficher "2 Euros" + "Kneeling to Warsaw" comme sous-titre).

## Critères de validation

Avant de passer à l'implémentation I1 "réelle", on doit pouvoir
répondre **OUI** à :

- [ ] Sur les 5 coins × 9 langues, le parser n'a **pas crashé**
  (toutes les entrées présentes dans le JSON, même si http_status=404).
- [ ] Pour chaque (coin, lang) avec `http_status=200`, `h1_text` est
  non-vide et UTF-8 propre (pas d'entités HTML résiduelles).
- [ ] Coin #3 (Bartgeier) : on voit bien `Bartgeier` en DE et
  `γυπαετός` (ou équivalent grec) en EL.
- [ ] Coin #5 (Saint-Marin) : on a au moins FR/EN/IT (Saint-Marin est
  italophone, Numista IT devrait avoir la fiche). Si EL/RU manquent,
  c'est OK — on documente le taux de couverture attendu.
- [ ] **Décision tranchée** : stocker `h1_text` (tout) ou
  `h1_main` + `h1_span` (séparés) dans `coin_names_i18n`.

Si un critère échoue → on patch le script de probe, on relance, on
itère. Tant qu'on n'est pas vert, **on n'écrit pas le script final**.

## Boucle d'itération anticipée

PBs probables à patcher :

| PB | Patch envisagé |
|---|---|
| `<h1>` avec attributs (class, id, style…) | `soup.find("h1")` ignore les attrs, OK par défaut |
| Entités HTML (`&amp;`, `&#39;`) | `soup.get_text()` les décode, OK par défaut |
| Plusieurs `<h1>` (peu probable) | Prendre le premier, logger si > 1 |
| `<span>` imbriqué dans le texte (pas en fin) | Capturer position relative dans `h1_main_text` |
| Redirect inter-langue (ex. `el.numista.com/104` → `en.numista.com/104` car non traduit) | Détecter via `response.url` final ≠ URL demandée → traiter comme "non traduit", `h1_text = null` |
| Cloudflare / WAF challenge | Inspecter status + body, documenter, voir si un header User-Agent plus banal aide |

## Ce que la probe NE fait PAS

- ❌ Pas d'écriture dans `coin_names_i18n` (ni aucune autre table).
- ❌ Pas de hook dans `bootstrap_coins_from_referential.py`.
- ❌ Pas de modification de schema (le `CHECK` lang reste inchangé
  pendant la probe).
- ❌ Pas de tests unitaires (script jetable).
- ❌ Pas d'intégration `Taskfile.yml`.

Tout ça arrive après, dans I1 "réel", une fois la probe verte.

## Après la probe

Une fois les critères validés et la décision `h1_text` vs `main+span`
prise, on revient sur `i18n-bootstrap-kickoff.md` et on exécute les
chunks I1-A à I1-E tels que prévus, **avec** :

- Le parser exact du script de probe recyclé en fonction pure
  `extract_title_from_html(html: str, lang: str) -> dict | None`.
- Le schéma final de `coin_names_i18n` confirmé (1 colonne `title` si
  on garde `h1_text`, ou 2 colonnes `denom` + `theme` si on sépare).

Et on planifie les **extensions hors I1** (kickoff originel ne les
couvre pas) :

- **I1-F** : sync `coin_names_i18n` SQLite → Supabase pour usage admin
  web (page coin details multilingue).
- **I1-G** : intégration dans `catalog_snapshot.json` pour usage app
  Android (affichage du nom de la pièce dans la langue de
  l'utilisateur).

Ces deux chunks méritent leur propre session de design (où on tranche
push vs pull, et comment évolue le format snapshot).

## Fichiers touchés (probe uniquement)

| Fichier | Nature |
|---|---|
| `ml/scripts/probe_coin_names_i18n.py` | **Nouveau** — jetable |
| `ml/state/_probe/i18n-probe-*.json` | Output (gitignore probablement) |

Rien d'autre. Aucun fichier de prod n'est touché par la probe.
