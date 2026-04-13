# Phase 2C.5 — Review tool (web UI + BCE images)

> Outil interactif pour résoudre les escalades Stage 5 de la pipeline de matching.
> Date : 2026-04-13.
> Doc parent : [`phase-2c-referential.md`](../phases/phase-2c-referential.md) §2C.5, [`data-referential-architecture.md`](./data-referential-architecture.md) §5.

---

## TL;DR

Un CLI interactif est **insuffisant** pour trancher entre deux commémos : le texte seul force l'humain à refaire exactement le travail que l'algo a raté. La vraie décision est **visuelle** : voir l'image du produit source à côté de l'image canonique de chaque candidat.

Le tool livré est donc un **serveur web local stdlib** qui affiche pour chaque groupe :
- l'image du produit source (depuis le snapshot lmdlp/mdp)
- les images canoniques BCE des candidats (scrapées depuis `comm_{year}.en.html`)
- un résumé d'enrichissement live par candidat (variantes lmdlp/mdp/ebay, prix P50, mintage)
- des raccourcis clavier pour enchaîner vite

Pour rendre ça possible, **Phase 2C.5 a été scindée en 2** : 2C.5b.1-5b.2 (scraper BCE pour les images canoniques) et 2C.5b.3-5b.5 (refactor core + serveur web + tests).

| Métrique | Valeur |
|---|---|
| Commémoratives totales | 517 |
| Avec image canonique BCE | **419 (81%)** |
| Avec `design_description` BCE | 505 (98%) |
| Années BCE couvertes | 2004-2025 (22 années) |
| Items en queue | 204 |
| Groupes uniques (décisions humaines) | **128** |
| Groupes avec toutes leurs candidates imagées | 56 |
| Groupes avec au moins 1 candidate imagée | 114 (89%) |
| Groupes sans aucune image canonique | 14 (11% — 2026 ou gap BCE) |
| Tests unit | **79 verts** |

---

## 1. Pourquoi un CLI texte-only ne suffit pas

Le cas que j'ai vécu en smoke test est révélateur :

```
Group [1/128]  lmdlp  AD/2018  theme=70-ans-droits-de-lhomme
Source: "2 euros Andorre 2018 – 70 ans Droits de l'Homme BU FDC Coincard"

Candidates:
  [1] ad-2018-2eur-25th-anniversary-of-the-andorran-constitution
      theme: 25th anniversary of the Andorran Constitution
  [2] ad-2018-2eur-70th-anniversary-of-the-universal-declaration-of-human
      theme: 70th anniversary of the Universal Declaration of Human Rights
```

Pour un humain qui connaît les pièces, la réponse est évidente : **[2]**, parce que "droits de l'Homme" et "Universal Declaration of Human Rights" c'est la même chose.

Mais pour un humain qui n'est **pas** numismate (= Raphaël + moi + 99% des users futurs d'un tool interne), c'est pas si évident. "25 ans de la Constitution" pourrait plausiblement mentionner des droits humains. La bonne manière de trancher, c'est de voir la pièce.

Si l'algorithme (Stage 3 fuzzy slug) a déjà échoué sur cette décision, refaire la même comparaison textuelle côté humain n'apporte aucune nouvelle information. Le signal manquant, c'est **visuel**.

---

## 2. Sourcing des images canoniques : BCE, pas Wikipedia

### Wikipedia n'a pas d'images de commémoratives

Vérifié empiriquement sur le snapshot `wikipedia_commemo_2026-04-13.html` : la wikitable des commémoratives contient :
- `cell[0]` : lien EUR-Lex vers le code JOUE (précieux pour une autre utilité)
- `cell[1]` : drapeau du pays (pas la pièce)
- `cell[2]` : feature text
- `cell[3]` : volume d'émission
- `cell[4]` : date d'émission

Aucun tag `<img>` pointant vers la pièce. Wikipedia a certes des images de commémoratives sur d'autres pages (certaines pages per-country, des galeries thématiques), mais pas de manière exhaustive ni structurée.

### BCE a tout ce qu'il faut

La page `https://www.ecb.europa.eu/euro/coins/comm/html/comm_{year}.en.html` structure chaque pièce comme :

