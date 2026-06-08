"""App FastAPI du service review (VPS, toujours allumé).

Lancement local (dev) :  go-task ml:review:serve   (uvicorn --reload :8048)
Prod VPS : voir docs/work-in-progress/collaborative-review/09-vps-deploy.md
           (systemd → uvicorn review_service.app:app, reverse-proxy HTTPS).

N'ouvre QUE review.db. Sert le build statique du front (admin/packages/review)
s'il est présent. Les routes amis sont à la racine, les routes admin sous /admin.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ml/ doit être sur sys.path pour `from shared.storage …` / `from review_service …`
# quand lancé via `uvicorn review_service.app:app` depuis ml/.
_ML_DIR = Path(__file__).resolve().parent.parent
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from review_service.db import ReviewDB  # noqa: E402
from review_service import routes_admin, routes_reviewer  # noqa: E402

app = FastAPI(title="Eurio Review Service", version="0.1.0", docs_url="/api/docs")

# CORS : front review en dev (Vite) + l'origine de prod via env.
_origins = [
    "http://localhost:5180",
    "http://localhost:5181",
    "http://127.0.0.1:5180",
]
_extra = os.environ.get("REVIEW_CORS_ORIGINS", "")
if _extra:
    _origins.extend(o.strip() for o in _extra.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,  # cookies de session
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.db = ReviewDB()

app.include_router(routes_reviewer.router)
app.include_router(routes_admin.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# Front statique (build de admin/packages/review). Monté en dernier pour ne pas
# masquer les routes API. Absent en dev pur (on utilise le Vite dev server).
_FRONT_DIST = _ML_DIR.parent / "admin" / "packages" / "review" / "dist"
if _FRONT_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONT_DIST), html=True), name="front")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "review_service.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("REVIEW_PORT", "8048")),
        reload=False,
    )
