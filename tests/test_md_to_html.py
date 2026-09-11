"""Unit tests for md_to_html.py sidecar (no browser)."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import md_to_html as mth  # noqa: E402


def test_default_html_output(tmp_path: Path):
    md = tmp_path / "notes.md"
    assert mth.default_html_output(md) == tmp_path / "notes.html"


def test_build_sidecar_html_keeps_relative_images_and_toc():
    md = (
        "> 来源: https://365.kdocs.cn/l/clGAK7peRoRk\n"
        "> 类型: WPS 智能文档 (.otl)\n\n"
        "# 应知应会手册\n\n"
        "## 怎么用这本手册\n\n"
        "正文\n\n"
        "![图](out_assets/image_001.png)\n\n"
        "## 第一章\n\n"
        "章节\n"
    )
    html = mth.build_sidecar_html(md, fallback_title="fallback")
    assert "<!DOCTYPE html>" in html
    assert "<title>应知应会手册</title>" in html
    assert 'src="out_assets/image_001.png"' in html
    assert '<div class="toc">' in html
    assert "怎么用这本手册" in html
    assert "sidecar-note" in html
    assert "<script" not in html.lower()


def test_build_sidecar_html_skips_toc_for_preview_screenshots():
    md = (
        "> 类型: WPS PDF 分享（网页预览分页截图 + OCR）\n\n"
        "# 演示\n\n"
        "## 第 1 页\n\n"
        "![](page_001.png)\n\n"
        "## 第 2 页\n\n"
        "![](page_002.png)\n"
    )
    html = mth.build_sidecar_html(md)
    assert '<div class="toc">' not in html
    assert 'src="page_001.png"' in html


def test_write_sidecar_html(tmp_path: Path):
    md = tmp_path / "out.md"
    md.write_text("# 标题\n\n## 一\n\na\n\n## 二\n\nb\n", encoding="utf-8")
    dest = mth.write_sidecar_html(md)
    assert dest == tmp_path / "out.html"
    text = dest.read_text(encoding="utf-8")
    assert "<title>标题</title>" in text
    assert dest.is_file()
