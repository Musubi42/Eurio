# Eurio — Product Requirements Document

> **Version** 0.1 — Draft initial  
> **Auteur** Raphaël / Musubi SASU  
> **Date** Avril 2026  
> **Statut** En cours de rédaction

---

## Table des matières

1. [Vision produit](#1-vision-produit)
2. [Positionnement & analyse concurrentielle](#2-positionnement--analyse-concurrentielle)
3. [Personas utilisateur](#3-personas-utilisateur)
4. [Périmètre v1](#4-périmètre-v1)
5. [Features détaillées](#5-features-détaillées)
   - 5.1 [Scan de pièce](#51-scan-de-pièce--la-killer-feature)
   - 5.2 [Fiche pièce & valorisation](#52-fiche-pièce--valorisation)
   - 5.3 [Le Coffre — collection personnelle](#53-le-coffre--collection-personnelle)
   - 5.4 [Gamification & achievements](#54-gamification--achievements)
   - 5.5 [Historique de prix & projection](#55-historique-de-prix--projection)
   - 5.6 [Social & partage](#56-social--partage)
   - 5.7 [Marketplace (phase 2)](#57-marketplace-phase-2)
6. [UX & design principles](#6-ux--design-principles)
7. [Architecture technique](#7-architecture-technique)
8. [Stack & environnement de développement](#8-stack--environnement-de-développement)
9. [Sources de données](#9-sources-de-données)
10. [Business model & roadmap](#10-business-model--roadmap)
11. [KPIs & critères de succès](#11-kpis--critères-de-succès)
12. [Risques & mitigation](#12-risques--mitigation)

---

## 1. Vision produit

**Eurio** est l'application mobile de référence pour les collectionneurs de pièces euro — des curieux du dimanche aux numismates confirmés.

L'idée centrale : **chaque pièce dans ta poche peut valoir plus que sa valeur faciale**. Eurio te le dit en quelques secondes, te aide à construire ta collection, et transforme la chasse aux pièces en une expérience engageante, sociale et financièrement transparente.

Là où les apps existantes sont soit trop américaines, soit trop austères, soit trop agressives sur les paywalls, Eurio mise sur trois piliers :

- **Fluidité absolue** — le scan fonctionne du premier coup, sans manipulation, sans friction
- **Valeur immédiate** — chaque scan révèle une information utile et souvent surprenante
- **Engagement progressif** — de la simple curiosité à la collection sérieuse, avec une boucle de gamification qui donne envie de revenir

À terme, la marketplace intégrée permettra aux collectionneurs d'acheter et vendre des pièces au sein d'une communauté qui partage le même référentiel de valeur — un avantage structurel qu'aucune plateforme généraliste (eBay, Vinted) ne peut offrir.

---

## 2. Positionnement & analyse concurrentielle

### Carte des acteurs

| App | Points forts | Points faibles | Positionnement |
|---|---|---|---|
| **CoinSnap** | Scan rapide, gamification, UX soignée | Très orienté US, paywall agressif dès le déuxième scan, pub omniprésente | Américain grand public |
| **CoinManager** (euro-oriented) | Catalogue euro complet, orienté Europe | UI austère et datée, expérience scan médiocre (cercle à caler, focus manuel), pub intrusive | Outil de catalogage européen |
| **eBay / Catawiki** | Données de prix réels | Pas d'app dédiée pièces, pas de scan, pas de collection | Marketplace généraliste |
| **Numista** (web) | Référence absolue du catalogue euro, communauté active | Pas d'app mobile digne de ce nom, pas de scan | Base de données communautaire |

### Positionnement Eurio

Eurio occupe un espace vide : **scan de qualité + catalogue européen + gamification + valorisation financière**, dans une interface moderne, sans pub intrusive, avec un modèle freemium honnête. La marketplace en phase 2 crée un fossé concurrentiel durable.

---

## 3. Personas utilisateur

### Persona A — Le curieux de passage
> Lucas, 28 ans, ne se considère pas collectionneur. Il a trouvé une vieille pièce de 2€ dans le fond d'un tiroir. Il cherche sur Google à quoi ça vaut. Tombe sur Eurio. Scanne. Découvre que ça vaut 34€. Il télécharge l'app.

- **Usage** : sporadique, scan à la demande
- **Motivation** : curiosité, valeur financière
- **Risque de décrochage** : si le scan échoue ou est trop lent au premier essai

### Persona B — Le collectionneur hobby
> Isabelle, 45 ans, a un bocal de pièces chez elle depuis 15 ans. Elle aime l'idée de les cataloguer mais les outils existants sont trop compliqués ou trop moche.

- **Usage** : sessions régulières de catalogage, 20-40 pièces par session
- **Motivation** : ordre, satisfaction de compléter des sets, valeur du portefeuille
- **Risque de décrochage** : si la saisie est laborieuse

### Persona C — Le chasseur de raretés
> Thomas, 34 ans, connaît déjà bien la numismatique. Il suit les nouvelles frappes, a des alertes sur les pièces qui l'intéressent, et cherche un outil communautaire pour comparer et échanger.

- **Usage** : quotidien, très engagé, attend la marketplace
- **Motivation** : compléter des séries rares, flip de pièces, communauté
- **Risque de décrochage** : si l'app n'a pas les données pro et la marketplace

---

## 4. Périmètre v1

### In scope — Phase 1 (MVP Android)

- Scan de pièce on-device, fluide, sans friction
- Identification : pièces euro de circulation (1c à 2€, tous pays) + commémoratives 2€
- Fiche pièce : pays, année, tirage, valeur de marché estimée
- Coffre personnel : collection, valeur totale du portefeuille
- Historique de prix (graphe sparkline)
- Gamification de base : achievements, badges de complétion de séries
- Onboarding simple et rapide

### Out of scope — Phase 1

- Marketplace (phase 2)
- Social / partage entre amis (phase 2)
- Pièces hors zone euro
- Pièces commémoratives de valeurs autres que 2€
- Pièces gradées (PCGS/NGC)
- Projection de prix avancée avec modèle ML (phase 2)
- Web app

### Out of scope — définitif

- Publicités intrusives
- Paywall sur les fonctions core (scan, collection, fiche pièce)

---

## 5. Features détaillées

### 5.1 Scan de pièce — la killer feature

#### Objectif UX
L'expérience de référence est celle des apps de lecture de code-barres modernes (Yuka, NutriScore...) : **tu pointes, ça lit**. Pas de bouton "prendre la photo", pas de cercle à aligner manuellement, pas de focus à gérer. La détection est en continu, le résultat apparaît dès que la pièce est nette dans le cadre.

#### Flow utilisateur cible

```
Ouverture caméra
→ Overlay circulaire indicatif (guide visuel, non bloquant)
→ Détection automatique de la pièce dans le flux vidéo
→ Feedback visuel quand la pièce est bien détectée (cercle vert pulsé)
→ Capture automatique dès que la netteté est suffisante (pas de bouton)
→ Résultat en < 2 secondes
→ Fiche pièce affichée
→ Option "Ajouter au coffre" en un tap
```

#### Ce qui doit être garanti
- Fonctionne en lumière intérieure normale (pas besoin de lumière parfaite)
- Fonctionne avec les deux faces (recto et verso identifiés séparément si besoin)
- Résiste aux reflets métalliques (normalisation d'histogramme, égalisation)
- Ne nécessite aucun zoom manuel
- Tourne entièrement on-device — pas d'appel serveur pour le scan

#### Gestion des cas d'échec
- Si la pièce n'est pas reconnue avec une confiance suffisante : affichage d'un état "pièce non identifiée" avec suggestions (pays probables, valeur faciale détectée)
- Jamais de crash silencieux, jamais de résultat fantaisiste affiché avec confiance

---

### 5.2 Fiche pièce & valorisation

Chaque pièce identifiée possède une fiche riche :

#### Informations de base
- Image de référence (recto + verso)
- Nom officiel de la pièce
- Pays émetteur
- Année de frappe
- Tirage (nombre d'exemplaires frappés, source Numista)
- Indice de rareté : **Commune / Peu courante / Rare / Très rare** (calculé à partir du tirage + estimation de la circulation actuelle)

#### Valorisation marché
- **Valeur faciale** : toujours rappelée
- **Valeur de marché estimée** : fourchette P25/P75 basée sur les ventes récentes (source : eBay completed listings)
- **Delta** : "+X% par rapport à la valeur faciale"
- **Dernière mise à jour des données**

#### Historique de prix
- Graphe sparkline 12 mois
- Vue étendue (5 ans) disponible via tap
- Prix min / max / médian sur la période

#### Projection (v1 simplifiée)
- Tendance calculée sur l'historique disponible (régression linéaire)
- Affichage : *"Si la tendance se maintient — dans 5 ans : 12 € à 18 €"*
- Toujours accompagné d'une mention de l'incertitude inhérente
- Pas de prétention à la précision : c'est une indication, pas un conseil financier

---

### 5.3 Le Coffre — collection personnelle

Le Coffre est l'espace central de l'utilisateur. C'est son patrimoine numismatique.

#### Vue principale
- Valeur totale du portefeuille (somme des valeurs de marché médianes)
- Delta depuis l'ajout : *"Ton coffre a pris +12% depuis que tu as commencé"*
- Nombre de pièces, nombre de pays représentés, nombre de séries complètes

#### Vue par pièce
- Photo scannée (celle de l'utilisateur) + photo de référence
- Date d'ajout au coffre
- Valeur au moment de l'ajout vs valeur actuelle
- Statut dans la gamification (contribue à quels achievements)

#### Organisation
- Filtres : par pays, par valeur faciale, par année, par rareté
- Recherche texte libre
- Vue grille ou vue liste

#### Export (v1)
- Export PDF simple du coffre (liste + valeurs)

---

### 5.4 Gamification & achievements

La gamification doit être **organique**, jamais agressive. Les achievements récompensent la progression naturelle du collectionneur — pas des dark patterns.

#### Système de sets

Un *set* est une collection cohérente de pièces. Compléter un set débloque un achievement et un badge visuel affiché sur le coffre.

**Exemples de sets :**

| Set | Description | Difficulté |
|---|---|---|
| **Série complète [Pays]** | Toutes les pièces courantes d'un pays (1c à 2€) | Facile |
| **Eurozone founding** | Une pièce de chaque pays fondateur de l'euro (2002) | Moyen |
| **Millésime [Année]** | Une pièce de chaque valeur frappée une année donnée | Moyen |
| **Commémoratives [Pays]** | Toutes les 2€ commémoratives d'un pays | Difficile |
| **Grande chasse** | Au moins une pièce de chaque pays de la zone euro | Difficile |
| **Vintage 2002** | Toutes les pièces frappées en 2002 (1ère année) | Très difficile |
| **Le Coffre d'or** | 10 pièces d'une valeur de marché > 10x leur face | Très difficile |

#### Progression individuelle
- Niveau de collectionneur : Découvreur → Passionné → Expert → Maître
- Basé sur le nombre de pièces uniques, la complétude des sets, la rareté moyenne

#### Notifications de chasse
- *"Il te manque 2 pièces pour compléter la série allemande"*
- *"Une nouvelle 2€ commémorative française vient d'être frappée — ajoute-la à ta liste de chasse"*

---

### 5.5 Historique de prix & projection

#### Données
- Prix de marché mis à jour hebdomadairement via eBay completed listings (API Finding)
- Stockage en time series par identifiant Numista
- Calcul de percentiles (P10, P25, P50, P75, P90) pour chaque pièce

#### Affichage
- Graphe interactif sur la fiche pièce
- Indicateur de tendance : ↑ hausse / → stable / ↓ baisse sur 3 mois
- Pour les pièces avec peu de transactions : affichage d'une valeur de cote (source Numista) avec mention de la source

#### Projection
- Modèle v1 : régression linéaire sur l'historique disponible (minimum 6 points de données)
- Résultat affiché avec une bande de confiance visuelle (pas de valeur exacte)
- Facteur de rareté intégré : si le tirage est faible, la tendance est pondérée à la hausse
- Wording systématiquement prudent : *"estimation indicative"*, jamais *"votre pièce vaudra X"*

---

### 5.6 Social & partage (phase 1 light, phase 2 full)

#### Phase 1 — Partage statique
- Partage d'une fiche pièce ou d'un screenshot du coffre via le share sheet natif Android
- Deep links vers des fiches pièces (pour partager entre utilisateurs Eurio)

#### Phase 2 — Social
- Profil public optionnel (pseudo + coffre visible)
- Comparaison de coffres entre amis
- Leaderboard par sets complétés
- Feed de nouveautés : nouvelles frappes, nouvelles commémoratives, records de prix
- Map de circulation : visualisation géographique des pièces les plus scannées par pays (données agrégées anonymisées)

---

### 5.7 Marketplace (phase 2)

La marketplace Eurio a un avantage structurel fort sur eBay ou Vinted : **la pièce est déjà identifiée, valorisée et cataloguée avant même de créer le listing**.

#### Flow vendeur
```
Pièce dans mon Coffre
→ "Mettre en vente"
→ Prix suggéré automatiquement (basé sur le marché)
→ Photos de la pièce (déjà scannées)
→ Condition (UNC / SUP / TTB / TB / B)
→ Listing publié en 30 secondes
```

#### Flow acheteur
```
Recherche par pays / valeur / année / rareté
→ Fiche pièce avec prix vendeurs disponibles
→ Achat direct ou offre
→ Paiement intégré (Stripe)
→ Expédition entre particuliers
```

#### Modèle économique
- Commission Eurio : 6% sur chaque transaction
- Pas de frais de listing
- Paiement sécurisé, fonds libérés à la confirmation de réception

#### Différenciation vs eBay
- Identification garantie (pas de "pièce rare" qui s'avère être une pièce commune)
- Fourchette de prix recommandée affichée au moment du listing
- Communauté de collectionneurs — vendeur et acheteur partagent le même contexte

---

## 6. UX & design principles

### Principes fondamentaux

**1. Le scan d'abord**
Le scan est le point d'entrée principal de l'app. Il doit être accessible depuis n'importe quel écran en un tap (bouton flottant persistant). Aucune friction entre l'ouverture de l'app et la caméra.

**2. La surprise comme moteur**
Le moment où l'utilisateur découvre qu'une pièce "normale" vaut 10x sa valeur faciale est le hook de rétention. L'interface doit amplifier ce moment : animation, mise en valeur visuelle, son optionnel.

**3. Zéro friction sur les actions principales**
Scan → Ajout au coffre doit prendre < 5 secondes et < 3 taps. Pas de formulaire, pas de saisie manuelle sauf exception.

**4. Honnêteté financière**
Les projections de prix sont toujours affichées avec des indicateurs d'incertitude. Jamais de promesses. L'utilisateur doit toujours savoir d'où vient une valeur et quand elle a été calculée.

**5. Design sobre et européen**
Pas de gamification criarde à l'américaine. L'aesthetic est moderne, sobre, avec une identité visuelle qui rappelle la précision et le patrimoine — comme une pièce bien frappée.

### Navigation

```
Bottom navigation bar (4 onglets) :
├── Scan (caméra — onglet central mis en valeur)
├── Coffre (ma collection)
├── Explorer (catalogue, tendances, nouvelles frappes)
└── Profil (achievements, stats, settings)
```

### Onboarding

- 3 écrans max, skip disponible immédiatement
- Écran 1 : "Scanne ta première pièce" — accès caméra direct
- Pas de compte obligatoire au démarrage (compte requis uniquement pour sync multi-device et marketplace)

---

## 7. Architecture technique

> Note : cette section décrit l'architecture cible. Elle est volontairement découplée de l'UX — les choix techniques ne doivent jamais impacter l'expérience utilisateur perçue.

### Pipeline d'identification (on-device)

```
Flux vidéo caméra
→ [Frame grabber] Extraction de frame toutes les 200ms
→ [Préprocessing] Détection de cercle (Hough Transform)
   Crop, resize 256×256, normalisation luminosité, niveaux de gris
→ [Identification en 2 passes]
   Passe 1 : valeur faciale (side commun, ~12 classes)
   Passe 2 : pays + année (side national, ~500 classes pour les 2€)
→ [Matching]
   MVP : ORB feature matching vs index pré-calculé
   V2  : MobileNetV3 fine-tuné, inférence TFLite
→ [Résultat] Identifiant Numista + score de confiance
→ Si confiance < seuil : état "non identifié" avec suggestions
```

**Modèle TFLite (v2)**
- Entraîné sur les images du catalogue Numista + augmentation de données (rotation, bruit, variation d'éclairage)
- Taille cible : < 15 Mo (embarquable dans l'APK)
- Inférence < 500ms sur Pixel 9a

### Backend

Architecture légère, coûts quasi nuls au démarrage :

```
Supabase (PostgreSQL + Auth + Storage)
├── Table coins          : catalogue Numista + métadonnées
├── Table price_history  : time series des prix eBay
├── Table collections    : coffres utilisateurs
├── Table achievements   : état gamification par user
└── Storage              : images de référence des pièces

Fastify (API légère)
├── /enrich/:numista_id  : retourne fiche complète + prix
├── /collection          : CRUD coffre utilisateur
└── /prices/:id/history  : historique de prix

Cron job (hebdomadaire)
└── Pull eBay Finding API → price_history
```

### Coût d'infra estimé au démarrage

| Composant | Coût |
|---|---|
| Supabase free tier | 0€ (jusqu'à 50k rows) |
| Fastify (Railway / Fly.io) | ~5€/mois |
| eBay Finding API | Gratuit (quotas généreux) |
| Numista API | Gratuit (usage raisonnable) |
| Scan on-device | 0€ |
| **Total** | **~5€/mois** |

---

## 8. Stack & environnement de développement

### Stack applicatif

| Couche | Technologie | Justification |
|---|---|---|
| App mobile | **React Native** (Expo) | Cross-platform à terme, skills existants, écosystème riche |
| Scan / vision | **OpenCV via module natif** (react-native-opencv ou module custom) | Gratuit, performant, tourne on-device |
| Matching v2 | **TFLite** via react-native-fast-tflite | Inférence on-device, zéro coût de requête |
| Backend | **Fastify** + **PostgreSQL** (Supabase) | Stack connue, déploiement rapide |
| Auth | **Supabase Auth** | Intégré, gratuit |
| Prix historiques | **eBay Finding API** + cron | Prix de marché réels |
| Catalogue | **Numista API** | Référence du domaine |

### Environnement de développement

**Machine de développement** : Mac (Apple Silicon M3)

**IDE** : VS Code + extensions React Native / Expo

**Build & test device** : Google Pixel 9a (Android)

**Workflow recommandé** :
```
VS Code (écriture du code)
→ Expo Dev Client (hot reload sur device via USB ou Wi-Fi)
→ Android Studio (uniquement pour : build release APK, debug natif, profiling)
→ Test sur Pixel 9a en conditions réelles
```

**Pourquoi Expo plutôt que bare React Native ?**
- Hot reload immédiat sur device sans passer par Android Studio
- Modules natifs disponibles via Expo Modules API
- Possibilité d'éjecter vers bare workflow si besoin (OpenCV, TFLite)

**Modules natifs requis (à intégrer en bare workflow) :**
- `react-native-vision-camera` — accès flux vidéo caméra avec frame processor
- `vision-camera-resize-plugin` — preprocessing des frames
- Module custom OpenCV pour le circle detection + ORB matching
- `react-native-fast-tflite` — inférence TFLite (v2)

**Commandes de base :**
```bash
# Démarrage dev
npx expo start --tunnel

# Build APK de développement (Android Studio)
npx expo run:android

# Envoi direct sur device connecté en USB
adb install build/app-debug.apk
```

---

## 9. Sources de données

### Catalogue de pièces

**Numista** (numista.com)
- API REST documentée, accès gratuit pour usage raisonnable
- Catalogue de référence : toutes les pièces euro de circulation + commémoratives
- Données disponibles : nom, pays, année, tirage, image recto/verso, cote communautaire
- Identifiant unique par pièce (utilisé comme clé primaire dans Eurio)

### Prix de marché

**eBay Finding API — completed listings**
- Prix de transactions réelles, datées
- Filtrage par keyword (ex: "2 euro commemorative germany 2006")
- Gratuit, quotas généreux (5000 req/jour)
- Permet de construire un historique propre en time series

**Fallback : Numista cote communautaire**
- Utilisée quand eBay a trop peu de transactions pour une pièce donnée
- Moins précise mais couvre toutes les pièces du catalogue

**Enrichissement futur :**
- Catawiki (ventes enchères, pièces rares)
- MA-Shops (marketplace européenne spécialisée)

### Images de référence

- Images haute résolution issues du catalogue Numista (licence à vérifier pour usage commercial)
- Alternativement : constitution d'une base propre via crowdsourcing (photos des utilisateurs Eurio)

---

## 10. Business model & roadmap

### Modèle économique

**Phase 1 — Gratuit, zéro pub**
- Application entièrement gratuite
- Aucune publicité
- Objectif : construire la base d'utilisateurs et valider les KPIs de rétention
- Coûts couverts par Musubi SASU (projet side, infra < 10€/mois)

**Phase 2 — Freemium + Marketplace**
- Core features : toujours gratuites (scan, coffre, fiche pièce, gamification de base)
- Premium optionnel (~2,99€/mois ou 19,99€/an) :
  - Projections de prix avancées
  - Alertes de prix et nouvelles frappes
  - Export PDF/CSV du coffre
  - Statistiques avancées
- Marketplace : commission 6% sur les transactions
- Pas de paywall sur les fonctions qui créent de la valeur pour la base d'utilisateurs

### Voies de financement

**Court terme (Phase 1)**
- Autofinancement via Musubi SASU
- Dossier BPI France Innovation si traction démontrée (angle "patrimoine culturel européen numérique")
- EuraTechnologies : programme d'accompagnement accessible depuis Lille

**Moyen terme (si KPIs solides)**
- Acquisition stratégique : Numista, Catawiki, maison de vente numismatique
- Les cibles idéales sont celles qui ont le catalogue mais pas l'app mobile grand public
- Note : levée VC classique moins adaptée à cette niche — préférer acquisition ou BPI non-dilutif

### Roadmap

#### Phase 1 — MVP (2-3 mois)
- [x] Définition produit (ce document)
- [ ] Setup environnement React Native + Expo sur Mac/Pixel 9a
- [ ] Module de scan : preprocessing OpenCV + détection cercle
- [ ] Identification : ORB matching vs index Numista (pièces 2€ commémoratives en priorité)
- [ ] Intégration Numista API (catalogue)
- [ ] Intégration eBay Finding API (prix)
- [ ] UI Coffre (collection personnelle)
- [ ] Fiche pièce avec graphe de prix
- [ ] Achievements de base (5 sets)
- [ ] Onboarding
- [ ] Test sur panel fermé (famille, amis collectionneurs)

#### Phase 2 — Croissance (mois 4-8)
- [ ] Gamification complète (20+ sets, niveaux, notifications)
- [ ] Modèle TFLite fine-tuné (identification plus robuste)
- [ ] Projections de prix avancées
- [ ] Social : partage, profils publics, comparaison de coffres
- [ ] Publication Google Play Store
- [ ] Communication : communities Reddit, forums numismatiques, groupes Facebook

#### Phase 3 — Marketplace (mois 9+)
- [ ] Listings vendeur
- [ ] Intégration paiement (Stripe)
- [ ] Système de réputation vendeur/acheteur
- [ ] Map de circulation des pièces

---

## 11. KPIs & critères de succès

### KPIs Phase 1 (MVP, 3 mois post-lancement)

| Métrique | Cible | Pourquoi |
|---|---|---|
| Taux de succès scan | > 85% | Mesure la qualité core de la killer feature |
| Temps moyen scan → résultat | < 3 secondes | Fluidité perçue |
| Rétention J7 | > 40% | Engagement initial |
| Rétention J30 | > 20% | Rétention réelle |
| Pièces ajoutées au coffre / utilisateur actif | > 10 | Indication d'engagement profond |
| NPS (enquête in-app) | > 40 | Satisfaction globale |

### KPIs Phase 2 (6 mois post-lancement)

| Métrique | Cible |
|---|---|
| MAU (Monthly Active Users) | > 5 000 |
| Pièces scannées total | > 100 000 |
| Sets complétés | > 1 000 |
| Reviews Google Play | > 4,3 étoiles |

### KPIs Phase 3 (Marketplace)

| Métrique | Cible |
|---|---|
| GMV mensuel | > 5 000 € |
| Taux de conversion vendeur (coffre → listing) | > 5% |
| Taux de litige | < 2% |

---

## 12. Risques & mitigation

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| Qualité du scan insuffisante en conditions réelles | Moyenne | Très élevé | Tests intensifs sur matériaux réels, itérations rapides sur le preprocessing, seuil de confiance strict |
| Données Numista incomplètes ou API rate limiting | Faible | Moyen | Cache agressif, fallback sur cote communautaire, contact Numista pour usage commercial |
| Marché trop niche pour attirer des utilisateurs | Moyenne | Élevé | Valider avec un panel avant le lancement public, angle "tout le monde a des euros en poche" |
| Changements API eBay / Numista | Faible | Moyen | Abstraction des sources de données, sources alternatives identifiées |
| Réglementation marketplace (paiements, TVA) | Faible (phase 2) | Moyen | Consulter un expert avant la phase 3, commencer par mise en relation sans paiement intégré |
| Concurrence : une app existante améliore drastiquement son UX | Faible | Élevé | Avantage first-mover sur la communauté et la marketplace ; accélérer sur les features sociales |

---

*Document vivant — à mettre à jour à chaque itération significative.*

*Eurio est un projet Musubi SASU — Raphaël, Hauts-de-France, 2026.*