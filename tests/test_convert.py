"""Unit tests for convert.py pure functions (no network, no browser)."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import convert as conv  # noqa: E402


def test_ext_for_mime_known():
    assert conv._ext_for_mime("jpeg") == "jpg"
    assert conv._ext_for_mime("png") == "png"
    assert conv._ext_for_mime("svg+xml") == "svg"
    assert conv._ext_for_mime("x-icon") == "ico"


def test_ext_for_mime_strips_params_and_case():
    assert conv._ext_for_mime("PNG; charset=utf-8") == "png"
    assert conv._ext_for_mime("JPEG") == "jpg"


def test_ext_for_mime_unknown_falls_back():
    assert conv._ext_for_mime("webp") == "webp"
    assert conv._ext_for_mime("x-foo") == "x-foo"


def test_extract_data_uris_replaces_markdown_image(tmp_path: Path):
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20).decode()
    md = f"![alt](data:image/png;base64,{png})"
    out, n = conv.extract_data_uris(md, tmp_path, "assets")
    assert n == 1
    assert "data:image" not in out
    assert "![alt](assets/image_001.png)" in out
    saved = tmp_path / "image_001.png"
    assert saved.is_file()
    assert saved.read_bytes().startswith(b"\x89PNG")


def test_extract_data_uris_handles_multiple(tmp_path: Path):
    a = base64.b64encode(b"AAAA").decode()
    b = base64.b64encode(b"BBBB").decode()
    md = f"![](data:image/png;base64,{a})\n![](data:image/jpeg;base64,{b})"
    out, n = conv.extract_data_uris(md, tmp_path, "assets")
    assert n == 2
    assert "image_001.png" in out
    assert "image_002.jpg" in out


def test_extract_data_uris_no_uris(tmp_path: Path):
    md = "plain text, no images"
    out, n = conv.extract_data_uris(md, tmp_path, "assets")
    assert n == 0
    assert out == md


def test_sort_ocr_lines_top_to_bottom():
    # boxes: [x0,y0,x1,y0,x1,y1,x0,y1]
    items = [
        [[[10, 100], [50, 100], [50, 120], [10, 120]], "bottom row", 0.9],
        [[[10, 10], [50, 10], [50, 30], [10, 30]], "top row", 0.9],
    ]
    lines = conv._sort_ocr_lines(items)
    assert lines == ["top row", "bottom row"]


def test_sort_ocr_lines_left_to_right_same_row():
    items = [
        [[[100, 10], [150, 10], [150, 30], [100, 30]], "right", 0.9],
        [[[10, 10], [50, 10], [50, 30], [10, 30]], "left", 0.9],
    ]
    lines = conv._sort_ocr_lines(items)
    assert lines == ["left", "right"]


def test_sort_ocr_lines_skips_empty_text():
    items = [
        [[[10, 10], [50, 10], [50, 30], [10, 30]], "", 0.9],
        [[[10, 40], [50, 40], [50, 60], [10, 60]], "real", 0.9],
    ]
    lines = conv._sort_ocr_lines(items)
    assert lines == ["real"]


def test_sort_ocr_lines_handles_malformed():
    items = [
        None,
        [None, "text"],
        [[[10, 10], [50, 10], [50, 30], [10, 30]], "ok", 0.9],
    ]
    lines = conv._sort_ocr_lines(items)
    assert lines == ["ok"]


def test_ocr_image_text_returns_tuple_and_engine_name(tmp_path: Path):
    # 1x1 png; no OCR engine is expected to read it, but the call shape must hold.
    png = tmp_path / "tiny.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 60)
    text, engine = conv.ocr_image_text(png)
    assert isinstance(text, str)
    assert isinstance(engine, str)
    assert engine in {"rapidocr", "tesseract:chi_sim+eng", "tesseract:chi_sim",
                      "tesseract:eng", "none"}


def test_image_suffixes_includes_common():
    for s in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"):
        assert s in conv.IMAGE_SUFFIXES


def test_inject_pdf_images_empty():
    assert conv.inject_pdf_images("body", []) == "body"


def test_inject_pdf_images_appends(tmp_path: Path):
    out = conv.inject_pdf_images("body", [(1, ["assets/p1.png"]), (3, ["assets/p3a.png"])])
    assert "Page 1 images" in out
    assert "Page 3 images" in out
    assert "![Page 1 image 1](assets/p1.png)" in out


def test_build_scan_markdown_structure():
    scan = [(1, "assets/p1.png", "some text", "rapidocr")]
    md = conv.build_scan_markdown("Title", scan)
    assert md.startswith("# Title")
    assert "## Page 1" in md
    assert "![Page 1](assets/p1.png)" in md
    assert "some text" in md
    assert "rapidocr" in md


def test_build_scan_markdown_empty_ocr():
    scan = [(2, "assets/p2.png", "", "none")]
    md = conv.build_scan_markdown("T", scan)
    assert "## Page 2" in md
    assert "OCR 文本" not in md  # no per-page OCR block when empty


def test_inject_pdf_scan_ocr_appends():
    scan = [(5, "assets/p5.png", "ocr text", "rapidocr")]
    out = conv.inject_pdf_scan_ocr("body", scan)
    assert "Page 5 (scanned)" in out
    assert "ocr text" in out


def test_inject_pdf_scan_ocr_empty():
    assert conv.inject_pdf_scan_ocr("body", []) == "body"
