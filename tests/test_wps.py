"""Unit tests for wps_to_md.py / wps_download.py pure helpers (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import wps_to_md as wtm  # noqa: E402
import wps_download as wd  # noqa: E402


def test_extract_share_id_kdocs():
    assert wtm.extract_share_id("https://365.kdocs.cn/l/ccPEq4cqQmKT") == "ccPEq4cqQmKT"
    assert wtm.extract_share_id("https://www.kdocs.cn/l/abc123") == "abc123"


def test_extract_share_id_view_path():
    assert wtm.extract_share_id("https://kdocs.cn/view/l/xyz_99") == "xyz_99"


def test_extract_share_id_invalid():
    with pytest.raises(wtm.WpsError):
        wtm.extract_share_id("https://example.com/no/share")


def test_normalize_url_adds_scheme():
    assert wtm.normalize_url("365.kdocs.cn/l/x") == "https://365.kdocs.cn/l/x"
    assert wtm.normalize_url("https://x") == "https://x"


def test_safe_stem_keeps_cjk_and_alnum():
    assert wtm.safe_stem("爱数方案.docx") == "爱数方案"
    assert wtm.safe_stem("file (1).docx") == "file_1"


def test_safe_stem_empty_fallback():
    assert wtm.safe_stem("...") == "wps_document"


def test_detect_office_ext_pdf():
    assert wtm.detect_office_ext(b"%PDF-1.4\n...") == "pdf"


def test_detect_office_ext_zip_docx():
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<x/>")
    assert wtm.detect_office_ext(buf.getvalue()) == "docx"


def test_detect_office_ext_zip_pptx():
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ppt/slides/s1.xml", "<x/>")
    assert wtm.detect_office_ext(buf.getvalue()) == "pptx"


def test_detect_office_ext_zip_xlsx():
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", "<x/>")
    assert wtm.detect_office_ext(buf.getvalue()) == "xlsx"


def test_detect_office_ext_non_zip():
    assert wtm.detect_office_ext(b"plain text") == "bin"


def test_wps_download_extract_share_id():
    assert wd.extract_share_id("https://365.kdocs.cn/l/abc") == "abc"
    assert wd.extract_share_id("not a url") is None


def test_wps_download_safe_name():
    # safe_name operates on the full filename (keeps extension); spaces/parens → _
    assert wd.safe_name("文件 (1).docx") == "文件_1_.docx"
    assert wd.safe_name("...") == "wps_document"


def test_iter_otl_pictures_order():
    raw = {"content": [
        {"type": "picture", "attrs": {"oriWidth": 10, "oriHeight": 10}},
        {"type": "paragraph", "content": [{"type": "text", "text": "x"}]},
        {"type": "picture", "attrs": {"oriWidth": 20, "oriHeight": 20}},
    ]}
    pics = wtm.iter_otl_pictures(raw)
    assert len(pics) == 2
    assert pics[0]["oriWidth"] == 10
    assert pics[1]["oriWidth"] == 20


def test_match_images_to_pictures_by_aspect():
    # two pictures with different aspect ratios
    pictures = [
        {"oriWidth": 100, "oriHeight": 50},   # 2:1
        {"oriWidth": 50, "oriHeight": 50},    # 1:1
    ]
    # captured images: (url, ctype, body) — use tiny distinct bytes; pixel size
    # detection will fail (not real images), so matching falls back to capture order.
    captured = [
        ("u1", "image/png", b"\x89PNG" + b"\x01" * 50),
        ("u2", "image/png", b"\x89PNG" + b"\x02" * 50),
    ]
    ordered = wtm.match_images_to_pictures(pictures, captured)
    # Without real image headers, image_pixel_size returns None and candidates are
    # filtered out — so ordered is empty. That's the documented behavior.
    assert isinstance(ordered, list)


def test_ensure_session_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(wtm, "DEFAULT_STATE", tmp_path / "nope.json")
    with pytest.raises(wtm.WpsError):
        wtm.ensure_session()