```html
<img src="comm_2018/comm_2018_andorra_70yrs_declhumrights.jpg">
<h3>Andorra</h3>
<p>Feature: 70 years of the Universal Declaration of Human Rights</p>
<p>Description: The design of the coin depicts seven staircases...</p>
<p>Issuing volume: 75 000 coins</p>
<p>Issuing date: November 2018</p>
```

Image **précède** le `h3` (important pour le parsing). Filename descriptif, JPG haute qualité, ~500×500.

### Bonus : descriptions officielles BCE

Les paragraphes `Description:` sont **le texte officiel** publié par la BCE en anglais — autrement plus descriptif que le slug Wikipedia. Ils sont maintenant dans `identity.design_description` pour 505/517 commémoratives (98%).

---

## 3. `ml/scrape_bce_images.py`

Un scraper dédié (~230 lignes) qui :

1. **Boucle** sur les années 2004 → current_year
2. **Fetch** `comm_{year}.en.html`, 404 gracieux (2026 pas encore publié)
3. **Snapshot** immuable dans `ml/datasets/sources/bce_comm_{year}_YYYY-MM-DD.html`
4. **Parse** : pour chaque `<h3>` country → `find_previous('img')` pour l'image, puis `p.Feature/Description/Issuing_volume/Issuing_date` en walking sibling
5. **Matche** chaque coin parsé contre le référentiel via le shared `matching.match()` (Stages 2/3)
6. **Enrichit** `entry.images[]` (additif, dedupe par URL absolue)
7. **Enrichit** `entry.identity.design_description` si vide
8. **Marque** `provenance.sources_used += ["bce_comm"]`

### Résultats du run

```
Years covered: 2004-2025 (22 années)
BCE coins parsed total: 493
Match stages: {'2': 146, '3': 275, '5': 72}  → 85% match auto
Images added: 421
```

Les 72 escalades Stage 5 restent en suspens (pas poussées en review queue — ce sont des paraphrases différentes entre le slug Wikipedia et la feature BCE, e.g. Wikipedia dit "Treaty of Rome" et BCE dit "50 years of the signing of the Treaty of Rome"). Pour le moment on accepte la couverture 81% — le reste serait résolu par une future passe de cross-matching BCE ↔ Wikipedia.

### Coverage réelle sur la queue

Sur les 128 groupes de la review queue (204 items lmdlp) :

| Cas | Groupes | % |
|---|---|---|
| Tous les candidates ont une image BCE | 56 | 44% |
| Au moins 1 candidate a une image | 58 | 45% |
| Aucune image sur les candidates | 14 | 11% |
| **Au moins partiellement imagé** | **114** | **89%** |

Les 11% sans image sont essentiellement des cas 2026 (BCE n'a pas encore publié 2026). Pour ces groupes, le serveur affiche un placeholder "no image" sur les candidates et on retombe sur le texte — dégradation acceptée.

---

## 4. Refactor : `review_queue.py` → `review_core.py`

Suite à la décision *"déprécier la CLI en faveur du serveur"*, l'ancien `ml/review_queue.py` est **supprimé**. La logique pure (pas d'I/O interactif) part dans `ml/review_core.py` :

```python
# review_core.py — NO interactive parts, pure helpers
@dataclass
class ReviewGroup:
    source, country, year, theme_slug, items, candidates
    @property key, sample_item

def build_groups(queue, *, source_filter=None, only_unresolved=True) -> list[ReviewGroup]
def mark_group_resolved(group, action, value)
def enrich_lmdlp(referential, eurio_id, items, snapshot) -> int
def candidate_preview(entry) -> dict      # NEW : enrichment summary for the UI

# Persistence
def load_queue() / save_queue()
def load_resolutions() / save_resolutions()
def append_matching_log(records)
def load_source_snapshot(source) -> list[dict]

SOURCE_ENRICHERS: dict[str, enricher_fn]   # dispatch table
```

Tests déplacés : `TestReviewQueue` importe maintenant depuis `review_core` sans modification d'API (l'import a changé mais pas le reste). **79 tests verts, aucune régression.**

---

## 5. `ml/review_queue_server.py`

Serveur web local stdlib (~400 lignes). Décisions architecturales :

