"""
modules/logger.py
=================
Configures a shared logger that writes to both stdout and a rotating log file.
Every run appends to a dated log file, preserving a full audit trail alongside
the Excel output — useful for debugging and demonstrating operational awareness.
"""

import logging
import sys
from datetime import date
from logging.handlers import RotatingFileHandler


def setup_logger(prefix: str = "scraper", log_dir: str = ".") -> logging.Logger:
    """
    Configure and return the root 'scraper' logger with two handlers:
      - StreamHandler  → stdout (INFO and above)
      - RotatingFileHandler → dated log file (DEBUG and above, max 5 MB, 3 backups)

    Args:
        prefix:  Filename prefix for the log file (e.g. the platform name).
        log_dir: Directory where the log file will be written.

    Returns:
        Configured logging.Logger instance.
    """
    log_path = f"{log_dir}/{prefix}_{date.today().strftime('%Y%m%d')}.log"

    formatter = logging.Formatter(
        fmt="%(asctime)s  [%(levelname)-8s]  %(message)s",
        datefmt="%H:%M:%S",
    )

    logger = logging.getLogger("scraper")
    logger.setLevel(logging.DEBUG)

    # Avoid adding duplicate handlers if setup_logger() is called more than once
    if logger.handlers:
        return logger

    # ── Console handler (INFO+) ───────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # ── Rotating file handler (DEBUG+) ────────────────────────────
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,   # 5 MB per file
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger
