from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings

# All display formatting and day-boundary logic uses UK wall-clock time;
# data is stored and compared in UTC
LONDON_TZ = ZoneInfo("Europe/London")


class Settings(BaseSettings):
    # extra="ignore" so leftover keys from earlier versions in .env do not
    # stop the app from starting
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Realtime Trains next-generation API (Bearer access token)
    rtt_api_token: str = ""

    # Train station CRS code (e.g., FOH for Forest Hill)
    train_station_crs: str = "FOH"

    # Comma-separated destination CRS codes
    train_destinations: str = "LBG,HHY"

    # Weather location
    weather_latitude: float = 51.4525
    weather_longitude: float = -0.0492

    # Comma-separated iCal feed URLs
    ical_feed_urls: str = ""

    @property
    def destination_list(self) -> list[str]:
        return [d.strip() for d in self.train_destinations.split(",") if d.strip()]

    @property
    def feed_url_list(self) -> list[str]:
        """Configured iCal feed URLs.

        webcal:// is an alias for HTTPS used by calendar apps (Apple's
        share sheet produces it); httpx cannot fetch it, so normalise.
        """
        urls = [u.strip() for u in self.ical_feed_urls.split(",") if u.strip()]
        return [
            "https://" + url.removeprefix("webcal://") if url.startswith("webcal://") else url
            for url in urls
        ]


settings = Settings()
