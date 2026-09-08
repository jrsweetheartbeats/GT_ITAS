from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core.config import BASE_DIR, cors_settings
from .core.db import SessionLocal, ensure_database_exists
from .routers import ALL_ROUTERS
from .services.bootstrap import seed_defaults
from .routers.development_import import migrate_training_submission_attachments


app = FastAPI(title="IT审计全流程管理系统", version="0.1.0")
_cors_origins, _cors_origin_regex = cors_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
for router in ALL_ROUTERS:
    app.include_router(router)


@app.on_event("startup")
def startup() -> None:
    ensure_database_exists()
    with SessionLocal() as db:
        seed_defaults(db)
        migrate_training_submission_attachments(db)
