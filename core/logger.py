import sys
from loguru import logger
from core.config import settings

def setup_logger():
    # Remove default handler
    logger.remove()

    # Add console handler with structured formatting
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        enqueue=True,  # Thread-safe logging
        backtrace=True,
        diagnose=True,
    )

# Initialize logger
setup_logger()
