Tout est prêt pour le PC. Récap de ce que j'ai fait, puis les commandes à lancer côté desktop.

Préparation faite

- Probe Mac tuée — verdict définitif : même avec le dataset 224px corrigé, le step MPS prend ≥15 s (workers quasi
idle, le GPU du M4 Air est le mur). Le Mac n'est pas la machine pour ce fine-tune.
- Code commité et pushé sur sources-jo-wikipedia (commit 9d7e93f, staging explicite — uniquement le payload training
+ scripts + docs du chantier ; tes WIP admin/review non touchés) : backbone DinoV2Embedder, --epoch-multiplier,
bake pos_embed dans foundation, builder/éval/bench/spike.
- Dataset uploadé sur MinIO (ml/datasets/ est gitignoré) : eurio-db/transfers/arcface_vits14_v1.tar.gz (22 Mo — 1
004 train / 60 val, matérialisé en 224px).

À lancer sur le PC (1080 Ti)

cd <repo Eurio> && git pull && cd ml
uv pip install --python .venv/bin/python -e .   # sync deps (timm ajouté)

# Récupérer le dataset depuis MinIO
.venv/bin/python -c "
import sys, tarfile; sys.path.insert(0,'.')
from shared.storage.local_cache import local_path
p = local_path('eurio-db','transfers/arcface_vits14_v1.tar.gz')
tarfile.open(p).extractall('datasets', filter='data'); print('dataset ok')"

# 1) PROBE — 1 epoch backbone dégelé (pire cas), ~1-3 min attendues sur 1080 Ti
.venv/bin/python -u -m training.train_embedder --mode arcface --backbone dinov2_vits14 \
--dataset datasets/arcface_vits14_v1/train --val-dataset datasets/arcface_vits14_v1/val \
--epochs 1 --freeze-epochs 0 --batch-size 32 --m-per-class 4 --epoch-multiplier 3 \
--lr 5e-4 --embedding-dim 384 \
--output checkpoints/arcface_vits14_probe --model-version arcface-vits14-probe

Check de santé de la probe : loss finie qui n'est pas NaN, R@1 val > 0, et le temps d'epoch affiché. La première
exécution télécharge les poids DINOv2 (~84 Mo, une fois). Si c'est sain :

# 2) RUN COMPLET — 12 epochs (2 gelées), même recette
.venv/bin/python -u -m training.train_embedder --mode arcface --backbone dinov2_vits14 \
--dataset datasets/arcface_vits14_v1/train --val-dataset datasets/arcface_vits14_v1/val \
--epochs 12 --freeze-epochs 2 --batch-size 32 --m-per-class 4 --epoch-multiplier 3 \
--lr 5e-4 --embedding-dim 384 \
--output checkpoints/arcface_vits14_v1 --model-version arcface-vits14-v1

Quand checkpoints/arcface_vits14_v1/best_model.pth est là, renvoie-le (même canal MinIO transfers/, ou dis-moi et je
te donne la ligne d'upload) — je déroule alors sur le Mac l'éval held-out (fine-tuné vs zero-shot vs vitl14, les 86
crops jamais vus) et, si les chiffres sont bons, l'export LiteRT fp16 avec la recette du spike. Si la probe montre
un problème, on s'arrête et on regarde ensemble avant toute relance.