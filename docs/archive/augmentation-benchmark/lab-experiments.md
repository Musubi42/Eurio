Plan — Lab & Experiments                                                                                                
                                                                                                                    
1. Modèle mental figé                                                                                                   
                                                
Un cohort = ensemble figé d'eurio_ids qui ont (ou auront) des photos réelles. C'est la piste de course.                 
                                                                                                                        
Une itération = un passage sur la piste. Elle a : une hypothèse, des inputs (recipe + variant_count + training_config), 
et une sortie (training_run + benchmark_run + verdict + delta vs parent).                                               
                                                                                                                        
Règle d'or : cohort frozen. Si tu veux ajouter/retirer des pièces, tu forks un nouveau cohort. Sinon, tu casses la      
comparabilité.
                                                                                                                        
2. Schéma de base de données                                    

Deux nouvelles tables dans training.db                                                                                  

CREATE TABLE experiment_cohorts (                                                                                       
id                  TEXT PRIMARY KEY,                                                                                 
name                TEXT NOT NULL UNIQUE,
description         TEXT,                                                                                             
zone                TEXT CHECK (zone IS NULL OR zone IN ('green','orange','red')),
eurio_ids_json      TEXT NOT NULL,         -- frozen list                                                             
created_at          TEXT NOT NULL DEFAULT (datetime('now')),
updated_at          TEXT NOT NULL DEFAULT (datetime('now'))                                                           
);                                                              
                                                                                                                        
CREATE TABLE experiment_iterations (                                                                                    
id                        TEXT PRIMARY KEY,
cohort_id                 TEXT NOT NULL REFERENCES experiment_cohorts(id) ON DELETE CASCADE,                          
parent_iteration_id       TEXT REFERENCES experiment_iterations(id) ON DELETE SET NULL,                               
name                      TEXT NOT NULL,
hypothesis                TEXT,                                                                                       
-- Inputs                                                     
recipe_id                 TEXT REFERENCES augmentation_recipes(id) ON DELETE SET NULL,                                
variant_count             INTEGER NOT NULL DEFAULT 100,                                                               
training_config_json      TEXT NOT NULL DEFAULT '{}',  -- {epochs, batch_size, m_per_class, ...}
-- Chain state                                                                                                        
status                    TEXT NOT NULL                                                                               
                            CHECK (status IN ('pending','training','benchmarking','completed','failed')),               
training_run_id           TEXT REFERENCES training_runs(id) ON DELETE SET NULL,                                       
benchmark_run_id          TEXT REFERENCES benchmark_runs(id) ON DELETE SET NULL,
-- Outcome                                                                                                            
verdict                   TEXT                                
                            CHECK (verdict IN ('pending','better','worse','mixed','no_change')),                        
verdict_override          TEXT,                              -- dev override manuel
delta_vs_parent_json      TEXT DEFAULT '{}',                 -- {r_at_1, r_at_3, per_zone, ...}                       
diff_from_parent_json     TEXT DEFAULT '{}',                 -- inputs qui ont changé                                 
notes                     TEXT,                                                                                       
error                     TEXT,                                                                                       
created_at                TEXT NOT NULL DEFAULT (datetime('now')),                                                    
started_at                TEXT,                               
finished_at               TEXT                                                                                        
);                                                              

CREATE INDEX idx_exp_iter_cohort ON experiment_iterations(cohort_id);                                                   
CREATE INDEX idx_exp_iter_parent ON experiment_iterations(parent_iteration_id);
CREATE INDEX idx_exp_iter_created ON experiment_iterations(created_at DESC);                                            
                                                                
Migration additive sur benchmark_runs (via _ensure_column)                                                              
                                                                
ALTER TABLE benchmark_runs ADD COLUMN per_condition_json TEXT NOT NULL DEFAULT '{}';                                    
-- stocke {lighting: {natural-direct: 0.92, ...}, background: {...}, angle: {...}}                                      
                                                                                                                        
3. Enrichissement benchmark — métriques par axe                                                                         
                                                                                                                        
evaluate_real_photos.py :                                                                                               
- Extrait (lighting, background, angle) par filename via les vocabulaires de real-photo-criteria.md (helper partagé avec
check_real_photos.py → refactorer dans un module ml/real_photo_meta.py).                                               
- Ajoute ces champs sur chaque PhotoResult.                              
- _aggregate calcule un bloc per_condition : {lighting: {natural-direct: 0.95, ...}, background: {...}, angle: {...}}.  
- Rapport JSON enrichi + nouvelle colonne per_condition_json sur benchmark_runs.                                        
                                                                                                                        
