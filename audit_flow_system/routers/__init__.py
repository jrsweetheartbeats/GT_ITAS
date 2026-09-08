from __future__ import annotations

from fastapi import APIRouter

from .attachments import router as attachments_router
from .auth import router as auth_router
from .autofill import router as autofill_router
from .clients import router as clients_router
from .config import router as config_router
from .development import router as development_router
from .development_import import router as development_import_router, training_router as development_training_router
from .learning import router as learning_router
from .materials import router as materials_router
from .projects import router as projects_router
from .reviews import router as reviews_router
from .roles import router as roles_router
from .users import router as users_router
from .workpapers import router as workpapers_router
from .workflow import router as workflow_router


ALL_ROUTERS: list[APIRouter] = [
    auth_router,
    config_router,
    development_router,
    development_import_router,
    development_training_router,
    learning_router,
    roles_router,
    users_router,
    clients_router,
    projects_router,
    workflow_router,
    materials_router,
    workpapers_router,
    attachments_router,
    autofill_router,
    reviews_router,
]
