# Evolution log — découvertes qui ont muté la vision/plan

> Append-only. Format : `YYYY-MM-DD — découverte — impact sur le plan`.
> Garde-le sous 150 lignes : ancien stuff peut être archivé dans
> `evolution-log.archive.md` si ça déborde.

---

## 2026-05-26 — Théorie 04 (scorer composite global) refuted

**Découverte** : un score unifié `composite × area_ratio_factor` ne
permet pas de séparer cat B (inner feature undercrop) de cat C (album
multi). Les deux ont area_ratio bas et passent les mêmes thresholds.

**Cause racine** : composite mesure "ressemble à une pièce", area_ratio
mesure "le crop est gros vs raw". Multiplier ne discrimine pas l'origine
du score bas.

**Impact plan** :
- Session S3 (unified v2) marquée ✅ avec verdict marginal.
- Sessions S4 (anti-A bg_uniformity) et S5 (anti-B max_hough_circle)
  passent en priorité — il faut **2 signaux indépendants**, pas un
  composite.
- Session S6 (reject auto 2 thresholds) ajoutée comme livraison
  conditionnelle à S4/S5.
- Théorie 04 marquée refuted dans `theories/README.md`.

---

## 2026-05-26 — composite is_coin asymétrique (TOP ✓, BOTTOM ✗)

**Découverte** : sur le composite v1 (théorie 04 step 1), le TOP 30 = 83
% cat D (clean wins) mais le BOTTOM 30 = 30 % cat A+B (pollué par cat C).

**Cause racine** : composite est sensible au rim_peak + metalness, donc
un crop tiny d'un macro shot bimétal a des features fortes → score
haut. Même un crop sur fond noir uniforme avec une mini-pièce bien
visible scoore haut.

**Impact plan** :
- Composite v1 adopté comme **tri par défaut** (S2 ✅) car bon pour TOP.
- Plus tenté de l'utiliser pour reject auto.
- Insight clé pour S4 : un signal **bg_uniformity** doit attaquer cat A
  spécifiquement, indépendant du composite.

---

## 2026-05-26 — composite TOP-scores sont souvent UNDERCROP SUSPECTS

**Découverte** : en visuel sur DE-2010, les cards avec composite 0.93+
ont area_ratio < 5 % (flag undercrop). Le crop "ressemble" à une pièce
parce qu'il EST un sous-extrait d'une vraie pièce, juste trop zoomé.

**Cause racine** : composite et area_ratio sont orthogonaux. Composite
juge le **contenu** du crop ; area_ratio juge la **proportion** vs raw.

**Impact plan** :
- A confirmé que S4 (anti-A) et S5 (anti-B) doivent être **séparés**.
- A motivé l'écriture de cet orchestrateur — la session N+1 doit
  hériter de ce finding pour ne pas refaire l'erreur de scoring global.

---

## 2026-05-26 — Théorie 01 (anti-A fond/luminosité) refuted

**Découverte** : deux proxies testés, les deux échouent.
(1) `bg_uniformity` (std hors disque) = 0 pour 80.9 % des crops — normalize_snap
masque toujours le fond en noir avant stockage, donc le signal est dégénéré.
(2) `near_white_ratio` (V > 220 dans disque intérieur) — TOP-30 ≈ 10 % cat A,
reste = pièces euro surexposées ou bimétal (cat D). Seuil win 80 % non atteint.

**Cause racine** : les pièces euro photographiées avec flash/lightbox ont des
zones métalliques spéculaires avec V >> 220, indiscernables du blanc papier d'un
strip. Le signal luminosité est corrélé à l'exposition photographique, pas au
type d'objet.

**Impact plan** :
- S4 marquée ❌ (refuted).
- S5 (anti-B Hough on raw) reste la prochaine session prioritaire.
- **Backlog anti-A** : OCR léger sur la bbox (présence de digits → cat A) reste
  viable mais complexe ; reporté après S5.

---

## Template pour futures entrées

```
## YYYY-MM-DD — <one-liner du finding>

**Découverte** : <fait observé + mesure>.

**Cause racine** : <pourquoi, en 1-2 phrases>.

**Impact plan** :
- Session SN marquée <status>
- Session SN+M ajoutée / retirée / repriorisée
- Théorie X marquée <status> dans theories/README.md
```
