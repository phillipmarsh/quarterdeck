import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from loguru import logger

from quarterdeck.models import DashboardData
from quarterdeck.services.calendar import fetch_agenda
from quarterdeck.services.trains import fetch_train_board
from quarterdeck.services.weather import fetch_weather
from quarterdeck.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Render the full dashboard page, fetching all data sources concurrently."""
    now = datetime.now(tz=UTC)
    data = DashboardData(now=now)

    weather_task = asyncio.create_task(fetch_weather())
    trains_task = asyncio.create_task(fetch_train_board())
    agenda_task = asyncio.create_task(fetch_agenda())

    try:
        data.weather = await weather_task
    except Exception as exc:
        logger.exception("Failed to fetch weather")
        data.weather_error = str(exc)

    try:
        data.trains = await trains_task
    except Exception as exc:
        logger.exception("Failed to fetch train departures")
        data.trains_error = str(exc)

    try:
        data.agenda = await agenda_task
    except Exception as exc:
        logger.exception("Failed to fetch calendar agenda")
        data.agenda_error = str(exc)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"data": data},
    )
