from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core.config import BASE_DIR
from .core.db import SessionLocal, ensure_database_exists
from .routers import ALL_ROUTERS
from .services.bootstrap import seed_defaults


app = FastAPI(title="IT审计全流程管理系统", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
for router in ALL_ROUTERS:
    app.include_router(router)


@app.on_event("startup")
def startup() -> None:
    ensure_database_exists()
    with SessionLocal() as db:
        seed_defaults(db)