Dans BenchmarkRunDetailPage.vue, nouvelle section "Par axe de variabilité" :                                            
- Tableau 3 colonnes (lighting/background/angle) avec R@1 par valeur.                                                   
- Colorisation : vert si ≥85%, orange 70-85%, rouge <70%.                                                               
- C'est la lecture qui transforme "R@1=82% global" en "R@1 chute à 45° (45%) et sur hand (68%)".                        
                                                                                                                        
4. Logique verdict                                                                                                      
                                                                                                                        
Δ_global = iter.r_at_1 - parent.r_at_1                                                                                  
Δ_per_zone = {z: iter.zones[z] - parent.zones[z] for z in common_zones}                                                 
                                                                                                                        
verdict =                                                                                                               
"better"     si Δ_global ≥ +0.02 ET aucun Δ_zone < -0.03                                                              
"worse"      si Δ_global ≤ -0.02                                                                                      
"mixed"      si Δ_global ∈ [-0.02, +0.02] ET ∃ zone avec |Δ| ≥ 0.02
            OU si Δ_global ≥ +0.02 mais une zone régresse > 3pts                                                       
"no_change"  si tous les |Δ| < 0.005                                                                                  
"pending"    si benchmark pas fini                                                                                    
                                                                                                                        
Champ verdict_override libre pour que tu puisses tagger "actually better than the auto thinks" avec une raison dans     
notes.                                                                                                                  
                                                                                                                        
5. Iteration runner — orchestration backend                                                                             

Nouveau module ml/api/iteration_runner.py (même pattern que training_runner.py).                                        
                                                                
Pour chaque itération lancée :                                                                                          
                                                                
1. status = "training"
    → stage les eurio_ids avec recipe_id                                                                                 
    → POST /training/run avec config {aug_recipe, target_augmented: variant_count, epochs, ...}                          
    → store training_run_id                                                                                              
                                                                                                                        
2. Thread daemon poll /training/runs/{id} toutes les 5s                                                                 
    → quand status=completed → passer à l'étape 3                
    → si failed → iteration.status = "failed", error = training error                                                    
                                                                                                                        
3. status = "benchmarking"                                                                                              
    → identifier le checkpoint produit (checkpoints/best_model.pth par convention)                                       
    → POST /benchmark/run avec {model_path, eurio_ids: cohort.eurio_ids, recipe_id}                                      
    → store benchmark_run_id                                                                                             
    → update benchmark_runs.training_run_id (ferme la boucle de traçabilité)                                             
                                                                                                                        
4. Poll /benchmark/runs/{id}                                                                                            
    → quand completed : compute verdict + delta_vs_parent                                                                
    → status = "completed"                                                                                               
                                                                
Si l'API redémarre au milieu, un iteration en training ou benchmarking est recovered au boot : le runner relit les IDs  
et reprend le polling. Pas de zombies.                          
                                                                                                                        
6. API — nouvelles routes                                                                                               

GET    /lab/cohorts                              # list                                                                 
POST   /lab/cohorts                              # create (name, description, zone?, eurio_ids[])
GET    /lab/cohorts/{id}                         # detail + iterations summary + best R@1                               
PUT    /lab/cohorts/{id}                         # update (name/description/zone — eurio_ids FROZEN)                    
DELETE /lab/cohorts/{id}                         # delete (cascade iterations)                                          
                                                                                                                        
GET    /lab/cohorts/{id}/iterations              # list                                                                 
POST   /lab/cohorts/{id}/iterations              # create + launch chain
GET    /lab/cohorts/{id}/iterations/{iter}       # detail (full, avec training + bench embedded)                        
PUT    /lab/cohorts/{id}/iterations/{iter}       # update (notes, verdict_override)                                     
DELETE /lab/cohorts/{id}/iterations/{iter}       # delete                                                               
                                                                                                                        
GET    /lab/cohorts/{id}/sensitivity             # computed parametric leverage                                         
GET    /lab/cohorts/{id}/trajectory              # compact timeseries pour sparkline
                                                                                                                        
Body de POST /lab/cohorts/{id}/iterations :                                                                             
{                                                                                                                       
"name": "green-v3 more variants",                                                                                     
"hypothesis": "Doubler variant_count devrait fermer le gap sur angle=45°",                                            
"parent_iteration_id": "abc123",                                          
"recipe_id": "green-tuned-v2",                                                                                        
"variant_count": 200,                                         
"training_config": { "epochs": 40, "batch_size": 256, "m_per_class": 4 }                                              
}                                                                         
                                                                                                                        
