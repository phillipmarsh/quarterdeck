import httpx
import pytest
import respx
import time_machine

import quarterdeck.services.rtt_auth as rtt_auth_mod
from quarterdeck.config import Settings
from quarterdeck.services.rtt_auth import RTT_BASE_URL, resolve_access_token

EXCHANGE_RESPONSE = {
    "token": "short-life-access-token",
    "entitlements": [],
    "validUntil": "2026-02-17T10:12:00+00:00",
}


@pytest.fixture
def configured_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "long-life-refresh-token"
    monkeypatch.setattr(rtt_auth_mod, "settings", Settings.model_construct(rtt_api_token=token))
    return token


class TestResolveAccessToken:
    """Test refresh-token exchange and caching."""

    async def test_no_configured_token_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Given no configured token, when resolved, then an empty string is returned."""
        monkeypatch.setattr(rtt_auth_mod, "settings", Settings.model_construct(rtt_api_token=""))

        async with httpx.AsyncClient() as client:
            assert await resolve_access_token(client) == ""

    @time_machine.travel("2026-02-17T09:42:00Z")
    @respx.mock
    async def test_exchanges_refresh_token_for_access_token(self, configured_token: str) -> None:
        """Given a refresh token, when resolved,
        then it is exchanged for a short-life access token.
        """
        route = respx.get(f"{RTT_BASE_URL}/api/get_access_token").mock(
            return_value=httpx.Response(200, json=EXCHANGE_RESPONSE)
        )

        async with httpx.AsyncClient() as client:
            token = await resolve_access_token(client)

        assert token == "short-life-access-token"
        assert route.calls[0].request.headers["Authorization"] == f"Bearer {configured_token}"

    @time_machine.travel("2026-02-17T09:42:00Z")
    @respx.mock
    async def test_caches_access_token_until_expiry(self, configured_token: str) -> None:
        """Given a valid cached access token, when resolved again,
        then the exchange endpoint is not called a second time.
        """
        route = respx.get(f"{RTT_BASE_URL}/api/get_access_token").mock(
            return_value=httpx.Response(200, json=EXCHANGE_RESPONSE)
        )

        async with httpx.AsyncClient() as client:
            first = await resolve_access_token(client)
            second = await resolve_access_token(client)

        assert first == second == "short-life-access-token"
        assert route.call_count == 1

    @time_machine.travel("2026-02-17T10:11:30Z")
    @respx.mock
    async def test_expiring_token_is_exchanged_again(self, configured_token: str) -> None:
        """Given a cached token inside the expiry buffer, when resolved,
        then a fresh exchange is made.
        """
        route = respx.get(f"{RTT_BASE_URL}/api/get_access_token").mock(
            return_value=httpx.Response(200, json=EXCHANGE_RESPONSE)
        )

        async with httpx.AsyncClient() as client:
            await resolve_access_token(client)
            await resolve_access_token(client)

        assert route.call_count == 2

    @time_machine.travel("2026-02-17T09:42:00Z")
    @respx.mock
    async def test_refused_exchange_falls_back_to_configured_token(
        self, configured_token: str
    ) -> None:
        """Given the exchange endpoint refuses the token, when resolved,
        then the configured token is treated as a long-life access token.
        """
        respx.get(f"{RTT_BASE_URL}/api/get_access_token").mock(return_value=httpx.Response(401))

        async with httpx.AsyncClient() as client:
            token = await resolve_access_token(client)

        assert token == configured_token
