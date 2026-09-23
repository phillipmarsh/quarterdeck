from datetime import UTC, datetime, time

import httpx
import pytest
import respx
import time_machine

import quarterdeck.services.rtt_auth as rtt_auth_mod
import quarterdeck.services.trains as trains_mod
from quarterdeck.config import Settings
from quarterdeck.models import TrainStatus
from quarterdeck.services.rtt_auth import RTT_BASE_URL
from quarterdeck.services.trains import (
    _parse_datetime,
    _parse_departure,
    _parse_services,
    fetch_train_board,
)

MOCK_EXCHANGE_RESPONSE = {
    "token": "short-life-access-token",
    "entitlements": [],
    "validUntil": "2026-02-17T10:12:00+00:00",
}

MOCK_STOPS_RESPONSE = {
    "stops": [
        {"shortCode": "FOH", "description": "Forest Hill"},
        {"shortCode": "LBG", "description": "London Bridge"},
        {"shortCode": "HHY", "description": "Highbury & Islington"},
    ]
}


def _service(
    uid: str,
    destination: str,
    destination_crs: str,
    scheduled: str,
    forecast: str | None = None,
    display_as: str = "CALL",
    platform: str | None = "1",
    in_passenger_service: bool = True,
) -> dict:
    return {
        "scheduleMetadata": {
            "uniqueIdentity": uid,
            "inPassengerService": in_passenger_service,
        },
        "temporalData": {
            "displayAs": display_as,
            "departure": {
                "scheduleAdvertised": scheduled,
                "realtimeForecast": forecast,
            },
        },
        "locationMetadata": {"platform": {"planned": platform, "actual": None}},
        "destination": [
            {"location": {"description": destination, "shortCodes": [destination_crs]}}
        ],
    }


ON_TIME_SERVICE = _service(
    "gb-nr:W12345:2026-02-17",
    "London Bridge",
    "LBG",
    scheduled="2026-02-17T09:48:00Z",
    forecast="2026-02-17T09:48:00Z",
)

LATE_SERVICE = _service(
    "gb-nr:W12346:2026-02-17",
    "Highbury & Islington",
    "HHY",
    scheduled="2026-02-17T09:52:00Z",
    forecast="2026-02-17T09:55:00Z",
    platform="2",
)

CANCELLED_SERVICE = _service(
    "gb-nr:W12347:2026-02-17",
    "London Bridge",
    "LBG",
    scheduled="2026-02-17T10:01:00Z",
    display_as="CANCELLED",
)

PASS_SERVICE = _service(
    "gb-nr:W12348:2026-02-17",
    "London Victoria",
    "VIC",
    scheduled="2026-02-17T09:50:00Z",
    display_as="PASS",
)

DEPARTED_SERVICE = _service(
    "gb-nr:W12349:2026-02-17",
    "London Bridge",
    "LBG",
    scheduled="2026-02-17T09:30:00Z",
    forecast="2026-02-17T09:30:00Z",
)

MOCK_ALL_LINE_UP = {
    "query": {"location": {"description": "Forest Hill", "shortCodes": ["FOH"]}},
    "services": [
        ON_TIME_SERVICE,
        LATE_SERVICE,
        CANCELLED_SERVICE,
        PASS_SERVICE,
        DEPARTED_SERVICE,
    ],
}

MOCK_LBG_LINE_UP = {
    "query": {"location": {"description": "Forest Hill", "shortCodes": ["FOH"]}},
    "services": [ON_TIME_SERVICE, CANCELLED_SERVICE],
}

MOCK_HHY_LINE_UP = {
    "query": {"location": {"description": "Forest Hill", "shortCodes": ["FOH"]}},
    "services": [LATE_SERVICE],
}

NOW = datetime(2026, 2, 17, 9, 42, tzinfo=UTC)


