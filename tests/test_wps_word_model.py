from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from wps_word_model import (
    figure_captions_from_paras,
    heading_level,
    image_bytes_from_data_uri,
    is_figure_caption,
    norm_caption,
    paragraphs_to_markdown,
    strip_word_fields,
    write_figure_png,
)


def test_strip_word_fields_keeps_display_text():
    raw = (
        "\x13 HYPERLINK \\l _Toc1 \x14修订记录\t"
        "\x13 PAGEREF _Toc1 \\h \x143\x15\x15"
    )
    assert strip_word_fields(raw) == "修订记录 3"
    toc = '\x13TOC \\o "1-2" \\h \\u \x14\x13 HYPERLINK \\l _Toc \x14修订记录\t\x13 PAGEREF \\h \x143\x15\x15'
    assert strip_word_fields(toc) == "修订记录 3"


def test_heading_level():
    assert heading_level("标题") == 1
    assert heading_level("标题 1") == 1
    assert heading_level("标题 3") == 3
    assert heading_level("正文") is None
    assert heading_level("目录 1") is None


def test_paragraphs_to_markdown_headings_lists_tables():
    md = paragraphs_to_markdown(
        [
            {"text": "1. 文档概述", "style": "标题 1"},
            {"text": "本文档说明三中心架构。", "style": "正文"},
            {
                "text": "高可用性",
                "style": "正文",
                "list_id": 12,
                "list_level": 0,
            },
            {"text": "版本号", "style": "正文", "table": True},
            {"text": "修订人", "style": "正文", "table": True},
            {"text": "", "style": "正文", "table": True, "table_row": True},
            {"text": "V1.1", "style": "正文", "table": True},
            {"text": "郝川", "style": "正文", "table": True},
            {"text": "", "style": "正文", "table": True, "table_row": True},
            {"text": "2.1 设计原则", "style": "标题 2"},
        ]
    )
    assert "# 1. 文档概述" in md
    assert "本文档说明三中心架构。" in md
    assert "- 高可用性" in md
    assert "| 版本号 | 修订人 |" in md
    assert "| V1.1 | 郝川 |" in md
    assert "## 2.1 设计原则" in md
    assert "第 1 页" not in md


def test_figure_caption_and_image_insert():
    paras = [
        {"text": "\x01", "style": "正文"},
        {"text": "图1  文档中心多中心架构图", "style": "正文"},
        {"text": "图 2-1 既有三存储中心架构", "style": "正文"},
    ]
    caps = figure_captions_from_paras(paras)
    assert caps[0].startswith("图1")
    assert is_figure_caption(caps[0])
    assert norm_caption("图1  文档中心多中心架构图") == "图1文档中心多中心架构图"
    md = paragraphs_to_markdown(
        paras,
        figures={
            "图1文档中心多中心架构图": "方案_assets/fig_001.png",
        },
    )
    assert "![图1 文档中心多中心架构图](方案_assets/fig_001.png)" in md
    assert "图1 文档中心多中心架构图" in md
    assert md.count("fig_001.png") == 1


def test_loose_picture_inserts_at_placeholder():
    md = paragraphs_to_markdown(
        [
            {"text": "架构说明", "style": "正文"},
            {"text": "\x01", "style": "正文"},
            {"text": "下一段", "style": "正文"},
        ],
        loose_images=["方案_assets/pic_001.png"],
    )
    assert "架构说明" in md
    assert "![](方案_assets/pic_001.png)" in md
    assert md.index("pic_001.png") < md.index("下一段")


def test_loose_picture_skips_when_caption_already_captured():
    md = paragraphs_to_markdown(
        [
            {"text": "\x01", "style": "正文"},
            {"text": "图1 架构图", "style": "正文"},
        ],
        figures={"图1架构图": "方案_assets/fig_001.png"},
        loose_images=["方案_assets/pic_001.png"],
    )
    assert "![图1 架构图](方案_assets/fig_001.png)" in md
    assert "![](方案_assets/pic_001.png)" in md
    assert md.index("fig_001.png") < md.index("![](方案_assets/pic_001.png)")


def test_table_cell_picture():
    md = paragraphs_to_markdown(
        [
            {"text": "名称", "style": "正文", "table": True},
            {"text": "\x01", "style": "正文", "table": True},
            {"text": "", "style": "正文", "table": True, "table_row": True},
        ],
        loose_images=["方案_assets/pic_001.png"],
    )
    assert "![](方案_assets/pic_001.png)" in md
    assert "| 名称 | ![](方案_assets/pic_001.png) |" in md


def test_data_uri_figure_bytes(tmp_path):
    raw = b"\x89PNG\r\n\x1a\n" + b"x" * 900
    href = "data:image/png;base64," + __import__("base64").b64encode(raw).decode("ascii")
    decoded = image_bytes_from_data_uri(href)
    assert decoded == raw
    dest = tmp_path / "fig_001.png"
    assert write_figure_png(dest, decoded)
    assert dest.read_bytes() == raw
    assert image_bytes_from_data_uri("https://example.com/x.png") is None
