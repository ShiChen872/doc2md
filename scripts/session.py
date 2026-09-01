"""Config-dir, work-dir, and Playwright session helpers (permissions, no cookie files)."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

CFG = Path.home() / ".config" / "doc2md"
DIR_MODE = 0o700
FILE_MODE = 0o600
COOKIE_FILES = ("wps_cookie.txt", "feishu_cookie.txt")
WORK_TOKEN_RE = re.compile(r"[^A-Za-z0-9._-]+")
GENERATED_ASSET_GLOBS = ("page_*.png", "page_*.jpg", "image_*", "slide_*")


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


def _work_slug(token: str) -> str:
    slug = WORK_TOKEN_RE.sub("_", token or "work").strip("._") or "work"
    return slug[:80]


def make_work_dir(token: str, *, keep: bool, beside: Path) -> Path:
    """Scratch dir for OTL JSON / stream URLs. Temp by default; beside output if keep."""
    slug = _work_slug(token)
    if keep:
        path = beside.expanduser().resolve().parent / f".doc2md_work_{slug}"
        path.mkdir(parents=True, exist_ok=True)
        tighten_path(path, DIR_MODE)
        return path
    path = Path(tempfile.mkdtemp(prefix=f"doc2md_work_{slug}_"))
    tighten_path(path, DIR_MODE)
    return path


def cleanup_work_dir(work: Path | None, *, keep: bool) -> None:
    if keep or work is None:
        return
    shutil.rmtree(work, ignore_errors=True)


def clear_generated_assets(
    assets_dir: Path, patterns: tuple[str, ...] | None = None
) -> None:
    """Unlink generated files only. Directories matching the glob are left alone."""
    if not assets_dir.is_dir():
        return
    for pattern in patterns or GENERATED_ASSET_GLOBS:
        for old in assets_dir.glob(pattern):
            if old.is_file():
                try:
                    old.unlink()
                except OSError:
                    pass


def should_clear_generated_assets(
    assets_dir: Path,
    *,
    default_dir: Path,
    force: bool = False,
) -> bool:
    """Default `{stem}_assets` may be wiped. A non-empty custom --assets-dir is not."""
    if force:
        return True
    try:
        if assets_dir.resolve() == default_dir.resolve():
            return True
    except OSError:
        return True
    if not assets_dir.exists():
        return True
    try:
        next(assets_dir.iterdir())
    except StopIteration:
        return True
    except OSError:
        return True
    return False