class TestParseDatetime:
    """Test StandardisedDateTime parsing."""

    def test_parses_utc_datetime(self) -> None:
        """Given a Z-suffixed datetime, when parsed, then an aware UTC datetime is returned."""
        parsed = _parse_datetime("2026-02-17T09:48:00Z")

        assert parsed == datetime(2026, 2, 17, 9, 48, tzinfo=UTC)

    def test_naive_datetime_assumes_london(self) -> None:
        """Given a naive datetime, when parsed,
        then the location's local timezone is assumed per the API specification.
        """
        parsed = _parse_datetime("2026-07-01T13:00:00")

        assert parsed is not None
        assert parsed.utcoffset() is not None
        # July is BST: 13:00 London is 12:00 UTC
        assert parsed.astimezone(UTC) == datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

    def test_none_returns_none(self) -> None:
        """Given no value, when parsed, then None is returned."""
        assert _parse_datetime(None) is None


class TestParseDeparture:
    """Test line-up object parsing."""

    def test_parses_on_time_service(self) -> None:
        """Given an on-time service, when parsed, then status is ON_TIME."""
        departure = _parse_departure(ON_TIME_SERVICE, NOW)

        assert departure is not None
        assert departure.scheduled == time(9, 48)
        assert departure.status == TrainStatus.ON_TIME
        assert departure.minutes_away == 6
        assert departure.platform == "1"
        assert departure.destination == "London Bridge"

    def test_parses_late_service(self) -> None:
        """Given a late service, when parsed, then status is LATE with correct expected time."""
        departure = _parse_departure(LATE_SERVICE, NOW)

        assert departure is not None
        assert departure.status == TrainStatus.LATE
        assert departure.expected == time(9, 55)
        assert departure.minutes_away == 13

    def test_parses_cancelled_service(self) -> None:
        """Given a cancelled service, when parsed, then status is CANCELLED."""
        departure = _parse_departure(CANCELLED_SERVICE, NOW)

        assert departure is not None
        assert departure.status == TrainStatus.CANCELLED

    def test_cancelled_departure_flag_marks_cancelled(self) -> None:
        """Given a service whose departure carries isCancelled, when parsed,
        then status is CANCELLED even though displayAs is CALL.
        """
        service = _service(
            "gb-nr:W12350:2026-02-17",
            "London Bridge",
            "LBG",
            scheduled="2026-02-17T09:58:00Z",
        )
        service["temporalData"]["departure"]["isCancelled"] = True

        departure = _parse_departure(service, NOW)

        assert departure is not None
        assert departure.status == TrainStatus.CANCELLED

    def test_skips_pass_service(self) -> None:
        """Given a passing (non-stopping) service, when parsed, then None is returned."""
        assert _parse_departure(PASS_SERVICE, NOW) is None

    def test_skips_non_passenger_service(self) -> None:
        """Given an empty-stock working, when parsed, then None is returned."""
        service = _service(
            "gb-nr:W12351:2026-02-17",
            "London Bridge",
            "LBG",
            scheduled="2026-02-17T09:58:00Z",
            in_passenger_service=False,
        )

        assert _parse_departure(service, NOW) is None

    def test_skips_service_without_advertised_departure(self) -> None:
        """Given a service with no advertised departure (e.g. a terminating train),
        when parsed, then None is returned.
        """
        service = _service(
            "gb-nr:W12352:2026-02-17",
            "London Bridge",
            "LBG",
            scheduled="2026-02-17T09:58:00Z",
        )
        service["temporalData"]["departure"] = {}

        assert _parse_departure(service, NOW) is None

    def test_bst_times_render_as_london_wall_clock(self) -> None:
        """Given a UTC departure time during BST, when parsed,
        then the displayed time is London wall-clock time.
        """
        service = _service(
            "gb-nr:W12353:2026-07-01",
            "London Bridge",
            "LBG",
            scheduled="2026-07-01T12:00:00Z",
        )
        summer_now = datetime(2026, 7, 1, 11, 50, tzinfo=UTC)

        departure = _parse_departure(service, summer_now)

        assert departure is not None
        assert departure.scheduled == time(13, 0)


