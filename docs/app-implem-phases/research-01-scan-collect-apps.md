# Recherche — Apps scan-centric & gamification de collection

> Consigné le 2026-04-15 dans le cadre de la planification de l'app Android Eurio. Étude comparative d'apps où l'action primaire est le scan + l'objectif est la complétion d'une collection ou de sets structurés.

## Objectif

Informer la structure de navigation, les mécaniques de gamification, et le sens de complétion de l'app Eurio en étudiant comment d'autres apps ont résolu les mêmes problèmes. Question de départ : "Comment construit-on une app autour de l'acte de scanner, comme TikTok est construit autour de la création de contenu ?"

## Vivino — scan étiquette vin → cellar

L'action scan est ancrée mais **pas en FAB central** : camera icon proéminent dans la top bar, plus un onglet "Scan" dédié dans la bottom nav (Feed, Explore, Cellar, Profile). Post-scan, l'utilisateur atterrit sur un **écran détail plein** (pas un overlay) : dial de note circulaire (score tactile, plus précis que les étoiles), moyenne communautaire, prix, notes de dégustation, action sheet avec "Add to Cellar" parmi d'autres (Like, Review, Buy). Le Cellar est l'inventaire perso, filtrable par cépage/style/drinking window — **séparé du catalogue de 16M vins**, qui se browse via Explore/Search.

**Ce qui marche** : le dial circulaire est une signature interaction mémorable qui fait office de logging gesture. **Ce qui rate** : les reviewers trouvent la home screen surchargée — trop de features secondaires concurrencent le scan.

