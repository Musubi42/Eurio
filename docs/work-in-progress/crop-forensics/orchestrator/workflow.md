# Workflow opérationnel

## Cycle d'une session

```
1. ORIENTATION       (~5 min)  charger les 5 files orchestrator/
2. THÉORIE           (~10 min) lire la session courante de plan.md
3. EXPÉRIENCE        (~30-60 min) coder + run + mesure
4. INSPECTION        (~10-20 min) chrome MCP screenshot + lecture
5. VERDICT           (~5 min)  écrire experiments/NN-*.md
6. EVOLUTION         (~5 min)  update plan.md + evolution-log.md
7. COMMIT            (~3 min)  git add + commit message structuré
8. HANDOFF           (~2 min)  écrire la prochaine session dans plan.md
```

Total ≈ 1h-2h. Si tu dépasses 2h, c'est trop : split en sessions.

## Lecture & exploration — éviter la surcharge contexte

### Quand utiliser Read direct
- Fichiers ≤ 200 lignes
- Code source ciblé que tu vas modifier
- Sidecar JSON < 50 KB

### Quand utiliser un subagent (`Agent` tool)
- Recherche dans le repo (`Explore` agent, "trouve les fichiers qui...")
- Question SOTA / web research (`general-purpose` + WebSearch)
- Classification visuelle de N screenshots (donne l'image au subagent
  avec consigne précise de retour)
- Gros JSON / log (sidecar > 100 KB) — donne le path et le pattern à
  extraire, retour = ≤ 30 lignes

Le subagent te renvoie une synthèse courte — tu ne pollues pas ton
contexte avec les données brutes.

## Chrome MCP — l'œil

### Screenshot pour mesurer

1. `mcp__chrome-devtools__navigate_page` à l'URL bench
2. `sleep 6-15s` pour laisser charger les images (ATTENTION : `loading="lazy"` empêche le préchargement off-viewport, **retire-le** dans les HTML samplers avec `sed` avant screenshot)
3. `mcp__chrome-devtools__take_screenshot` avec `fullPage: true`
4. `Read` l'image dans ton contexte (Claude vision)

Range les screenshots dans `ml/state/crop_scores/expeNN_*.png` —
**commit ces images** comme preuve visuelle.

### Inspection automatique vs manuelle

Si tu peux catégoriser à l'œil (cat A/B/C/D évidentes) → fais-le toi.

Si l'image est ambigüe ou trop dense, délègue à un subagent avec
consigne :

```
Voici un screenshot d'un sampler bench (path: <path>). Il montre 30
crops eBay catégorisés en :
  A = strip numérique / sticker non-pièce
  B = bbox tiny sur une grosse pièce visible
  C = album multi-pièces avec bbox isolant une coin
  D = pièce isolée bien cadrée
Donne-moi un compte par catégorie + 3 exemples ID pour chaque.
```

## Mesure — quantifier le verdict

Chaque expérience a 2 mesures :

1. **Visuelle** : sur 30 BOTTOM + 30 TOP de l'output trié, compter les
   catégories. C'est la mesure principale.
2. **Distribution** : min / p10 / median / p90 / max du score. Permet
   de calibrer les thresholds.

Tu écris ces 2 mesures dans `experiments/NN-*.md` sections **Mesure** et
**Résultat**.

## Critère de win/lose/inconclu

| Cat | Win | Lose | Inconclu |
|---|---|---|---|
| Anti-A | bottom ≥ 80 % cat A | bottom < 50 % cat A | entre |
| Anti-B | flag ≥ 70 % cat B sans dépasser 20 % faux positifs D | rate < 50 % cat B OU dépasse 30 % faux positifs | entre |
| Sort default | top ≥ 80 % cat D | top < 60 % D | entre |

Inconclu n'est pas une excuse pour ne pas conclure : tu kills la
théorie OU tu reformules pour une expé ciblée.

## Commit & handoff

### Format de commit

```
coin-richness: crop forensics chunk N — <slug du résultat>

<paragraphe résumé : but, setup, verdict en 1 ligne>

<bullets des changements concrets : scripts ajoutés, sidecars produits,
docs créés/updatés, signal exposé en API/UI>

Verdict : <win|lose|inconclu marginal|...>. Action : <prochain pas>.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

### Handoff

Avant de stopper, **écris la prochaine session** dans `plan.md` avec :
- Objectif (1 ligne)
- Setup (qu'est-ce qu'on calcule / construit)
- Mesure (quel sampler / quelle assertion)
- Action si win / lose

Comme ça la session suivante a 0 ambiguïté.
