r"""Centralized logging.

Inspired by Backutil's structured event categories, but routed through
Python's standard logging module so we get:
  * a rotating file log next to the app (or under %APPDATA%\Anchor\logs\
    as a fallback when the app folder isn't writable)
  * an in-memory tail that the GUI's log viewer can read
  * coloured console output when run from a terminal
"""
from __future__ import annotations

import logging
import logging.handlers
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Deque, Iterable, List, Optional

from .app_config import LOGS_DIR, ensure_dirs

_FMT = "%(asctime)s [%(levelname)s] %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


class TailHandler(logging.Handler):
    """Keeps the last N log records in memory for the GUI log viewer."""

    def __init__(self, capacity: int = 2000):
        super().__init__()
        self.buffer: Deque[str] = deque(maxlen=capacity)
        self._listeners: List = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.buffer.append(msg)
            for listener in list(self._listeners):
                try:
                    listener(record.levelname, msg)
                except Exception:
                    pass
        except Exception:
            self.handleError(record)

    def add_listener(self, fn) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn) -> None:
        try:
            self._listeners.remove(fn)
        except ValueError:
            pass

    def snapshot(self) -> List[str]:
        return list(self.buffer)


_tail = TailHandler()


def setup_logging(profile_name: Optional[str] = None) -> logging.Logger:
    """Configure root logger. Idempotent — safe to call multiple times.

    Levels chosen so the GUI stays readable but the file log keeps full
    forensics:
      - root logger: DEBUG (so handlers can choose their own threshold)
      - file handler: DEBUG (everything, including per-file Adopted/Deleted)
      - in-memory tail (GUI viewer): INFO (high-signal summary lines only)
      - console: INFO
    """
    ensure_dirs()
    root = logging.getLogger("anchor")
    if getattr(root, "_configured", False):
        return root
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(_FMT, datefmt=_DATE_FMT)

    log_path = LOGS_DIR / f"anchor-{datetime.now():%Y%m}.log"
    file_h = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_h.setLevel(logging.DEBUG)
    file_h.setFormatter(fmt)
    root.addHandler(file_h)

    _tail.setLevel(logging.INFO)
    _tail.setFormatter(fmt)
    root.addHandler(_tail)

    # Console (best-effort)
    try:
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(fmt)
        root.addHandler(console)
    except Exception:
        pass

    root._configured = True  # type: ignore[attr-defined]
    return root


def get_tail() -> TailHandler:
    return _tail


def get_logger(name: str = "anchor") -> logging.Logger:
    return logging.getLogger(name)
