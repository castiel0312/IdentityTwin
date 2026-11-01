"""Rate limiting for the Trust Gateway."""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional
from threading import Lock


@dataclass
class TokenBucket:
    """Token bucket for rate limiting."""
    capacity: int
    refill_rate: float
    tokens: float = field(init=False)
    last_refill: float = field(init=False)
    
    def __post_init__(self):
        self.tokens = float(self.capacity)
        self.last_refill = time.time()
    
    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Returns True if successful."""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False
    
    def retry_after(self) -> float:
        """Seconds until next token available."""
        if self.tokens >= 1:
            return 0.0
        return (1 - self.tokens) / self.refill_rate


class RateLimiter:
    """Thread-safe rate limiter with multiple bucket strategies."""
    
    def __init__(self):
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = Lock()
        self._config: dict[str, tuple[int, float]] = {}
    
    def configure(self, key: str, capacity: int, refill_rate: float) -> None:
        """Configure a rate limit bucket."""
        self._config[key] = (capacity, refill_rate)
    
    def _get_bucket(self, key: str) -> TokenBucket:
        with self._lock:
            if key not in self._buckets:
                capacity, refill_rate = self._config.get(key, (100, 10.0))
                self._buckets[key] = TokenBucket(capacity, refill_rate)
            return self._buckets[key]
    
    def check_limit(self, key: str, tokens: int = 1) -> tuple[bool, dict]:
        """Check rate limit. Returns (allowed, headers)."""
        bucket = self._get_bucket(key)
        allowed = bucket.consume(tokens)
        
        headers = {
            "X-RateLimit-Limit": str(bucket.capacity),
            "X-RateLimit-Remaining": str(max(0, int(bucket.tokens))),
            "X-RateLimit-Reset": str(int(time.time() + bucket.retry_after())),
        }
        
        if not allowed:
            headers["Retry-After"] = str(int(bucket.retry_after()) + 1)
        
        return allowed, headers


# Global rate limiter instance
rate_limiter = RateLimiter()


def configure_default_limits() -> None:
    """Configure default rate limits."""
    # Per-merchant API limits
    rate_limiter.configure("merchant:api", 1000, 50.0)  # 1000 req, 50/sec refill
    rate_limiter.configure("merchant:payouts", 50, 1.0)  # 50 payouts, 1/sec refill
    rate_limiter.configure("merchant:events", 200, 10.0)  # 200 events, 10/sec refill
    
    # Per-IP global limits
    rate_limiter.configure("ip:global", 200, 20.0)  # 200 req, 20/sec refill
    rate_limiter.configure("ip:auth", 10, 0.5)  # 10 auth attempts, 1 per 2 sec
    
    # Per-session limits
    rate_limiter.configure("session:api", 500, 20.0)