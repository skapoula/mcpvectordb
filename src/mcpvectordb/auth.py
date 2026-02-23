"""Google OAuth token verification for mcpvectordb (Resource Server mode)."""

import hashlib
import logging
import time
from dataclasses import dataclass

import httpx
from mcp.server.auth.provider import AccessToken

logger = logging.getLogger(__name__)

GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
CACHE_TTL_SECONDS = 60


@dataclass
class _CacheEntry:
    access_token: AccessToken
    expires_at: float  # monotonic time


class GoogleTokenVerifier:
    """Verify Google access tokens via the tokeninfo endpoint.

    Implements the mcp.server.auth.provider.TokenVerifier protocol.
    Valid token responses are cached for CACHE_TTL_SECONDS to reduce latency.
    """

    def __init__(self, client_id: str, allowed_emails: list[str]) -> None:
        """Initialise the verifier.

        Args:
            client_id: The Google OAuth 2.0 client_id to validate against the
                token's ``aud`` claim.
            allowed_emails: Allowlist of Google account emails. Empty list means
                any authenticated Google user is accepted.
        """
        self._client_id = client_id
        self._allowed_emails: frozenset[str] = frozenset(allowed_emails)
        self._cache: dict[str, _CacheEntry] = {}

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a Google bearer token and return an AccessToken on success.

        Returns None on any failure: expired, wrong audience, disallowed email,
        or network/API error.

        Args:
            token: The raw bearer token string from the Authorization header.

        Returns:
            AccessToken if the token is valid and passes all checks; None otherwise.
        """
        self._evict_expired()
        cache_key = hashlib.sha256(token.encode()).hexdigest()
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached.access_token

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    GOOGLE_TOKENINFO_URL,
                    params={"access_token": token},
                    timeout=5.0,
                )
        except httpx.HTTPError as exc:
            logger.warning("Google tokeninfo network error: %s", exc)
            return None

        if response.status_code != 200:
            logger.debug(
                "Google tokeninfo rejected token: HTTP %s", response.status_code
            )
            return None

        try:
            data = response.json()
        except Exception:
            logger.warning("Google tokeninfo response was not valid JSON")
            return None

        # Validate audience — Google may return it as "aud" or "audience"
        aud = data.get("aud") or data.get("audience")
        if aud != self._client_id:
            logger.debug(
                "Token audience mismatch: expected %s, got %s", self._client_id, aud
            )
            return None

        # Validate email allowlist
        email = data.get("email", "")
        if self._allowed_emails and email not in self._allowed_emails:
            logger.debug("Email not in allowlist: %s", email)
            return None

        # Build expires_at from the tokeninfo expires_in field
        expires_in_str = data.get("expires_in")
        expires_at: int | None = None
        if expires_in_str is not None:
            try:
                expires_at = int(time.time()) + int(expires_in_str)
            except (ValueError, TypeError):
                pass

        scopes_str = data.get("scope", "")
        scopes = scopes_str.split() if scopes_str else []

        access_token = AccessToken(
            token=token,
            client_id=self._client_id,
            scopes=scopes,
            expires_at=expires_at,
        )
        self._cache[cache_key] = _CacheEntry(
            access_token=access_token,
            expires_at=time.monotonic() + CACHE_TTL_SECONDS,
        )
        return access_token

    def _evict_expired(self) -> None:
        """Remove stale entries from the token cache."""
        now = time.monotonic()
        stale = [k for k, v in self._cache.items() if v.expires_at <= now]
        for k in stale:
            del self._cache[k]
