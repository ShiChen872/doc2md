"""Config-dir and Playwright session helpers (permissions, no cookie files)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

CFG = Path.home() / ".config" / "doc2md"
DIR_MODE = 0o700
FILE_MODE = 0o600
COOKIE_FILES = ("wps_cookie.txt", "feishu_cookie.txt")


def ensure_config_dir(root: Path | None = None) -> Path:
    """Create ~/.config/doc2md at 0700. Existing dirs are chmod'd, never refused."""
    path = root if root is not None else CFG
    path.mkdir(parents=True, exist_ok=True)
    tighten_path(path, DIR_MODE)
    return path


def tighten_path(path: Path, mode: int = FILE_MODE) -> None:
    if not path.exists():
        return
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def tighten_file(path: Path) -> None:
    if path.is_file():
        tighten_path(path, FILE_MODE)


def remove_legacy_cookie_files(root: Path | None = None) -> None:
    """Delete unused plaintext cookie backups if they still exist."""
    base = root if root is not None else CFG
    for name in COOKIE_FILES:
        path = base / name
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass


def write_storage_state(context: object, dest: Path) -> None:
    """Write Playwright storage_state via a 0600 temp file, then replace dest."""
    ensure_config_dir(dest.parent)
    fd, tmp_name = tempfile.mkstemp(prefix=dest.name + ".", dir=str(dest.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tighten_path(tmp_path, FILE_MODE)
        context.storage_state(path=str(tmp_path))  # type: ignore[attr-defined]
        tighten_path(tmp_path, FILE_MODE)
        os.replace(tmp_path, dest)
        tighten_path(dest, FILE_MODE)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    remove_legacy_cookie_files(dest.parent)


def redact_url_for_log(url: str) -> str:
    """Host + path only so SSO query tokens (code/ticket) stay out of logs."""
    parsed = urlparse(url or "")
    host = parsed.netloc or parsed.path
    if not parsed.scheme:
        return parsed.path or url[:80]
    path = parsed.path or "/"
    return f"{parsed.scheme}://{host}{path}"
