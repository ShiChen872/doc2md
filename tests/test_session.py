"""Unit tests for session permission helpers (no network)."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import session as sess  # noqa: E402


class _DummyContext:
    def storage_state(self, path: str) -> None:
        Path(path).write_text('{"cookies":[]}\n', encoding="utf-8")


def test_ensure_config_dir_mode(tmp_path: Path):
    root = tmp_path / "cfg"
    sess.ensure_config_dir(root)
    mode = stat.S_IMODE(root.stat().st_mode)
    assert mode == 0o700


def test_write_storage_state_is_0600_and_removes_cookie_txt(tmp_path: Path):
    root = tmp_path / "cfg"
    root.mkdir()
    cookie = root / "wps_cookie.txt"
    cookie.write_text("sid=secret\n", encoding="utf-8")
    dest = root / "wps_storage_state.json"
    dest.write_text("old\n", encoding="utf-8")
    dest.chmod(0o644)
    sess.write_storage_state(_DummyContext(), dest)
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600
    assert dest.read_text(encoding="utf-8").startswith("{")
    assert not cookie.exists()


def test_tighten_existing_0644(tmp_path: Path):
    f = tmp_path / "state.json"
    f.write_text("{}\n", encoding="utf-8")
    f.chmod(0o644)
    sess.tighten_file(f)
    assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_redact_url_for_log_drops_query():
    raw = "https://accounts.feishu.cn/callback?code=SECRET&ticket=T"
    out = sess.redact_url_for_log(raw)
    assert "SECRET" not in out
    assert "ticket=" not in out
    assert "accounts.feishu.cn/callback" in out


def test_make_work_dir_temp_cleaned(tmp_path: Path):
    out = tmp_path / "out.md"
    out.write_text("# x\n", encoding="utf-8")
    work = sess.make_work_dir("wps_abc", keep=False, beside=out)
    assert work.is_dir()
    assert work.parent != tmp_path
    (work / "stream_path.txt").write_text("cdn?token=secret\n", encoding="utf-8")
    sess.cleanup_work_dir(work, keep=False)
    assert not work.exists()


def test_make_work_dir_keep_beside_output(tmp_path: Path):
    out = tmp_path / "out.md"
    out.write_text("# x\n", encoding="utf-8")
    work = sess.make_work_dir("wps_abc", keep=True, beside=out)
    assert work.parent == tmp_path
    assert work.name.startswith(".doc2md_work_")
    sess.cleanup_work_dir(work, keep=True)
    assert work.is_dir()


def test_clear_generated_assets_skips_directories(tmp_path: Path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "page_001.png").write_bytes(b"user")
    (assets / "image_x").mkdir()
    (assets / "image_001.png").write_bytes(b"gen")
    (assets / "keep.txt").write_text("ok\n", encoding="utf-8")
    sess.clear_generated_assets(assets)
    assert (assets / "image_x").is_dir()
    assert not (assets / "image_001.png").exists()
    assert not (assets / "page_001.png").exists()
    assert (assets / "keep.txt").read_text(encoding="utf-8") == "ok\n"


def test_should_clear_generated_assets_custom_nonempty(tmp_path: Path):
    default = tmp_path / "note_assets"
    custom = tmp_path / "shared"
    custom.mkdir()
    (custom / "page_001.png").write_bytes(b"user")
    assert sess.should_clear_generated_assets(default, default_dir=default) is True
    assert sess.should_clear_generated_assets(custom, default_dir=default) is False
    assert (
        sess.should_clear_generated_assets(custom, default_dir=default, force=True)
        is True
    )
    empty = tmp_path / "empty_custom"
    empty.mkdir()
    assert sess.should_clear_generated_assets(empty, default_dir=default) is True
