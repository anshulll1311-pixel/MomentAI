import logging
import sys
from logging.config import dictConfig


def configure_logging(log_level: str) -> None:
    """Configure consistent application-wide console logging."""
    level = log_level.upper()
    if level not in logging.getLevelNamesMapping():
        level = "INFO"

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "stream": sys.stdout,
                }
            },
            "root": {"handlers": ["console"], "level": level},
        }
    )