class TestParseServices:
    """Test line-up filtering and ordering."""

    def test_filters_departed_and_passing_services(self) -> None:
        """Given a mixed line-up, when parsed,
        then departed trains and passes are excluded and the rest sorted by soonest.
        """
        departures = _parse_services(MOCK_ALL_LINE_UP, NOW)

        assert len(departures) == 3
        assert [d.minutes_away for d in departures] == sorted(d.minutes_away for d in departures)
        assert all(d.minutes_away >= 0 for d in departures)


class TestFetchTrainBoard:
    """Test the full train board fetching flow."""

    @time_machine.travel("2026-02-17T09:42:00Z")
    @respx.mock
    async def test_fetches_all_and_filtered_departures(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Given next-generation API responses, when fetched,
        then both all and per-destination departures are returned
        using an exchanged access token.
        """
        settings = Settings.model_construct(
            train_station_crs="FOH",
            train_destinations="LBG,HHY",
            rtt_api_token="refresh-token",
        )
        monkeypatch.setattr(trains_mod, "settings", settings)
        monkeypatch.setattr(rtt_auth_mod, "settings", settings)

        respx.get(f"{RTT_BASE_URL}/api/get_access_token").mock(
            return_value=httpx.Response(200, json=MOCK_EXCHANGE_RESPONSE)
        )
        respx.get(f"{RTT_BASE_URL}/data/stops").mock(
            return_value=httpx.Response(200, json=MOCK_STOPS_RESPONSE)
        )
        # Filtered routes are registered first: respx matches in
        # registration order and the unfiltered params are a subset
        respx.get(f"{RTT_BASE_URL}/gb-nr/location", params={"code": "FOH", "filterTo": "LBG"}).mock(
            return_value=httpx.Response(200, json=MOCK_LBG_LINE_UP)
        )
        respx.get(f"{RTT_BASE_URL}/gb-nr/location", params={"code": "FOH", "filterTo": "HHY"}).mock(
            return_value=httpx.Response(200, json=MOCK_HHY_LINE_UP)
        )
        all_route = respx.get(f"{RTT_BASE_URL}/gb-nr/location", params={"code": "FOH"}).mock(
            return_value=httpx.Response(200, json=MOCK_ALL_LINE_UP)
        )

        board = await fetch_train_board()

        assert board.station_name == "Forest Hill"
        assert len(board.all_departures) == 3
        assert len(board.destination_groups) == 2
        assert board.destination_groups[0].destination_name == "London Bridge"
        assert board.destination_groups[1].destination_name == "Highbury & Islington"
        assert (
            all_route.calls[0].request.headers["Authorization"] == "Bearer short-life-access-token"
        )

    @time_machine.travel("2026-02-17T09:42:00Z")
    @respx.mock
    async def test_no_services_returns_empty_board(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Given a 204 no-services response, when fetched,
        then an empty board with the CRS as station name is returned.
        """
        settings = Settings.model_construct(
            train_station_crs="FOH",
            train_destinations="",
            rtt_api_token="refresh-token",
        )
        monkeypatch.setattr(trains_mod, "settings", settings)
        monkeypatch.setattr(rtt_auth_mod, "settings", settings)

        respx.get(f"{RTT_BASE_URL}/api/get_access_token").mock(
            return_value=httpx.Response(200, json=MOCK_EXCHANGE_RESPONSE)
        )
        respx.get(f"{RTT_BASE_URL}/data/stops").mock(
            return_value=httpx.Response(200, json=MOCK_STOPS_RESPONSE)
        )
        respx.get(f"{RTT_BASE_URL}/gb-nr/location", params={"code": "FOH"}).mock(
            return_value=httpx.Response(204)
        )

        board = await fetch_train_board()

        assert board.station_name == "FOH"
        assert board.all_departures == []
        assert board.destination_groups == []