Retour immédiat : { iteration_id, status: "training" }. Tu poll le GET /detail.
                                                                                                                        
7. Sensibilité — calcul à la volée                                                                                      
                                                                                                                        
Pour un cohort, on parcourt ses itérations et on extrait :                                                              
                                                                
Pour chaque pair (iteration, parent) :                                                                                  
- diff = différences sur {recipe_params, variant_count, training_config} — aplaties en chemins :
recipe.perspective.max_tilt_degrees, variant_count, training.epochs, etc.                                               
- delta_r_at_1 = iter.r_at_1 − parent.r_at_1                             
                                                                                                                        
Agrégat par chemin modifié :                                                                                            
[                                                                                                                       
{ "path": "variant_count", "observations": 3, "avg_delta_r1": 0.012, "direction": "+" },                              
{ "path": "recipe.perspective.max_tilt_degrees", "observations": 2, "avg_delta_r1": 0.031, "direction": "+" },        
{ "path": "recipe.overlays.opacity_range", "observations": 1, "avg_delta_r1": -0.004, "direction": "=" }              
]                                                                                                                       
                                                                                                                        
Tri par |avg_delta_r1| décroissant → tu vois direct les leviers qui comptent.                                           
                                                                                                                        
V1 : simple aggregate (mean). V2 : ajouter variance + sample count en confidence.                                       
                                                                                                                        
8. UI — feature module features/lab/                                                                                    
                                                                
Structure :                                                                                                             
features/lab/                                                   
├── pages/   
│   ├── LabHomePage.vue                    # cohort grid                                                                
│   ├── CohortDetailPage.vue               # THE key page
│   ├── CohortNewPage.vue                  # wizard create cohort                                                       
│   ├── IterationDetailPage.vue            # drill-down + hypothesis + notes
│   └── IterationNewPage.vue               # wizard create iteration                                                    
├── components/                                                                                                         
│   ├── CohortCard.vue                     # tile for home                                                              
│   ├── TrajectoryChart.vue                # R@1 waterfall over iterations                                              
│   ├── IterationRow.vue                   # row in cohort detail table                                                 
│   ├── InputDiffChip.vue                  # shows "variant_count 100 → 200"                                            
│   ├── VerdictBadge.vue                   # colored pill                                                               
│   ├── SensitivityPanel.vue               # leverage table                                                             
│   └── PerConditionTable.vue              # lighting/bg/angle R@1 (réutilisé dans /benchmark aussi)                    
├── composables/                                                                                                        
│   └── useLabApi.ts                                                                                                    
└── types.ts                                                    
                                                                                                                        
Design — tokens existants uniquement                            
                                                                                                                        
Toutes les couleurs : var(--indigo-700) (brand), var(--success) / var(--warning) / var(--danger) (zones + verdict),     
var(--gold) (hairline sous header), var(--ink) / var(--ink-400) / var(--ink-500).                                       
                                                                                                                        
Ombres : var(--shadow-sm) pour cartes, var(--shadow-card) pour modals.                                                  

Typographie : font-display italic pour titres, font-mono pour IDs/métriques, text-[10px] uppercase                      
tracking-[var(--tracking-eyebrow)] pour eyebrows.               
                                                                                                                        
Patterns recyclés : header + hairline gold = identique à ConfusionMapPage et BenchmarkPage. Pills ML API online/offline 
= composant existant (composer pour dédup). Empty states avec border-dashed = idem.
                                                                                                                        
Pages en détail                                                 

/lab (LabHomePage)                                                                                                      
- Header : titre "Lab — Expériences", pill ML API, CTA "Nouveau cohort"
- Stats rapides : N cohorts · N iterations · best R@1 global                                                            
- Grid de CohortCard : nom + zone badge + X/Y photos + # iterations + best R@1 + mini sparkline
                                                                                                                        
/lab/cohorts/new (CohortNewPage) — wizard 3 étapes                                                                      
- Step 1 : name (kebab-check), description, zone (optional)                                                             
- Step 2 : eurio_ids (CSV textarea OU bouton "depuis /coins" qui redirige avec return_to)                               
- Step 3 : photo-readiness check (via /benchmark/library) → badges ✓/⚠ par coin → soft gate
                                                                                                                        
