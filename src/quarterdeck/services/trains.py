"""Train departures from the Realtime Trains next-generation API.

Uses the /gb-nr/location line-up endpoint on data.rtt.io with Bearer
token auth (the legacy basic-auth api.rtt.io is switched off from
September 2026). Token handling, including the refresh-token exchange,
lives in rtt_auth.
"""

import asyncio
from datetime import UTC, datetime

import httpx
from loguru import logger

from quarterdeck.config import LONDON_TZ, settings
from quarterdeck.models import (
    TrainBoard,
    TrainDeparture,
    TrainDestinationGroup,
    TrainStatus,
)
from quarterdeck.services.rtt_auth import RTT_BASE_URL, resolve_access_token

# Look-ahead for the line-up query; the API default of 60 minutes can
# leave sparse routes with too few departures to fill a panel
TIME_WINDOW_MINUTES = 120

# displayAs values meaning the train no longer calls at this location
CANCELLED_DISPLAY_VALUES = frozenset({"CANCELLED", "DIVERTED"})


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse a StandardisedDateTime; a naive value means the location's
    local timezone per the API specification."""
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LONDON_TZ)
    return parsed


def _resolve_platform(service: dict) -> str | None:
    platform_data = service.get("locationMetadata", {}).get("platform") or {}
    return platform_data.get("actual") or platform_data.get("planned")


def _resolve_destination_name(service: dict) -> str:
    destinations = service.get("destination", [])
    if not destinations:
        return "Unknown"
    return destinations[0].get("location", {}).get("description", "Unknown")


def _parse_departure(service: dict, now: datetime) -> TrainDeparture | None:
    """Convert a location line-up object into a TrainDeparture.

    Returns None for services that do not belong on a departure board:
    passes, services without an advertised departure, and services not
    in passenger use.
    """
    temporal = service.get("temporalData", {})
    display_as = temporal.get("displayAs") or "PASS"
    if display_as == "PASS":
        return None

    if service.get("scheduleMetadata", {}).get("inPassengerService") is False:
        return None

    departure_data = temporal.get("departure") or {}
    scheduled_dt = _parse_datetime(departure_data.get("scheduleAdvertised"))
    if scheduled_dt is None:
        return None

    expected_dt = _parse_datetime(
        departure_data.get("realtimeForecast") or departure_data.get("realtimeActual")
    )

    is_cancelled = display_as in CANCELLED_DISPLAY_VALUES or departure_data.get(
        "isCancelled", False
    )
    status = TrainStatus.CANCELLED if is_cancelled else TrainStatus.ON_TIME
    if (
        status is not TrainStatus.CANCELLED
        and expected_dt is not None
        and expected_dt > scheduled_dt
    ):
        status = TrainStatus.LATE

    effective_dt = expected_dt if expected_dt is not None else scheduled_dt
    minutes_away = int((effective_dt - now).total_seconds() // 60)

    return TrainDeparture(
        scheduled=scheduled_dt.astimezone(LONDON_TZ).time(),
        expected=expected_dt.astimezone(LONDON_TZ).time() if expected_dt is not None else None,
        minutes_away=minutes_away,
        destination=_resolve_destination_name(service),
        status=status,
        platform=_resolve_platform(service),
        service_uid=service.get("scheduleMetadata", {}).get("uniqueIdentity", ""),
    )


def _parse_services(line_up: dict, now: datetime) -> list[TrainDeparture]:
    departures: list[TrainDeparture] = []
    for service in line_up.get("services", []) or []:
        departure = _parse_departure(service, now)
        if departure is not None and departure.minutes_away >= 0:
            departures.append(departure)
    return sorted(departures, key=lambda d: d.minutes_away)


# CRS -> station name, resolved once per process from /data/stops (the
# line-up responses carry no CRS codes to resolve names from directly)
_station_names: dict[str, str] = {}


async def _resolve_station_names(client: httpx.AsyncClient) -> dict[str, str]:
    if _station_names:
        return _station_names

    response = await client.get(f"{RTT_BASE_URL}/data/stops")
    response.raise_for_status()
    for stop in response.json().get("stops", []):
        code = stop.get("shortCode")
        if code and code not in _station_names:
            _station_names[code] = stop.get("description", code)
    return _station_names


async def _fetch_line_up(
    client: httpx.AsyncClient, code: str, filter_to: str | None = None
) -> dict:
    params: dict[str, str | int] = {"code": code, "timeWindow": TIME_WINDOW_MINUTES}
    if filter_to is not None:
        params["filterTo"] = filter_to
    response = await client.get(f"{RTT_BASE_URL}/gb-nr/location", params=params)
    response.raise_for_status()
    if response.status_code == 204:
        return {}
    return response.json()


async def fetch_train_board() -> TrainBoard:
    """Fetch train departures for the configured station and destinations.

    The unfiltered line-up and each per-destination line-up are fetched
    concurrently against the shared rate limit.
    """
    station_crs = settings.train_station_crs
    destinations = settings.destination_list
    now = datetime.now(tz=UTC)

    logger.info("Fetching train departures for {}", station_crs)

    async with httpx.AsyncClient(timeout=10.0) as client:
        access_token = await resolve_access_token(client)
        # An empty token would make an illegal "Bearer " header; sending no
        # header lets the API's own 401 drive the check-your-token panel hint
        if access_token:
            client.headers["Authorization"] = f"Bearer {access_token}"
        station_names = await _resolve_station_names(client)
        all_data, *destination_data = await asyncio.gather(
            _fetch_line_up(client, station_crs),
            *(_fetch_line_up(client, station_crs, dest_crs) for dest_crs in destinations),
        )

    station_name = all_data.get("query", {}).get("location", {}).get("description", station_crs)

    destination_groups = [
        TrainDestinationGroup(
            destination_name=station_names.get(dest_crs, dest_crs),
            destination_crs=dest_crs,
            departures=_parse_services(line_up, now),
        )
        for dest_crs, line_up in zip(destinations, destination_data, strict=True)
    ]

    return TrainBoard(
        station_name=station_name,
        destination_groups=destination_groups,
        all_departures=_parse_services(all_data, now),
        fetched_at=now,
    )
