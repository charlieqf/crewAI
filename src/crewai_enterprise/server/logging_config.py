"""
Logging configuration for WeCom callback server.

When running under systemd (detected via INVOCATION_ID or JOURNAL_STREAM env vars):
  - Only logs to stdout (systemd captures to journal and configured log files)

When running standalone (local dev, tests):
  - Logs to both console and rotating log files
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(
    log_level: str = "INFO",
    log_dir: str | None = None,
    log_file: str = "wecom_callback.log",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> None:
    """
    Configure logging with file and console handlers.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_dir: Directory for log files. Defaults to /var/log/wecom-callback or ./logs
        log_file: Name of the log file
        max_bytes: Maximum size of each log file before rotation
        backup_count: Number of backup files to keep
    """
    # Determine log directory
    if log_dir is None:
        log_dir = os.getenv("LOG_DIR")

    if log_dir is None:
        # Try system log dir first, fall back to local
        if os.path.isdir("/var/log") and os.access("/var/log", os.W_OK):
            log_dir = "/var/log/wecom-callback"
        else:
            log_dir = "./logs"

    # Create log directory if needed
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Get log level from environment or parameter
    level_str = os.getenv("LOG_LEVEL", log_level).upper()
    level = getattr(logging, level_str, logging.INFO)

    # Detect if running under systemd (which captures stdout to journal/file)
    running_under_systemd = (
        os.getenv("INVOCATION_ID") is not None
        or os.getenv("JOURNAL_STREAM") is not None
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Log format with structured fields for grep
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

    if running_under_systemd:
        # Under systemd: only log to stdout (systemd captures to file)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        logging.info(f"Logging initialized (systemd mode): level={level_str}")
    else:
        # Standalone: log to both console and file
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        # File handler with rotation
        log_file_path = log_path / log_file
        file_handler = RotatingFileHandler(
            log_file_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        # Error log (separate file for errors only)
        error_log_path = log_path / "wecom_callback_error.log"
        error_handler = RotatingFileHandler(
            error_log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        root_logger.addHandler(error_handler)

        logging.info(f"Logging initialized: level={level_str}, dir={log_dir}")
        logging.info(f"Log files: {log_file_path}, {error_log_path}")


# Auto-configure on import if running as main server
if os.getenv("WECOM_AUTO_LOGGING", "").lower() in ("1", "true", "yes"):
    setup_logging()
