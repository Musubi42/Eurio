export const meta = {
  name: 'coin-census-bench-v0',
  description: 'Construit la verite-terrain du bench de recensement de pieces (LLM-professeur lit les images) + confronte au n_crops du detecteur actuel',
  phases: [
    { title: 'Census', detail: 'Agents vision : lire chaque raw, compter les pieces physiques distinctes (regles avers/revers, bimetal, coincard)' },
    { title: 'Analyse', detail: 'Joindre labels vs n_crops : taux de faux-single, piege front/back, ou le detecteur echoue' },
  ],
}

const PATH = '/tmp/census_bench_manifest.json'
const TOTAL = 110
const BATCH = 10

const CENSUS_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    items: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          source_image_id: { type: 'string' },
          n_coins: { type: 'integer' },
          n_disks_visible: { type: 'integer' },
          scene_type: { type: 'string', enum: ['single_one_face', 'single_two_faces', 'multi_distinct', 'packaged_single', 'set_or_roll', 'au_choix_offer', 'unclear'] },
          is_lot: { type: 'boolean' },
          confidence: { type: 'string', enum: ['high', 'med', 'low'] },
          note: { type: 'string' },
        },
        required: ['source_image_id', 'n_coins', 'n_disks_visible', 'scene_type', 'is_lot', 'confidence'],
      },
    },
  },
  required: ['items'],
}

const ANALYSIS_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    summary_md: { type: 'string' },
    by_stratum_md: { type: 'string' },
    false_single_rate: { type: 'string' },
    false_lot_rate: { type: 'string' },
    frontback_trap: { type: 'string' },
    clear_false_singles: { type: 'array', items: { type: 'string' } },
    low_confidence_for_human: { type: 'array', items: { type: 'string' } },
    recommendations: { type: 'array', items: { type: 'string' } },
  },
  required: ['summary_md', 'by_stratum_md', 'false_single_rate', 'false_lot_rate', 'frontback_trap', 'recommendations'],
}

function censusPrompt(start, end) {
  return `Tu construis la VERITE-TERRAIN d'un bench de "recensement de pieces" : combien de pieces PHYSIQUES distinctes sur une photo d'annonce eBay. Tu es le PROFESSEUR — tes labels serviront a entrainer/evaluer un detecteur. Sois rigoureux et regarde vraiment chaque image.

ETAPE 1 : recupere ta tranche d'items :
  jq -c ".[${start}:${end}]" ${PATH}
Chaque item = {source_image_id, raw_path, title, ...}.

ETAPE 2 : pour CHAQUE item, ouvre l'image avec l'outil Read sur "raw_path" (chemin local), observe, puis compte.

REGLES (n_coins = pieces PHYSIQUES distinctes) :
- Une piece montree des DEUX cotes (avers + revers cote a cote) = 1 piece (2 disques, 1 piece physique : meme diametre/tranche, designs complementaires).
- Une piece BIMETALLIQUE = 1 piece (l'anneau exterieur + le coeur sont la meme piece ; l'anneau interieur n'est PAS une 2e piece).
- Une piece en COINCARD / BLISTER / CAPSULE / FOLDER = 1 piece (l'emballage et sa fenetre ronde ne comptent pas).
- DEUX pieces DIFFERENTES (pays/annee/design distincts, ou 2 exemplaires) = 2 (et plus).
- Objets ronds NON-pieces (capsule vide, bouton, reflet, logo) = 0 piece.

CHAMPS par item :
- n_coins : pieces physiques distinctes (regles ci-dessus).
- n_disks_visible : nombre de disques "piece-like" visibles AVANT regles (ex : avers+revers d'1 piece = 2 disques mais n_coins=1 ; bimetal = 1 disque). Mesure le piege des detecteurs naifs.
- scene_type : single_one_face | single_two_faces | multi_distinct | packaged_single | set_or_roll | au_choix_offer | unclear.
- is_lot : true si n_coins >= 2.
- confidence : high/med/low (low si flou, occlusion, ou ambigu "2 faces d'1 piece" vs "2 pieces").
- note : 1 phrase de ce que tu vois.

Retourne {items:[...]} avec exactement une entree par item de ta tranche (meme source_image_id).`
}

phase('Census')
const batches = []
for (let s = 0; s < TOTAL; s += BATCH) batches.push([s, Math.min(s + BATCH, TOTAL)])
const labeled = (await parallel(batches.map(([s, e]) => () =>
  agent(censusPrompt(s, e), { label: `census:${s}-${e}`, phase: 'Census', schema: CENSUS_SCHEMA, model: 'sonnet' })
))).filter(Boolean).flatMap(r => r.items)

log(`Census : ${labeled.length}/${TOTAL} items labellises`)

phase('Analyse')
const analysis = await agent(
  `Analyse du bench de recensement de pieces. Tu recois (1) les labels LLM = VERITE-TERRAIN, et tu dois lire (2) le manifeste avec n_crops (sortie du detecteur ACTUEL) + route_decision + stratum.

LIS le manifeste : jq -c '.' ${PATH}  (array d'items {source_image_id, n_crops, route_decision, is_lot_suspected, stratum, title}).
JOINS par source_image_id avec les LABELS ci-dessous.

LABELS (verite-terrain) JSON :
${JSON.stringify(labeled)}

Calcule et rends (schema) :
- summary_md : tableau de comparaison n_crops (detecteur actuel) vs n_coins (verite) — accord exact, ecart, et n_crops vs n_disks_visible. Verdict global.
- by_stratum_md : par stratum ET par scene_type, ou n_crops echoue (0 crop sur une vraie piece ? 1 crop sur 2 pieces distinctes ? sur-compte les avers+revers ?).
- false_single_rate : part (et compte) des items ou la verite est un LOT (n_coins>=2) MAIS route_decision est review_single ou pending (pas classe lot) — l'erreur COUTEUSE (training empoisonne).
- false_lot_rate : part des items n_coins=1 classes review_lot.
- frontback_trap : combien de single_two_faces (1 piece, 2 disques) ; ce que n_crops a produit dessus ; ce qu'un detecteur OBJET naif produirait (n_disks_visible) → quantifie le piege.
- clear_false_singles : ids/titres les plus nets (verite multi, classe single/pending).
- low_confidence_for_human : items confidence=low a faire adjuger par l'humain.
- recommendations : 3-5 implications CONCRETES pour le design du detecteur census (ex : faut-il collapser avers/revers via identite ? un proposeur objet + verify is-coin ? seuils ?).`,
  { label: 'analyse', phase: 'Analyse', schema: ANALYSIS_SCHEMA, model: 'sonnet' },
)

return { labeled, analysis }
