from datetime import datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from quarterdeck.config import LONDON_TZ

TEMPLATES_DIR = Path(__file__).parent / "templates"


def localtime(value: datetime) -> datetime:
    """Convert an aware datetime to UK wall-clock time for display.

    Naive datetimes are passed through unchanged: they carry no zone to
    convert from and are assumed already local.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(LONDON_TZ)


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["localtime"] = localtime
