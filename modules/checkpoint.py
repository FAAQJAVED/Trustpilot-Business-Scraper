"""
modules/checkpoint.py
=====================
Checkpoint persistence for resumable scrape runs.

A checkpoint is a small JSON file that records the last successfully completed
page, the total page count, and the set of slugs already seen. On the next run,
the scraper loads this file and resumes from where it left off rather than
re-fetching all previous pages.

All writes are atomic (write to .tmp → os.replace) to ensure the checkpoint
file is never left in a half-written state even if the process is interrupted.
"""

import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger("scraper")


def save(data: Dict[str, Any], path: str) -> None:
    """
    Atomically write checkpoint data to a JSON file.

    Writes to a temporary file first, then renames it over the target path.
    This guarantees the file is either the old version or the new version —
    never a partially-written corrupt state.

    Args:
        data: Dict containing checkpoint fields, e.g.:
              {
                  "last_completed_page": 12,
                  "total_pages": 69,
                  "seen_slugs": ["slug-a", "slug-b", ...]
              }
        path: Target checkpoint file path.
    """
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
        logger.debug(
            f"Checkpoint saved — page {data.get('last_completed_page', '?')} "
            f"of {data.get('total_pages', '?')}"
        )
    except Exception as exc:
        logger.warning(f"Checkpoint save failed: {exc}")
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def load(path: str) -> Dict[str, Any]:
    """
    Load checkpoint data from a JSON file.

    Args:
        path: Path to the checkpoint file.

    Returns:
        Checkpoint dict, or empty dict if the file does not exist or is corrupt.
    """
    if not os.path.exists(path):
        return {}

    try:
        with open(path, encoding="utf-8") as fh:
            content = fh.read().strip()
        if not content:
            return {}
        data = json.loads(content)
        logger.info(
            f"Checkpoint loaded — resuming from page "
            f"{data.get('last_completed_page', 0) + 1}"
        )
        return data
    except Exception as exc:
        logger.warning(f"Checkpoint load failed (will start from page 1): {exc}")
        return {}


def clear(path: str) -> None:
    """
    Remove the checkpoint file after a fully successful run.

    Args:
        path: Path to the checkpoint file.
    """
    if os.path.exists(path):
        try:
            os.remove(path)
            logger.info("Checkpoint cleared — run completed successfully.")
        except Exception as exc:
            logger.warning(f"Could not remove checkpoint file: {exc}")
