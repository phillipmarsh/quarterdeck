from datetime import UTC, datetime, time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quarterdeck.app import create_app
from quarterdeck.models import (
    CalendarEvent,
    HourlyWeather,
    TodayAgenda,
    TrainBoard,
    TrainDeparture,
    TrainDestinationGroup,
    TrainStatus,
    WeatherForecast,
)
from quarterdeck.refresh import ErrorKind, Snapshot, Sources

FETCHED_AT = datetime(2026, 2, 17, 10, 0, tzinfo=UTC)

MOCK_WEATHER = WeatherForecast(
    current_temp_c=14,
    current_description="Partly cloudy",
    current_emoji="⛅",
    hourly=[
        HourlyWeather(
            hour=10,
            temperature_c=10,
            weather_code=3,
            description="Overcast",
            emoji="☁️",
        ),
        HourlyWeather(
            hour=11,
            temperature_c=11,
            weather_code=61,
            description="Slight rain",
            emoji="🌧️",
        ),
    ],
    fetched_at=FETCHED_AT,
)

MOCK_TRAINS = TrainBoard(
    station_name="Forest Hill",
    destination_groups=[
        TrainDestinationGroup(
            destination_name="London Bridge",
            destination_crs="LBG",
            departures=[
                TrainDeparture(
                    scheduled=time(9, 48),
                    expected=time(9, 48),
                    minutes_away=6,
                    destination="London Bridge",
                    status=TrainStatus.ON_TIME,
                    platform="1",
                ),
            ],
        ),
    ],
    all_departures=[
        TrainDeparture(
            scheduled=time(9, 48),
            expected=time(9, 48),
            minutes_away=6,
            destination="London Bridge",
            status=TrainStatus.ON_TIME,
            platform="1",
        ),
    ],
    fetched_at=FETCHED_AT,
)

MOCK_AGENDA = TodayAgenda(
    events=[
        CalendarEvent(
            summary="Team standup",
            start=datetime(2026, 2, 17, 9, 0, tzinfo=UTC),
            is_all_day=False,
        ),
        CalendarEvent(
            summary="Dentist",
            start=datetime(2026, 2, 17, 11, 30, tzinfo=UTC),
            is_all_day=False,
            location="123 High Street",
        ),
    ],
    fetched_at=FETCHED_AT,
    feed_count=1,
)


@pytest.fixture
def app() -> FastAPI:
    """App without lifespan, so no background refresh loops run.

    Tests inject panel state by assigning snapshots on app.state.sources.
    """
    return create_app()


@pytest.fixture
def sources(app: FastAPI) -> Sources:
    return app.state.sources


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def populate_all(sources: Sources) -> None:
    sources.weather.snapshot = Snapshot(data=MOCK_WEATHER, fetched_at=FETCHED_AT)
    sources.trains.snapshot = Snapshot(data=MOCK_TRAINS, fetched_at=FETCHED_AT)
    sources.agenda.snapshot = Snapshot(data=MOCK_AGENDA, fetched_at=FETCHED_AT)


class TestDashboardRoute:
    """Test the main dashboard page."""

    def test_dashboard_renders_successfully(self, sources: Sources, client: TestClient) -> None:
        """Given all sources have data, when GET /,
        then the full dashboard renders with 200.
        """
        populate_all(sources)

        response = client.get("/")

        assert response.status_code == 200
        assert "Quarterdeck" in response.text
        assert "Partly cloudy" in response.text
        assert "London Bridge" in response.text
        assert "Team standup" in response.text

    def test_dashboard_handles_train_error_gracefully(
        self, sources: Sources, client: TestClient
    ) -> None:
        """Given trains never fetched successfully, when GET /,
        then other panels still render.
        """
        populate_all(sources)
        sources.trains.snapshot = Snapshot(error="RTT down", error_kind=ErrorKind.UNKNOWN)

        response = client.get("/")

        assert response.status_code == 200
        assert "Train data unavailable" in response.text
        assert "Partly cloudy" in response.text
        assert "Team standup" in response.text

    def test_dashboard_shows_loading_before_first_fetch(self, client: TestClient) -> None:
        """Given no source has fetched yet, when GET /,
        then panels show a loading state rather than errors.
        """
        response = client.get("/")

        assert response.status_code == 200
        assert "Loading..." in response.text
        assert "unavailable" not in response.text


