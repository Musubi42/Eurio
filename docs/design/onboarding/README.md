# Onboarding

> **Objectif UX** : amener l'user à scanner sa première pièce en moins de 15 secondes après l'ouverture de l'app. Pas de compte obligatoire. Pas de formulaire. Pas de login. Le scan EST la valeur ajoutée — on la montre en premier.
>
> **Inspiration** : Duolingo (valeur avant auth), Yuka (scan direct), apps de lecture de code-barres.

---

## Décisions tranchées

| Décision | Contexte |
|---|---|
| **Zéro auth au démarrage** | Voir [`_shared/auth-strategy.md`](../_shared/auth-strategy.md). L'app est 100% utilisable en mode guest. |
| **3 écrans max, skip dispo immédiatement** | Tiré du PRD §6. Le skip est visible dès l'écran 1, pas caché. |
| **Demande permission caméra sur l'écran 1** | Parce que l'écran 1 propose directement "scanne ta première pièce". La demande native Android se déclenche au tap sur le bouton. |
| **Pas de choix de langue** | L'app suit la locale Android. i18n géré en Compose. |

---

## Flow cible

```
Install → Open app
  ↓
[Écran 1] "Scanne ta première pièce"
  - Visuel : une pièce euro stylisée qui pulse légèrement
  - Headline : "Découvre ce que vaut chaque pièce dans ta poche"
  - CTA principal : "Commencer" (bouton plein, déclenche permission caméra)
  - CTA secondaire : "Passer" (texte discret en haut à droite)
  ↓
[Écran 2] "Construis ton coffre"
  - Visuel : aperçu du coffre avec ~6 pièces et un delta "+12%"
  - Headline : "Garde une trace de ta collection"
  - Sous-texte : "Valeur totale, progression, achievements — tout en local sur ton téléphone"
  - CTA : "Suivant"
  ↓
[Écran 3] "Complète des séries"
  - Visuel : une grille de 8 pièces d'un pays avec 2 manquantes en gris
  - Headline : "Débloque des achievements en complétant des séries"
  - CTA : "C'est parti" → direct sur l'onglet Scan
  ↓
[Onglet Scan] caméra active, prêt à scanner
```

## Règles

- **Skippable à tout moment.** Un tap sur "Passer" = on va direct sur l'onglet Scan, les 3 écrans ne s'affichent plus jamais.
- **Pas de compte demandé.** Ni maintenant, ni à la fin. Jamais pendant l'onboarding.
- **Pas de tutoriel sur le scan lui-même.** Le scan est censé marcher comme un QR code : l'user pointe, ça lit. Aucun besoin d'expliquer.
- **Pas de swipe entre les écrans.** Navigation avec un bouton "Suivant" pour éviter les gestes conflictuels avec les futurs écrans.

## Soft prompts post-onboarding

Ces prompts apparaissent **pendant l'usage normal**, pas pendant l'onboarding, et toujours de manière non-bloquante :

| Trigger | Prompt | Objectif |
|---|---|---|
| Après la 3ème pièce ajoutée au coffre | "Sauvegarde ta collection — un tap avec Google" | Déclenche Credential Manager (v2) |
| Après 48h d'usage sans notifications | "Active les alertes de complétion de série" | Permission notifications |
| Première ouverture avec Wi-Fi détecté | "Mettre à jour le catalogue des nouvelles pièces ?" | Active le delta fetch |

Ces prompts sont **skippables sans pénalité**. Un refus = on ne redemande pas avant 2 semaines minimum.

---

## Questions ouvertes

- [ ] Faut-il un écran "0" de sélection de marché (France / Allemagne / Europe entière) pour pré-filtrer les pièces affichées dans le coffre vide ? → probablement non, l'app est euro-zone par nature.
- [ ] Le visuel animé de la pièce qui pulse : quelle pièce montrer ? Une générique "€2" ou la commémorative du moment ? → probablement générique pour éviter de dater l'asset.
- [ ] Est-ce qu'on montre l'icône marketplace grisée dans l'onboarding pour teaser la v2, ou on cache totalement ? → décision produit, pas tech.
