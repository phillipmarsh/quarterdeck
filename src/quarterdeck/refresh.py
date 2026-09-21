"""Background refresh loops that keep per-source snapshots current.

Fetching happens off the request path: each data source has a Refresher
running its own asyncio loop on a fixed cadence. Requests only ever read
the latest snapshot, so panels render instantly and a failed refresh
degrades to stale data rather than an error. A source that is failing or
partially degraded retries on a shorter interval so recovery is quick.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

import httpx
from loguru import logger

from quarterdeck.models import TodayAgenda, TrainBoard, WeatherForecast
from quarterdeck.services.calendar import fetch_agenda
from quarterdeck.services.trains import fetch_train_board
from quarterdeck.services.weather import fetch_weather


class ErrorKind(StrEnum):
    AUTH = "auth"
    TRANSIENT = "transient"
    UNKNOWN = "unknown"


def classify_error(exc: BaseException) -> ErrorKind:
    """Distinguish fix-your-credentials failures from ones that self-heal.

    The dashboard is unattended, so telling the viewer whether to act
    (rotate credentials) or wait (network blip) is the difference between
    a useful error and a mystery.
    """
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403):
        return ErrorKind.AUTH
    if isinstance(exc, httpx.TransportError):
        return ErrorKind.TRANSIENT
    return ErrorKind.UNKNOWN


@dataclass(frozen=True)
class Snapshot[T]:
    """The latest known state of one data source.

    data survives refresh failures: it is the last successful result,
    with fetched_at recording when it was obtained. error/error_kind
    describe the most recent refresh attempt, so data plus error means
    "showing stale data while the source is down".
    """

    data: T | None = None
    fetched_at: datetime | None = None
    error: str | None = None
    error_kind: ErrorKind | None = None

    @property
    def is_stale(self) -> bool:
        return self.data is not None and self.error is not None


class Refresher[T]:
    """Owns the fetch cadence for one data source.

    is_degraded lets a source flag a partially failed result (e.g. one of
    two calendar feeds down) so it retries on the shorter interval even
    though the fetch itself succeeded.
    """

    def __init__(
        self,
        name: str,
        fetch: Callable[[], Awaitable[T]],
        interval_seconds: float,
        retry_interval_seconds: float | None = None,
        is_degraded: Callable[[T], bool] | None = None,
    ) -> None:
        self.name = name
        self._fetch = fetch
        self._interval_seconds = interval_seconds
        self._retry_interval_seconds = (
            retry_interval_seconds if retry_interval_seconds is not None else interval_seconds
        )
        self._is_degraded = is_degraded
        self.snapshot: Snapshot[T] = Snapshot()

    async def refresh_once(self) -> None:
        """Fetch once, keeping the previous data if the fetch fails."""
        try:
            data = await self._fetch()
        except Exception as exc:
            kind = classify_error(exc)
            logger.exception("Refresh of {} failed ({})", self.name, kind)
            self.snapshot = Snapshot(
                data=self.snapshot.data,
                fetched_at=self.snapshot.fetched_at,
                error=str(exc),
                error_kind=kind,
            )
            return

        self.snapshot = Snapshot(data=data, fetched_at=datetime.now(tz=UTC))

    def _next_interval(self) -> float:
        if self.snapshot.error is not None:
            return self._retry_interval_seconds
        data = self.snapshot.data
        if self._is_degraded is not None and data is not None and self._is_degraded(data):
            return self._retry_interval_seconds
        return self._interval_seconds

    async def run(self) -> None:
        while True:
            await self.refresh_once()
            await asyncio.sleep(self._next_interval())


@dataclass
class Sources:
    """The dashboard's data sources, exposed to routes via app.state."""

    weather: Refresher[WeatherForecast]
    trains: Refresher[TrainBoard]
    agenda: Refresher[TodayAgenda]

    def all(
        self,
    ) -> tuple[Refresher[WeatherForecast], Refresher[TrainBoard], Refresher[TodayAgenda]]:
        return (self.weather, self.trains, self.agenda)


def build_sources() -> Sources:
    """Wire each fetcher to its refresh cadence.

    Intervals match how often the underlying data meaningfully changes;
    retry intervals are shorter so an outage or partial feed failure
    recovers quickly rather than waiting out a full cycle.
    """
    return Sources(
        weather=Refresher(
            "weather", fetch_weather, interval_seconds=1800, retry_interval_seconds=120
        ),
        trains=Refresher("trains", fetch_train_board, interval_seconds=30),
        agenda=Refresher(
            "agenda",
            fetch_agenda,
            interval_seconds=300,
            retry_interval_seconds=60,
            is_degraded=lambda agenda: agenda.failed_feed_count > 0,
        ),
    )
