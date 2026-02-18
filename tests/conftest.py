import pytest

from quarterdeck.services.calendar import _cache as calendar_cache
from quarterdeck.services.trains import _cache as trains_cache
from quarterdeck.services.weather import _cache as weather_cache


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    """Clear all service caches before each test to ensure isolation."""
    weather_cache.clear()
    trains_cache.clear()
    calendar_cache.clear()
