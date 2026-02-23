"""Unit tests for GoogleTokenVerifier in auth.py."""

import time
from unittest.mock import patch

import pytest

from mcpvectordb.auth import CACHE_TTL_SECONDS, GoogleTokenVerifier


CLIENT_ID = "test-client.apps.googleusercontent.com"
VALID_TOKEN = "valid-google-access-token"
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


def _tokeninfo_response(
    aud: str = CLIENT_ID,
    email: str = "user@gmail.com",
    expires_in: str = "3600",
    scope: str = "openid email",
) -> dict:
    return {
        "aud": aud,
        "email": email,
        "expires_in": expires_in,
        "scope": scope,
    }


@pytest.mark.unit
class TestGoogleTokenVerifier:
    """Tests for GoogleTokenVerifier."""

    @pytest.mark.asyncio
    async def test_valid_token_returns_access_token(self, httpx_mock):
        """A valid token with correct aud returns a populated AccessToken."""
        httpx_mock.add_response(
            url=f"{TOKENINFO_URL}?access_token={VALID_TOKEN}",
            json=_tokeninfo_response(),
        )
        verifier = GoogleTokenVerifier(
            client_id=CLIENT_ID, allowed_emails=[]
        )
        result = await verifier.verify_token(VALID_TOKEN)

        assert result is not None
        assert result.token == VALID_TOKEN
        assert result.client_id == CLIENT_ID
        assert "openid" in result.scopes
        assert "email" in result.scopes

    @pytest.mark.asyncio
    async def test_caches_valid_token(self, httpx_mock):
        """Second call for the same token uses the cache — no second HTTP request."""
        httpx_mock.add_response(
            url=f"{TOKENINFO_URL}?access_token={VALID_TOKEN}",
            json=_tokeninfo_response(),
        )
        verifier = GoogleTokenVerifier(client_id=CLIENT_ID, allowed_emails=[])

        first = await verifier.verify_token(VALID_TOKEN)
        second = await verifier.verify_token(VALID_TOKEN)

        assert first is second
        # Only one HTTP request should have been made
        assert len(httpx_mock.get_requests()) == 1

    @pytest.mark.asyncio
    async def test_wrong_audience_returns_none(self, httpx_mock):
        """Token with a different aud claim returns None."""
        httpx_mock.add_response(
            url=f"{TOKENINFO_URL}?access_token={VALID_TOKEN}",
            json=_tokeninfo_response(aud="wrong-client.apps.googleusercontent.com"),
        )
        verifier = GoogleTokenVerifier(client_id=CLIENT_ID, allowed_emails=[])
        result = await verifier.verify_token(VALID_TOKEN)

        assert result is None

    @pytest.mark.asyncio
    async def test_disallowed_email_returns_none(self, httpx_mock):
        """Token from an email not in the allowlist returns None."""
        httpx_mock.add_response(
            url=f"{TOKENINFO_URL}?access_token={VALID_TOKEN}",
            json=_tokeninfo_response(email="intruder@example.com"),
        )
        verifier = GoogleTokenVerifier(
            client_id=CLIENT_ID,
            allowed_emails=["allowed@gmail.com"],
        )
        result = await verifier.verify_token(VALID_TOKEN)

        assert result is None

    @pytest.mark.asyncio
    async def test_allowed_email_passes(self, httpx_mock):
        """Token from an email in the allowlist is accepted."""
        httpx_mock.add_response(
            url=f"{TOKENINFO_URL}?access_token={VALID_TOKEN}",
            json=_tokeninfo_response(email="allowed@gmail.com"),
        )
        verifier = GoogleTokenVerifier(
            client_id=CLIENT_ID,
            allowed_emails=["allowed@gmail.com"],
        )
        result = await verifier.verify_token(VALID_TOKEN)

        assert result is not None

    @pytest.mark.asyncio
    async def test_empty_allowlist_accepts_any_email(self, httpx_mock):
        """Empty allowed_emails list accepts any authenticated Google user."""
        httpx_mock.add_response(
            url=f"{TOKENINFO_URL}?access_token={VALID_TOKEN}",
            json=_tokeninfo_response(email="anyone@anydomain.com"),
        )
        verifier = GoogleTokenVerifier(client_id=CLIENT_ID, allowed_emails=[])
        result = await verifier.verify_token(VALID_TOKEN)

        assert result is not None

    @pytest.mark.asyncio
    async def test_google_error_response_returns_none(self, httpx_mock):
        """Non-200 response from tokeninfo returns None."""
        httpx_mock.add_response(
            url=f"{TOKENINFO_URL}?access_token={VALID_TOKEN}",
            status_code=400,
            json={"error": "invalid_token"},
        )
        verifier = GoogleTokenVerifier(client_id=CLIENT_ID, allowed_emails=[])
        result = await verifier.verify_token(VALID_TOKEN)

        assert result is None

    @pytest.mark.asyncio
    async def test_network_error_returns_none(self, httpx_mock):
        """Network error during tokeninfo call returns None (no exception raised)."""
        import httpx as _httpx

        httpx_mock.add_exception(
            _httpx.ConnectError("connection refused"),
            url=f"{TOKENINFO_URL}?access_token={VALID_TOKEN}",
        )
        verifier = GoogleTokenVerifier(client_id=CLIENT_ID, allowed_emails=[])
        result = await verifier.verify_token(VALID_TOKEN)

        assert result is None

    @pytest.mark.asyncio
    async def test_expired_cache_refetches(self, httpx_mock):
        """After TTL expires, the next call re-fetches from Google."""
        httpx_mock.add_response(
            url=f"{TOKENINFO_URL}?access_token={VALID_TOKEN}",
            json=_tokeninfo_response(),
        )
        httpx_mock.add_response(
            url=f"{TOKENINFO_URL}?access_token={VALID_TOKEN}",
            json=_tokeninfo_response(),
        )
        verifier = GoogleTokenVerifier(client_id=CLIENT_ID, allowed_emails=[])

        await verifier.verify_token(VALID_TOKEN)

        # Manually expire the cache entry
        import hashlib

        cache_key = hashlib.sha256(VALID_TOKEN.encode()).hexdigest()
        verifier._cache[cache_key].expires_at = time.monotonic() - 1

        await verifier.verify_token(VALID_TOKEN)

        assert len(httpx_mock.get_requests()) == 2

    @pytest.mark.asyncio
    async def test_expires_at_set_from_tokeninfo(self, httpx_mock):
        """expires_at on the returned AccessToken reflects tokeninfo expires_in."""
        httpx_mock.add_response(
            url=f"{TOKENINFO_URL}?access_token={VALID_TOKEN}",
            json=_tokeninfo_response(expires_in="3600"),
        )
        verifier = GoogleTokenVerifier(client_id=CLIENT_ID, allowed_emails=[])
        before = int(time.time())
        result = await verifier.verify_token(VALID_TOKEN)
        after = int(time.time())

        assert result is not None
        assert result.expires_at is not None
        assert before + 3600 <= result.expires_at <= after + 3600

    @pytest.mark.asyncio
    async def test_missing_expires_in_sets_none(self, httpx_mock):
        """Missing expires_in in tokeninfo response results in expires_at=None."""
        data = _tokeninfo_response()
        del data["expires_in"]
        httpx_mock.add_response(
            url=f"{TOKENINFO_URL}?access_token={VALID_TOKEN}",
            json=data,
        )
        verifier = GoogleTokenVerifier(client_id=CLIENT_ID, allowed_emails=[])
        result = await verifier.verify_token(VALID_TOKEN)

        assert result is not None
        assert result.expires_at is None

    @pytest.mark.asyncio
    async def test_invalid_json_response_returns_none(self, httpx_mock):
        """Non-JSON response body from tokeninfo returns None."""
        httpx_mock.add_response(
            url=f"{TOKENINFO_URL}?access_token={VALID_TOKEN}",
            content=b"not-json",
            headers={"content-type": "text/plain"},
        )
        verifier = GoogleTokenVerifier(client_id=CLIENT_ID, allowed_emails=[])
        result = await verifier.verify_token(VALID_TOKEN)

        assert result is None
