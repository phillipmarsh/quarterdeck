from datetime import UTC, date, datetime

import httpx
import pytest
import respx
import time_machine

from quarterdeck.models import CalendarEvent
from quarterdeck.services.calendar import (
    CalendarFeedError,
    _parse_ical_events,
    _sort_events,
    fetch_agenda,
)

ICAL_TIMED_EVENT = """\
BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Team standup
DTSTART:20260217T090000Z
DTEND:20260217T093000Z
END:VEVENT
END:VCALENDAR
"""

ICAL_ALL_DAY_EVENT = """\
BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Bank Holiday
DTSTART;VALUE=DATE:20260217
DTEND;VALUE=DATE:20260218
END:VEVENT
END:VCALENDAR
"""

ICAL_MIXED_EVENTS = """\
BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Morning run
DTSTART;VALUE=DATE:20260217
DTEND;VALUE=DATE:20260218
END:VEVENT
BEGIN:VEVENT
SUMMARY:Team standup
DTSTART:20260217T090000Z
DTEND:20260217T093000Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:Dentist
DTSTART:20260217T113000Z
DTEND:20260217T120000Z
LOCATION:123 High Street
END:VEVENT
BEGIN:VEVENT
SUMMARY:Yesterday's meeting
DTSTART:20260216T140000Z
DTEND:20260216T150000Z
END:VEVENT
END:VCALENDAR
"""

ICAL_MULTI_DAY_ALL_DAY = """\
BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Holiday
DTSTART;VALUE=DATE:20260216
DTEND;VALUE=DATE:20260219
END:VEVENT
END:VCALENDAR
"""


class TestParseIcalEvents:
    """Test iCal parsing and date filtering."""

    def test_parses_timed_event_on_target_date(self) -> None:
        """Given a timed event on today, when parsed, then the event is included."""
        events = _parse_ical_events(ICAL_TIMED_EVENT, date(2026, 2, 17))

        assert len(events) == 1
        assert events[0].summary == "Team standup"
        assert not events[0].is_all_day

    def test_parses_all_day_event_on_target_date(self) -> None:
        """Given an all-day event on today, when parsed,
        then it is included and marked as all-day.
        """
        events = _parse_ical_events(ICAL_ALL_DAY_EVENT, date(2026, 2, 17))

        assert len(events) == 1
        assert events[0].summary == "Bank Holiday"
        assert events[0].is_all_day

    def test_excludes_events_on_other_dates(self) -> None:
        """Given events on different dates, when parsed for today,
        then only today's events are returned.
        """
        events = _parse_ical_events(ICAL_MIXED_EVENTS, date(2026, 2, 17))

        summaries = [e.summary for e in events]
        assert "Yesterday's meeting" not in summaries
        assert len(events) == 3

    def test_includes_location_when_present(self) -> None:
        """Given an event with a location, when parsed, then the location is captured."""
        events = _parse_ical_events(ICAL_MIXED_EVENTS, date(2026, 2, 17))
        dentist = next(e for e in events if e.summary == "Dentist")

        assert dentist.location == "123 High Street"

    def test_multi_day_all_day_event_included_within_range(self) -> None:
        """Given a multi-day all-day event, when parsed on a day within range,
        then it is included.
        """
        events = _parse_ical_events(ICAL_MULTI_DAY_ALL_DAY, date(2026, 2, 17))

        assert len(events) == 1
        assert events[0].summary == "Holiday"

    def test_utc_event_near_midnight_lands_on_local_day(self) -> None:
        """Given a timed event at 23:30 UTC during BST (00:30 next day in London),
        when parsed for the London day, then it is included.
        """
        ical = """\
BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Late night
DTSTART:20260630T233000Z
DTEND:20260701T003000Z
END:VEVENT
END:VCALENDAR
"""
        events = _parse_ical_events(ical, date(2026, 7, 1))

        assert len(events) == 1
        assert events[0].summary == "Late night"

    def test_multi_day_all_day_event_excluded_after_range(self) -> None:
        """Given a multi-day all-day event, when parsed after the end date, then it is excluded."""
        events = _parse_ical_events(ICAL_MULTI_DAY_ALL_DAY, date(2026, 2, 19))

        assert len(events) == 0


class TestSortEvents:
    """Test event sorting logic."""

    def test_all_day_events_sorted_before_timed(self) -> None:
        """Given mixed event types, when sorted, then all-day events come first."""
        events = [
            CalendarEvent(
                summary="Standup",
                start=datetime(2026, 2, 17, 9, 0, tzinfo=UTC),
                is_all_day=False,
            ),
            CalendarEvent(
                summary="Holiday",
                start=date(2026, 2, 17),
                is_all_day=True,
            ),
        ]

        sorted_events = _sort_events(events)

        assert sorted_events[0].summary == "Holiday"
        assert sorted_events[1].summary == "Standup"

    def test_timed_events_sorted_by_start(self) -> None:
        """Given multiple timed events, when sorted, then they are ordered by start time."""
        events = [
            CalendarEvent(
                summary="Late meeting",
                start=datetime(2026, 2, 17, 14, 0, tzinfo=UTC),
                is_all_day=False,
            ),
            CalendarEvent(
                summary="Early meeting",
                start=datetime(2026, 2, 17, 9, 0, tzinfo=UTC),
                is_all_day=False,
            ),
        ]

        sorted_events = _sort_events(events)

        assert sorted_events[0].summary == "Early meeting"
        assert sorted_events[1].summary == "Late meeting"


