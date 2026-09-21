from pydantic_settings import BaseSettings


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
        return [u.strip() for u in self.ical_feed_urls.split(",") if u.strip()]


settings = Settings()
