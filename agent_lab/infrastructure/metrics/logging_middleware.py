import logging
import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from agent_lab.infrastructure.metrics.tracer import excluded_paths

logger = logging.getLogger(__name__)

_REDACTED_HEADERS = {"authorization", "cookie", "set-cookie", "proxy-authorization"}


def _redact(headers) -> dict:
    return {
        key: ("***" if key.lower() in _REDACTED_HEADERS else value)
        for key, value in headers.items()
    }


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        if any(path.startswith(ep) for ep in excluded_paths):
            return await call_next(request)

        # Log incoming request details
        logger.info(f"Incoming request {request.method}: {request.url}")
        logger.debug(f"Request headers: {_redact(request.headers)}")
        start_time = time.time()
        try:
            response = await call_next(request)
        except Exception as e:
            # Log exception as error
            logger.exception("An error occurred during request processing")
            raise e

        process_time = (time.time() - start_time) * 1000
        logger.info(
            f"Outgoing response {response.status_code} for {request.method}: {request.url} (time: {process_time:.2f} ms)"
        )
        logger.debug(f"Response headers: {_redact(response.headers)}")
        return response