/lab/cohorts/:id (CohortDetailPage) — LA VUE CLÉ                                                                        
- Header : cohort info + coins list (compact) + "Fork this cohort" + "Edit"                                             
- TrajectoryChart : SVG inline, X=iterations chronologiques, Y=R@1, color=verdict                                       
- Table des itérations avec IterationRow :                                                                              
- Name + hypothesis (truncated avec tooltip)                                                                          
- InputDiffChip (chips des paramètres modifiés vs parent)                                                             
- R@1 (+ delta badge)                                                                                                 
- VerdictBadge                                                                                                        
- Date, link vers detail                                      
- SensitivityPanel à droite ou en bas : table des leviers triée par impact                                              
- CTA "Nouvelle itération"                                                                                              
                                                                                                                        
/lab/cohorts/:id/iterations/new (IterationNewPage) — wizard                                                             
- Parent iteration selector (default: last)                                                                             
- Hypothesis (required, min 10 chars)                                                                                   
- Recipe : dropdown des recipes existantes + lien "Éditer dans Studio" (ouvre /augmentation avec return_to)
- Variant count : slider 50-500, default hérité du parent                                                               
- Training config : epochs (40), batch_size (256), m_per_class (4) — pré-remplis depuis parent                          
- Review card : "Tu vas modifier variant_count (100→200), tout le reste est identique au parent"                        
- Launch button                                                                                                         
                                                                                                                        
/lab/cohorts/:id/iterations/:iter (IterationDetailPage)                                                                 
- Header : iteration name + verdict badge + date + status (si pas completed, live update)                               
- 2 colonnes :                                                                                                          
- Gauche (inputs) : hypothesis card, recipe snapshot (link to Studio read-only), variant_count, training_config,
parent link                                                                                                             
- Droite (outcomes) : delta_vs_parent cards (R@1, per zone), then embedded benchmark results (reuse                   
BenchmarkRunDetailPage content: per_zone, per_coin, confusion, top_confusions, per_condition)                           
- Bottom : Notes textarea (autosave), verdict_override dropdown, logs training (collapsible)                            
                                                                                            
Entry points                                                                                                            
                                                                                                                        
