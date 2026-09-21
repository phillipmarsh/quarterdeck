from datetime import UTC, datetime, time

import httpx
from cachetools import TTLCache
from loguru import logger

from quarterdeck.config import settings
from quarterdeck.models import (
    TrainBoard,
    TrainDeparture,
    TrainDestinationGroup,
    TrainStatus,
)

RTT_BASE_URL = "https://api.rtt.io/api/v1"

_cache: TTLCache[str, TrainBoard] = TTLCache(maxsize=1, ttl=30)  # 30 sec


def _parse_time(time_str: str) -> time:
    """Parse RTT time string (HHMM) into a time object."""
    return time(hour=int(time_str[:2]), minute=int(time_str[2:4]))


def _calculate_minutes_away(departure_time: time, now: datetime) -> int:
    """Calculate minutes until the train departs."""
    now_minutes = now.hour * 60 + now.minute
    dep_minutes = departure_time.hour * 60 + departure_time.minute
    return dep_minutes - now_minutes


def _parse_departure(service: dict, now: datetime) -> TrainDeparture | None:
    """Parse a single RTT service object into a TrainDeparture."""
    location_detail = service.get("locationDetail", {})

    # Skip non-stopping services
    display_as = location_detail.get("displayAs", "CALL")
    if display_as == "PASS":
        return None

    # Determine status
    status = TrainStatus.CANCELLED if display_as == "CANCELLED_CALL" else TrainStatus.ON_TIME

    # Get scheduled departure time
    scheduled_str = location_detail.get("gbttBookedDeparture")
    if scheduled_str is None:
        return None
    scheduled = _parse_time(scheduled_str)

    # Get realtime departure if available
    realtime_str = location_detail.get("realtimeDeparture")
    expected: time | None = None
    if realtime_str is not None:
        expected = _parse_time(realtime_str)
        # Check if late (realtime is after scheduled)
        if status != TrainStatus.CANCELLED and expected > scheduled:
            status = TrainStatus.LATE

    effective_time = expected if expected is not None else scheduled
    minutes_away = _calculate_minutes_away(effective_time, now)

    # Get destination name
    destination_parts = service.get("filter", {}).get("destination", [])
    if destination_parts:
        destination = destination_parts[0].get("description", "Unknown")
    else:
        destination = location_detail.get("destination", [{}])[0].get("description", "Unknown")

    platform = location_detail.get("platform")

    return TrainDeparture(
        scheduled=scheduled,
        expected=expected,
        minutes_away=minutes_away,
        destination=destination,
        status=status,
        platform=platform,
        service_uid=service.get("serviceUid", ""),
    )


def _get_auth() -> tuple[str, str]:
    return (settings.rtt_username, settings.rtt_password)


async def fetch_train_board() -> TrainBoard:
    """Fetch train departures from RTT for the configured station and destinations."""
    cached = _cache.get("trains")
    if cached is not None:
        return cached

    station_crs = settings.train_station_crs
    destinations = settings.destination_list
    auth = _get_auth()
    now = datetime.now(tz=UTC)
    today_str = now.strftime("%Y/%m/%d")

    logger.info("Fetching train departures for {}", station_crs)

    async with httpx.AsyncClient(timeout=10.0, auth=auth) as client:
        # Fetch all departures
        all_response = await client.get(
            f"{RTT_BASE_URL}/json/search/{station_crs}/{today_str}",
        )
        all_response.raise_for_status()
        all_data = all_response.json()

        station_name = all_data.get("location", {}).get("name", station_crs)

        # Parse all departures
        all_departures: list[TrainDeparture] = []
        for service in all_data.get("services", []) or []:
            departure = _parse_departure(service, now)
            if departure is not None and departure.minutes_away >= 0:
                all_departures.append(departure)

        # Fetch per-destination
        destination_groups: list[TrainDestinationGroup] = []
        for dest_crs in destinations:
            dest_response = await client.get(
                f"{RTT_BASE_URL}/json/search/{station_crs}/to/{dest_crs}/{today_str}",
            )
            dest_response.raise_for_status()
            dest_data = dest_response.json()

            dest_name = dest_crs
            dest_departures: list[TrainDeparture] = []
            for service in dest_data.get("services", []) or []:
                departure = _parse_departure(service, now)
                if departure is not None and departure.minutes_away >= 0:
                    dest_departures.append(departure)
                    if dest_name == dest_crs and departure.destination:
                        dest_name = departure.destination

            # Use filter destination name from response if available
            filter_dest = dest_data.get("filter", {}).get("destination", {})
            if filter_dest.get("name"):
                dest_name = filter_dest["name"]

            destination_groups.append(
                TrainDestinationGroup(
                    destination_name=dest_name,
                    destination_crs=dest_crs,
                    departures=sorted(dest_departures, key=lambda d: d.minutes_away),
                )
            )

    board = TrainBoard(
        station_name=station_name,
        destination_groups=destination_groups,
        all_departures=sorted(all_departures, key=lambda d: d.minutes_away),
        fetched_at=now,
    )

    _cache["trains"] = board
    return board
