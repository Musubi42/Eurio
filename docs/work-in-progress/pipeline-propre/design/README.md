# Design `/besoin` — phase D6

> Session du **2026-08-22** avec le PO. **Rien n'est implémenté.**
> Les maquettes sont **jetables** et ne doivent pas être copiées dans
> `studio-local`.

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
| file ouverte | 6 574 — dont **4 804 parqués (73 %)** |
| couvrable par la file | 908 exemplaires · 97 classes comblables |
| palier 1 à portée | 147 classes · ≈ 338 crops |
| à scraper | 288 classes, dont **274 jamais visées** |
| acquis hors banque | 1 451 crops → **76** exemplaires au rebuild |
| rendements mesurés | 6,6 annonces / exemplaire · 2,3 crops tranchés / validé |
