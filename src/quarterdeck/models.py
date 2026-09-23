from datetime import UTC, date, datetime, time
from enum import StrEnum

from pydantic import BaseModel


class HourlyWeather(BaseModel):
    hour: int
    temperature_c: float
    weather_code: int
    description: str
    emoji: str


class WeatherForecast(BaseModel):
    current_temp_c: float
    current_description: str
    current_emoji: str
    hourly: list[HourlyWeather]
    fetched_at: datetime


class TrainStatus(StrEnum):
    ON_TIME = "on_time"
    LATE = "late"
    CANCELLED = "cancelled"


class TrainDeparture(BaseModel):
    scheduled: time
    expected: time | None = None
    departs_at: datetime
    destination: str
    status: TrainStatus
    platform: str | None = None
    service_uid: str = ""

    @property
    def minutes_away(self) -> int:
        """Signed minutes until the effective departure, computed at access
        time so the countdown stays live between background refreshes.
        Negative once the train has left."""
        return int((self.departs_at - datetime.now(tz=UTC)).total_seconds() // 60)

    @property
    def display_minutes(self) -> int:
        """Countdown for display, floored at zero once the train has left."""
        return max(0, self.minutes_away)


class TrainDestinationGroup(BaseModel):
    destination_name: str
    destination_crs: str
    departures: list[TrainDeparture]


class TrainBoard(BaseModel):
    station_name: str
    destination_groups: list[TrainDestinationGroup]
    all_departures: list[TrainDeparture]
    fetched_at: datetime


class CalendarEvent(BaseModel):
    summary: str
    start: datetime | date
    end: datetime | date | None = None
    is_all_day: bool = False
    location: str | None = None


class TodayAgenda(BaseModel):
    events: list[CalendarEvent]
    fetched_at: datetime
    feed_count: int = 0
    failed_feed_count: int = 0
