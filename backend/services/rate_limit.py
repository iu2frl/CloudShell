"""
services/rate_limit.py — Rate limiting utilities

Provides in-memory rate limiting for API endpoints using client IP address
as the key. Requests exceeding the limit are rejected with HTTP 429.

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


logger = logging.getLogger(__name__)


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request headers or connection."""
    if request.headers.get("x-forwarded-for"):
        return request.headers["x-forwarded-for"].split(",")[0].strip()
    if request.headers.get("x-real-ip"):
        return request.headers["x-real-ip"]
    if request.client:
        return request.client.host
    return "unknown"


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
        requests_per_minute: int = 60,
    ) -> None:
        """
        Check if client has exceeded rate limit for the endpoint.

        Args:
            request: FastAPI Request object
            endpoint: Endpoint identifier (e.g., "/auth/token")
            requests_per_minute: Max requests allowed per minute

        Raises:
            HTTPException: 429 Too Many Requests if limit exceeded
        """
        client_ip = _get_client_ip(request)
        key = f"{endpoint}:{client_ip}"
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
                "Rate limit exceeded for %s from %s: %d requests in last minute",
                endpoint,
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
