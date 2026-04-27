"""File-system helpers: safe paths, name sanitisation, streamed upload write."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException, UploadFile

_FILENAME_BAD = re.compile(r"[\x00-\x1f\x7f]")
_PATH_SEP_RE = re.compile(r"[\\/]+")
_CMD_NAME_RE = re.compile(r"[^A-Za-z0-9_-]")


def safe_path(base: Path, user_path: str) -> Path:
    """Resolve user_path against base; raise 400 on traversal.

    user_path may be empty (means base itself), '/'-separated.
    """
    base_real = Path(os.path.realpath(base))
    if not base_real.exists():
        base_real.mkdir(parents=True, exist_ok=True)

    # normalise: strip leading slashes, collapse separators
    raw = (user_path or "").strip()
    if raw.startswith("/") or raw.startswith("\\"):
        raise HTTPException(status_code=400, detail="absolute path not allowed")
    if "\x00" in raw:
        raise HTTPException(status_code=400, detail="invalid path")

    candidate = (base_real / raw) if raw else base_real
    candidate_real = Path(os.path.realpath(candidate))

    try:
        candidate_real.relative_to(base_real)
    except ValueError:
        raise HTTPException(status_code=400, detail="path escapes base")
    return candidate_real


def sanitize_filename(name: str) -> str:
    """Strip control chars, path separators, leading dots; cap length."""
    if not name:
        return "file"
    n = _FILENAME_BAD.sub("", name)
    n = _PATH_SEP_RE.sub("_", n)
    n = n.lstrip(".")
    n = n.strip()
    if len(n) > 200:
        n = n[:200]
    return n or "file"


def sanitize_command_name_for_dir(name: str) -> str:
    """Convert command name into a filesystem-safe directory name."""
    return _CMD_NAME_RE.sub("_", name)


def timestamp_prefix() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


async def stream_upload_to_file(
    upload: UploadFile,
    target_path: Path,
    max_bytes: int,
) -> int:
    """Stream UploadFile to disk; on overflow remove partial file and raise 413.

    Returns bytes written.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    chunk_size = 1024 * 1024
    f: BinaryIO | None = None
    try:
        f = open(target_path, "wb")
        while True:
            chunk = await upload.read(chunk_size)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                f.close()
                f = None
                try:
                    target_path.unlink()
                except FileNotFoundError:
                    pass
                raise HTTPException(status_code=413, detail="file too large")
            f.write(chunk)
    finally:
        if f is not None:
            f.close()
    return written
