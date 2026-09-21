import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from quarterdeck.refresh import Sources, build_sources
from quarterdeck.routes import dashboard, partials

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Run one background refresh loop per data source for the app's lifetime."""
    sources: Sources = application.state.sources
    tasks = [asyncio.create_task(refresher.run()) for refresher in sources.all()]
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def create_app() -> FastAPI:
    application = FastAPI(title="Quarterdeck", docs_url=None, redoc_url=None, lifespan=lifespan)
    application.state.sources = build_sources()
    application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    application.include_router(dashboard.router)
    application.include_router(partials.router)
    return application


app = create_app()
