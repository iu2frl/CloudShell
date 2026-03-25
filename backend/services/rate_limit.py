"""
services/rate_limit.py — Rate limiting utilities

Provides in-memory rate limiting for API endpoints using account + client IP
as the key. Requests exceeding the limit are rejected with HTTP 429.

Forwarded IP headers are trusted only when the direct peer is listed in
`TRUSTED_PROXIES`.

Example:
    @router.post("/endpoint")
    async def my_endpoint(request: Request):
        limiter.check_limit(request, requests_per_minute=5)
        ...
"""
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status

from backend.config import get_settings


logger = logging.getLogger(__name__)


def _parse_trusted_proxies() -> set[str]:
    """Return trusted reverse proxy IPs configured via `TRUSTED_PROXIES`."""
    settings = get_settings()
    raw = settings.trusted_proxies.strip()
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _get_client_ip(request: Request) -> str:
    """Extract client IP, trusting forwarded headers only from trusted proxies."""
    trusted_proxies = _parse_trusted_proxies()
    peer_ip = request.client.host if request.client else "unknown"

    if peer_ip in trusted_proxies:
        x_forwarded_for = request.headers.get("x-forwarded-for", "")
        if x_forwarded_for:
            first_hop = x_forwarded_for.split(",")[0].strip()
            if first_hop:
                return first_hop

        x_real_ip = request.headers.get("x-real-ip", "").strip()
        if x_real_ip:
            return x_real_ip

    if request.client:
        return request.client.host
    return "unknown"


def _normalize_account(account: str | None) -> str:
    """Normalize optional account identifiers for stable rate-limit keys."""
    if not account:
        return "anonymous"
    normalized = account.strip().lower()
    return normalized or "anonymous"


def _build_rate_limit_key(endpoint: str, account: str | None, client_ip: str) -> str:
    """Build the canonical rate-limit key for request tracking."""
    return f"{endpoint}:{_normalize_account(account)}:{client_ip}"


def _display_account(account: str | None) -> str:
    """Return a safe account label for operational logs."""
    return _normalize_account(account)


class RateLimiter:
    """Simple in-memory rate limiter using sliding window approach."""

    def __init__(self):
        """Initialize empty request tracking store."""
        # Structure: {endpoint_ip: [(timestamp, count), ...]}
        self._requests: dict[str, list[tuple[datetime, int]]] = defaultdict(list)

    def check_limit(
        self,
        request: Request,
        endpoint: str,
        account: str | None = None,
        requests_per_minute: int = 60,
    ) -> None:
        """
        Check if client has exceeded rate limit for the endpoint.

        Args:
            request: FastAPI Request object
            endpoint: Endpoint identifier (e.g., "/auth/token")
            account: Optional account identifier for per-account bucketing
            requests_per_minute: Max requests allowed per minute

        Raises:
            HTTPException: 429 Too Many Requests if limit exceeded
        """
        client_ip = _get_client_ip(request)
        key = _build_rate_limit_key(endpoint, account, client_ip)
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=1)

        # Clean up old entries
        self._requests[key] = [
            (ts, count) for ts, count in self._requests[key] if ts > cutoff
        ]

        # Count requests in the last minute
        request_count = sum(count for _, count in self._requests[key])

        if request_count >= requests_per_minute:
            logger.warning(
                "Rate limit exceeded for %s (account=%s) from %s: %d requests in last minute",
                endpoint,
                _display_account(account),
                client_ip,
                request_count,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
            )

        # Record this request
        if self._requests[key] and self._requests[key][-1][0] == now:
            # Increment counter for same timestamp
            self._requests[key][-1] = (now, self._requests[key][-1][1] + 1)
        else:
            self._requests[key].append((now, 1))

    def reset(self) -> None:
        """Clear all rate limit data (useful for testing)."""
        self._requests.clear()


# Global rate limiter instance
_limiter = RateLimiter()


def get_limiter() -> RateLimiter:
    """Return the global rate limiter instance."""
    return _limiter
