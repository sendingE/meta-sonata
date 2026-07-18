from __future__ import annotations

import mimetypes
import urllib.request
from pathlib import Path

from .providers import USER_AGENT


def extension_from_content_type(content_type: str | None, fallback: str = ".jpg") -> str:
    if not content_type:
        return fallback
    mime = content_type.split(";", 1)[0].strip().lower()
    return mimetypes.guess_extension(mime) or fallback


def download_cover(url: str, target_dir: Path, *, timeout: int = 20) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        data = res.read()
        ext = extension_from_content_type(res.headers.get("Content-Type"))
    out = target_dir / f"remote-cover{ext}"
    out.write_bytes(data)
    return out
