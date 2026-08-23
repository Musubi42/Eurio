# Design `/besoin` — phase D6

> Session de design du **2026-08-22** avec le PO. **Tout a été implémenté
> depuis** (lots 0-6, `643d6487..64409be8`).
>
> 👉 **Pour l'état du code et la suite : [`../REPRENDRE-ICI.md`](../REPRENDRE-ICI.md).**
> Ce dossier est la trace de la CONCEPTION, pas de l'état. Les maquettes sont
> **jetables** et ne doivent pas être copiées dans `studio-local`.

| fichier | quoi |
|---|---|
| [`DESIGN.md`](DESIGN.md) | le parcours, les 7 décisions, les états, le vocabulaire |
| [`maquette.html`](maquette.html) | maquette jetable — vue besoin, session, pêche O4, variante émission commune. Clair + sombre. Données réelles. |
| [`QUESTIONS-OUVERTES.md`](QUESTIONS-OUVERTES.md) | 8 points non tranchés, avec recommandation |
| [`PLAN-IMPLEM.md`](PLAN-IMPLEM.md) | 8 lots, chacun avec son test et son déploiement |

## Les trois choses à retenir

1. **O4c est un prérequis d'O2, pas son voisin.** Le filtre pays, actif par
   défaut, viderait entièrement **147 des 293 classes en besoin** et **82 % du
   palier 1**. Sans son désarmement automatique, la vue besoin affiche un écran
   faux le jour de son branchement.

2. **`have` ne bouge qu'au rebuild** — donc une file cadrée par le besoin
   ressert une classe qu'on vient de remplir. D8 (`accepted_pending`) est ce qui
   rend l'exigence du PO réalisable ; `need_only` seul ne suffit pas.

3. **Le premier exemplaire vaut ~9× les neuf suivants** depuis l'amorce médoïde.
   D7 pose deux paliers (couverture, puis profondeur) — sous réserve de la
   courbe « 1 exemplaire partout », qui reste à mesurer (Q1).

## Les chiffres de référence

Banque `a55e6594da3247ec80bc609f93342f51`, `built_at 2026-08-22 18:06:22`.
**Relancer la requête, ne pas recopier le nombre** — la banque a été rebâtie
deux fois pendant cette session.

```bash
cd ml && ./.venv/bin/python -c "
import sqlite3, sys, collections; sys.path.insert(0,'.')
from shared.class_need import all_needs
c = sqlite3.connect('file:state/eurio.replica.db?mode=ro', uri=True)
n = all_needs(c, anchors_kind='2eur_all', encoder_version='dinov2-vitl14')
print(len(n), dict(collections.Counter(x.bottleneck for x in n)), sum(x.need for x in n))"
# 671 {'pleine': 90, 'review': 293, 'scrape': 288} 4066
```

| | |
|---|---:|
| couverture (`have ≥ 1`) | 250 / 671 |
| Σ `need` | 4 066 |
| file ouverte | 6 371 — dont **5 041 parqués**, 1 985 écartés par l'ère, 1 236 par le pays |
| servis (`pending_scoped`) | **3 150** |
| couvrable par la file | **557** exemplaires |
| palier 1 à portée | **92** classes (dont 30 à marge ≥ 0,10) |
| à scraper | **349** classes, dont **323 jamais visées** |
| acquis hors banque | 1 610 crops → **184** exemplaires au rebuild |
| rendements mesurés | 6,6 annonces / exemplaire · 2,3 crops tranchés / validé |

⚠️ Les chiffres de la session de design (908 à portée, 147 classes au palier 1)
étaient calculés **avant** que `pending_scoped` porte les filtres O4. L'écart
n'est pas une régression — c'est du travail qui n'existait pas.
