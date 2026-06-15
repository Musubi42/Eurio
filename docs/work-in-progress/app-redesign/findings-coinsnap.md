# Findings CoinSnap — ce qui marche, ce qu'on prend

> Distillation orientée **décision** du [teardown complet](../coinsnap-teardown/README.md).
> Ici : ce que le PO a explicitement aimé/rejeté en testant CoinSnap, et ce qu'on en fait.
> (CoinSnap = `com.coinidentifyer.ai`, éditeur Glority — identifieur IA grand public.)

## ✅ Ce qui marche (et qu'on adopte)

| Finding | Pourquoi c'est bon | Où ça atterrit chez nous |
|---|---|---|
| **Fiche pièce dense MAIS propre** | Beaucoup d'info (valeur, mintage, caractéristiques, design) sans saturation : tout est hiérarchisé, aéré, esthétique. C'est LE modèle visé. | `coin-detail.md` — refondre notre hiérarchie |
| **Feed d'articles léger** | Bande discrète « Coin Talk » / pièce du jour : présence éditoriale sans alourdir. | `coffre.md` — bande articles légère |
| **Header patrimoine sobre** | € total · pièces · issuers en haut, lisible, pas 36 stats. | `coffre.md` — alléger nos stats |
| **Nav 3 zones + FAB caméra central** | Simple, le scan est roi. Valide notre shell — sauf qu'on a 4 onglets (Marché en trop). | shell — passer à 3 icônes (T1) |
| **Render physique « premium »** | Diagramme coté (Ø) qui rend une fiche technique désirable. | déjà amorcé (C3), à intégrer proprement |
| **Courbe de rareté** | Si la pièce est rare, une petite courbe de rareté → lecture immédiate « tu tiens un truc rare ». | `coin-detail.md` — nouvelle (distincte de la cote) |
| **Toggle Yours / Référence** | Comparer sa photo à la référence. Chez nous : **Réf = modèle 3D**, Yours = photo. PO le veut. | `coin-detail.md` — récupérer le toggle (mock photo en proto / réel Android) |
| **Bloc communauté « Stay Connected »** | Lien vers une communauté (Facebook chez eux) en bas de fiche → fidélisation. | `coin-detail.md` — bloc **Discord** |

## ❌ Ce qu'on rejette (anti-patterns)

| Anti-pattern CoinSnap | Raison |
|---|---|
| Paywall à chaque session + nudges permanents | Hostile. Notre modèle ≠ abonnement-identifieur. |
| Capture à shutter explicite | Nous = scan **continu** QR-style, sans bouton (doctrine). On garde notre scan. |
| Identification présentée avec aplomb (a sorti « Andorra » pour une Finlande) | Notre **honnêteté de confiance** (abstention par spread, gate denom) est un différenciateur. |
| Grading-par-photo survendu | Le grading fiable depuis une photo est douteux ; on ne promet pas ce qu'on ne tient pas. |

## 🟰 Ce qu'on fait DIFFÉREMMENT (notre force)

- **Le scan « identifié » animé** (halo, son, titre, pièce 3D qui se fixe) : on l'a déjà et **c'est mieux que CoinSnap**. On le garde, on le polit (pas de replay — T3).
- **Le récit immersif** de la pièce : CoinSnap n'a pas ça. À arbitrer : densité vs immersion (cf. `coin-detail.md`).
- **Le coffre gamifié** (best coins, jalons, carte à gratter) : à garder mais **alléger la façade**.

## Préférences PO explicites (2026-06-15)

1. **Fiche pièce** : partir de la **densité propre** de CoinSnap comme cible.
2. **Coffre actuel = trop lourd** : « pièces, 7, valeur totale, courbe, nb pièces, pays, séries, recherche, filtres, tris, ENFIN la pièce ». Trop. À dégraisser.
3. **Scan** : adore l'animation d'identification ; **pas de replay** ; tap = stop + fin ; puis **sheet qui monte → fiche full page**, navbar persistante.
4. **Retirer le Marché** de la nav → 3 icônes.
