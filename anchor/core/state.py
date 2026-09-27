"""Per-profile SQLite state DB.

Records what's been successfully backed up to each destination so subsequent
runs can compute the incremental diff without re-stat'ing the destination
(which is slow over network / cloud).

Schema:
    files (
        dest_id     TEXT,
        sub         TEXT,    -- source label (subfolder name)
        rel_path    TEXT,    -- forward-slash relative path
        size        INTEGER,
        mtime       REAL,
        sha256      TEXT,    -- nullable; only set if hash-verify mode used
        backed_up_at TEXT,
        PRIMARY KEY (dest_id, sub, rel_path)
    )
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

from ..app_config import STATE_DIR, ensure_dirs


_lock = threading.RLock()


class StateDB:
    def __init__(self, profile_id: str):
        ensure_dirs()
        self.path: Path = STATE_DIR / f"{profile_id}.sqlite"
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        with _lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    dest_id     TEXT NOT NULL,
                    sub         TEXT NOT NULL,
                    rel_path    TEXT NOT NULL,
                    size        INTEGER,
                    mtime       REAL,
                    sha256      TEXT,
                    backed_up_at TEXT,
                    PRIMARY KEY (dest_id, sub, rel_path)
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_files_dest ON files(dest_id)"
            )

    def get(self, dest_id: str, sub: str, rel_path: str) -> Optional[Tuple]:
        with _lock:
            cur = self._conn.execute(
                "SELECT size, mtime, sha256, backed_up_at FROM files "
                "WHERE dest_id=? AND sub=? AND rel_path=?",
                (dest_id, sub, rel_path),
            )
            return cur.fetchone()

    def upsert(
        self,
        dest_id: str,
        sub: str,
        rel_path: str,
        size: int,
        mtime: float,
        sha256: Optional[str],
    ) -> None:
        with _lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO files (dest_id, sub, rel_path, size, mtime, sha256, backed_up_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(dest_id, sub, rel_path) DO UPDATE SET
                    size=excluded.size,
                    mtime=excluded.mtime,
                    sha256=excluded.sha256,
                    backed_up_at=excluded.backed_up_at
                """,
                (
                    dest_id, sub, rel_path,
                    size, mtime, sha256,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )

    def delete(self, dest_id: str, sub: str, rel_path: str) -> None:
        with _lock, self._conn:
            self._conn.execute(
                "DELETE FROM files WHERE dest_id=? AND sub=? AND rel_path=?",
                (dest_id, sub, rel_path),
            )

    def all_for_dest(self, dest_id: str) -> Dict[Tuple[str, str], Tuple]:
        with _lock:
            cur = self._conn.execute(
                "SELECT sub, rel_path, size, mtime, sha256 FROM files WHERE dest_id=?",
                (dest_id,),
            )
            return {(r[0], r[1]): (r[2], r[3], r[4]) for r in cur.fetchall()}

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
