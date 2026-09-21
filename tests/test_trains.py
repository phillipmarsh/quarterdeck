from datetime import UTC, datetime, time

import httpx
import respx
import time_machine

from quarterdeck.models import TrainStatus
from quarterdeck.services.trains import (
    RTT_BASE_URL,
    _calculate_minutes_away,
    _parse_departure,
    _parse_time,
    fetch_train_board,
)

MOCK_RTT_ALL_DEPARTURES = {
    "location": {"name": "Forest Hill", "crs": "FOH"},
    "services": [
        {
            "serviceUid": "W12345",
            "locationDetail": {
                "gbttBookedDeparture": "0948",
                "realtimeDeparture": "0948",
                "displayAs": "CALL",
                "platform": "1",
                "destination": [{"description": "London Bridge", "crs": "LBG"}],
            },
        },
        {
            "serviceUid": "W12346",
            "locationDetail": {
                "gbttBookedDeparture": "0952",
                "realtimeDeparture": "0955",
                "displayAs": "CALL",
                "platform": "2",
                "destination": [{"description": "Highbury & Islington", "crs": "HHY"}],
            },
        },
        {
            "serviceUid": "W12347",
            "locationDetail": {
                "gbttBookedDeparture": "1001",
                "displayAs": "CANCELLED_CALL",
                "platform": "1",
                "destination": [{"description": "London Bridge", "crs": "LBG"}],
            },
        },
        {
            "serviceUid": "W12348",
            "locationDetail": {
                "gbttBookedDeparture": "0930",
                "displayAs": "PASS",
                "destination": [{"description": "London Victoria", "crs": "VIC"}],
            },
        },
    ],
}

MOCK_RTT_LBG_DEPARTURES = {
    "location": {"name": "Forest Hill", "crs": "FOH"},
    "filter": {"destination": {"name": "London Bridge", "crs": "LBG"}},
    "services": [
        {
            "serviceUid": "W12345",
            "locationDetail": {
                "gbttBookedDeparture": "0948",
                "realtimeDeparture": "0948",
                "displayAs": "CALL",
                "platform": "1",
                "destination": [{"description": "London Bridge", "crs": "LBG"}],
            },
            "filter": {"destination": [{"description": "London Bridge", "crs": "LBG"}]},
        },
    ],
}

MOCK_RTT_HHY_DEPARTURES = {
    "location": {"name": "Forest Hill", "crs": "FOH"},
    "filter": {"destination": {"name": "Highbury & Islington", "crs": "HHY"}},
    "services": [
        {
            "serviceUid": "W12346",
            "locationDetail": {
                "gbttBookedDeparture": "0952",
                "realtimeDeparture": "0955",
                "displayAs": "CALL",
                "platform": "2",
                "destination": [{"description": "Highbury & Islington", "crs": "HHY"}],
            },
            "filter": {"destination": [{"description": "Highbury & Islington", "crs": "HHY"}]},
        },
    ],
}


class TestParseTime:
    """Test RTT time string parsing."""

    def test_parses_morning_time(self) -> None:
        """Given a morning time string, when parsed, then the correct time object is returned."""
        assert _parse_time("0948") == time(9, 48)

    def test_parses_afternoon_time(self) -> None:
        """Given an afternoon time string, when parsed, then the correct time object is returned."""
        assert _parse_time("1430") == time(14, 30)

    def test_parses_midnight(self) -> None:
        """Given midnight time string, when parsed, then 00:00 is returned."""
        assert _parse_time("0000") == time(0, 0)


class TestCalculateMinutesAway:
    """Test minutes-away calculation."""

    def test_calculates_minutes_correctly(self) -> None:
        """Given a departure time and now, when calculated,
        then the correct minutes are returned.
        """
        now = datetime(2026, 2, 17, 9, 42, tzinfo=UTC)
        result = _calculate_minutes_away(time(9, 48), now)
        assert result == 6

    def test_negative_for_past_trains(self) -> None:
        """Given a departure time in the past, when calculated,
        then a negative value is returned.
        """
        now = datetime(2026, 2, 17, 10, 0, tzinfo=UTC)
        result = _calculate_minutes_away(time(9, 48), now)
        assert result == -12


