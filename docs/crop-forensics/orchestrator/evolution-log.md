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

## 2026-05-27 — Théorie 02 (anti-B via Hough on raw) refuted comme signal pur

**Découverte** : sur DE/2 €/2010 (221 assets, 74 raws), `inner_feature_score`
sature (99 % ≥ 1.3, médian 3.82). Le filtre "circle contient bbox center"
écarte cat A mais ne distingue pas cat B (vrai inner feature undercrop)
de cat C (album multi-pièces, où la géométrie garantit un grand cercle
plausible englobant un bbox). TOP-30 ≈ 13 % cat B, ~70 % cat C → seuil
80 % loin.

**Cause racine** : un signal géométrique unique sur le raw ne peut pas
discriminer B vs C — les deux ont un grand cercle Hough et un bbox petit
à l'intérieur. Même antinomie que `composite × area_ratio` (refuted en
S3). Pour séparer B et C il faut un attribut externe (lot-flag, count
de coins détectés, ou OCR digits).

**Impact plan** :
- S5 marquée ❌ (refuted comme anti-B pur).
- S6 nouvelle session ajoutée : restreindre `inner_feature_score` aux raws
  `is_lot_suspected = 0` (singles), re-tester TOP-30 → ≥ 80 % cat B ?
- Renumérotation S6→S7 (reject auto), S7→S8 (v2 default sort), S8→S9
  (théorie 03).
- Si S6 échoue aussi : théorie 02 morte globalement, retour au backlog
  (OCR anti-A en priorité).

---

## 2026-05-27 — Théorie 02 morte aussi sur singles (S6 refuted)

**Découverte** : sur les vrais singles DE/2010 (`n_crops_detected=1`,
30 raws), TOP-30 de `inner_feature_score` ≈ 33-40 % cat B fort. Filtre
`is_lot_suspected=0` (167 raws) inutile car les collector folders ne
sont pas flaggés `lot`. Le signal corrèle visuellement avec l'undercrop
général mais ne discrimine pas cat B (inner ring bimétal) de cat D
(single coin tight crop) ni de mild undercrop.

**Cause racine** : `inner_feature_score` mesure "y a-t-il un cercle plus
gros que le bbox dans le raw" — c'est saturé sur les macros (zoom fort
sur la pièce → toujours un grand cercle contient le bbox). Pour
discriminer cat B strict il faudrait mesurer "y a-t-il un rim
circulaire à un radius > bbox_radius mais non capturé par le crop" —
plus sophistiqué.

**Impact plan** :
- S6 marquée ❌.
- Théorie 02 archivée globalement (refuted en post-filter ; reste
  viable en upstream re-rank Hough mais hors-scope).
- Sessions S10 (OCR anti-A) et S11 (décision produit) ajoutées comme
  options de continuation.
- Toutes les théories single-signal post-filter ont échoué (01 et 02).
  Insight clé : la séparation A/B/C/D pourrait nécessiter soit un
  upstream fix, soit un classifier supervisé léger.

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
