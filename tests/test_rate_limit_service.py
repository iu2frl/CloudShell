"""
tests/test_rate_limit_service.py — Unit tests for rate limiting service.
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from backend.services.rate_limit import RateLimiter


class TestRateLimiter:
    """Test rate limiting functionality."""

    def test_rate_limiter_allows_requests_under_limit(self):
        """Should allow requests under the limit."""
        limiter = RateLimiter()
        request = MagicMock()
        request.client = MagicMock(host="192.168.1.1")
        request.headers = {}

        # Should allow up to limit
        for i in range(5):
            limiter.check_limit(request, "/test", requests_per_minute=5)

    def test_rate_limiter_rejects_requests_over_limit(self):
        """Should reject requests exceeding the limit."""
        from fastapi import HTTPException
        
        limiter = RateLimiter()
        request = MagicMock()
        request.client = MagicMock(host="192.168.1.1")
        request.headers = {}

        # Allow up to limit
        for i in range(5):
            limiter.check_limit(request, "/test", requests_per_minute=5)

        # Next request should be rejected
        with pytest.raises(HTTPException) as exc_info:
            limiter.check_limit(request, "/test", requests_per_minute=5)
        
        assert exc_info.value.status_code == 429

    def test_rate_limiter_resets_after_minute(self):
        """Should reset counter after old entries are cleaned up."""
        from datetime import datetime, timezone, timedelta
        
        limiter = RateLimiter()
        request = MagicMock()
        request.client = MagicMock(host="192.168.1.1")
        request.headers = {}

        # Fill up the limit with current timestamps
        for i in range(5):
            limiter.check_limit(request, "/test", requests_per_minute=5)

        # Manually add an old request that is >1 minute old
        key = "/test:192.168.1.1"
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(minutes=2)
        limiter._requests[key].append((old_time, 1))

        # The old request should be cleaned up on next check, allowing a new request
        # (even though we have 5 current requests + 1 old, after cleanup we only have 5)
        limiter.check_limit(request, "/test", requests_per_minute=6)

    def test_rate_limiter_uses_client_ip(self):
        """Should use client IP from request."""
        from fastapi import HTTPException
        
        limiter = RateLimiter()

        # IP 1
        request1 = MagicMock()
        request1.client = MagicMock(host="192.168.1.1")
        request1.headers = {}

        # IP 2
        request2 = MagicMock()
        request2.client = MagicMock(host="192.168.1.2")
        request2.headers = {}

        # Fill up IP 1
        for i in range(3):
            limiter.check_limit(request1, "/test", requests_per_minute=3)

        # IP 2 should still be allowed
        limiter.check_limit(request2, "/test", requests_per_minute=3)

    def test_rate_limiter_extracts_x_forwarded_for(self):
        """Should extract IP from x-forwarded-for header."""
        from fastapi import HTTPException
        
        limiter = RateLimiter()

        request1 = MagicMock()
        request1.client = MagicMock(host="192.168.1.1")
        request1.headers = {"x-forwarded-for": "10.0.0.1, 10.0.0.2"}

        request2 = MagicMock()
        request2.client = MagicMock(host="192.168.1.2")
        request2.headers = {}

        # Fill up the forwarded IP
        for i in range(2):
            limiter.check_limit(request1, "/test", requests_per_minute=2)

        # Next request from same forwarded IP should fail
        with pytest.raises(HTTPException) as exc_info:
            limiter.check_limit(request1, "/test", requests_per_minute=2)
        assert exc_info.value.status_code == 429

        # But different IP should succeed
        limiter.check_limit(request2, "/test", requests_per_minute=2)

    def test_rate_limiter_different_endpoints_isolated(self):
        """Should isolate rate limits between different endpoints."""
        limiter = RateLimiter()
        request = MagicMock()
        request.client = MagicMock(host="192.168.1.1")
        request.headers = {}

        # Fill up endpoint 1
        for i in range(3):
            limiter.check_limit(request, "/endpoint1", requests_per_minute=3)

        # Endpoint 2 should still allow requests
        limiter.check_limit(request, "/endpoint2", requests_per_minute=3)

    def test_rate_limiter_reset(self):
        """Should reset all data when reset() is called."""
        from fastapi import HTTPException
        
        limiter = RateLimiter()
        request = MagicMock()
        request.client = MagicMock(host="192.168.1.1")
        request.headers = {}

        # Fill up the limit
        for i in range(3):
            limiter.check_limit(request, "/test", requests_per_minute=3)

        # Reset
        limiter.reset()

        # Should now allow requests again
        limiter.check_limit(request, "/test", requests_per_minute=3)

    def test_rate_limiter_error_message(self):
        """Should have appropriate error message."""
        from fastapi import HTTPException
        
        limiter = RateLimiter()
        request = MagicMock()
        request.client = MagicMock(host="192.168.1.1")
        request.headers = {}

        # Fill up the limit
        for i in range(2):
            limiter.check_limit(request, "/test", requests_per_minute=2)

        # Next request should be rejected with descriptive message
        with pytest.raises(HTTPException) as exc_info:
            limiter.check_limit(request, "/test", requests_per_minute=2)
        
        assert "Rate limit exceeded" in exc_info.value.detail
