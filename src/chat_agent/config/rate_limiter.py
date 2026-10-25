"""RateLimiter dependency for FastAPI routes using pyrate-limiter."""

from typing import Any, Callable, Optional

from fastapi import HTTPException, Request, status

try:
    from pyrate_limiter import Duration, Limiter, Rate
except ImportError:
    logger.warning("pyrate-limiter not installed; rate limiting disabled.")

    class Duration:  # type: ignore[no-redef]
        SECOND = 1
        MINUTE = 60
        HOUR = 3600
        DAY = 86400

    class Rate:  # type: ignore[no-redef]
        def __init__(self, limit: int, duration: int) -> None:
            self.limit = limit
            self.duration = duration

    class Limiter:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def try_acquire(self, key: str) -> None:
            pass


class RateLimiter:
    """FastAPI route dependency for client rate limiting."""

    def __init__(
        self,
        limiter: Optional[Limiter] = None,
        key_func: Optional[Callable[[Request], str]] = None,
    ) -> None:
        self.limiter: Limiter = limiter or Limiter(Rate(60, Duration.MINUTE))
        self.key_func: Callable[[Request], str] = key_func or self._default_key

    def _default_key(self, request: Request) -> str:
        client = request.client
        return client.host if client else "default"

    async def __call__(self, request: Request) -> None:
        key = self.key_func(request)
        try:
            self.limiter.try_acquire(key)
        except Exception:
            logger.warning("Rate limit exceeded for client %s on %s", key, request.url.path)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
            )


__all__ = ["RateLimiter", "Limiter", "Rate", "Duration"]
