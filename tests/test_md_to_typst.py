"""Unit tests for Markdown → Typst conversion (no compiler required)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import md_to_pdf as mtp  # noqa: E402
import md_to_typst as mtt  # noqa: E402


def test_escape_and_inline():
    assert r"\#" in mtt.escape_text("use #set")
    out = mtt.convert_inline("见 **良率** 与 [链接](https://example.com)")
    assert "*良率*" in out
    assert '#link("https://example.com")' in out
    img = mtt.convert_inline("![图](foo_assets/a.png)")
    assert "foo_assets/a.png" in img
    assert "#image(" in img


def test_markdown_to_typst_headings_table_list():
    md = (
        "# 标题\n\n"
        "引言 **强调**。\n\n"
        "## 背景\n\n"
        "| A | B |\n"
        "| --- | --- |\n"
        "| 1 | ![x](doc_assets/p.png) |\n\n"
        "- 一项\n"
        "- 二项\n\n"
        "```python\nprint(1)\n```\n"
    )
    body = mtt.markdown_to_typst(md)
    assert "= 标题" in body
    assert "== 背景" in body
    assert "table(" in body
    assert "doc_assets/p.png" in body
    assert "- 一项" in body
    assert "```python" in body
    assert "print(1)" in body


def test_wrap_typst_brand_has_outline_and_navy():
    body = mtt.markdown_to_typst("# 报告\n\n## 一\n\nx\n\n## 二\n\ny\n")
    src = mtt.wrap_typst_document(
        body, title="报告", theme="brand", toc=True, pdf_preview=False
    )
    assert "163A5F" in src
    assert "目录" in src
    assert "#outline(" in src
    assert src.index("= 报告") < src.index("#outline(")
    assert "PingFang SC" in src
    preview = mtt.wrap_typst_document(
        body, title="演示", theme="brand", toc=True, pdf_preview=True
    )
    assert "#outline(" not in preview


def test_pdf_preview_skips_page_headings():
    md = (
        "# 演示\n\n"
        "## 第 1 页\n\n"
        "![](a_assets/page_001.png)\n\n"
        "## 第 2 页\n\n"
        "![](a_assets/page_002.png)\n"
    )
    body = mtt.markdown_to_typst(md, pdf_preview=True)
    assert "= 演示" not in body
    assert "第 1 页" not in body
    assert "pagebreak" in body
    assert "page_001.png" in body
    assert body.index("page_001.png") < body.index("pagebreak")


def test_theme_tokens_reject_unknown():
    with pytest.raises(mtt.TypstError, match="Unknown theme"):
        mtt.theme_tokens("neon")


def test_video_fallback_becomes_link():
    html = (
        '<p class="video-fallback">'
        '<a href="demo_assets/preview.mp4">preview.mp4</a>'
        "（PDF 无法内嵌播放）</p>\n"
    )
    out = mtt.markdown_to_typst(html)
    assert "preview.mp4" in out
    assert "#link(" in out
    assert "<video" not in out
    assert "video-fallback" not in out


def test_chrome_brand_css(tmp_path: Path):
    md_path = tmp_path / "note.md"
    md_path.write_text("# 报告\n\n## 背景\n\n文字\n\n## 结论\n\n完\n", encoding="utf-8")
    html = mtp.build_print_html(
        md_path.read_text(encoding="utf-8"), md_path, theme="brand"
    )
    assert "163A5F" in html
    assert "2B6CB0" in html
    default = mtp.build_print_html(md_path.read_text(encoding="utf-8"), md_path)
    assert "PingFang SC" in default


def test_unknown_engine(tmp_path: Path):
    md = tmp_path / "n.md"
    md.write_text("# T\n", encoding="utf-8")
    with pytest.raises(mtp.MdPdfError, match="Unknown engine"):
        mtp.markdown_file_to_pdf(md, engine="latex")
