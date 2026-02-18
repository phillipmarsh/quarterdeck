from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from loguru import logger

from quarterdeck.services.calendar import fetch_agenda
from quarterdeck.services.trains import fetch_train_board
from quarterdeck.services.weather import fetch_weather
from quarterdeck.templating import templates

router = APIRouter(prefix="/partials")


@router.get("/header", response_class=HTMLResponse)
async def header_partial(request: Request) -> HTMLResponse:
    """Return the header partial with current weather summary."""
    now = datetime.now(tz=UTC)
    weather = None
    weather_error = None

    try:
        weather = await fetch_weather()
    except Exception as exc:
        logger.exception("Failed to fetch weather for header")
        weather_error = str(exc)

    return templates.TemplateResponse(
        request=request,
        name="partials/header.html",
        context={"weather": weather, "weather_error": weather_error, "now": now},
    )


@router.get("/trains", response_class=HTMLResponse)
async def trains_partial(request: Request, mode: str = "filtered") -> HTMLResponse:
    """Return the trains partial. mode=filtered shows per-destination, mode=all shows everything."""
    trains = None
    trains_error = None

    try:
        trains = await fetch_train_board()
    except Exception as exc:
        logger.exception("Failed to fetch trains")
        trains_error = str(exc)

    return templates.TemplateResponse(
        request=request,
        name="partials/trains.html",
        context={"trains": trains, "trains_error": trains_error, "mode": mode},
    )


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_partial(request: Request) -> HTMLResponse:
    """Return the calendar partial with today's events."""
    agenda = None
    agenda_error = None

    try:
        agenda = await fetch_agenda()
    except Exception as exc:
        logger.exception("Failed to fetch calendar")
        agenda_error = str(exc)

    return templates.TemplateResponse(
        request=request,
        name="partials/calendar.html",
        context={"agenda": agenda, "agenda_error": agenda_error},
    )


@router.get("/weather", response_class=HTMLResponse)
async def weather_partial(request: Request) -> HTMLResponse:
    """Return the hourly weather strip partial."""
    weather = None
    weather_error = None

    try:
        weather = await fetch_weather()
    except Exception as exc:
        logger.exception("Failed to fetch weather strip")
        weather_error = str(exc)

    return templates.TemplateResponse(
        request=request,
        name="partials/weather_strip.html",
        context={"weather": weather, "weather_error": weather_error},
    )