Sources : [Vivino Cellar](https://www.vivino.com/en/wine-news/discover-vivinos-wine-cellar-feature), [Jancis Robinson review](https://www.jancisrobinson.com/articles/best-wine-labelscanning-apps)

## Untappd — check-in bière → badges

Untappd traite le **check-in comme un post social**, pas un log silencieux : après identification, l'utilisateur écrit une note, rate 0–5, attache photo/venue, publie dans un feed. Nav 5-onglets (Feed, Search/Discover, Check-in FAB centre, Notifications, Profile) — le pattern center-FAB est explicite ici et marche parce que chaque session a une raison unique : "log this beer". Les **badges** (des centaines) sont la boucle de rétention, pas XP/niveaux. Le redesign 2025 a ajouté **"Nearby Local Badges"** sur la home, et rendu les listes de badges triables par "recently unlocked" — leçon directe : **visible-next-goal beats giant-trophy-wall**. Les listes (wishlist, top-rated) sont construites par l'utilisateur, pas des sets système.

Sources : [Untappd blog](https://untappd.com/blog/badge-changes-for-august-19-2025/1819), [Untappd updates](https://updates.untappd.com/)

## Pokémon TCG Pocket — collect cards, complete sets

**L'analogue structurel le plus proche d'Eurio** : scan → add → complete sets. Home surface le **prochain pack à ouvrir** ; nav bottom (Cards/Binders, Shop/Packs, Battle, Social, Menu). La vue "My Cards" montre chaque carte dans une **grille set avec silhouettes pour les cartes manquantes** et un compteur visible `owned/total` par set — **les slots vides sont le moteur d'engagement**. Les **Binders** (max 15, 30 cards each) sont des showcases user-curés par-dessus le modèle "set" système — ils comblent le besoin "montrer mes meilleures trouvailles" séparément du tracking de complétion.

Le flow post-pull est délibérément **cérémoniel** : animations de flip séquentielles, les cartes immersives rares ont une animation full-screen dédiée **rejouable plus tard depuis le détail de la carte** — le moment de découverte est un reward en soi. **Anti-pattern** : la cérémonie n'est pas skippable et génère des plaintes soutenues ; les batch/speedrun users se sentent punis.

Sources : [Binders explained (TheGamer)](https://www.thegamer.com/pokemon-pocket-binders-explained/), [Immersive animations replay](https://gamerant.com/pokemon-tcg-pocket-replay-immersive-card-animations/), [UI critique](https://www.thegamer.com/why-is-pokemon-tcg-pockets-ui-so-annoying/)

## Shazam — tag song → My Shazams

Shazam est l'app "one big button" canonique et la leçon est le **minimalisme radical** : la **home screen EST la surface de scan** — le bouton géant remplit l'écran, zéro onglet en compétition. "My Shazams" (library de tags, reverse-chronologique) est accédé par **swipe-up** depuis la home, explicitement pour garder l'action scan uncontested. Le résultat post-tag slide en card avec artwork, titre, CTA Apple Music, lyrics — dismiss → scan en un geste.

**Ce qui marche** : zéro friction entre "j'ai entendu un truc" et "c'est identifié". **Absent notable** : aucune notion de "complétion de collection" — Shazam est un log, pas un set tracker, et c'est pourquoi les users finissent par abandonner leur library.

Sources : [Shazam UX case study](https://medium.com/design-bootcamp/capturing-the-music-around-you-understanding-the-user-flow-of-shazam-e13b9b9a9826), [Shazam rearchitecture](https://marie-lejeail.com/shazam-rearchitecture)

## CoinSnap — compétiteur direct

Scan-first home (caméra plein écran), bottom nav avec Scan / Collection / Identify-from-gallery / Settings. Post-scan présente nom de la pièce, pays, année, mintage, **fourchette de valeur estimée**, et un bouton "Add to Collection". La Collection tab a une feature signature : une **carte du monde interactive montrant la couverture géographique** des pièces possédées — une métrique de complétion spatiale qui feel plus rewarding qu'une liste à plat, et **directement applicable à Eurio** (21 pays eurozone). Les users peuvent grouper en sets custom, mais **pas de sets système curés** type "toutes les commémos françaises" — exactement là où Eurio peut différencier.

**Anti-pattern majeur** : les valorisations sont unreliable (même pièce scannée trois fois → prix wildly différents) → érode la confiance vite. Leçon pour Eurio : si on affiche un prix un jour, il doit être déterministe depuis une source fiable — et la mémoire `reference_numista_no_price` nous rappelle que Numista n'en expose pas. **Ne pas fake**.

Sources : [CoinSnap review](https://coin-identifier.com/blog/collector-apps-and-tools/coinsnap-may-let-you-down-heres-a-smarter-way-to-scan-your-coins), [Reading Room review](https://readingroom.money.org/mind-the-app-coinsnaps-pros-cons/)

## Duolingo — pure gamification reference

Ne scanne rien mais définit la grammaire gamification que tout le monde copie :
- **Streak** (flamme orange, toujours visible top bar)
- **XP** (jaune, per-session)
- **Hearts** (rouge, currency d'échec)
- **Leagues** (violet, compétition 7 jours, 10 tiers)

Chaque couleur est une mécanique. La home screen est un **lesson path vertical** — la progression EST la map, pas un écran séparé. **Stat de rétention clé** : les users avec 7-day streak sont 3.6× plus likely à rester long-terme, c'est pourquoi la flamme est l'élément UI le plus proéminent. Les leagues fournissent de la pression sociale sans nécessiter d'amis.

Sources : [Duolingo gamification (Orizon)](https://www.orizon.co/blog/duolingos-gamification-secrets), [Deconstructor of Fun](https://www.deconstructoroffun.com/blog/2025/4/14/duolingo-how-the-15b-app-uses-gaming-principles-to-supercharge-dau-growth)

---

## Synthèse — patterns qui s'appliquent à Eurio

### 1. Scan = écran d'accueil, pas onglet ni FAB
Shazam et CoinSnap convergent sur "caméra plein écran comme surface par défaut". Combiné à la directive user Eurio ("scan UX = QR scanner style"), c'est le signal le plus fort : l'app *s'ouvre* sur la caméra. Les autres destinations apparaissent via nav basse minimale.

### 2. Séparer 3 surfaces : Catalogue / Vault / Sets
Vivino (Explore vs Cellar), Pocket (all-cards vs binders), CoinSnap (catalogue vs collection) gardent tous "ce qui existe" distinct de "ce que je possède". Le catalogue bootstrappé JOUE d'Eurio est la surface référence ; le vault est perso ; les sets sont le pont. **Ne pas collapser.**

### 3. Grilles silhouette > progress bars pour la complétion de set
Les silhouettes de cartes manquantes de Pocket sont plus motivantes qu'un pourcentage parce qu'elles pointent une cible next. Afficher "Commémos françaises 2024" comme grille 20 slots avec 14 remplis et 6 silhouettes — c'est la boucle d'engagement.

### 4. Complétion spatiale/géographique comme second axe
La carte monde de CoinSnap est **le pattern le plus transférable** à une app de pièces eurozone. Une carte 21 pays avec niveau de fill par pays est une métrique uniquement numismatique qu'aucune progress bar ne peut répliquer. Différenciateur fort pour Eurio.

### 5. Post-scan = card full-screen, pas bottom sheet
Vivino et Pocket s'engagent tous deux sur un moment "you found this" plein écran. Les bottom sheets signalent "continue à scanner", les full screens signalent "célèbre cette trouvaille". **La bonne réponse pour Eurio** : full-screen si c'est nouveau ou complète un set ; toast minimal si déjà owned — la cérémonie matche l'enjeu.

### 6. Next-goal surfacing > trophy walls
Le move "Nearby Local Badges" d'Untappd 2025 et la streak always-visible de Duolingo s'accordent : montrer le *prochain* thing atteignable, pas l'étagère du passé. Le home d'Eurio doit surfacer "2 scans away from completing Slovenia 2023" au-dessus de toute stat lifetime.

### 7. Streak comme single always-visible retention hook
Duolingo prouve qu'un nombre persistant (flamme + count) surperforme les trophy walls pour le DAU. Un streak counter dans la top bar de l'écran scan — scanner n'importe quelle pièce (même dup) le garde vivant.

## Anti-patterns à éviter

- **Cérémonies non-skippables** (Pocket pack-opening) : célébrer les rares finds, mais toujours laisser les power users long-press/swipe-dismiss. La directive "QR-scanner-style" exige ça.
- **Valorisations peu fiables** (bug CoinSnap $0.57→$1538) : si Eurio montre un jour un prix/cote, il doit être déterministe depuis une référence. La mémoire `reference_numista_no_price` dit que Numista n'a pas de prix — **c'est un avantage** : on ne peut pas fake.
- **Home screens surchargés** (Vivino) : feature creep sur la surface d'entrée dilue l'action scan. Chaque élément non-scan sur la home doit justifier sa place vs "est-ce que ça aide à scanner ou voir la prochaine cible ?".
