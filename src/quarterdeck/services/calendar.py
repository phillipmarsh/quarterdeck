import asyncio
from datetime import UTC, date, datetime

import httpx
import icalendar
from loguru import logger

from quarterdeck.config import LONDON_TZ, settings
from quarterdeck.models import CalendarEvent, TodayAgenda


class CalendarFeedError(Exception):
    """Raised when no configured iCal feed could be fetched.

    Distinguishes an unreachable calendar from a genuinely empty day,
    so the dashboard can show an error rather than "No events today".
    """


def _parse_ical_events(cal_data: str, today: date) -> list[CalendarEvent]:
    """Parse iCal data and return events for the given date."""
    cal = icalendar.Calendar.from_ical(cal_data)
    events: list[CalendarEvent] = []

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        dt_start = component.get("dtstart")
        if dt_start is None:
            continue

        start_value = dt_start.dt
        summary = str(component.get("summary", "Untitled"))

        dt_end = component.get("dtend")
        end_value = dt_end.dt if dt_end is not None else None

        location_prop = component.get("location")
        location = str(location_prop) if location_prop is not None else None

        if isinstance(start_value, datetime):
            # Timed event — the day boundary is UK wall-clock, so a UTC
            # start near midnight lands on the correct local day
            event_date = (
                start_value.astimezone(LONDON_TZ).date()
                if start_value.tzinfo is not None
                else start_value.date()
            )
            if event_date != today:
                continue
            events.append(
                CalendarEvent(
                    summary=summary,
                    start=start_value,
                    end=end_value,
                    is_all_day=False,
                    location=location,
                )
            )
        elif isinstance(start_value, date):
            # All-day event — check if today is within the range
            if start_value > today:
                continue
            if isinstance(end_value, date) and end_value <= today:
                continue
            if start_value != today and end_value is None:
                continue
            events.append(
                CalendarEvent(
                    summary=summary,
                    start=start_value,
                    end=end_value,
                    is_all_day=True,
                    location=location,
                )
            )

    return events


def _sort_events(events: list[CalendarEvent]) -> list[CalendarEvent]:
    """Sort events: all-day first, then by start time."""

    def sort_key(event: CalendarEvent) -> tuple[int, datetime | date]:
        if event.is_all_day:
            return (0, event.start)
        return (1, event.start)

    return sorted(events, key=sort_key)


async def _fetch_feed(client: httpx.AsyncClient, url: str, today: date) -> list[CalendarEvent]:
    logger.info("Fetching iCal feed: {}", url[:60])
    response = await client.get(url)
    response.raise_for_status()
    return _parse_ical_events(response.text, today)


async def fetch_agenda() -> TodayAgenda:
    """Fetch and merge calendar events from all configured iCal feeds.

    Feeds are fetched concurrently so one slow feed cannot hold up the
    rest. A feed that fails is counted rather than fatal, unless every
    feed fails — an unreachable calendar must not masquerade as a free day.
    """
    feed_urls = settings.feed_url_list
    if not feed_urls:
        logger.warning("No iCal feed URLs configured")
        return TodayAgenda(events=[], fetched_at=datetime.now(tz=UTC))

    # "Today" is the UK wall-clock day, regardless of the host's timezone
    today = datetime.now(tz=LONDON_TZ).date()

    async with httpx.AsyncClient(timeout=15.0) as client:
        results = await asyncio.gather(
            *(_fetch_feed(client, url, today) for url in feed_urls),
            return_exceptions=True,
        )

    all_events: list[CalendarEvent] = []
    failed_feed_count = 0
    for url, result in zip(feed_urls, results, strict=True):
        if isinstance(result, BaseException):
            logger.error("Failed to fetch iCal feed {}: {}", url[:60], result)
            failed_feed_count += 1
            continue
        all_events.extend(result)

    if failed_feed_count == len(feed_urls):
        raise CalendarFeedError(f"All {len(feed_urls)} configured iCal feed(s) failed to fetch")

    return TodayAgenda(
        events=_sort_events(all_events),
        fetched_at=datetime.now(tz=UTC),
        feed_count=len(feed_urls),
        failed_feed_count=failed_feed_count,
    )
