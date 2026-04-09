import sys
import logging
from loguru import logger
from core.config import settings


class _HealthCheckFilter(logging.Filter):
    """Suppress uvicorn access log entries for the /health endpoint."""
    def filter(self, record: logging.LogRecord) -> bool:
        return "GET /health" not in record.getMessage()


def setup_logger():
    # Remove default loguru handler
    logger.remove()

    # Add console handler with structured formatting
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    # Silence /health spam from uvicorn access log
    logging.getLogger("uvicorn.access").addFilter(_HealthCheckFilter())

    # httpx logs every HTTP request at INFO — only show at DEBUG, otherwise WARNING
    httpx_level = logging.DEBUG if settings.log_level.upper() == "DEBUG" else logging.WARNING
    logging.getLogger("httpx").setLevel(httpx_level)
    logging.getLogger("httpcore").setLevel(httpx_level)


# Initialize logger
setup_logger()
