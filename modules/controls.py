"""
modules/controls.py
===================
Cross-platform scrape controls: pause, resume, quit, and status reporting.

Two independent control channels run simultaneously so the scraper is
operable in any environment:

  1. Keyboard listener (pynput) — interactive terminal sessions.
     Catches P / R / Q / S keys in the background via a daemon thread.
     Falls back gracefully with a warning if pynput is not installed.

  2. Command file — headless / scheduled / remote sessions.
     Write one of: pause | resume | stop | status | fresh
     to 'command.txt' in the working directory and the scraper reads it
     within the next loop iteration. The file is cleared after reading.
"""

import logging
import os
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger("scraper")

# ── Optional pynput import ────────────────────────────────────────
try:
    from pynput import keyboard as _kb

    _PYNPUT_OK = True
except ImportError:
    _PYNPUT_OK = False


# ================================================================
# SHARED STATE
# ================================================================

class State:
    """
    Thread-safe container for scraper control signals.

    Attributes:
        paused: When True the main loop blocks until resumed.
        stop:   When True the main loop exits and saves a checkpoint.
    """

    def __init__(self) -> None:
        self.paused: bool = False
        self.stop: bool = False
        self._lock = threading.Lock()

    def set_paused(self, value: bool) -> None:
        with self._lock:
            self.paused = value

    def set_stop(self, value: bool) -> None:
        with self._lock:
            self.stop = value


# ================================================================
# KEYBOARD LISTENER (pynput — cross-platform)
# ================================================================

def start_keyboard_listener(
    state: State,
    status_callback: Optional[Callable[[], None]] = None,
) -> Optional[object]:
    """
    Start a background daemon thread that listens for P / R / Q / S keypresses.

    Args:
        state:           Shared State object mutated on key events.
        status_callback: Optional callable invoked when S is pressed.

    Returns:
        The pynput Listener instance (call .stop() to terminate), or None if
        pynput is unavailable.
    """
    if not _PYNPUT_OK:
        logger.warning(
            "pynput not installed — keyboard controls unavailable. "
            "Use command.txt instead, or run: pip install pynput"
        )
        return None

    def _on_press(key: object) -> None:
        try:
            char = key.char.upper() if hasattr(key, "char") and key.char else None
        except Exception:
            return

        if char == "P":
            state.set_paused(not state.paused)
            if state.paused:
                logger.info("[PAUSED]  — press R to resume")
            else:
                logger.info("[RESUMED]")

        elif char == "R" and state.paused:
            state.set_paused(False)
            logger.info("[RESUMED]")

        elif char == "Q":
            state.set_stop(True)
            logger.info("[QUIT] — saving checkpoint...")

        elif char == "S" and status_callback:
            status_callback()

    listener = _kb.Listener(on_press=_on_press)
    listener.daemon = True
    listener.start()
    logger.info("Keyboard controls active — P=pause  R=resume  Q=quit  S=status")
    return listener


# ================================================================
# COMMAND FILE CONTROLS (all platforms / headless)
# ================================================================

def check_command_file(
    state: State,
    cmd_file: str,
    ctx: Optional[dict] = None,
) -> None:
    """
    Read and execute a command from the command file, then clear it.

    Supported commands:
        pause   — suspend the scrape loop
        resume  — resume the scrape loop
        stop / quit — exit cleanly after saving
        status  — log current progress (requires ctx dict)
        fresh   — documented reminder that --fresh CLI flag clears the checkpoint

    Args:
        state:    Shared State object.
        cmd_file: Path to the command text file.
        ctx:      Optional scrape context dict {"saved": int, "page": int}.
    """
    if not os.path.exists(cmd_file):
        return

    try:
        with open(cmd_file, encoding="utf-8") as fh:
            cmd = fh.read().strip().lower()
        # Clear immediately to avoid re-reading
        open(cmd_file, "w").close()

        if not cmd:
            return

        if cmd == "pause":
            state.set_paused(True)
            logger.info("[PAUSED] via command file")

        elif cmd in ("resume", "r"):
            state.set_paused(False)
            logger.info("[RESUMED] via command file")

        elif cmd in ("stop", "quit", "q"):
            state.set_stop(True)
            logger.info("[STOP] via command file — checkpoint will be saved")

        elif cmd == "status" and ctx is not None:
            logger.info(
                f"STATUS — saved: {ctx.get('saved', 0)}  "
                f"page: {ctx.get('page', 0)}"
            )

        elif cmd == "fresh":
            logger.info(
                "To start fresh, re-run with the --fresh flag: "
                "python scraper.py --fresh"
            )

        else:
            logger.warning(f"Unknown command in {cmd_file!r}: {cmd!r}")

    except Exception as exc:
        logger.debug(f"Command file read error: {exc}")


def wait_if_paused(
    state: State,
    cmd_file: str,
    ctx: Optional[dict] = None,
) -> None:
    """
    Block the calling thread until state.paused is False or state.stop is True.
    Polls the command file every 300 ms while waiting.

    Args:
        state:    Shared State object.
        cmd_file: Path to the command text file.
        ctx:      Optional context dict passed to check_command_file.
    """
    while state.paused and not state.stop:
        check_command_file(state, cmd_file, ctx)
        time.sleep(0.3)
