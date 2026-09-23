from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import pytest
from loguru import logger

if TYPE_CHECKING:
    from loguru import Record

from quarterdeck.refresh import ErrorKind, Refresher, Snapshot, build_sources, classify_error


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.example.com")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


class TestClassifyError:
    """Test failure classification for the UI."""

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_auth_status_codes_classified_as_auth(self, status_code: int) -> None:
        """Given a 401 or 403 response error, when classified, then it is an auth failure."""
        assert classify_error(_http_status_error(status_code)) is ErrorKind.AUTH

    @pytest.mark.parametrize(
        "exc",
        [
            httpx.ConnectTimeout("timed out"),
            httpx.ConnectError("connection refused"),
            httpx.ReadTimeout("read timed out"),
        ],
    )
    def test_transport_errors_classified_as_transient(self, exc: Exception) -> None:
        """Given a transport-level error, when classified, then it is transient."""
        assert classify_error(exc) is ErrorKind.TRANSIENT

    def test_429_classified_as_rate_limited(self) -> None:
        """Given a 429 response error, when classified, then it is rate limited."""
        assert classify_error(_http_status_error(429)) is ErrorKind.RATE_LIMITED

    @pytest.mark.parametrize("exc", [_http_status_error(500), ValueError("bad payload")])
    def test_other_errors_classified_as_unknown(self, exc: Exception) -> None:
        """Given a server error or parse failure, when classified, then it is unknown."""
        assert classify_error(exc) is ErrorKind.UNKNOWN


class TestRefresher:
    """Test snapshot lifecycle across refresh successes and failures."""

    async def test_successful_refresh_populates_snapshot(self) -> None:
        """Given a working fetcher, when refreshed, then the snapshot holds the data."""

        async def fetch() -> str:
            return "fresh"

        refresher = Refresher("test", fetch, interval_seconds=60)

        await refresher.refresh_once()

        assert refresher.snapshot.data == "fresh"
        assert refresher.snapshot.error is None
        assert refresher.snapshot.fetched_at is not None
        assert not refresher.snapshot.is_stale

    async def test_failed_refresh_keeps_previous_data(self) -> None:
        """Given a fetcher that fails after a success, when refreshed,
        then the previous data survives and the snapshot is marked stale.
        """
        responses: list[str | None] = ["first", None]

        async def fetch() -> str:
            value = responses.pop(0)
            if value is None:
                raise httpx.ConnectError("network down")
            return value

        refresher = Refresher("test", fetch, interval_seconds=60)
        await refresher.refresh_once()
        first_fetched_at = refresher.snapshot.fetched_at

        await refresher.refresh_once()

        assert refresher.snapshot.data == "first"
        assert refresher.snapshot.fetched_at == first_fetched_at
        assert refresher.snapshot.error is not None
        assert refresher.snapshot.error_kind is ErrorKind.TRANSIENT
        assert refresher.snapshot.is_stale

    async def test_failed_refresh_with_no_prior_data(self) -> None:
        """Given a fetcher that fails immediately, when refreshed,
        then the snapshot records the error with no data.
        """

        async def fetch() -> str:
            raise _http_status_error(401)

        refresher = Refresher("test", fetch, interval_seconds=60)

        await refresher.refresh_once()

        assert refresher.snapshot.data is None
        assert refresher.snapshot.error_kind is ErrorKind.AUTH
        assert not refresher.snapshot.is_stale

    async def test_repeated_failure_logs_traceback_only_once(self) -> None:
        """Given the same failure on consecutive refreshes, when refreshed,
        then the full traceback is logged once and repeats log a single warning line.
        """

        async def fetch() -> str:
            raise httpx.ConnectError("network down")

        refresher = Refresher("test", fetch, interval_seconds=60)
        records: list[Record] = []
        sink_id = logger.add(lambda message: records.append(message.record), level="DEBUG")

        try:
            await refresher.refresh_once()
            await refresher.refresh_once()
        finally:
            logger.remove(sink_id)

        refresh_records = [r for r in records if "Refresh of test" in r["message"]]
        assert len(refresh_records) == 2
        assert refresh_records[0]["exception"] is not None
        assert refresh_records[1]["exception"] is None
        assert refresh_records[1]["level"].name == "WARNING"

    async def test_recovery_clears_error(self) -> None:
        """Given a fetcher that recovers after a failure, when refreshed,
        then the snapshot returns to a healthy state.
        """
        responses: list[str | None] = [None, "recovered"]

        async def fetch() -> str:
            value = responses.pop(0)
            if value is None:
                raise httpx.ConnectError("network down")
            return value

        refresher = Refresher("test", fetch, interval_seconds=60)
        await refresher.refresh_once()

        await refresher.refresh_once()

        assert refresher.snapshot.data == "recovered"
        assert refresher.snapshot.error is None
        assert not refresher.snapshot.is_stale


