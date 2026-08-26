Tout est prêt côté Mac. Ce qui reste est sur le PC, et je ne peux pas le jouer d'ici.

À jouer sur le PC

cd /chemin/vers/Eurio
git fetch github repo-cleanup && git merge --ff-only github/repo-cleanup
direnv reload                       # profil pc → nvidiaHook + flipHook

go-task ml:setup                    # attendu : cuda=True
go-task ml:augment-textures-check ; echo "exit=$?"      # ⚠️ colle-moi la sortie
export EURIO_CACHE_MAX_GB=0         # sinon tu repaies la taxe rglob, ~1,25 s/fichier

go-task ml:db:pull-replica
cd ml && sqlite3 "file:state/eurio.replica.db?mode=ro" \
  "select count(*) from image_assets where eval_corpus is not null;"   # attendu 300

Puis le mode compute, dans cet ordre (le VACUUM INTO doit venir après le pull et après que l'itération existe au canonique — c'est le cas depuis 01:36) :

cd /chemin/vers/Eurio
[ -e ml/state/eurio.work-matrice.db ] || nix develop .#pc --command \
  sqlite3 ml/state/eurio.replica.db "VACUUM INTO 'ml/state/eurio.work-matrice.db'"
lsof -ti :8042 | xargs kill          # par PID — jamais `pkill -f`, il tue ton shell
EURIO_DB_READONLY= EURIO_DB_PATH="$PWD/ml/state/eurio.work-matrice.db" go-task ml:api-prod

Puis baker et entraîner :

C=2e51f2b3d633 ; I=b55b61b59632
curl -s -X POST "http://127.0.0.1:8042/lab/cohorts/$C/iterations/$I/bake"
# … attendre que augmentations/job ne soit plus 'running' (≈ 10 min + MinIO à froid)
curl -s -X POST "http://127.0.0.1:8042/lab/cohorts/$C/iterations/$I/launch-training"

🔴 Après chaque lancement, le seul contrôle qui vaille — HTTP 200 ne dit rien, le job est un subprocess détaché :

cd ml && ./.venv/bin/python -c "
import sys;sys.path.insert(0,'.');import jobs
for r in jobs.connection().execute('select kind,status,error from jobs order by rowid desc limit 3'): print(dict(r))"
# 'readonly database' → le mode compute n'est pas actif

Ce que j'ai fait, et l'état

┌────────────┬──────────────────────────────────────────────────────────────────────────────────┐
│            │                                                                                  │
├────────────┼──────────────────────────────────────────────────────────────────────────────────┤
│ cohorte    │ matrice-60c = 2e51f2b3d633, 60 classes, ready=true, 0 block, 0 warn,             │
│            │ n_ebay=1908, gelée                                                               │
├────────────┼──────────────────────────────────────────────────────────────────────────────────┤
│ itération  │ matrice-arcface-60c-calib = b55b61b59632, 3 epochs, val_source=none,             │
│            │ centroid_source=train_mean, graine 20260826 — les cinq clés relues sur la ligne  │
├────────────┼──────────────────────────────────────────────────────────────────────────────────┤
│ images     │ 300/300 tirés de MinIO et décodés, 224×224                                       │
│ d'éval     │                                                                                  │
└────────────┴──────────────────────────────────────────────────────────────────────────────────┘

Deux choses à relever pendant le run : la sortie de ml:augment-textures-check (elle décide si le run est comparable à A/B) et le nombre de samples du bake — l'estimation de 2 h 21 pour 40 epochs est une extrapolation linéaire non mesurée, et tes 3 epochs la fermeront.

Ce qui manquera encore après : noter sur les 300 frames. replay_corpus ne lit que scan_corpus — le lot A (7 points à changer, dont la double identité truth_eurio_id/class_id et normalize_device_path ≠ normalize_listing_path) n'est pas écrit. Et pour le bras DINO, le lot B (load_embedder n'accepte pas le .npz de la banque). Dis-moi si tu veux que j'attaque l'un des deux pendant que ton run tourne.
