"""Unit tests for otl_to_md.py (WPS intelligent-doc JSON → Markdown)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import otl_to_md as otl  # noqa: E402


def _text_node(t: str) -> dict:
    return {"type": "text", "text": t}


def _doc(*children) -> dict:
    """Build a minimal OTL root matching real structure: {content: {type:doc, content:[...]}}."""
    return {"content": {"type": "doc", "content": list(children)}}


def _para(t: str, *, list_type: str = "") -> dict:
    attrs = {"listType": list_type} if list_type else {}
    return {"type": "paragraph", "attrs": attrs, "content": [_text_node(t)]}


def test_outline_title():
    raw = _doc({"type": "outline-title", "content": [_text_node("标题")]})
    md = otl.otl_to_markdown(raw)
    assert md.strip().startswith("# 标题")


def test_heading_levels():
    raw = _doc(
        {"type": "heading2", "attrs": {"level": 2}, "content": [_text_node("二级")]},
        {"type": "heading3", "content": [_text_node("三级")]},
    )
    md = otl.otl_to_markdown(raw)
    assert "## 二级" in md
    assert "### 三级" in md


def test_paragraph_bullet_list():
    raw = _doc(
        _para("第一", list_type="bullet"),
        _para("第二", list_type="bullet"),
    )
    md = otl.otl_to_markdown(raw)
    assert "- 第一" in md
    assert "- 第二" in md


def test_paragraph_ordered_list():
    raw = _doc(_para("第一", list_type="ordered"))
    md = otl.otl_to_markdown(raw)
    assert "1. 第一" in md


def test_picture_with_image_names():
    raw = _doc(
        {"type": "picture", "attrs": {"oriWidth": 100, "oriHeight": 50}},
        {"type": "picture", "attrs": {"oriWidth": 200, "oriHeight": 100}},
    )
    md = otl.otl_to_markdown(raw, image_names=["image_001.png", "image_002.png"], assets_rel="assets")
    assert "![image 1](assets/image_001.png)" in md
    assert "![image 2](assets/image_002.png)" in md


def test_picture_missing_image_placeholder():
    raw = _doc({"type": "picture", "attrs": {"imgID": "abc"}})
    md = otl.otl_to_markdown(raw)
    assert "missing picture 1" in md


def test_code_block_with_language():
    raw = _doc({"type": "code_block", "attrs": {"lang": "python"}, "content": [_text_node("print(1)")]})
    md = otl.otl_to_markdown(raw)
    assert "```python" in md
    assert "print(1)" in md
    assert md.count("```") == 2


def test_code_block_without_language():
    raw = _doc({"type": "code_block", "attrs": {}, "content": [_text_node("x = 1")]})
    md = otl.otl_to_markdown(raw)
    assert "```\nx = 1\n```" in md


def test_table_renders_markdown_table():
    cell = lambda txt: {"type": "outline-table-cell", "content": [
        {"type": "CellBlock", "attrs": {"type": "CellBlock"}, "content": [
            {"type": "sub_doc", "attrs": {}, "content": [_para(txt)]}
        ]}
    ]}
    row = lambda *cells: {"type": "outline-table-row", "content": list(cells)}
    raw = _doc(
        {"type": "outline-table", "attrs": {}, "content": [
            row(cell("A"), cell("B")),
            row(cell("1"), cell("2")),
        ]}
    )
    md = otl.otl_to_markdown(raw)
    assert "| A | B |" in md
    assert "| --- | --- |" in md
    assert "| 1 | 2 |" in md


def test_table_escapes_pipes_in_cells():
    cell = lambda txt: {"type": "outline-table-cell", "content": [
        {"type": "CellBlock", "attrs": {}, "content": [_para(txt)]}
    ]}
    raw = _doc(
        {"type": "outline-table", "content": [
            {"type": "outline-table-row", "content": [cell("a|b"), cell("c")]},
        ]}
    )
    md = otl.otl_to_markdown(raw)
    assert r"a\|b" in md


def test_horizontal_rule():
    raw = _doc({"type": "horizontal_rule"})
    md = otl.otl_to_markdown(raw)
    assert "---" in md


def test_blockquote():
    raw = _doc(
        {"type": "blockquote", "attrs": {}, "content": [_text_node("引用内容")]}
    )
    md = otl.otl_to_markdown(raw)
    assert "> 引用内容" in md


def test_emoji_inline():
    raw = _doc(
        {"type": "paragraph", "attrs": {}, "content": [
            {"type": "emoji", "attrs": {"emoji": "💡"}},
            _text_node(" 提示"),
        ]}
    )
    md = otl.otl_to_markdown(raw)
    assert "💡" in md


def test_source_note_header():
    raw = _doc(_para("正文"))
    md = otl.otl_to_markdown(raw, source_note="> 来源: https://example.com\n> 类型: 测试")
    assert md.startswith("> 来源: https://example.com")
    assert "正文" in md


def test_inline_marks_bold_italic_code_link():
    raw = _doc(
        {"type": "paragraph", "attrs": {}, "content": [
            {"type": "text", "text": "粗", "marks": [{"type": "bold"}]},
            {"type": "text", "text": "斜", "marks": [{"type": "italic"}]},
            {"type": "text", "text": "码", "marks": [{"type": "code"}]},
            {"type": "text", "text": "链", "marks": [{"type": "link", "attrs": {"href": "http://x"}}]},
        ]}
    )
    md = otl.otl_to_markdown(raw)
    assert "**粗**" in md
    assert "*斜*" in md
    assert "`码`" in md
    assert "[链](http://x)" in md


def test_convert_file_writes_output(tmp_path: Path):
    raw = _doc(
        {"type": "outline-title", "content": [_text_node("测试标题")]},
        _para("一段正文"),
    )
    import json
    src = tmp_path / "in.otl.json"
    src.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out.md"
    stats = otl.convert_file(src, out)
    assert out.is_file()
    assert "测试标题" in out.read_text(encoding="utf-8")
    assert stats["pictures_in_otl"] == 0
