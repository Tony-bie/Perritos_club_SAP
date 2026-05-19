"""Logging configuration helper to set structured logging for the app."""
import logging
import sys
from .config import LOG_LEVEL


def configure_logging() -> None:
    """Configure root logger with stdout handler and configured log level."""
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    root = logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)
    fmt = "%(asctime)s %(levelname)s %(name)s - %(message)s"
    handler.setFormatter(logging.Formatter(fmt))
    root.handlers = [handler]
    root.setLevel(level)
