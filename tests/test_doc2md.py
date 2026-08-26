"""Unit tests for unified doc2md.py classifier (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import doc2md as cli  # noqa: E402


def test_classify_local_file(tmp_path: Path):
    f = tmp_path / "note.docx"
    f.write_bytes(b"PK")
    assert cli.classify(str(f)) == "local"


def test_classify_wps_kdocs():
    assert cli.classify("https://365.kdocs.cn/l/ccPEq4cqQmKT") == "wps"
    assert cli.classify("https://plus.wps.cn/view/media/l/cnU6phmAZZKr") == "wps"
    assert cli.classify("www.kdocs.cn/l/abc123") == "wps"
    assert cli.classify("https://365.kdocs.cn/wiki/l/0lcoPwGoRMiAkL") == "wps"
    assert cli.classify("365.kdocs.cn/wiki/l/0lcoPwGoRMiAkL") == "wps"


def test_classify_feishu():
    assert (
        cli.classify("https://waytoagi.feishu.cn/wiki/DyQPwr5Uui6n0HktnoxcYDrwngd")
        == "feishu"
    )
    assert cli.classify("https://acme.larksuite.com/docx/ABC123xyz") == "feishu"


def test_classify_unknown_url():
    with pytest.raises(ValueError, match="Unrecognized cloud URL"):
        cli.classify("https://example.com/wiki/abc")


def test_classify_missing_file():
    with pytest.raises(ValueError, match="not a local file"):
        cli.classify("/tmp/definitely-missing-doc2md-xyz.docx")


def test_default_output_local(tmp_path: Path):
    f = tmp_path / "a.docx"
    f.write_bytes(b"x")
    out = cli.default_output(str(f), "local")
    assert out.suffix == ".md"
    assert out.stem == "a"


def test_default_output_wps():
    out = cli.default_output("https://plus.wps.cn/view/media/l/cnU6phmAZZKr", "wps")
    assert out.name == "wps_cnU6phmAZZKr.md"


def test_default_output_feishu():
    out = cli.default_output(
        "https://waytoagi.feishu.cn/wiki/FnkSwOxXsiPtU2kL1U5cVEQZnqh",
        "feishu",
    )
    assert out.name == "feishu_FnkSwOxXsiPtU2kL1U5cVEQZnqh.md"


def test_looks_like_url():
    assert cli.looks_like_url("https://kdocs.cn/l/x")
    assert cli.looks_like_url("365.kdocs.cn/l/x")
    assert not cli.looks_like_url("report.docx")


def test_cli_no_login_flag():
    import subprocess
    import sys

    help_text = subprocess.check_output(
        [sys.executable, str(SCRIPTS / "doc2md.py"), "-h"],
        text=True,
    )
    assert "--no-login" in help_text
    assert "--recursive" in help_text
    assert "--max-depth" in help_text
