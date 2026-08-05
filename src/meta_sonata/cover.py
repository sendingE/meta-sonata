from __future__ import annotations

import mimetypes
from pathlib import Path

from .network import USER_AGENT, fetch_bytes


def extension_from_content_type(content_type: str | None, fallback: str = ".jpg") -> str:
    if not content_type:
        return fallback
    mime = content_type.split(";", 1)[0].strip().lower()
    return mimetypes.guess_extension(mime) or fallback


def download_cover(url: str, target_dir: Path, *, timeout: int = 20) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    response = fetch_bytes(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    data = response.body
    ext = extension_from_content_type(response.content_type)
    out = target_dir / f"remote-cover{ext}"
    out.write_bytes(data)
    return out
