from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from quarterdeck.refresh import Sources
from quarterdeck.templating import templates

router = APIRouter(prefix="/partials")


@router.get("/header", response_class=HTMLResponse)
async def header_partial(request: Request) -> HTMLResponse:
    """Return the header partial with current weather summary."""
    sources: Sources = request.app.state.sources

    return templates.TemplateResponse(
        request=request,
        name="partials/header.html",
        context={"weather": sources.weather.snapshot, "now": datetime.now(tz=UTC)},
    )


@router.get("/trains", response_class=HTMLResponse)
async def trains_partial(request: Request, mode: str = "filtered") -> HTMLResponse:
    """Return the trains partial. mode=filtered shows per-destination, mode=all shows everything."""
    sources: Sources = request.app.state.sources

    return templates.TemplateResponse(
        request=request,
        name="partials/trains.html",
        context={"trains": sources.trains.snapshot, "mode": mode},
    )


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_partial(request: Request) -> HTMLResponse:
    """Return the calendar partial with today's events."""
    sources: Sources = request.app.state.sources

    return templates.TemplateResponse(
        request=request,
        name="partials/calendar.html",
        context={"agenda": sources.agenda.snapshot},
    )


@router.get("/weather", response_class=HTMLResponse)
async def weather_partial(request: Request) -> HTMLResponse:
    """Return the hourly weather strip partial."""
    sources: Sources = request.app.state.sources

    return templates.TemplateResponse(
        request=request,
        name="partials/weather_strip.html",
        context={"weather": sources.weather.snapshot},
    )
