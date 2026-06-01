# Consolidation psycho → UX (snapshot transitoire)

> **Doc transitoire.** Synthèse opérationnelle de ce qu'on a **aligné** en discutant, reliée aux
> recherches. **État : après recherche `05`** (juice). Recherches **6, 7, 8 encore à faire** →
> ce doc évoluera. **Rien n'est figé** (« on ne fiche rien ») : c'est une photo de l'alignement,
> pas une charte verrouillée.
>
> Voisins : [`psychologie-retention.md`](./psychologie-retention.md) (doc vivant / grille) ·
> [`psychologie-experience-mapping.md`](./psychologie-experience-mapping.md) (surface → drive) ·
> [`psychologie-documentation/`](./psychologie-documentation/) (recherches brutes).

## 1. Carte du chantier

| Recherche | Sujet | Statut |
|---|---|---|
| [`01`](./psychologie-documentation/01-motivations-baseline.md) | Motivations (baseline) | 🟢 |
| [`02`](./psychologie-documentation/02-qui-paie-en-especes.md) | Audience / supply (SPACE) | 🟢 |
| [`03`](./psychologie-documentation/03-comparaison-sociale-classement.md) | Comparaison sociale / classement | 🟢 |
| [`04`](./psychologie-documentation/04-streak-vs-defis.md) | Streak vs défis | 🟢 |
| [`05`](./psychologie-documentation/05-juice-du-scan.md) | Juice du scan | 🟢 |
| [`06`](./psychologie-documentation/06-completion-double-axe.md) | Complétion & double axe (+ carte à gratter) | 🟢 |
| [`07`](./psychologie-documentation/07-sens-storytelling.md) | Sens & storytelling | 🟢 |
| [`08`](./psychologie-documentation/08-marque-positionnement.md) | Marque & positionnement | 🟢 |

> **MàJ** : les 8 recherches sont désormais faites. Les conclusions de 06-08 (double Zeigarnik +
> sous-sets + carte à gratter · IKEA effect natif + transportation · Eurio parapluie + « collection
> sans manipulation ») restent **à tisser** dans le flow/mapping lors d'une prochaine passe.

---

## 2. Le flow UX du scan, étape par étape × levier psychologique

Le cœur de la consolidation : chaque micro-étape branchée sur le biais qu'elle déclenche et la
recherche qui le fonde. (« Quand on fait cette animation → on trigger tel levier. »)

| # | Étape UX | Ce qui se passe | Levier psychologique | Source |
|---|---|---|---|---|
| 1 | **Ouverture app** | l'écran de scan **est** l'accueil ; pas de menu avant l'acte | Fogg : *Ability max* (l'acte central est immédiat) | [`04`](./psychologie-documentation/04-streak-vs-defis.md) · mémoire `feedback_scan_ux` |
| 2 | **Présenter la pièce** | scan continu façon QR, **pas de bouton/guide** | flow / friction nulle ; habitude par facilité | mémoire `project_scan_single_coin` |
| 3 | **Reconnaissance** | bon scan détecté → point de bascule | — (charnière) | — |
| 4 | **Transition diégétique** | freeze frame caméra → **morph du 3D à la position/taille exactes** de la pièce → *flick-spin* (lancée au pouce) → décélération | **anticipation = dopamine** ; *pull éthique* (incertitude **épistémique**, zéro hasard) | [`05`](./psychologie-documentation/05-juice-du-scan.md) |
| 5 | **Settle** | la pièce se pose → **haptique ~400 ms + son « clink »** synchronisés sur l'arrêt | **peak-end rule** (l'arrêt = le pic mémorisé) ; haptic reward ~400 ms | [`05`](./psychologie-documentation/05-juice-du-scan.md) |
| 6 | **Reveal** | **héros 3D** (haut-centre, rotatable au doigt) + **une carte-lentille** : Découverte + ligne de complétion + 1 accent contextuel | **stratification** anti-surcharge (Miller/Hick) ; servir **≥3 drives** d'un coup | [`05`](./psychologie-documentation/05-juice-du-scan.md) · [`01`](./psychologie-documentation/01-motivations-baseline.md) |
| 7 | **Lentilles** | **swipe latéral** pour feuilleter Histoire / Rareté / Valeur / Complétion ; épingle optionnelle ou « dernier-état » | **autonomie** (SDT) sans profiling ; progressive disclosure | [`01`](./psychologie-documentation/01-motivations-baseline.md) · [`05`](./psychologie-documentation/05-juice-du-scan.md) |
| 8 | **Accent contextuel** | piloté par *la pièce* : rareté « 3ᵉ à scanner / 2% détiennent » · série « complète X/Y » · valeur « ~12€ TTB » | rareté → **N-effect** + comparaison descendante ; complétion ; sécurité financière | [`03`](./psychologie-documentation/03-comparaison-sociale-classement.md) · `06` · [`01`](./psychologie-documentation/01-motivations-baseline.md) |
| 9 | **Profondeur** | tap → **page de la pièce** : histoire complète, cote par qualité, série entière | **progressive disclosure** (le pic resserré au scan, la profondeur à la demande) | [`05`](./psychologie-documentation/05-juice-du-scan.md) |
| 10 | **Jalon ?** | si l'événement le mérite → **célébration** (catégorie dédiée) | **économie des célébrations** / peak-end (le pic reste rare = il reste un pic) | [`05`](./psychologie-documentation/05-juice-du-scan.md) |