class TestRateLimitHandling:
    """Test that a 429's Retry-After is respected rather than retried blind."""

    async def test_429_records_retry_after(self) -> None:
        """Given a 429 with Retry-After, when refreshed,
        then the lockout duration is recorded on the snapshot.
        """
        request = httpx.Request("GET", "https://api.example.com")
        response = httpx.Response(429, request=request, headers={"retry-after": "2350"})

        async def fetch() -> str:
            raise httpx.HTTPStatusError("limited", request=request, response=response)

        refresher = Refresher("test", fetch, interval_seconds=300, retry_interval_seconds=60)

        await refresher.refresh_once()

        assert refresher.snapshot.error_kind is ErrorKind.RATE_LIMITED
        assert refresher.snapshot.retry_after_seconds == 2350
        assert refresher._next_interval() == 2355  # pyright: ignore[reportPrivateUsage]

    async def test_429_without_retry_after_uses_retry_interval(self) -> None:
        """Given a 429 with no Retry-After header, when refreshed,
        then the normal retry cadence applies.
        """
        request = httpx.Request("GET", "https://api.example.com")
        response = httpx.Response(429, request=request)

        async def fetch() -> str:
            raise httpx.HTTPStatusError("limited", request=request, response=response)

        refresher = Refresher("test", fetch, interval_seconds=300, retry_interval_seconds=60)

        await refresher.refresh_once()

        assert refresher.snapshot.retry_after_seconds is None
        assert refresher._next_interval() == 60  # pyright: ignore[reportPrivateUsage]


class TestRefreshCadence:
    """Test that degraded sources retry sooner than healthy ones."""

    @staticmethod
    async def _fetch() -> str:
        return "data"

    def test_healthy_snapshot_uses_normal_interval(self) -> None:
        """Given a healthy snapshot, when the next interval is chosen,
        then the normal cadence applies.
        """
        refresher = Refresher("test", self._fetch, interval_seconds=300, retry_interval_seconds=60)
        refresher.snapshot = Snapshot(data="data", fetched_at=datetime.now(tz=UTC))

        assert refresher._next_interval() == 300  # pyright: ignore[reportPrivateUsage]

    def test_errored_snapshot_uses_retry_interval(self) -> None:
        """Given a failed refresh, when the next interval is chosen,
        then the shorter retry cadence applies.
        """
        refresher = Refresher("test", self._fetch, interval_seconds=300, retry_interval_seconds=60)
        refresher.snapshot = Snapshot(error="down", error_kind=ErrorKind.TRANSIENT)

        assert refresher._next_interval() == 60  # pyright: ignore[reportPrivateUsage]

    def test_degraded_data_uses_retry_interval(self) -> None:
        """Given a successful fetch flagged as degraded, when the next interval is chosen,
        then the shorter retry cadence applies so partial failures recover quickly.
        """
        refresher = Refresher(
            "test",
            self._fetch,
            interval_seconds=300,
            retry_interval_seconds=60,
            is_degraded=lambda data: data == "degraded",
        )
        refresher.snapshot = Snapshot(data="degraded", fetched_at=datetime.now(tz=UTC))

        assert refresher._next_interval() == 60  # pyright: ignore[reportPrivateUsage]


class TestBuildSources:
    """Test the production source wiring."""

    def test_builds_all_three_sources(self) -> None:
        """Given the production factory, when built,
        then all three refreshers exist with empty snapshots.
        """
        sources = build_sources()

        assert [r.name for r in sources.all()] == ["weather", "trains", "agenda"]
        assert all(r.snapshot.data is None for r in sources.all())
