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
        "> 客户说AI，你听得懂\n\n"
        "## 怎么用这本手册\n\n"
        "正文\n\n"
        "![图](out_assets/image_001.png)\n\n"
        "## 第一章｜任务\n\n"
        "章节\n"
    )
    html = mth.build_sidecar_html(md, fallback_title="fallback")
    assert "<!DOCTYPE html>" in html
    assert "<title>应知应会手册</title>" in html
    assert 'src="out_assets/image_001.png"' in html
    assert "data:image/" not in html
    assert '<div class="toc">' in html
    assert "怎么用这本手册" in html
    assert "sidecar-note" in html
    assert "<script" not in html.lower()
    assert 'class="hero"' in html
    assert "WPS 智能文档" in html
    assert "客户说AI，你听得懂" in html
    hero_html = html.split('<div class="hero">', 1)[1].split('<div class="wrap">', 1)[0]
    assert "来源:" not in hero_html
    assert "来源: https://365.kdocs.cn" not in html
    assert html.count("<h1>") == 1
    assert "doc-img" in html
    assert 'class="deck-page"' not in html
    assert "演示文稿" not in html


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
    assert 'class="hero deck"' in html
    assert "deck-page" in html
    assert "2 页讲稿" in html


def test_write_sidecar_html(tmp_path: Path):
    md = tmp_path / "out.md"
    md.write_text("# 标题\n\n## 一\n\na\n\n## 二\n\nb\n", encoding="utf-8")
    dest = mth.write_sidecar_html(md)
    assert dest == tmp_path / "out.html"
    text = dest.read_text(encoding="utf-8")
    assert "<title>标题</title>" in text
    assert dest.is_file()


def test_hero_kicker_from_chapter_headings():
    headings = [
        (1, "手册"),
        (2, "怎么用这本手册"),
        (2, "第一章｜任务"),
        (2, "第二章｜知识"),
        (2, "毕业篇｜背诵"),
        (2, "附录A｜名词"),
        (2, "附录B｜六问"),
        (2, "附录C｜验收"),
    ]
    assert mth.hero_kicker(headings) == "二章正文 · 毕业背诵 · 附录A/B/C"


def test_decorate_callouts_wraps_emoji_sections():
    html = (
        "<h2>第一章</h2>\n"
        "<p>🎬<strong> 先看一个故事</strong></p>\n"
        "<p>老板只说写个方案。</p>\n"
        "<p>📗<strong> 必背正文</strong></p>\n"
        "<p>Prompt 是任务。</p>\n"
        "<p><img src='out_assets/image_003.png'/></p>\n"
    )
    out = mth.decorate_callouts(html)
    assert 'class="story"' in out
    assert 'class="canon"' in out
    assert "老板只说写个方案。" in out.split('class="story"')[1].split("</div>")[0]
    assert "<img" in out
    assert "image_003.png" in out.split('class="canon"')[1].split("<img")[1]


def test_lead_quote_skips_converter_metadata():
    md = (
        "> 来源: https://example.com/x\n"
        "> 类型: WPS 智能文档 (.otl)\n"
        "> 说明: 正文由 open/otl JSON 解析\n\n"
        "# 标题\n\n"
        "> 客户说AI，你听得懂；客户问原理，你讲得清。\n"
    )
    assert mth.lead_quote(md) == "客户说AI，你听得懂；客户问原理，你讲得清。"
    assert mth.type_label(md) == "WPS 智能文档"


def test_is_deck_markdown_pages_not_chapters():
    assert mth.is_page_heading_text("第一页")
    assert mth.is_page_heading_text("第 2 页")
    assert not mth.is_page_heading_text("第一章｜任务")
    assert mth.is_deck_markdown(
        "> **Note:** PPTX is exported as per-page speaker notes\n",
        [(2, "第一页")],
    )
    assert mth.is_deck_markdown(
        "# 课\n\n## 第一页\n\na\n\n## 第二页\n\nb\n",
        [(1, "课"), (2, "第一页"), (2, "第二页")],
    )
    assert not mth.is_deck_markdown(
        "# 手册\n\n## 怎么用这本手册\n\n## 第一章｜任务\n",
        [(1, "手册"), (2, "怎么用这本手册"), (2, "第一章｜任务")],
    )


def test_deck_html_cards_put_image_above_notes():
    md = (
        "> **Note:** PPTX is exported as per-page speaker notes + full-slide screenshots "
        "(via office2pdf; not individual icons).\n\n"
        "## 第一页\n\n"
        "1. 开场：把合同预审讲给客户听\n\n"
        "![第一页](deck_assets/slide_001.png)\n\n"
        "## 第二页\n\n"
        "四段结构\n\n"
        "![第二页](deck_assets/slide_002.png)\n"
    )
    html = mth.build_sidecar_html(md, fallback_title="合同预审场景解析_Comate9月必修课")
    assert "PPTX is exported" not in html
    assert '<div class="toc">' not in html
    assert html.count('class="deck-page"') == 2
    assert "2 页讲稿" in html
    assert "演示文稿" in html
    assert 'src="deck_assets/slide_001.png"' in html
    assert "data:image/" not in html
    first = html.split("第二页")[0]
    assert first.index("slide_001.png") < first.index("开场")
    assert "deck-notes" in html