| Choix | Raison |
|---|---|
| `http.server.HTTPServer` stdlib | Zéro nouvelle dep. Suffisant pour localhost single-user. |
| String templates Python f-strings | Pas de jinja. 400 lignes totales incluses CSS + HTML. |
| State in-memory mutable | Single-threaded server, pas de contention. `state.persist()` après chaque mutation. |
| Images servies directement par le CDN source | Pas de proxy. Le browser fetch lmdlp/bce avec ses propres headers. |
| Keyboard JS inline | 1-9 pick, `s` skip, `n` no_match, `q` quit. Pas de framework JS. |
| Dark theme | Parce que c'est mieux pour travailler 30 min sur des images. |

### Flow utilisateur

```
python ml/review_queue_server.py
  → [server] listening on http://127.0.0.1:8765/review/0
  → [server] 128 unresolved groups to review
  → [browser] auto-ouvert sur http://127.0.0.1:8765/review/0

Page /review/<idx> :
  GET → render group (source + candidates)
  POST /review/<idx>/action (action=pick|skip|no_match, candidate_idx=N)
       → apply → persist → 302 → next group
  POST /quit → persist → 302 → done page → server shuts down
```

### Layout de la page

```
┌──────────────────────────────────────────────────────┐
│ Eurio review | Group 3/128 · 200 items | stats       │
├──────────────────────────────────────────────────────┤
│ SOURCE PRODUCT · lmdlp · IT/2026 · 3 variants        │
│ ┌────────┐ 2 euros Italie 2026 – Carlo Collodi       │
│ │ image  │ Pinocchio UNC                             │
│ │ source │ theme_slug: carlo-collodi-pinocchio       │
│ │ 260px  │ price: 4.50€ · qualité: UNC · mintage: —  │
│ └────────┘ view on lmdlp ↗                           │
├──────────────────────────────────────────────────────┤
│ CANONICAL CANDIDATES (2)                             │
│                                                      │
│ ┌─────┐ (1) 800th anniversary of Francis of Assisi   │
│ │ img │     slug: 800th-anniversary-of-the-death-... │
│ │ BCE │     description: The coin depicts...         │
│ │180px│     [lmdlp: 0 variants] [mdp: —] [ebay: —]   │
│ └─────┘                                              │
│                                                      │
│ ┌─────┐ (2) Pinocchio — 200th birthday Carlo Collodi │
│ │ img │     slug: pinocchio-200th-birthday-...       │
│ │ BCE │     description: The design depicts...       │
│ │180px│     [lmdlp: 0 variants] [mdp: —] [ebay: —]   │
│ └─────┘                                              │
├──────────────────────────────────────────────────────┤
│ [Skip (s)]  [No match (n)]               [Quit (q)]  │
│ Keyboard: 1..2 pick, s skip, n no_match, q quit.     │
└──────────────────────────────────────────────────────┘
```

Tout le block "CANDIDATE" est un formulaire clickable — 1 clic n'importe où dans la card = pick. Raccourcis clavier pour power users.

### Live enrichment preview

Sous chaque candidate, des pills colorées montrent l'état actuel de l'entry canonique :

| Pill | Signification |
|---|---|
| `lmdlp: 4 variants` (vert) | 4 variantes déjà attachées par le scraper lmdlp |
| `mdp: 2 issues` (vert) | 2 prix d'émission officiels MDP |
| `ebay: 29 samples` (vert) | 29 listings eBay agrégés |
| `P50 6.50€` (vert) | Médiane marché pondérée |
| `mintage: 500,000` (vert) | Volume Wikipedia |
| `joint 19 pays` (vert) | Émission commune européenne |
| `lmdlp: —` (gris) | Pas encore enrichi par cette source |

Signal : si un candidate est déjà richement enrichi (lmdlp + mdp + ebay avec prix) et que l'autre est vide, c'est un indice **fort** que le premier est le bon. L'humain peut trancher plus vite.

### Persistance

Exactement comme le CLI supprimé : même 3 fichiers, mêmes helpers (`save_queue`, `save_resolutions`, `save_referential`). Mutation flushée à chaque action. Ctrl-C safe. Le bouton Quit fait un `persist()` explicite avant d'arrêter le serveur.

---

## 6. Smoke test end-to-end

J'ai validé le serveur en :