class TestParseDeparture:
    """Test RTT service parsing."""

    def test_parses_on_time_service(self) -> None:
        """Given an on-time service, when parsed, then status is ON_TIME."""
        now = datetime(2026, 2, 17, 9, 42, tzinfo=UTC)
        service = MOCK_RTT_ALL_DEPARTURES["services"][0]

        departure = _parse_departure(service, now)

        assert departure is not None
        assert departure.scheduled == time(9, 48)
        assert departure.status == TrainStatus.ON_TIME
        assert departure.minutes_away == 6
        assert departure.platform == "1"

    def test_parses_late_service(self) -> None:
        """Given a late service, when parsed, then status is LATE with correct expected time."""
        now = datetime(2026, 2, 17, 9, 42, tzinfo=UTC)
        service = MOCK_RTT_ALL_DEPARTURES["services"][1]

        departure = _parse_departure(service, now)

        assert departure is not None
        assert departure.status == TrainStatus.LATE
        assert departure.expected == time(9, 55)
        assert departure.minutes_away == 13

    def test_parses_cancelled_service(self) -> None:
        """Given a cancelled service, when parsed, then status is CANCELLED."""
        now = datetime(2026, 2, 17, 9, 42, tzinfo=UTC)
        service = MOCK_RTT_ALL_DEPARTURES["services"][2]

        departure = _parse_departure(service, now)

        assert departure is not None
        assert departure.status == TrainStatus.CANCELLED

    def test_skips_pass_service(self) -> None:
        """Given a passing (non-stopping) service, when parsed, then None is returned."""
        now = datetime(2026, 2, 17, 9, 42, tzinfo=UTC)
        service = MOCK_RTT_ALL_DEPARTURES["services"][3]

        departure = _parse_departure(service, now)

        assert departure is None


class TestFetchTrainBoard:
    """Test the full train board fetching flow."""

    @time_machine.travel("2026-02-17T09:42:00Z")
    @respx.mock
    async def test_fetches_all_and_filtered_departures(self, monkeypatch: object) -> None:
        """Given RTT responses, when fetched,
        then both all and per-destination departures are returned.
        """
        import quarterdeck.services.trains as trains_mod

        monkeypatch.setattr(  # type: ignore[attr-defined]
            trains_mod,
            "settings",
            type(
                "S",
                (),
                {
                    "train_station_crs": "FOH",
                    "destination_list": ["LBG", "HHY"],
                    "rtt_username": "test",
                    "rtt_password": "test",
                },
            )(),
        )

        respx.get(f"{RTT_BASE_URL}/json/search/FOH/2026/02/17").mock(
            return_value=httpx.Response(200, json=MOCK_RTT_ALL_DEPARTURES)
        )
        respx.get(f"{RTT_BASE_URL}/json/search/FOH/to/LBG/2026/02/17").mock(
            return_value=httpx.Response(200, json=MOCK_RTT_LBG_DEPARTURES)
        )
        respx.get(f"{RTT_BASE_URL}/json/search/FOH/to/HHY/2026/02/17").mock(
            return_value=httpx.Response(200, json=MOCK_RTT_HHY_DEPARTURES)
        )

        board = await fetch_train_board()

        assert board.station_name == "Forest Hill"
        # All departures should exclude PASS and past trains
        assert len(board.all_departures) == 3
        # Two destination groups
        assert len(board.destination_groups) == 2
        assert board.destination_groups[0].destination_name == "London Bridge"
        assert board.destination_groups[1].destination_name == "Highbury & Islington"

    @time_machine.travel("2026-02-17T09:42:00Z")
    @respx.mock
    async def test_caches_result(self, monkeypatch: object) -> None:
        """Given a successful fetch, when called again, then the cached result is returned."""
        import quarterdeck.services.trains as trains_mod

        monkeypatch.setattr(  # type: ignore[attr-defined]
            trains_mod,
            "settings",
            type(
                "S",
                (),
                {
                    "train_station_crs": "FOH",
                    "destination_list": ["LBG"],
                    "rtt_username": "test",
                    "rtt_password": "test",
                },
            )(),
        )

        all_route = respx.get(f"{RTT_BASE_URL}/json/search/FOH/2026/02/17").mock(
            return_value=httpx.Response(200, json=MOCK_RTT_ALL_DEPARTURES)
        )
        respx.get(f"{RTT_BASE_URL}/json/search/FOH/to/LBG/2026/02/17").mock(
            return_value=httpx.Response(200, json=MOCK_RTT_LBG_DEPARTURES)
        )

        first = await fetch_train_board()
        second = await fetch_train_board()

        assert first == second
        assert all_route.call_count == 1
