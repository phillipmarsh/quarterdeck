from datetime import UTC, datetime, time
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from quarterdeck.app import app
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

client = TestClient(app)

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
    fetched_at=datetime(2026, 2, 17, 10, 0, tzinfo=UTC),
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
    fetched_at=datetime(2026, 2, 17, 9, 42, tzinfo=UTC),
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
    fetched_at=datetime(2026, 2, 17, 10, 0, tzinfo=UTC),
    feed_count=1,
)

_PATCH_WEATHER = "quarterdeck.routes.dashboard.fetch_weather"
_PATCH_TRAINS = "quarterdeck.routes.dashboard.fetch_train_board"
_PATCH_AGENDA = "quarterdeck.routes.dashboard.fetch_agenda"
_PATCH_P_WEATHER = "quarterdeck.routes.partials.fetch_weather"
_PATCH_P_TRAINS = "quarterdeck.routes.partials.fetch_train_board"
_PATCH_P_AGENDA = "quarterdeck.routes.partials.fetch_agenda"


class TestDashboardRoute:
    """Test the main dashboard page."""

    @patch(_PATCH_AGENDA, new_callable=AsyncMock, return_value=MOCK_AGENDA)
    @patch(_PATCH_TRAINS, new_callable=AsyncMock, return_value=MOCK_TRAINS)
    @patch(_PATCH_WEATHER, new_callable=AsyncMock, return_value=MOCK_WEATHER)
    def test_dashboard_renders_successfully(
        self,
        mock_weather: AsyncMock,
        mock_trains: AsyncMock,
        mock_agenda: AsyncMock,
    ) -> None:
        """Given all services return data, when GET /,
        then the full dashboard renders with 200.
        """
        response = client.get("/")

        assert response.status_code == 200
        assert "Quarterdeck" in response.text
        assert "Partly cloudy" in response.text
        assert "London Bridge" in response.text
        assert "Team standup" in response.text

    @patch(_PATCH_AGENDA, new_callable=AsyncMock, return_value=MOCK_AGENDA)
    @patch(_PATCH_TRAINS, new_callable=AsyncMock, side_effect=Exception("RTT down"))
    @patch(_PATCH_WEATHER, new_callable=AsyncMock, return_value=MOCK_WEATHER)
    def test_dashboard_handles_train_error_gracefully(
        self,
        mock_weather: AsyncMock,
        mock_trains: AsyncMock,
        mock_agenda: AsyncMock,
    ) -> None:
        """Given trains API fails, when GET /,
        then other panels still render.
        """
        response = client.get("/")

        assert response.status_code == 200
        assert "Train data unavailable" in response.text
        assert "Partly cloudy" in response.text
        assert "Team standup" in response.text


class TestPartialRoutes:
    """Test HTMX partial endpoints."""

    @patch(_PATCH_P_WEATHER, new_callable=AsyncMock, return_value=MOCK_WEATHER)
    def test_header_partial(self, mock_weather: AsyncMock) -> None:
        """Given weather data, when GET /partials/header,
        then the header renders.
        """
        response = client.get("/partials/header")

        assert response.status_code == 200
        assert "Partly cloudy" in response.text

    @patch(_PATCH_P_TRAINS, new_callable=AsyncMock, return_value=MOCK_TRAINS)
    def test_trains_partial_filtered_mode(self, mock_trains: AsyncMock) -> None:
        """Given train data, when GET /partials/trains?mode=filtered,
        then destination groups render.
        """
        response = client.get("/partials/trains?mode=filtered")

        assert response.status_code == 200
        assert "London Bridge" in response.text
        assert "By destination" not in response.text
        assert "All departures" in response.text

    @patch(_PATCH_P_TRAINS, new_callable=AsyncMock, return_value=MOCK_TRAINS)
    def test_trains_partial_all_mode(self, mock_trains: AsyncMock) -> None:
        """Given train data, when GET /partials/trains?mode=all,
        then all departures render.
        """
        response = client.get("/partials/trains?mode=all")

        assert response.status_code == 200
        assert "By destination" in response.text

    @patch(_PATCH_P_AGENDA, new_callable=AsyncMock, return_value=MOCK_AGENDA)
    def test_calendar_partial(self, mock_agenda: AsyncMock) -> None:
        """Given calendar data, when GET /partials/calendar,
        then events render.
        """
        response = client.get("/partials/calendar")

        assert response.status_code == 200
        assert "Team standup" in response.text
        assert "Dentist" in response.text

    @patch(_PATCH_P_WEATHER, new_callable=AsyncMock, return_value=MOCK_WEATHER)
    def test_weather_strip_partial(self, mock_weather: AsyncMock) -> None:
        """Given weather data, when GET /partials/weather,
        then hourly forecast renders.
        """
        response = client.get("/partials/weather")

        assert response.status_code == 200
        assert "10:00" in response.text

    @patch(
        _PATCH_P_WEATHER,
        new_callable=AsyncMock,
        side_effect=Exception("API error"),
    )
    def test_header_partial_handles_error(self, mock_weather: AsyncMock) -> None:
        """Given a weather error, when GET /partials/header,
        then the error message renders.
        """
        response = client.get("/partials/header")

        assert response.status_code == 200
        assert "Weather unavailable" in response.text
