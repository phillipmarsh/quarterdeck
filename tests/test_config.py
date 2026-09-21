from quarterdeck.config import Settings


class TestFeedUrlList:
    """Test iCal feed URL parsing and normalisation."""

    def test_webcal_urls_normalised_to_https(self) -> None:
        """Given a webcal:// feed URL (as produced by Apple's share sheet),
        when parsed, then it is rewritten to https:// so httpx can fetch it.
        """
        settings = Settings(ical_feed_urls="webcal://p14-caldav.icloud.com/published/2/abc")

        assert settings.feed_url_list == ["https://p14-caldav.icloud.com/published/2/abc"]

    def test_https_urls_pass_through_unchanged(self) -> None:
        """Given https:// feed URLs, when parsed, then they are returned as-is."""
        settings = Settings(ical_feed_urls="https://calendar.google.com/calendar/ical/x/basic.ics")

        assert settings.feed_url_list == ["https://calendar.google.com/calendar/ical/x/basic.ics"]

    def test_splits_and_strips_multiple_urls(self) -> None:
        """Given comma-separated URLs with whitespace and empties,
        when parsed, then a clean list is returned.
        """
        settings = Settings(
            ical_feed_urls=" https://a.example/one.ics , webcal://b.example/two.ics ,,"
        )

        assert settings.feed_url_list == [
            "https://a.example/one.ics",
            "https://b.example/two.ics",
        ]

    def test_empty_config_gives_empty_list(self) -> None:
        """Given no configured feeds, when parsed, then an empty list is returned."""
        settings = Settings(ical_feed_urls="")

        assert settings.feed_url_list == []