1. **Lancement** : `python ml/review_queue_server.py --no-browser` → serveur up sur 8765, 128 groupes annoncés ✓
2. **GET /review/0** : 200, page HTML rendue avec source image lmdlp + 2 candidate images BCE ✓ — le HTML montre bien `comm_2018_andorra-25const.jpg` et `comm_2018_andorra_70yrs_declhumrights.jpg`
3. **POST /review/0/action action=pick candidate_idx=1** : 302 → Location /review/0 (même idx, mais le groupe a avancé car le groupe 0 est maintenant résolu) ✓
4. **Stats mises à jour** : `picked 1 · variants 2` dans la topbar ✓
5. **Groupe suivant** : GET /review/0 affiche maintenant AD/2019 au lieu de AD/2018 ✓ (le `_refresh_groups` a bien effet)
6. **Persistance** : `manual_resolutions.json` contient l'entrée, `eurio_referential.json` a les variantes ajoutées ✓

Après le smoke test, j'ai rollback proprement les décisions de test via un script Python ciblé (suppression des variantes dans le référentiel + remise des items en unresolved + vidage de `manual_resolutions.json`). Cette rollback confirmée par re-lecture : queue 204/204 unresolved, 0 resolutions, `ad-2018-*-constitution` et `ad-2019-*-council` nettoyés.

---

## 7. Sortie observable

```
ml/review_core.py                           # NEW pure helpers
ml/review_queue_server.py                   # NEW local web UI
ml/scrape_bce_images.py                     # NEW BCE image scraper
ml/review_queue.py                          # DELETED (ancien CLI)

ml/datasets/sources/bce_comm_2004_2026-04-13.html .. bce_comm_2025_*.html
ml/datasets/eurio_referential.json          # +419 images, +505 design_descriptions
ml/datasets/review_queue.json               # toujours 204 items unresolved
ml/datasets/manual_resolutions.json         # vide, prêt pour le vrai run humain
ml/datasets/matching_log.jsonl              # 493 nouvelles lignes BCE
```

---

## 8. Comment lancer pour le vrai

```bash
# Serveur, navigateur auto-ouvert
python ml/review_queue_server.py

# Sans auto-open (si tu es en SSH ou autre)
python ml/review_queue_server.py --no-browser --port 8765

# Filtre par source (pour l'instant il n'y a que lmdlp avec escalades)
python ml/review_queue_server.py --source lmdlp
```

Raccourcis clavier dans le browser :
- `1`..`9` → pick candidate
- `s` → skip (ne retrier jamais)
- `n` → no match (aucun candidat ne convient)
- `q` → quit (persist + arrêt du serveur)
- clic sur la card du candidate = pick aussi

Estimation : 128 groupes × ~10 s avec images = **~20 minutes** pour traiter la queue complète. Raccourcis clavier permettent de blast encore plus vite si la majorité des cas sont évidents.

---

## 9. Limitations connues

| Limitation | Mitigation | Plan |
|---|---|---|
| 14 groupes (11%) n'ont aucune image canonique | Fallback texte avec placeholder "no image" | BCE publiera 2026 en juin ; re-run `scrape_bce_images.py` |
| BCE 72 entrées Stage 5 non matchées (paraphrases) | Ignorées — les pièces sont bien dans le référentiel, juste sans l'image ni la description BCE | Passe future : cross-matching slug ↔ feature avec threshold plus bas |
| Pas de désélection/undo d'une décision | Édition manuelle des 3 fichiers JSON possible | À implémenter si besoin réel |
| Pas d'authentification (serveur public) | `127.0.0.1` only, single-user sur la machine locale | Usage interne, pas de risque |
| Pas de tests end-to-end HTTP | Smoke test manuel via curl | Acceptable pour un outil d'usage ponctuel |
| Une image canonique par candidate seulement | Le serveur affiche `images[0]` | Si on veut avers + revers, stocker `role: "obverse"` / `"reverse"` — BCE n'a que l'obverse de toute façon |

---

## 10. Prochaine étape

La queue est **prête à être traitée par un humain**. Deux options pour la suite :

- **A.** Raphaël lance `python ml/review_queue_server.py` et traite les 128 groupes en ~20 min de vraie review visuelle
- **B.** On enchaîne sur Phase 2C.7 (sync Supabase) sans passer par la review manuelle, la queue reste pour plus tard

Je te recommande **B** pour l'instant : la queue n'est pas bloquante pour le reste du pipeline, et 20 min de clicking peuvent attendre une session dédiée. Le tool est prêt quand tu veux.
