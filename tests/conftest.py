import pytest

from quarterdeck.services import rtt_auth, trains


@pytest.fixture(autouse=True)
def _reset_rtt_caches() -> None:
    """Clear cached RTT auth and reference data before each test to ensure isolation."""
    rtt_auth._state.access_token = None  # pyright: ignore[reportPrivateUsage]
    rtt_auth._state.valid_until = None  # pyright: ignore[reportPrivateUsage]
    trains._station_names.clear()  # pyright: ignore[reportPrivateUsage]
