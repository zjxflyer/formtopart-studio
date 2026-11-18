"""Canonical local paths, including Windows paths beyond the legacy length limit."""
from __future__ import annotations

import ntpath
import os
from pathlib import Path


def extended_windows_path(value: str) -> str:
    """Convert an absolute drive/UNC path; keep an existing extended prefix stable."""
    value = ntpath.normpath(value)
    if value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\.\\"):
        raise ValueError("Device paths cannot be used as project folders")
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    drive, tail = ntpath.splitdrive(value)
    if not drive or not tail.startswith("\\"):
        raise ValueError("An absolute project folder path is required")
    return "\\\\?\\" + value


def filesystem_path(value: str | Path) -> Path:
    """Resolve consistently before any directory, SQLite or source-file operations.

    The prefix avoids requiring registry/policy changes on machines where an
    application manifest alone does not enable legacy-limit bypass.
    """
    path = Path(value).expanduser()
    if os.name == "nt":
        # Prefix before resolve: resolving an existing long path itself may need
        # Windows extended-path semantics. absolute() does not open the path.
        return Path(extended_windows_path(str(path.absolute()))).resolve()
    return path.resolve()
