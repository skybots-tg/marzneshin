import asyncio
import logging
import time

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.perf_logger import log_slow_request, log_pool_pressure

logger = logging.getLogger(__name__)


class TimeoutMiddleware(BaseHTTPMiddleware):
    """Timeout + performance instrumentation middleware.

    - Enforces a hard timeout on every request.
    - Measures wall-clock duration and logs slow requests (with pool/CPU
      context) to the dedicated performance log file.
    """

    def __init__(self, app, timeout: int = 30):
        super().__init__(app)
        self.timeout = timeout

    async def dispatch(self, request: Request, call_next):
        t0 = time.monotonic()
        method = request.method
        path = request.url.path

        try:
            response = await asyncio.wait_for(
                call_next(request),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            duration = time.monotonic() - t0
            logger.warning(
                "Request timeout (%ds): %s %s",
                self.timeout, method, path,
            )
            log_slow_request(
                method, path, 504, duration, extra="TIMEOUT"
            )
            return JSONResponse(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                content={"detail": "Request timeout"},
            )

        duration = time.monotonic() - t0
        log_slow_request(method, path, response.status_code, duration)
        return response
