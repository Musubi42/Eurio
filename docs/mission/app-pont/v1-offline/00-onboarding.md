# Vue — Onboarding (v1-offline)

> Doc-pont psychologie → app. Périmètre **v1-offline**. Overview : [`../README.md`](../README.md).

## 1. Rôle

> Faire vivre **la première capture magique** en < 1 min, créditer une avance de collection, et
> poser (en douceur) la **question-lentille**. La première impression *est* la promesse.

**Drive primaire** : Découverte. L'onboarding ne *raconte* pas l'app — il la *fait vivre* (premier scan réel ou guidé).

## 2. Leviers psy mobilisés

| Levier | Ce qu'il fait | Source |
|---|---|---|
| **Fogg B=MAP** | mener à l'acte vite ; pas de mur avant la valeur | [`04`](../../psychologie-documentation/04-streak-vs-defis.md) |
| **Endowed progress** | la 1ʳᵉ pièce **crédite déjà** la barre (« tu as commencé ta collection ! ») → motive à continuer | [`06`](../../psychologie-documentation/06-completion-double-axe.md) |
| **Peak-end rule** | la 1ʳᵉ capture doit être un **pic** (juice) — on s'en souvient | [`05`](../../psychologie-documentation/05-juice-du-scan.md) |
| **IKEA effect** | le 1ᵉʳ scan = 1ᵉʳ acte *mérité* → début d'attachement (pic sur la pièce réelle chassée ; plus embryonnaire sur le scan démo) | [`07`](../../psychologie-documentation/07-sens-storytelling.md) |
| **Autonomie (SDT)** | la question-lentille = un *choix*, pas un profilage | [`01`](../../psychologie-documentation/01-motivations-baseline.md) |

## 3. Flow × biais

| # | Étape | Levier |
|---|---|---|
| 1 | **Splash** (auto-advance ~1,4 s) | amorce de marque |
| 2 | **3 slides** : « Scanne » · « Ton coffre » · « Complète des séries » (montrent une collection *déjà* avancée, pas vide) | aperçu aspirationnel / social proof (réduction de l'incertitude) |
| 3 | **Question-lentille** (optionnelle, skippable) : *« Ce qui te branche dans les pièces ? Histoire · Valeur · Compléter »* → pose le **défaut** de reveal | autonomie (SDT) |
| 4 | **Pre-prompt permission caméra** (pattern Duolingo : on explique *avant* le dialogue natif) | confiance, friction maîtrisée |
| 5 | **1ᵉʳ scan** (guidé si pas de pièce sous la main : mode démo) → reveal **célébré** | peak-end + IKEA (fort si pièce réelle, embryonnaire si mode démo) |
| 6 | **« Tu as commencé ! 1 pièce, X pays à découvrir »** → entrée dans l'app | endowed progress + Zeigarnik (boucle ouverte) |

## 4. Contenu / interactions

- Slides **courtes, swipe**, bouton « passer » toujours visible.
- Question-lentille : 3 chips, un tap, **« plus tard » possible** (défaut = Découverte).
- Mode démo si pas de pièce : scanner une pièce d'exemple pour *sentir* le geste.

## 5. Garde-fous

- **Court + skippable** : jamais un tunnel ; l'acte (scan) prime sur le discours.
- **Pas de demande de compte** (v1-offline).
- Permission caméra : pre-prompt honnête, l'inline fallback reste si « plus tard ».
- La question-lentille **n'est pas** un profilage — un choix réversible (Réglages/Profil).

## 6. Drives servis

Découverte ⬤ · Complétion ◑ (endowed progress) · Sens ◔ · autonomie (transverse).

## 7. À proto'er (R1)

La **question-lentille** (nouvelle) et le **reveal célébré du 1ᵉʳ scan** (lié à `02-reveal`). Le reste
(splash, 3 slides, pre-prompt) existe déjà en proto — à **confronter au merge**, pas à re-designer.

**Mode démo** (scan guidé sans pièce physique, état distinct de `scan-idle.html`) — interaction nouvelle, aucun équivalent proto existant. ❌ Bloque le démarrage du code Android correspondant.
