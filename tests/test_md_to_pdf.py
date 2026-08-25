"""Unit tests for md_to_pdf.py HTML assembly (no Chrome required)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import md_to_pdf as mtp  # noqa: E402


def test_default_pdf_output(tmp_path: Path):
    md = tmp_path / "notes.md"
    assert mtp.default_pdf_output(md) == tmp_path / "notes.pdf"


def test_strip_html_comments():
    text = "hello\n<!-- download: original file download denied -->\nworld"
    assert "download" not in mtp.strip_html_comments(text)
    assert "hello" in mtp.strip_html_comments(text)


def test_degrade_video_tags():
    md = (
        '本地预览:\n\n'
        '<video src="演示_assets/preview.mp4" controls preload="metadata" '
        'width="100%"></video>\n'
    )
    out = mtp.degrade_video_tags(md)
    assert "<video" not in out
    assert "preview.mp4" in out
    assert "PDF 无法内嵌播放" in out
    assert "video-fallback" in out


def test_degrade_iframe_tags():
    md = (
        '<iframe src="https://example.com/embed" width="100%" height="450">'
        "</iframe>\n\n[打开视频](https://example.com/embed)\n"
    )
    out = mtp.degrade_iframe_tags(md)
    assert "<iframe" not in out
    assert "https://example.com/embed" in out
    assert "打开嵌入内容" in out


def test_is_pdf_preview_markdown():
    assert mtp.is_pdf_preview_markdown(
        "> 类型: WPS PDF 分享（网页预览分页截图 + OCR）\n"
    )
    assert not mtp.is_pdf_preview_markdown("# 普通文档\n")


def test_demote_pdf_preview_ocr():
    md = (
        "> 类型: WPS PDF 分享（网页预览分页截图 + OCR）\n\n"
        "# 标题\n\n"
        "## 第 1 页\n\n"
        "![](doc_assets/page_001.png)\n\n"
        "封面文字\n第二行 OCR\n\n"
        "## 第 2 页\n\n"
        "![](doc_assets/page_002.png)\n"
    )
    dropped = mtp.demote_pdf_preview_ocr(md)
    assert "![](doc_assets/page_001.png)" in dropped
    assert "封面文字" not in dropped
    assert "ocr-aux" not in dropped
    kept = mtp.demote_pdf_preview_ocr(md, keep_ocr=True)
    assert 'class="ocr-aux"' in kept
    assert "封面文字" in kept
    assert kept.index("page_001.png") < kept.index("ocr-aux")
    plain = "# Hi\n\n## 第 1 页\n\n![](a.png)\n\ntext\n"
    assert mtp.demote_pdf_preview_ocr(plain) == plain


def test_resolve_local_url(tmp_path: Path):
    assets = tmp_path / "note_assets"
    assets.mkdir()
    img = assets / "page_001.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    uri = mtp.resolve_local_url("note_assets/page_001.png", tmp_path)
    assert uri is not None
    assert uri.startswith("file:")
    assert img.name in uri
    assert mtp.resolve_local_url("https://example.com/a.png", tmp_path) is None
    assert mtp.resolve_local_url("note_assets/missing.png", tmp_path) is None


def test_rewrite_local_urls_in_html_and_markdown(tmp_path: Path):
    assets = tmp_path / "note_assets"
    assets.mkdir()
    img = assets / "cover.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 12)
    html = '<p><img src="note_assets/cover.jpg" alt="封面"/></p>'
    out = mtp.rewrite_local_urls(html, tmp_path)
    assert "file:" in out
    assert "cover.jpg" in out
    md = "![封面](note_assets/cover.jpg)"
    md_out = mtp.rewrite_local_urls(md, tmp_path)
    assert md_out.startswith("![封面](file:")


def test_build_print_html_preview_and_video(tmp_path: Path):
    assets = tmp_path / "demo_assets"
    assets.mkdir()
    (assets / "page_001.png").write_bytes(b"\x89PNG\r\n\x1a\nxxxx")
    (assets / "preview.mp4").write_bytes(b"\x00" * 64)
    md_path = tmp_path / "demo.md"
    md_path.write_text(
        "> 类型: WPS PDF 分享（网页预览分页截图 + OCR）\n\n"
        "# 演示\n\n"
        "## 第 1 页\n\n"
        "![](demo_assets/page_001.png)\n\n"
        "OCR 一行\n\n"
        '<video src="demo_assets/preview.mp4" controls></video>\n',
        encoding="utf-8",
    )
    html = mtp.build_print_html(md_path.read_text(encoding="utf-8"), md_path)
    assert "<!DOCTYPE html>" in html
    assert "PingFang SC" in html
    assert "OCR 一行" not in html
    assert 'class="ocr-aux"' not in html
    assert "<video" not in html
    assert "preview.mp4" in html
    assert "file:" in html
    assert "page_001.png" in html
    html_ocr = mtp.build_print_html(
        md_path.read_text(encoding="utf-8"), md_path, keep_ocr=True
    )
    assert "ocr-aux" in html_ocr
    assert "OCR 一行" in html_ocr


def test_markdown_file_to_pdf_rejects_missing(tmp_path: Path):
    with pytest.raises(mtp.MdPdfError, match="not found"):
        mtp.markdown_file_to_pdf(tmp_path / "nope.md")


def test_markdown_file_to_pdf_rejects_non_md(tmp_path: Path):
    f = tmp_path / "notes.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(mtp.MdPdfError, match="Expected a .md file"):
        mtp.markdown_file_to_pdf(f)
