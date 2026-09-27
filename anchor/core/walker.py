"""Recursive source walker with glob-based exclusions.

Each item yielded is a (source_root, absolute_path, relative_path) tuple so the
destination can mirror the relative layout under a per-source subfolder.
"""
from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, List, Tuple


@dataclass
class ExclusionRules:
    file_globs: List[str] = field(default_factory=list)
    dir_names: List[str] = field(default_factory=list)  # basename match

    def is_dir_excluded(self, name: str, full_path: str) -> bool:
        for d in self.dir_names:
            if d == name:
                return True
            # allow absolute path matches too
            if os.path.normcase(d) == os.path.normcase(full_path):
                return True
        # glob style on dir name
        for g in self.file_globs:
            if fnmatch.fnmatch(name, g):
                return True
        return False

    def is_file_excluded(self, name: str, rel_path: str) -> bool:
        for g in self.file_globs:
            if fnmatch.fnmatch(name, g) or fnmatch.fnmatch(rel_path, g):
                return True
        return False


@dataclass
class WalkItem:
    source_root: str  # original source dir (e.g. "C:\Users\<you>\Documents")
    abs_path: str     # absolute source file path
    rel_path: str     # path relative to source_root (forward slashes)
    size: int
    mtime: float


def source_label(path: str) -> str:
    """Stable subfolder name for a source root (used under destination).

    Examples:
        "C:\\Users\\<you>\\Documents"  -> "C__Users_<you>_Documents"
        "\\\\NAS\\share\\stuff"        -> "UNC_NAS_share_stuff"
    """
    p = path.replace("\\", "/").rstrip("/")
    if p.startswith("//"):
        return "UNC_" + p.lstrip("/").replace("/", "_").replace(":", "")
    return p.replace(":", "_").replace("/", "_").strip("_") or "root"


# Back-compat alias for any external caller.
_source_label = source_label


def existing_source_labels(sources: Iterable[str]) -> set:
    """Return the set of source labels whose root path currently exists on disk.

    The engine uses this to refuse mirror-deletion for sources that have
    vanished (e.g. an unmounted USB drive) — otherwise mirror-delete would
    wipe the whole backup for that source.
    """
    out: set = set()
    for raw_src in sources:
        src = os.path.abspath(raw_src) if not raw_src.startswith("\\\\") else raw_src
        if os.path.exists(src):
            out.add(source_label(src))
    return out


def walk_sources(
    sources: Iterable[str],
    rules: ExclusionRules,
    follow_symlinks: bool = False,
    flat: bool = False,
) -> Iterator[Tuple[str, WalkItem]]:
    """Yield (dest_subfolder, WalkItem) for every non-excluded file.

    When `flat` is True, the sub-label is always "" so files land directly
    under the destination root with no per-source subfolder. This is only
    safe for single-source profiles (the engine enforces that).
    """
    for raw_src in sources:
        src = os.path.abspath(raw_src) if not raw_src.startswith("\\\\") else raw_src
        if not os.path.exists(src):
            continue
        sub = "" if flat else source_label(src)

        if os.path.isfile(src):
            try:
                st = os.stat(src)
            except OSError:
                continue
            yield sub, WalkItem(
                source_root=os.path.dirname(src),
                abs_path=src,
                rel_path=os.path.basename(src),
                size=st.st_size,
                mtime=st.st_mtime,
            )
            continue

        for root, dirs, files in os.walk(src, followlinks=follow_symlinks):
            # prune dirs in-place
            dirs[:] = [
                d for d in dirs
                if not rules.is_dir_excluded(d, os.path.join(root, d))
            ]
            for name in files:
                abs_p = os.path.join(root, name)
                rel = os.path.relpath(abs_p, src).replace("\\", "/")
                if rules.is_file_excluded(name, rel):
                    continue
                try:
                    st = os.stat(abs_p)
                except OSError:
                    continue
                yield sub, WalkItem(
                    source_root=src,
                    abs_path=abs_p,
                    rel_path=rel,
                    size=st.st_size,
                    mtime=st.st_mtime,
                )
