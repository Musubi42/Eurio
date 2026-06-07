# État actuel par source

> Ce qu'on capture aujourd'hui, ce qu'on rate, et où le code vit.

## Vue synthétique

| Source | Type | Photos capturées | Prix capturés | Métadonnées | Module | Quota |
|---|---|---|---|---|---|---|
| Numista API | API | obverse + reverse canoniques (1 paire) | ❌ | ✅ riche | `ml/referential/batch_fetch_images.py`, `enrich_from_numista.py` | mensuel partagé 1800 |
| eBay Browse | API | ❌ (on jette) | ✅ P10/P50/P90 actifs | ❌ | `ml/market/scrape_ebay.py` | quotidien 5000 |
| LMDLP | scrape HTML | partiel | ✅ cotation marchand FR | partielle | `ml/referential/scrape_lmdlp.py` | none |
| Monnaie de Paris | scrape HTML | ✅ officielles | ❌ | tirage, designer | `ml/referential/scrape_monnaiedeparis.py` | none |
| BCE | scrape HTML | ✅ 1 photo officielle/commémo | ❌ | annonce officielle | `ml/referential/scrape_bce_images.py`, `fetch_bce_images.py` | none |
| Wikipedia | future | — | — | — | non écrit | none |
| **Catawiki** | API/scrape | ❌ pas câblé | ❌ | — | à écrire | TBD |
| **NumisCorner** | scrape | ❌ pas câblé | ❌ | — | à écrire | none |
| **CGB** | scrape | ❌ pas câblé | ❌ | — | à écrire | none |

## Détail par source

### Numista API

- **Capté** : pour chaque pièce avec `numista_id`, on télécharge `obverse.jpg` + `reverse.jpg` canoniques. Métadonnées riches (theme, designer, atelier, tirage, composition…).
- **Manqué** : aucun prix. Les annonces marketplace de Numista (forum, swap) ne sont pas exploitées.
- **Quota** : 2 clés API, mensuel 1800 calls partagé. Aujourd'hui ~70% consommé.
- **Stockage** : `ml/datasets/<numista_id>/{obverse,reverse}.jpg` + colonnes `coins.*`.
- **Verdict** : la source canonique fonctionne. À garder telle quelle, exposer ses images aussi via `image_assets` avec `variant_kind='canonical'`.

### eBay Browse

- **Capté** : prix actifs P10/P50/P90 sur listings, agrégé par eurio_id ciblé.
- **Manqué** : **les images des listings sont jetées.** C'est notre plus gros gisement raté — gratuit (quota déjà payé pour le prix), distribution réaliste (in-hand, lumière variable, qualité variable).
- **Quota** : 5000 calls/jour, on en utilise 100-500 actuellement.
- **Résolution `listing → eurio_id`** : aujourd'hui via matching naïf sur titre + filtres. Bruité. Cf. `open-problems.md`.
- **Verdict** : c'est **la** source à élargir en priorité. Capture des images au passage = quasi gratuit.

### LMDLP (La Monnaie de la Pièce)

- **Capté** : cotation marchand FR par pièce, parfois condition (UNC/SUP/TTB).
- **Manqué** : photos partiellement. À vérifier si le scraper en sauve.
- **Quota** : politesse (rate limit manuel), pas de hard cap.
- **Verdict** : prix OK, vérifier ce qu'on fait des photos.

### Monnaie de Paris

- **Capté** : photos officielles haute qualité, métadonnées tirage/designer.
- **Manqué** : pas de prix marché (ce sont les prix officiels de vente, pas marché secondaire).
- **Verdict** : photos `variant_kind='official_press'`, à verser dans `image_assets`.

### BCE

- **Capté** : 1 photo officielle par commémo, par année.
- **Manqué** : pas de prix.
- **Verdict** : photos officielles, à verser dans `image_assets` avec `variant_kind='official_press'`.

### Wikipedia (future)

- **À faire** : scraper page catalogue par pays (21 pays eurozone), backfill métadonnées + photos disponibles.
- **License** : variable selon image (Commons vs fair-use). À tagger explicitement.

### Catawiki (nouveau)

- **Potentiel** : enchères → photos in-hand de qualité variable mais souvent bonne (vendeurs pros), prix de vente réels (~marché eBay sold), condition souvent déclarée.
- **Risques** : scraping de site dynamique JS, ToS à vérifier, license images = fair_use_research uniquement.

### NumisCorner (nouveau)

- **Potentiel** : marchand pro, photos catalogue propres, prix par condition (UNC, BU, FDC).
- **Risques** : site marchand, scraping respectueux, license fair-use.

### CGB (nouveau)

- **Potentiel** : marchand FR pro, photos très haute qualité, grading précis (FDC, SPL, SUP, TTB, TB, B).
- **Risques** : idem NumisCorner.

## Pourquoi le statu quo est bloquant

1. **Training data plafonne** : sans Catawiki/eBay images, on ne peut pas faire grandir significativement le dataset par classe — ce qui maintient les R@1 live strict bas (cf. `lab-prod-refacto/README.md`).
2. **Comparer ses prix** : impossible de dire à l'utilisateur "ton prix est sous le marché actif eBay mais au-dessus de la cotation LMDLP" parce qu'on n'a qu'une valeur consolidée mal définie.
3. **Onboarding source = copy-paste** : chaque nouveau scraper réinvente la roue (dédup, quota guard, run logging, intégration admin). Catawiki + NumisCorner + CGB en l'état = 3× la même dette.
4. **Admin aveugle** : la page `/sources` montre que ça tourne, mais pas ce que ça produit. Impossible de savoir ce qui a été récolté lors du dernier run sans aller fouiller le disque.
