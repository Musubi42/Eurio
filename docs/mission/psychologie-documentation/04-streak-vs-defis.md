# 04 — Streak vs défis & la ligne du dark pattern

> **Question de recherche** : faut-il une **streak** (continuité type Duolingo/Snapchat) dans
> Eurio, ou des **défis adaptatifs** (l'instinct de Raphaël) ? Que dit la recherche sur ce qui
> *retient* vs ce qui *manipule/épuise* ? Et où passe la ligne du dark pattern — sachant notre
> contrainte dure : **on ne peut pas exiger un scan quotidien** (supply-gated).
>
> **Date** : 2026-06-01 · **Catégorie** : 3 (streak / aversion à la perte) ·
> **Statut** : 🟢. Débloque la **question ouverte n°1** du [mapping](../psychologie-experience-mapping.md).

---

## Ce que la streak fait de bien (et pourquoi c'est si fort)

- **Aversion à la perte** (Kahneman & Tversky) : une perte fait ~**2× plus mal** qu'un gain
  équivalent. À 180 jours, l'user n'est pas motivé par *atteindre 181*, mais par *ne pas perdre
  180* ([JustAnotherPM](https://www.justanotherpm.com/blog/the-psychology-behind-duolingos-streak-feature),
  [Yu-kai Chou](https://yukaichou.com/gamification-study/master-the-art-of-streak-design-for-short-term-engagement-and-long-term-success/)).
- **La streak convertit l'effort en identité** : « 300 jours » n'est pas un score, c'est *qui tu
  es* — la casser, c'est casser le soi.
- **Effet rétention massif** : users avec streak 7+ jours retiennent à **2,4×** le taux de ceux
  sans streak ([Trophy case study](https://trophy.so/blog/duolingo-gamification-case-study)).
- **2025, 6 études, ~4500 participants** : on produit *plus* avec une incitation en streak
  qu'avec une récompense stable plus grosse ([Psychology Today / U. Delaware](https://www.psychologytoday.com/us/blog/ulterior-motives/202306/how-broken-streaks-sap-motivation),
  [phys.org](https://phys.org/news/2024-03-streaks.html)).

## Ce que la streak casse (et pourquoi c'est dangereux pour nous)

- **L'anxiété croît avec la longueur** : plus la streak est longue, plus on est *terrifié* de la
  perdre — la fierté devient peur ([Cohorty](https://blog.cohorty.app/the-psychology-of-streaks-why-they-work-and-when-they-backfire/)).
- **La casse est dévastatrice → churn** : quand la streak saute, beaucoup **n'recommencent jamais**.
  Duolingo voit *plus* de churn après une casse. Les streaks rigides dopent le court terme mais
  **amplifient l'abandon** au premier lapsus inévitable.
- **Éviction de la motivation intrinsèque** : quand la récompense externe (la streak) devient le
  *moteur principal*, le plaisir intrinsèque baisse (SDT, cf. [`01`](./01-motivations-baseline.md)).
  Test cruel (Fogg) : un user qui grind « pour ne pas perdre sa streak » ne construit pas une
  *pratique* — il construit une **tolérance à l'app**
  ([Nudge Notes](https://medium.com/nudge-notes/the-science-behind-habit-forming-products-b0be52dec61e)).
- **Notre tueur** : la streak quotidienne suppose une **action quotidienne possible**. Notre acte
  central (scanner une pièce neuve) est **supply-gated** → une streak-scan **punit** mécaniquement
  (impossible de trouver une pièce neuve chaque jour). C'est un non-départ.

## La ligne du dark pattern

Les streaks/limited-time exploitent **culpabilité sociale, FOMO, biais d'engagement** ; ils entrent
en **tension avec l'autonomie** (besoin SDT), surtout chez les **jeunes/vulnérables**
([Springer — hostility framework](https://link.springer.com/article/10.1007/s10676-025-09856-z),
[SagePub — dark patterns in games](https://journals.sagepub.com/doi/10.1177/15554120251319173)).
Notre **R0 « pas de dette »** s'étend ici en **dette éthique** : on refuse le manipulatoire.

Côté **lumineux**, ce qui reste éthique (recherche convergente) :
- **Du « slack »** : freezes, grâces, retries. Recherche **Penn + UCLA** : offrir un peu de mou est
  *plus* motivant qu'une règle rigide. Le **Streak Freeze de Duolingo a réduit le churn de 21%**
  des users à risque, en baissant l'anxiété *sans* tuer la loss aversion.
- **Transparence** : dire comment la mécanique marche, son but.
- **Cadrer en fierté/identité, jamais en peur** (« regarde ton chemin », pas « tu vas TOUT perdre »).
- **Pas de pression temporelle artificielle** ni de compteur qu'on ne peut pas alimenter.

## Le cadre de décision — Fogg B=MAP

Comportement = **Motivation × Ability × Prompt** ([Fogg](https://www.behaviormodel.org/),
[Yu-kai Chou](https://yukaichou.com/behavioral-analysis/bj-fogg-extended-part-1-of-2/)). Deux leçons :
1. **Augmenter l'Ability (rendre l'action facile) bat presque toujours pomper la Motivation.**
   → l'action quotidienne doit être **triviale** (ouvrir, voir, 1 tap), pas « trouve une pièce ».
2. **Ce sont les émotions qui créent l'habitude, pas la répétition.** → chaque retour doit livrer
   une **micro-émotion positive** (découverte, progrès), pas une corvée anti-peur.

---

## Recommandation pour Eurio

| Option | Verdict | Pourquoi |
|---|---|---|
| **Streak-scan quotidienne** | ❌ **Non** | supply-gated → punit ; casse → churn ; dark pattern |
| **Streak « engagement » quotidienne** sur un rituel renouvelable trivial (ouvrir + voir pièce du jour) | ⚠️ **Avec garde-fous, optionnel** | possible *si* freezes/slack généreux, cadré fierté, jamais peur ; mais risque « tolérance à l'app » → à tester, pas un pilier |
| **Défis adaptatifs** (mensuels/hebdo, asymétrie positive) | ✅ **Pilier** | rien à perdre / bonus à gagner → pas d'anxiété ni dark pattern ; goal-gradient + complétion (cat. 6) ; gamifie l'**acquisition** réelle (cat. 2) |

**Tranché** : l'instinct de Raphaël est **psychologiquement le plus sain**. On fait des **défis
adaptatifs le pilier**, pas une streak rigide.

**Comment garder le meilleur de la streak sans le poison :**
- **Asymétrie positive** : le défi non fait ne *retire* rien (pas de loss aversion punitive) ;
  le faire *donne* (badge/grade/point). On garde la dopamine, on jette la peur.
- **Cadence forgiving** : si on veut un signal de régularité (« cadence collectionneur »), il est
  **généreusement freezé** et **non gated sur l'acte rare** — il s'accroche au rituel renouvelable.
- **Adaptatif sans profiling** : la cible du défi se cale sur **l'état du coffre** (un débutant et
  un avancé n'ont pas le même « scanne 10 nouvelles »), pas sur un profil psychologique (R0).
- **Action quotidienne = Ability max** : la boucle quotidienne n'est *jamais* « scanne », c'est
  « ouvre → pièce du jour / son histoire / 1 tap » — facile, émotion positive (Fogg).
- **Levier social honnête** (le vrai moteur Snapchat/Duolingo) : partager une complétion, « 100ᵉ
  jour de collectionneur », comparer aux amis (relatedness SDT) — fierté, pas culpabilité.

## Ce qu'on en retient (→ doc vivant + mapping)

1. **Défis adaptatifs = pilier de rétention**, pas la streak rigide. Réponse à la **question
   ouverte n°1** du mapping.
2. **Asymétrie positive** comme règle d'or (gagner > ne pas perdre) — c'est notre garde-fou
   anti-dark-pattern par défaut.
3. Si « cadence/streak » un jour : **forgiving (freezes), cadrée fierté, non-supply-gated, testée**
   — jamais imposée comme pilier.
4. **Boucle quotidienne = Ability max + émotion positive** (Fogg), pas la peur de perdre.
5. Le **social** est le levier durable (relatedness), à brancher sur complétion/partage (cat. 4/6).

## Sources

- Duolingo / loss aversion : [JustAnotherPM](https://www.justanotherpm.com/blog/the-psychology-behind-duolingos-streak-feature) · [Yu-kai Chou — streak design](https://yukaichou.com/gamification-study/master-the-art-of-streak-design-for-short-term-engagement-and-long-term-success/) · [Trophy case study](https://trophy.so/blog/duolingo-gamification-case-study) · [Duolingo blog — habit](https://blog.duolingo.com/how-duolingo-streak-builds-habit/)
- Côté sombre / churn : [Psychology Today (U. Delaware)](https://www.psychologytoday.com/us/blog/ulterior-motives/202306/how-broken-streaks-sap-motivation) · [phys.org](https://phys.org/news/2024-03-streaks.html) · [Cohorty](https://blog.cohorty.app/the-psychology-of-streaks-why-they-work-and-when-they-backfire/) · [Yu-kai Chou — burnout](https://yukaichou.com/gamification-analysis/streak-design-gamification-motivation-burnout/)
- Dark patterns / éthique : [Springer — hostility framework](https://link.springer.com/article/10.1007/s10676-025-09856-z) · [SagePub — dark patterns in games](https://journals.sagepub.com/doi/10.1177/15554120251319173) · [Medium — dark side of gamification](https://medium.com/@jgruver/the-dark-side-of-gamification-ethical-challenges-in-ux-ui-design-576965010dba)
- Habit / Fogg : [behaviormodel.org](https://www.behaviormodel.org/) · [Yu-kai Chou — Fogg](https://yukaichou.com/behavioral-analysis/bj-fogg-extended-part-1-of-2/) · [Nudge Notes](https://medium.com/nudge-notes/the-science-behind-habit-forming-products-b0be52dec61e)
