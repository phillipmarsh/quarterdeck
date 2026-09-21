"""Access token resolution for the Realtime Trains next-generation API.

The API portal issues either a long-life access token or a long-life
refresh token that must be exchanged for short-life access tokens via
/api/get_access_token. The two are not reliably distinguishable offline,
so the exchange is attempted first and the configured token is used
directly when the exchange is refused. Exchanged tokens are cached until
shortly before their expiry.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from loguru import logger

from quarterdeck.config import settings

RTT_BASE_URL = "https://data.rtt.io"

# Exchange again this long before the cached access token expires, so a
# token never goes stale mid-request
EXPIRY_BUFFER_SECONDS = 60


@dataclass
class _TokenState:
    access_token: str | None = None
    valid_until: datetime | None = None


_state = _TokenState()


def _cached_token(now: datetime) -> str | None:
    if _state.access_token is None or _state.valid_until is None:
        return None
    if now + timedelta(seconds=EXPIRY_BUFFER_SECONDS) >= _state.valid_until:
        return None
    return _state.access_token


async def resolve_access_token(client: httpx.AsyncClient) -> str:
    """Return a bearer token usable against data.rtt.io, or "" if none configured.

    An empty return means the caller should send no Authorization header
    and let the API's 401 surface the configuration problem.
    """
    configured = settings.rtt_api_token
    if not configured:
        return ""

    now = datetime.now(tz=UTC)
    cached = _cached_token(now)
    if cached is not None:
        return cached

    response = await client.get(
        f"{RTT_BASE_URL}/api/get_access_token",
        headers={"Authorization": f"Bearer {configured}"},
    )
    if response.status_code != 200:
        logger.info(
            "RTT token exchange returned {}; treating configured token as an access token",
            response.status_code,
        )
        return configured

    data = response.json()
    _state.access_token = data["token"]
    _state.valid_until = datetime.fromisoformat(data["validUntil"])
    logger.info("Obtained RTT access token valid until {}", data["validUntil"])
    return data["token"]