class TestPartialRoutes:
    """Test HTMX partial endpoints."""

    def test_header_partial(self, sources: Sources, client: TestClient) -> None:
        """Given weather data, when GET /partials/header,
        then the header renders.
        """
        populate_all(sources)

        response = client.get("/partials/header")

        assert response.status_code == 200
        assert "Partly cloudy" in response.text

    def test_trains_partial_filtered_mode(self, sources: Sources, client: TestClient) -> None:
        """Given train data, when GET /partials/trains?mode=filtered,
        then destination groups render.
        """
        populate_all(sources)

        response = client.get("/partials/trains?mode=filtered")

        assert response.status_code == 200
        assert "London Bridge" in response.text
        assert "By destination" not in response.text
        assert "All departures" in response.text

    def test_trains_partial_all_mode(self, sources: Sources, client: TestClient) -> None:
        """Given train data, when GET /partials/trains?mode=all,
        then all departures render.
        """
        populate_all(sources)

        response = client.get("/partials/trains?mode=all")

        assert response.status_code == 200
        assert "By destination" in response.text

    def test_calendar_partial(self, sources: Sources, client: TestClient) -> None:
        """Given calendar data, when GET /partials/calendar,
        then events render.
        """
        populate_all(sources)

        response = client.get("/partials/calendar")

        assert response.status_code == 200
        assert "Team standup" in response.text
        assert "Dentist" in response.text

    def test_weather_strip_partial(self, sources: Sources, client: TestClient) -> None:
        """Given weather data, when GET /partials/weather,
        then hourly forecast renders.
        """
        populate_all(sources)

        response = client.get("/partials/weather")

        assert response.status_code == 200
        assert "10:00" in response.text

    def test_header_partial_handles_error(self, sources: Sources, client: TestClient) -> None:
        """Given a weather error with no prior data, when GET /partials/header,
        then the error message renders.
        """
        sources.weather.snapshot = Snapshot(error="API error", error_kind=ErrorKind.UNKNOWN)

        response = client.get("/partials/header")

        assert response.status_code == 200
        assert "Weather unavailable" in response.text


class TestDegradedStates:
    """Test stale-data serving and error-cause display."""

    def test_trains_auth_error_shows_credentials_hint(
        self, sources: Sources, client: TestClient
    ) -> None:
        """Given an auth failure with no prior data, when GET /partials/trains,
        then the panel tells the viewer to check RTT credentials.
        """
        sources.trains.snapshot = Snapshot(error="401 Unauthorised", error_kind=ErrorKind.AUTH)

        response = client.get("/partials/trains")

        assert response.status_code == 200
        assert "check RTT credentials" in response.text

    def test_trains_transient_error_has_no_credentials_hint(
        self, sources: Sources, client: TestClient
    ) -> None:
        """Given a transient failure with no prior data, when GET /partials/trains,
        then the generic message renders without the credentials hint.
        """
        sources.trains.snapshot = Snapshot(error="timeout", error_kind=ErrorKind.TRANSIENT)

        response = client.get("/partials/trains")

        assert response.status_code == 200
        assert "Train data unavailable" in response.text
        assert "credentials" not in response.text

    def test_stale_trains_data_still_renders_with_marker(
        self, sources: Sources, client: TestClient
    ) -> None:
        """Given train data whose refresh is now failing, when GET /partials/trains,
        then the last good departures render with a staleness marker.
        """
        sources.trains.snapshot = Snapshot(
            data=MOCK_TRAINS,
            fetched_at=FETCHED_AT,
            error="timeout",
            error_kind=ErrorKind.TRANSIENT,
        )

        response = client.get("/partials/trains")

        assert response.status_code == 200
        assert "London Bridge" in response.text
        assert "As of 10:00" in response.text
        assert "Train data unavailable" not in response.text

    def test_calendar_partial_feed_failure_shows_warning(
        self, sources: Sources, client: TestClient
    ) -> None:
        """Given an agenda where one of two feeds failed, when GET /partials/calendar,
        then events render alongside an unreachable-feed warning.
        """
        degraded = MOCK_AGENDA.model_copy(update={"feed_count": 2, "failed_feed_count": 1})
        sources.agenda.snapshot = Snapshot(data=degraded, fetched_at=FETCHED_AT)

        response = client.get("/partials/calendar")

        assert response.status_code == 200
        assert "Team standup" in response.text
        assert "1 of 2 calendar feeds unreachable" in response.text

    def test_calendar_unconfigured_shows_message(
        self, sources: Sources, client: TestClient
    ) -> None:
        """Given an agenda with no feeds configured, when GET /partials/calendar,
        then the unconfigured message renders instead of an empty day.
        """
        unconfigured = TodayAgenda(events=[], fetched_at=FETCHED_AT, feed_count=0)
        sources.agenda.snapshot = Snapshot(data=unconfigured, fetched_at=FETCHED_AT)

        response = client.get("/partials/calendar")

        assert response.status_code == 200
        assert "No calendar feeds configured" in response.text
        assert "No events today" not in response.text