- Navbar : "Lab" (icône FlaskConical ou BeakerIcon) devient l'entrée primaire de la section Outils.                     
- /coins sticky footer : garde "Augmenter", ajoute "Nouveau cohort Lab" (même pattern que "Ajouter au training").       
- /benchmark reste accessible pour les runs ad-hoc mais devient secondaire.                                             
- /augmentation sans entrée navbar (confirmé la session d'avant).                                                       
                                                                                                                        
9. Ce qu'on touche (fichiers)                                                                                           
                                                                                                                        
ML — backend                                                                                                            
                                                                
┌────────────────────────────┬───────────────────────────────────────────────────────────────────┐                      
│          Fichier           │                              Change                               │
├────────────────────────────┼───────────────────────────────────────────────────────────────────┤
│ ml/state/schema.sql        │ +2 tables + 1 migration additive                                  │
├────────────────────────────┼───────────────────────────────────────────────────────────────────┤
│ ml/state/store.py          │ 2 Row dataclasses + CRUD + update_benchmark_run(training_run_id=) │                      
├────────────────────────────┼───────────────────────────────────────────────────────────────────┤                      
│ ml/state/__init__.py       │ exports                                                           │                      
├────────────────────────────┼───────────────────────────────────────────────────────────────────┤                      
│ ml/real_photo_meta.py      │ nouveau — helper de parsing filename (partagé check + eval)       │
├────────────────────────────┼───────────────────────────────────────────────────────────────────┤                      
│ ml/check_real_photos.py    │ utilise real_photo_meta.py                                        │
├────────────────────────────┼───────────────────────────────────────────────────────────────────┤                      
│ ml/evaluate_real_photos.py │ utilise real_photo_meta.py + calcule per_condition + persiste     │
├────────────────────────────┼───────────────────────────────────────────────────────────────────┤                      
│ ml/api/iteration_runner.py │ nouveau — orchestrateur training → bench + verdict                │
├────────────────────────────┼───────────────────────────────────────────────────────────────────┤                      
│ ml/api/lab_routes.py       │ nouveau — routes /lab/*                                           │
├────────────────────────────┼───────────────────────────────────────────────────────────────────┤                      
│ ml/api/server.py           │ mount lab router + startup hook (recovery)                        │
└────────────────────────────┴───────────────────────────────────────────────────────────────────┘                      

Admin — frontend                                                                                                        
                                                                
┌─────────────────────────────────────────────────────┬───────────────────────────────────────────────────────┐
│                       Fichier                       │                        Change                         │
├─────────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
│ features/lab/**                                     │ nouveau — 5 pages + 7 components + composable + types │
├─────────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤
│ features/benchmark/pages/BenchmarkRunDetailPage.vue │ +section PerConditionTable                            │         
├─────────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤         
│ features/coins/pages/CoinsPage.vue                  │ +CTA "Nouveau cohort Lab" dans footer sticky          │         
├─────────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤         
│ app/router.ts                                       │ routes /lab/*                                         │
├─────────────────────────────────────────────────────┼───────────────────────────────────────────────────────┤         
│ app/nav.ts                                          │ entrée Lab                                            │
└─────────────────────────────────────────────────────┴───────────────────────────────────────────────────────┘         
                                                                
Tests                                                                                                                   

┌────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────────┐  
│          Fichier           │                                         Tests                                         │
├────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
│ ml/tests/test_lab.py       │ Store CRUD (cohorts + iterations) + verdict logic + delta compute + sensitivity       │
│                            │ aggregate                                                                             │
├────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤  
│ ml/tests/test_lab_api.py   │ Routes CRUD + iteration launch (monkeypatch runner)                                   │  
├────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤  
│ ml/tests/test_benchmark.py │ +tests per_condition aggregation                                                      │  
└────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────────┘  

Docs                                                                                                                    
                                                                
┌───────────────────────────────────────────────────────────┬──────────────────────┐                                    
│                          Fichier                          │        Change        │
├───────────────────────────────────────────────────────────┼──────────────────────┤                                    
│ docs/augmentation-benchmark/04-experiments-lab.md         │ nouveau — PRD du Lab │
├───────────────────────────────────────────────────────────┼──────────────────────┤
│ docs/augmentation-benchmark/README.md                     │ link vers PRD04      │                                    
├───────────────────────────────────────────────────────────┼──────────────────────┤                                    
│ docs/augmentation-benchmark/PRD04-implementation-notes.md │ après implem         │                                    
└───────────────────────────────────────────────────────────┴──────────────────────┘                                    
                                                                
10. Ordre d'implémentation                                                                                              
                                                                
Phase A — Fondations backend (peut être testé isolément)                                                                
1. Schema + Store (cohorts + iterations + migration per_condition_json)
2. real_photo_meta.py helper partagé                                                                                    
3. Enrichissement evaluate_real_photos.py (per_condition) + tests
4. Verdict logic + delta computer (unit tests)                                                                          
                                                                
Phase B — Orchestration                                                                                                 
5. iteration_runner.py — chain training → bench + recovery au boot
6. Routes /lab/* — CRUD cohorts + iterations + sensitivity                                                              
7. Tests API                                                                                                            
                                                                                                                        
Phase C — UI — primary flow                                                                                             
8. Types + composable useLabApi                                 
9. LabHomePage + CohortNewPage + CohortCard                                                                             
10. CohortDetailPage + TrajectoryChart + IterationRow + InputDiffChip + VerdictBadge                                    
11. IterationNewPage + IterationDetailPage                                                                              
                                                                                                                        
Phase D — UI — finitions                                                                                                
12. SensitivityPanel                                            
13. PerConditionTable dans Benchmark detail aussi                                                                       
14. CTA /coins → new cohort                                                                                             
15. Navbar entry                                                                                                        
                                                                                                                        
Phase E — Docs + QA                                                                                                     
16. PRD04 + handoff doc                                         
17. Smoke test end-to-end manuel (créer cohort, lancer iteration, voir verdict)                                         
                                                                                                                        
11. Risques / points à surveiller                                                                                       
                                                                                                                        
- Training checkpoint naming : aujourd'hui tous les trainings écrivent sur checkpoints/best_model.pth. Si 2 itérations  
tournent en parallèle, collision. V1 : une itération à la fois par cohort (gate côté iteration_runner). Multi-parallel =
V2.                                                                                                                    
- Recovery au boot : cruciale sinon une itération en cours survit pas à un ml:api restart. À tester explicitement.
- Variant_count pourrait dépasser la capacité de ton M4 si >500 — garder cap soft.                                      
- Delta calculé sur runs incomplets : si parent n'a pas fini, on skip le calcul jusqu'à ce que le parent complète.      
- Cohort frozen vs user qui veut modifier : UI doit clairement signaler qu'on fork, pas qu'on édite. 