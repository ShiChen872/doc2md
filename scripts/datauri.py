"""Decode Markdown/HTML data-URI images into files (no process helpers)."""

from __future__ import annotations

import base64
import re
from pathlib import Path

DATA_URI_RE = re.compile(
    r"!\[([^\]]*)\]\((data:image/([a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+))\)",
    re.MULTILINE,
)
BARE_DATA_URI_RE = re.compile(
    r"(data:image/([a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=]+))",
)

EXT_MAP = {
    "jpeg": "jpg",
    "jpg": "jpg",
    "png": "png",
    "gif": "gif",
    "webp": "webp",
    "bmp": "bmp",
    "svg+xml": "svg",
    "x-icon": "ico",
    "tiff": "tiff",
}


def _ext_for_mime(subtype: str) -> str:
    subtype = subtype.lower().split(";")[0].strip()
    return EXT_MAP.get(subtype, subtype.replace("+", "_") or "bin")


def extract_data_uris(markdown: str, assets_dir: Path, rel_prefix: str) -> tuple[str, int]:
    """Replace data-URI images with files under assets_dir. Returns (md, count)."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    counter = {"n": 0}

    def save_blob(subtype: str, b64: str) -> str:
        counter["n"] += 1
        ext = _ext_for_mime(subtype)
        filename = f"image_{counter['n']:03d}.{ext}"
        path = assets_dir / filename
        raw = base64.b64decode(re.sub(r"\s+", "", b64))
        path.write_bytes(raw)
        return f"{rel_prefix}/{filename}"

    def repl_md(m: re.Match) -> str:
        alt, _subtype, b64 = m.group(1), m.group(3), m.group(4)
        rel = save_blob(_subtype, b64)
        return f"![{alt}]({rel})"

    out = DATA_URI_RE.sub(repl_md, markdown)

    def repl_bare(m: re.Match) -> str:
        subtype, b64 = m.group(2), m.group(3)
        rel = save_blob(subtype, b64)
        return rel

    out = BARE_DATA_URI_RE.sub(repl_bare, out)
    return out, counter["n"]
