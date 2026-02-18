from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from quarterdeck.routes import dashboard, partials

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    application = FastAPI(title="Quarterdeck", docs_url=None, redoc_url=None)
    application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    application.include_router(dashboard.router)
    application.include_router(partials.router)
    return application


app = create_app()
