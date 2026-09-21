from datetime import UTC, datetime

from quarterdeck.templating import localtime


class TestLocaltime:
    """Test the localtime display filter."""

    def test_converts_utc_to_bst_wall_clock(self) -> None:
        """Given an aware UTC datetime during British Summer Time,
        when converted, then the London wall-clock hour is returned.
        """
        converted = localtime(datetime(2026, 7, 1, 12, 0, tzinfo=UTC))

        assert converted.hour == 13

    def test_gmt_datetimes_are_unchanged_in_winter(self) -> None:
        """Given an aware UTC datetime in winter, when converted,
        then the hour matches UTC (London is on GMT).
        """
        converted = localtime(datetime(2026, 2, 17, 12, 0, tzinfo=UTC))

        assert converted.hour == 12

    def test_naive_datetime_passes_through(self) -> None:
        """Given a naive datetime, when converted, then it is returned unchanged."""
        naive = datetime(2026, 7, 1, 12, 0)

        assert localtime(naive) is naive
