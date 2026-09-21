from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quarterdeck.refresh import Sources
from quarterdeck.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Render the full dashboard page from the latest source snapshots."""
    sources: Sources = request.app.state.sources

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "now": datetime.now(tz=UTC),
            "weather": sources.weather.snapshot,
            "trains": sources.trains.snapshot,
            "agenda": sources.agenda.snapshot,
            "mode": "filtered",
        },
    )
