# Sources de photos réelles

> Catalogue des sources accessibles, ce qu'elles donnent, comment y
> accéder. Document **vivant** — chaque source attaquée doit voir sa
> ligne mise à jour avec volume réel observé, taux d'auto-validation,
> blockers rencontrés.

## Principe

On veut, pour chaque pièce du catalogue, un **set de photos réelles
in-the-wild** d'une dizaine d'images minimum (à calibrer en phase 2),
chacune prise dans des conditions différentes (lumière, angle,
fond, usure). Pas besoin de qualité studio — au contraire, plus c'est
"sale", plus c'est représentatif des scans users.

Toute source candidate doit répondre à trois questions :

1. **Accès** — API, scraping autorisé, ou manuel ?
2. **Confiance label** — quand la source dit "c'est telle pièce", à
   quel point on la croit ?
3. **Volume** — combien de photos par pièce on peut espérer ?

La règle : **on ne fait jamais confiance à 100% à une source qui
n'est pas Numista**. Tout passe par l'auto-validateur (cf.
[`auto-validator.md`](./auto-validator.md)) avant d'entrer dans le
training set.

## Table de référence

> Les valeurs en italique sont des **estimations à valider** quand la
> source est attaquée. Aucun chiffre n'est mesuré aujourd'hui.

| Source | Accès | Confiance label brute | Volume estimé / coin | ROI estimé | Statut |
|---|---|---|---|---|---|
| **Numista** (canonique) | Scraping | ✅ Très haute (catalogue éditorial) | 1 (la photo officielle) | Référence — déjà en place | ✅ en place |
| **Numista** (user-uploads) | À vérifier | Haute (modéré par admin Numista) | *Variable, à mesurer* | À évaluer en phase 3 | 🔲 |
| **eBay** | API officielle (limites quotas) ou scraping | Moyenne (titre seller, parfois faux) | *Élevé sur communes, faible sur rares* | Best ROI — première cible | 🔲 |
| **Catawiki** | Scraping (à vérifier ToS) | Haute (maisons de vente sérieuses) | *Modéré* | Phase 3 | 🔲 |
| **MA-Shops** | Scraping | Haute (marchands pros) | *Modéré* | Phase 3 | 🔲 |
| **vCoins** | Scraping | Haute (marchands US, peu d'euros) | *Faible sur euros* | Phase 3 ou skip | 🔲 |
| **Sixbid** | Scraping | Haute (enchères pros) | *Faible volume mais qualité* | Phase 3 | 🔲 |
| **Colnect** | Scraping ou API | Moyenne (catalogue communautaire) | *Variable* | Phase 3 | 🔲 |
| **Wikimedia Commons** | API | Très haute (mais peu d'images par pièce) | *Faible (1-3)* | Phase 3, complément | 🔲 |
| **Reddit** (r/Eurocoins, r/coins) | API ou scraping | Faible (post amateur) | *Aléatoire* | Phase 4 si besoin | 🔲 |
| **Forums** (Eurocollections, NumisCorner…) | Scraping | Faible | *Aléatoire* | Skip sauf cas particulier | ⏸️ |

## Détails par source

### Numista

- **Canonique** : `numista.com/catalogue/<id>.html` — une photo
  obverse + une photo reverse, parfois retouchées, qualité studio.
  Déjà scrapée et utilisée comme référence d'entraînement.
- **User-uploads** : à vérifier. Certaines pages affichent une
  galerie de photos contribuées par les collectionneurs. À
  investiguer :
  - Endpoint / page exposant ces photos
  - Volume effectif par pièce (probablement très inégal — communes >
    rares)
  - Métadonnées disponibles (uploader, date, validé ou non)
  - ToS pour usage entraînement modèle
- Si exploitable : confiance haute par défaut, **chaque photo passe
  quand même par l'auto-validateur** (un user peut s'être trompé).

### eBay

- **API officielle** Browse / Finding : recherche par mot-clé, filtre
  par catégorie "Coins & Paper Money > Coins: World > Europe > Euro".
  Quotas gratuits limités, applications dev possibles.
- **Pattern de requête** : "2 euro Allemagne Kniefall 2020", "2 euro
  Belgium 2007", etc. Construit depuis le catalogue Eurio (pays +
  année + nom commémo connu).
- **Risques de bruit** :
  - Listings de lots (plusieurs pièces en photo)
  - Faux match texte (vendeur écrit "Kniefall" dans une description
    de lot mixte)
  - Photos stock dupliquées (vendeurs qui réutilisent l'image
    Numista)
  - Mauvais cadrage (pièce minuscule dans la photo, fond chargé)
- **Mitigations** :
  - Pré-filtrage par OpenCV (détection cercle déjà en place)
  - pHash dedup contre la photo canonique
  - Auto-validateur sur chaque photo individuelle
  - Côté requête : préférer les listings "single coin" via filtres
    (parfois exposés)
- **Première source à attaquer** parce que volume × accessibilité ×
  ROI maximaux.

### Catawiki, MA-Shops, Sixbid

- Maisons de vente / plateformes pro avec **photos haute qualité** et
  **labels précis** (numéro KM, année, état de conservation).
- Volume plus faible qu'eBay mais bruit minimal.
- ToS scraping à vérifier au cas par cas. Parfois robots.txt
  permissif, parfois non.
- Investigation prioritaire : Catawiki (bon volume euros).

### vCoins

- Plateforme orientée marché US, peu d'euros récents. À skipper sauf
  pour pièces rares spécifiques.

### Colnect

- Catalogue communautaire avec photos user-uploadées. Curation
  variable. Confiance moyenne.
- API existe (à vérifier statut actuel et terms).

### Wikimedia Commons

- Photos sous licence libre, qualité éditoriale haute, volume **très
  faible** par pièce (souvent 0 ou 1 photo).
- Utile comme **complément** plutôt que source principale.

### Reddit, forums

- Volume aléatoire, friction technique, label faible.
- À considérer seulement si on plafonne sur les sources curées.

## Stratégie d'attaque

**Phase 2 (premier scrape)** : eBay seul, **commémoratives uniquement**
(designs uniques, faciles à auto-valider). Objectif :
faisabilité prouvée + premières N photos par pièce dans le
training set.

**Phase 3 (élargissement)** : ajouter Catawiki, Numista user-uploads,
Wikimedia. Étendre aux standards UE (qui demandent un validateur
plus strict, cf. [`auto-validator.md`](./auto-validator.md)).

**Phase 4+** : itérer selon les manques observés (pièces sous-
représentées, conditions sous-représentées).

## Métriques à suivre par source

À tracker dans `ml/state/` (table à créer) ou dans un simple JSON
versionné en lab :

- Nombre de photos candidates récupérées
- Nombre auto-validées (par seuil)
- Nombre review queue
- Nombre rejetées
- Précision spot-checked sur échantillon hand-labelé
- Latence d'ingestion / coût

Permet de comparer le ROI réel de chaque source et de couper celles
qui rapportent peu.

## Aspects légaux

- **Respecter les ToS** de chaque plateforme (rate-limit, user-agent,
  pas de scraping derrière login).
- **Usage entraînement modèle** : zone grise mais généralement
  toléré pour des photos publiquement accessibles. À documenter par
  source.
- **Pas de redistribution** des photos brutes — on stocke localement
  pour entraînement, on ne republie pas.
- **Wikimedia Commons** : crédit obligatoire si on cite des photos
  individuelles dans un doc public ; usage entraînement libre.