**Garde-fou vitesse** : sur une session « vide ton bocal », étapes 4-5 doivent rester **courtes
(~0,8-1,2 s) + skippables (tap pour poser)** + **version allégée pour doublons/scan rapide**.
Sinon l'anticipation devient corvée (anti-Fogg).

---

## 3. Décisions de design alignées

### Lentilles épinglables
- **Défaut excellent** (Découverte d'abord, sert 3 drives) → 90% n'y touchent jamais.
- Exploration par **swipe** (pas de menu), points indicateurs.
- **Épingle** optionnelle (punaise) **ou** simple mémoire du *dernier-état* (≠ profiling, R0-safe).
- Option finition : **1 question d'onboarding** « histoire / valeur / compléter ? » → défaut initial,
  modifiable (autonomie SDT).

### Transition scan → 3D
- **Diégétique** : le rendu *continue* le réel → bascule réalité→jeu (notre pack-opening éthique).
- **Pas cher** : réutilise le modèle 3D existant, **pas de décor thématique requis** (le drame =
  physique du spin + lumière + settle).
- **Morph sans saut** (match position/taille/rotation au scan), **settle = pic** (haptic+son),
  **rapide + skippable + version light** (doublons/rapide).

### Économie des célébrations — 4 catégories **à plat** (pas des niveaux)
1. **Nouvelle pièce** — le reveal standard, le plus léger.
2. **Set complété** — banderole, habillage du set.
3. **Pays complété** → **carte à gratter** (cf. ci-dessous).
4. **Exploit de rareté/statut** — 1ᵉʳ à compléter, légendaire, 1ᵉʳ à scanner ce mois (N-effect).

Chacune : thématique / animation / banderole / data propres. La **rareté garde le pic spécial**.

### Carte à gratter (eurozone)
Référent : *scratch maps* de voyageurs. On **gratte** le contour d'un pays complété → des infos
se **révèlent dans le contour** (découverte + progressive disclosure). Fait de la **carte eurozone
l'asset partageable n°1** (différenciateur). → à approfondir en recherche `06`.

### Notifications
**Pas de quotidien.** Fréquence **adaptative à la fréquence d'ouverture**, **configurable**,
**qualité > régularité** : la notif est un **cadeau** (« ça fait longtemps, agréable surprise »),
jamais un rappel anxiogène.

---

## 4. Direction & vision (non figée)

> **Parce qu'Eurio est *réel*, on offre le frisson du « pull » sans aucun des poisons** — pas de
> fausse supply, pas de hasard/casino, pas de streak punitive, pas de FOMO manipulateur. Chaque
> poison qu'on *refuse*, on peut se le permettre, car notre payload est authentique (vraie pièce,
> vraie histoire, vraie rareté, vraie valeur, vraie géographie).

→ À la fois **principe de design** et **positionnement de marque** : *le jeu de collection qui ne
te manipule pas.* (À confronter en recherche `08`.)

## 5. Règles émergentes (non fichées)

1. **Acte rare vs rituel renouvelable** — jamais accrocher l'engagement au scan supply-gated.
2. **Asymétrie positive** — gagner > ne pas perdre ; pas de punition par loss aversion.
3. **Pull éthique** — anticipation + reveal + multisensoriel, **zéro hasard/near-miss** ; dopamine = incertitude épistémique.
4. **Défaut excellent + lentille optionnelle** — servir ≥3 drives, autonomie, pas de profiling.
5. **Stratifier, pas surcharger** — héros + ≤3 + profondeur à la demande.
6. **Économie des célébrations** — le pic réservé aux jalons ; catégories distinctes.
7. **Filtre SDT** sur toute mécanique (compétence / autonomie / relatedness).
8. **Local > global** + **N-effect** — la rareté comme levier de statut.
9. **Notif = cadeau, pas rappel** — fréquence adaptative, qualité > régularité.
10. **Le garde-fou éthique EST le positionnement** — on refuse le dark pattern par marque, pas par contrainte.

## 6. Reste à chercher

- `06` complétion & double axe (absorbe la **carte à gratter**) · `07` sens & storytelling · `08` marque & naming.
- **2ᵉ ordre** (à noter) : design de l'économie des célébrations, design de la carte eurozone,
  onboarding (la question-lentille), profondeur des mécaniques sociales/partage (touche la mission Croissance).
