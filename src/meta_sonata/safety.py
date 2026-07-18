from __future__ import annotations

import os
from pathlib import Path


PROTECTED_PATHS_ENV = "META_SONATA_PROTECTED_PATHS"


class ProtectedPathError(RuntimeError):
    """Raised when a write operation targets a protected real library path."""


def normalize_path(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def protected_library_paths() -> tuple[Path, ...]:
    raw = os.environ.get(PROTECTED_PATHS_ENV, "")
    if not raw.strip():
        return ()
    parts = []
    for chunk in raw.replace("\n", os.pathsep).split(os.pathsep):
        chunk = chunk.strip()
        if chunk:
            parts.append(Path(chunk).expanduser())
    return tuple(parts)


def is_protected_path(path: Path | str) -> bool:
    candidate = normalize_path(path)
    return any(is_relative_to(candidate, normalize_path(root)) for root in protected_library_paths())


def assert_write_allowed(path: Path | str, *, allow_protected: bool = False) -> None:
    if allow_protected:
        return
    if is_protected_path(path):
        protected = "\n".join(str(p) for p in protected_library_paths())
        raise ProtectedPathError(
            "Refusing to write inside the protected real music library. "
            "Copy a subset to a sandbox or use the staging library for experiments.\n"
            f"Configured by {PROTECTED_PATHS_ENV}:\n{protected}"
        )
