import httpx
import pytest
import respx
import time_machine

from quarterdeck.services.weather import (
    OPEN_METEO_URL,
    _decode_wmo,
    fetch_weather,
)

MOCK_OPEN_METEO_RESPONSE = {
    "current": {
        "temperature_2m": 14.2,
        "weather_code": 2,
    },
    "hourly": {
        "time": [
            "2026-02-17T08:00",
            "2026-02-17T09:00",
            "2026-02-17T10:00",
            "2026-02-17T11:00",
            "2026-02-17T12:00",
            "2026-02-17T13:00",
        ],
        "temperature_2m": [8.1, 9.5, 10.8, 11.2, 12.5, 13.1],
        "weather_code": [3, 3, 61, 63, 2, 0],
        "wind_speed_10m": [12.0, 14.0, 16.0, 18.0, 15.0, 10.0],
    },
}


class TestDecodeWmo:
    """Test WMO weather code to description/emoji mapping."""

    def test_known_code_returns_correct_description(self) -> None:
        """Given a known WMO code, when decoded, then the correct description is returned."""
        desc, emoji = _decode_wmo(0)
        assert desc == "Clear sky"
        assert emoji == "☀️"

    def test_overcast_code(self) -> None:
        """Given the overcast WMO code, when decoded, then 'Overcast' is returned."""
        desc, emoji = _decode_wmo(3)
        assert desc == "Overcast"
        assert emoji == "☁️"

    def test_unknown_code_returns_fallback(self) -> None:
        """Given an unknown WMO code, when decoded, then a fallback is returned."""
        desc, emoji = _decode_wmo(999)
        assert desc == "Unknown"
        assert emoji == "❓"


class TestFetchWeather:
    """Test the Open-Meteo weather fetching logic."""

    @time_machine.travel("2026-02-17T10:30:00Z")
    @respx.mock
    async def test_fetch_weather_returns_forecast(self) -> None:
        """Given a valid Open-Meteo response, when fetched,
        then a forecast with filtered hours is returned.
        """
        respx.get(OPEN_METEO_URL).mock(
            return_value=httpx.Response(200, json=MOCK_OPEN_METEO_RESPONSE)
        )

        forecast = await fetch_weather()

        assert forecast.current_temp_c == 14
        assert forecast.current_description == "Partly cloudy"
        assert forecast.current_emoji == "⛅"
        # Hours before 10 should be filtered out (current hour is 10)
        assert len(forecast.hourly) == 4
        assert forecast.hourly[0].hour == 10
        assert forecast.hourly[0].description == "Slight rain"

    @time_machine.travel("2026-02-17T10:30:00Z")
    @respx.mock
    async def test_fetch_weather_caches_result(self) -> None:
        """Given a successful fetch, when called again, then the cached result is returned."""
        route = respx.get(OPEN_METEO_URL).mock(
            return_value=httpx.Response(200, json=MOCK_OPEN_METEO_RESPONSE)
        )

        first = await fetch_weather()
        second = await fetch_weather()

        assert first == second
        assert route.call_count == 1

    @time_machine.travel("2026-02-17T10:30:00Z")
    @respx.mock
    async def test_fetch_weather_raises_on_http_error(self) -> None:
        """Given an HTTP error, when fetched, then the error propagates."""
        respx.get(OPEN_METEO_URL).mock(return_value=httpx.Response(500))

        with pytest.raises(httpx.HTTPStatusError):
            await fetch_weather()