class TestFetchAgenda:
    """Test the full agenda fetching flow."""

    @time_machine.travel("2026-02-17T10:00:00Z")
    @respx.mock
    async def test_fetches_and_merges_multiple_feeds(self, monkeypatch: object) -> None:
        """Given two iCal feeds, when fetched, then events from both are merged and sorted."""
        import quarterdeck.services.calendar as cal_mod

        monkeypatch.setattr(  # type: ignore[attr-defined]
            cal_mod,
            "settings",
            type(
                "S",
                (),
                {
                    "feed_url_list": [
                        "https://cal.example.com/feed1.ics",
                        "https://cal.example.com/feed2.ics",
                    ],
                },
            )(),
        )

        feed1 = """\
BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:From feed 1
DTSTART:20260217T110000Z
DTEND:20260217T120000Z
END:VEVENT
END:VCALENDAR
"""
        feed2 = """\
BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:From feed 2
DTSTART:20260217T090000Z
DTEND:20260217T100000Z
END:VEVENT
END:VCALENDAR
"""
        respx.get("https://cal.example.com/feed1.ics").mock(
            return_value=httpx.Response(200, text=feed1)
        )
        respx.get("https://cal.example.com/feed2.ics").mock(
            return_value=httpx.Response(200, text=feed2)
        )

        agenda = await fetch_agenda()

        assert len(agenda.events) == 2
        assert agenda.events[0].summary == "From feed 2"
        assert agenda.events[1].summary == "From feed 1"

    @time_machine.travel("2026-02-17T10:00:00Z")
    @respx.mock
    async def test_continues_when_one_feed_fails(self, monkeypatch: object) -> None:
        """Given one failing feed, when fetched,
        then events from working feeds are still returned.
        """
        import quarterdeck.services.calendar as cal_mod

        monkeypatch.setattr(  # type: ignore[attr-defined]
            cal_mod,
            "settings",
            type(
                "S",
                (),
                {
                    "feed_url_list": [
                        "https://cal.example.com/broken.ics",
                        "https://cal.example.com/good.ics",
                    ],
                },
            )(),
        )

        good_feed = """\
BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Working event
DTSTART:20260217T090000Z
DTEND:20260217T100000Z
END:VEVENT
END:VCALENDAR
"""
        respx.get("https://cal.example.com/broken.ics").mock(return_value=httpx.Response(500))
        respx.get("https://cal.example.com/good.ics").mock(
            return_value=httpx.Response(200, text=good_feed)
        )

        agenda = await fetch_agenda()

        assert len(agenda.events) == 1
        assert agenda.events[0].summary == "Working event"
        assert agenda.feed_count == 2
        assert agenda.failed_feed_count == 1

    @time_machine.travel("2026-02-17T10:00:00Z")
    @respx.mock
    async def test_raises_when_all_feeds_fail(self, monkeypatch: object) -> None:
        """Given every configured feed failing, when fetched,
        then CalendarFeedError is raised rather than an empty agenda returned.
        """
        import quarterdeck.services.calendar as cal_mod

        monkeypatch.setattr(  # type: ignore[attr-defined]
            cal_mod,
            "settings",
            type(
                "S",
                (),
                {
                    "feed_url_list": [
                        "https://cal.example.com/broken1.ics",
                        "https://cal.example.com/broken2.ics",
                    ],
                },
            )(),
        )

        respx.get("https://cal.example.com/broken1.ics").mock(return_value=httpx.Response(500))
        respx.get("https://cal.example.com/broken2.ics").mock(return_value=httpx.Response(401))

        with pytest.raises(CalendarFeedError):
            await fetch_agenda()

    @time_machine.travel("2026-02-17T10:00:00Z")
    async def test_returns_unconfigured_agenda_when_no_feeds(self, monkeypatch: object) -> None:
        """Given no configured feeds, when fetched,
        then an empty agenda with a zero feed count is returned.
        """
        import quarterdeck.services.calendar as cal_mod

        monkeypatch.setattr(  # type: ignore[attr-defined]
            cal_mod,
            "settings",
            type("S", (), {"feed_url_list": []})(),
        )

        agenda = await fetch_agenda()

        assert agenda.events == []
        assert agenda.feed_count == 0
        assert agenda.failed_feed_count == 0
