# Vue — Scan (l'acte) (v1-offline)

> Doc-pont psychologie → app. Périmètre **v1-offline**. Overview : [`../README.md`](../README.md).
> Séparé de [`02-reveal.md`](./02-reveal.md) (le reveal est assez lourd pour vivre seul).

## 1. Rôle

> **L'acte central** : capturer une vraie pièce. Du viseur au *settle* de la pièce 3D. Le geste doit
> être **trivial à déclencher** (Fogg) et **inoubliable à vivre** (juice) — notre pull éthique.

**Drive primaire** : Découverte/anticipation. C'est l'**acte rare** (supply-gated) — on le rend
magique, jamais obligatoire.

## 2. Leviers psy mobilisés

| Levier | Ce qu'il fait | Source |
|---|---|---|
| **Fogg B=MAP** (Ability max) | scan = accueil, scan **continu façon QR**, **pas de bouton** | [`04`](../../psychologie-documentation/04-streak-vs-defis.md) · `feedback_scan_ux` |
| **Pull éthique** (incertitude *épistémique*) | l'anticipation du *settle* + reveal = dopamine, **zéro hasard/near-miss** | [`05`](../../psychologie-documentation/05-juice-du-scan.md) |
| **Game feel / juice** | anim + audio + haptique → geste satisfaisant | [`05`](../../psychologie-documentation/05-juice-du-scan.md) |
| **Peak-end rule** | le **settle** (l'arrêt de la pièce) = le pic mémorisé | [`05`](../../psychologie-documentation/05-juice-du-scan.md) |
| **IKEA effect** (labeur signifiant) | scanner = petit acte *mérité* → attachement (≠ tap insignifiant) — à condition que la flick-spin reste un geste **initié par l'utilisateur**, jamais déclenché automatiquement (cf. `07` §Garde-fous) | [`07`](../../psychologie-documentation/07-sens-storytelling.md) |

## 3. États

`Idle (viseur)` → `Détection` → `Capture validée` → **`Transition 3D`** → **`Settle`** → (passe la main à [`02-reveal`](./02-reveal.md)).
→ `No match` → (état non-identifié — hors scope v1-offline ou renvoi explicite)
→ Après `Capture validée` : → `Doublon` → version light (cf. §6)

## 4. Flow × biais

| # | Étape | Ce qui se passe | Levier |
|---|---|---|---|
| 1 | **Viseur (accueil)** | caméra plein écran, scan continu, **pas de bouton/guide** | Fogg : Ability max |
| 2 | **Détection** | reconnaissance en continu ; feedback discret de **confiance du matching** (pulse : « ça chauffe ») — signal qualité du match, **pas** un guide de positionnement spatial | flow, friction nulle |
| 3 | **Capture validée** | bon match → on **gèle la frame caméra** | charnière |
| 4 | **Transition diégétique** | le 3D apparaît **à la position/taille/rotation exactes** de la vraie pièce (morph sans saut) → **flick-spin** (lancée au pouce) qui décélère | **anticipation = dopamine** ; pull éthique ; IKEA |
| 5 | **Settle** | la pièce se **pose** → **haptique ~400 ms + son « clink »** synchronisés sur l'arrêt | **peak-end** ; haptic reward |

## 5. Contenu / interactions

- **Aucun chrome** parasite sur le viseur (≠ top-bar streak — *supprimée*, cf. merge).
- Le 3D est **rotatable/zoomable au doigt** dès le settle (continuité avec le reveal).
- Debug mode scoped scan (7-tap badge version) — *préservé du existant au merge*.

## 6. Garde-fous

- ❌ **Zéro hasard** (pas de tirage : on scanne une pièce qu'on tient).
- ⏱️ **Vitesse + skippable** : transition **~0,8-1,2 s** + **tap pour poser** + **version light** pour
  doublons/scan rapide (session « vide ton bocal » ne doit jamais devenir une corvée — une corvée détruit l'Ability, Fogg [`04`](../../psychologie-documentation/04-streak-vs-defis.md)).
- 📳 Haptique/son **qualitatifs**, jamais trompeurs.

## 7. Drives servis

Découverte ⬤ (anticipation) · Sens ◔ (l'objet *mérité*).

## 8. À proto'er (R1)

La **transition diégétique** caméra → 3D (morph + flick-spin + settle synchronisé) — **plus riche**
que les scènes `scan-*.html` actuelles. La suite (le reveal) → [`02-reveal`](./02-reveal.md).
