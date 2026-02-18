from datetime import UTC, datetime

import httpx
from cachetools import TTLCache
from loguru import logger

from quarterdeck.config import settings
from quarterdeck.models import HourlyWeather, WeatherForecast

# WMO Weather interpretation codes → (description, emoji)
# https://open-meteo.com/en/docs#weathervariables
WMO_CODES: dict[int, tuple[str, str]] = {
    0: ("Clear sky", "☀️"),
    1: ("Mainly clear", "🌤️"),
    2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Foggy", "🌫️"),
    48: ("Rime fog", "🌫️"),
    51: ("Light drizzle", "🌦️"),
    53: ("Moderate drizzle", "🌦️"),
    55: ("Dense drizzle", "🌧️"),
    56: ("Light freezing drizzle", "🌧️"),
    57: ("Dense freezing drizzle", "🌧️"),
    61: ("Slight rain", "🌧️"),
    63: ("Moderate rain", "🌧️"),
    65: ("Heavy rain", "🌧️"),
    66: ("Light freezing rain", "🌧️"),
    67: ("Heavy freezing rain", "🌧️"),
    71: ("Slight snow", "🌨️"),
    73: ("Moderate snow", "🌨️"),
    75: ("Heavy snow", "🌨️"),
    77: ("Snow grains", "🌨️"),
    80: ("Slight showers", "🌦️"),
    81: ("Moderate showers", "🌧️"),
    82: ("Violent showers", "🌧️"),
    85: ("Slight snow showers", "🌨️"),
    86: ("Heavy snow showers", "🌨️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm with hail", "⛈️"),
    99: ("Thunderstorm with heavy hail", "⛈️"),
}

_cache: TTLCache[str, WeatherForecast] = TTLCache(maxsize=1, ttl=1800)  # 30 min

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def _decode_wmo(code: int) -> tuple[str, str]:
    return WMO_CODES.get(code, ("Unknown", "❓"))


async def fetch_weather() -> WeatherForecast:
    """Fetch hourly weather forecast from Open-Meteo for the configured location."""
    cached = _cache.get("weather")
    if cached is not None:
        return cached

    logger.info("Fetching weather from Open-Meteo")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            OPEN_METEO_URL,
            params={
                "latitude": settings.weather_latitude,
                "longitude": settings.weather_longitude,
                "hourly": "temperature_2m,weather_code,wind_speed_10m",
                "current": "temperature_2m,weather_code",
                "timezone": "Europe/London",
                "forecast_days": 1,
            },
        )
        response.raise_for_status()

    data = response.json()

    now = datetime.now(tz=UTC)
    current_hour = now.hour

    current = data["current"]
    current_code = int(current["weather_code"])
    current_desc, current_emoji = _decode_wmo(current_code)

    hourly_data = data["hourly"]
    hourly: list[HourlyWeather] = []

    for i, time_str in enumerate(hourly_data["time"]):
        hour = int(time_str.split("T")[1].split(":")[0])
        if hour < current_hour:
            continue

        code = int(hourly_data["weather_code"][i])
        desc, emoji = _decode_wmo(code)
        hourly.append(
            HourlyWeather(
                hour=hour,
                temperature_c=round(hourly_data["temperature_2m"][i]),
                weather_code=code,
                description=desc,
                emoji=emoji,
            )
        )

    forecast = WeatherForecast(
        current_temp_c=round(current["temperature_2m"]),
        current_description=current_desc,
        current_emoji=current_emoji,
        hourly=hourly,
        fetched_at=now,
    )

    _cache["weather"] = forecast
    return forecast
