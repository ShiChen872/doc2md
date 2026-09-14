"""Unit tests for otl_to_md.py (WPS intelligent-doc JSON → Markdown)."""

from __future__ import annotations

import json
import re
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


def test_ordered_headings_restart_under_new_h1():
    h = lambda level, lid, text: {
        "type": "heading",
        "attrs": {"level": level, "listType": "ordered", "listId": lid},
        "content": [_text_node(text)],
    }
    raw = _doc(
        h(1, "h1", "落地方法论"),
        h(2, "h2", "怎么找到的这个场景"),
        h(2, "h2", "需要哪些人来做"),
        h(1, "h1", "下一章"),
        h(2, "h2", "第一节"),
    )
    md = otl.otl_to_markdown(raw)
    assert "# 1. 落地方法论" in md
    assert "## 1. 怎么找到的这个场景" in md
    assert "## 2. 需要哪些人来做" in md
    assert "# 2. 下一章" in md
    assert "## 1. 第一节" in md


def test_blockquote_hard_breaks_become_lines():
    raw = _doc(
        {
            "type": "blockquote",
            "content": [
                {"type": "text", "text": "①先"},
                {"type": "text", "text": "找到客户侧"},
                {
                    "type": "text",
                    "text": "有明确「AI提效指标」的部门",
                    "marks": [{"type": "bold"}],
                },
                {"type": "hard_break"},
                {"type": "text", "text": "②了解这个部门的痛点场景"},
                {"type": "hard_break"},
                {"type": "text", "text": "③按以下维度判断"},
            ],
        }
    )
    md = otl.otl_to_markdown(raw)
    assert "> ①先找到客户侧**有明确「AI提效指标」的部门**" in md
    assert "> ②了解这个部门的痛点场景" in md
    assert "> ③按以下维度判断" in md
    assert "①先找到" in md
    assert "①先 找到" not in md


def test_paragraph_bullet_list():
    raw = _doc(
        _para("第一", list_type="bullet"),
        _para("第二", list_type="bullet"),
    )
    md = otl.otl_to_markdown(raw)
    assert "- 第一" in md
    assert "- 第二" in md


def test_paragraph_ordered_list():
    raw = _doc(
        _para("第一", list_type="ordered"),
        _para("第二", list_type="ordered"),
        {"type": "heading2", "attrs": {"level": 2}, "content": [_text_node("下一节")]},
        _para("重新开始", list_type="ordered"),
    )
    md = otl.otl_to_markdown(raw)
    assert "1. 第一" in md
    assert "2. 第二" in md
    assert "1. 重新开始" in md


def test_list_then_paragraph_has_blank_line():
    raw = _doc(
        _para("合格回答", list_type="bullet"),
        {
            "type": "paragraph",
            "content": [
                {"type": "emoji", "attrs": {"emoji": "📖"}},
                {"type": "text", "text": " 本章配套图解", "marks": [{"type": "bold"}]},
            ],
        },
    )
    md = otl.otl_to_markdown(raw)
    assert "- 合格回答\n\n📖 **" in md


def _circle(kind: str, *children: dict, extra: dict | None = None) -> dict:
    attrs: dict = {"type": kind}
    if extra:
        attrs.update(extra)
    return {"type": "circle_object", "attrs": attrs, "content": list(children)}


def test_adjacent_bold_runs_merge():
    raw = _doc(
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "已同客户签订", "marks": [{"type": "bold"}]},
                {"type": "text", "text": "保密协议", "marks": [{"type": "bold"}]},
                {"type": "text", "text": "，请勿外发", "marks": [{"type": "bold"}]},
            ],
        }
    )
    md = otl.otl_to_markdown(raw)
    assert md.count("**") == 2
    assert "**已同客户签订 保密协议，请勿外发**" in md


def test_bold_code_badge_does_not_leak_markers():
    raw = _doc(
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "50+条", "marks": [{"type": "bold"}]},
                {
                    "type": "text",
                    "text": "支持后续新增",
                    "marks": [{"type": "bold"}, {"type": "code"}],
                },
            ],
        }
    )
    md = otl.otl_to_markdown(raw)
    assert "`" not in md
    assert "**50+条 支持后续新增**" in md


def test_circle_column_becomes_table():
    raw = _doc(
        _circle(
            "CircleColumn",
            _circle("CircleColumnItem", _circle("CircleObjectTile", _para("规则覆盖率")), _circle("CircleObjectTile", _para("70%"))),
            _circle(
                "CircleColumnItem",
                _circle("CircleObjectTile", _para("单份制度审核周期")),
                _circle("CircleObjectTile", _para("3个月→1个月")),
            ),
            _circle(
                "CircleColumnItem",
                _circle("CircleObjectTile", _para("沉淀审核规则")),
                _circle("CircleObjectTile", _para("50+条")),
            ),
        )
    )
    md = otl.otl_to_markdown(raw)
    assert "| 规则覆盖率 | 单份制度审核周期 | 沉淀审核规则 |" in md
    assert "| 70% | 3个月→1个月 | 50+条 |" in md
    assert md.find("规则覆盖率") < md.find("70%")


def test_emoji_then_bold_has_space():
    raw = _doc(
        {
            "type": "paragraph",
            "content": [
                {"type": "emoji", "attrs": {"emoji": "🎬"}},
                {"type": "text", "text": " 先看一个故事", "marks": [{"type": "bold"}]},
            ],
        }
    )
    md = otl.otl_to_markdown(raw)
    assert "🎬 **" in md
    assert "🎬**" not in md


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


def test_table_cell_merges_adjacent_bold():
    cell = {
        "type": "outline-table-cell",
        "content": [
            {
                "type": "CellBlock",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "从这里切入", "marks": [{"type": "bold"}]},
                            {"type": "text", "text": "，", "marks": [{"type": "bold"}]},
                            {"type": "text", "text": "缩短轮次", "marks": [{"type": "bold"}]},
                        ],
                    }
                ],
            }
        ],
    }
    raw = _doc(
        {
            "type": "outline-table",
            "content": [{"type": "outline-table-row", "content": [cell]}],
        }
    )
    md = otl.otl_to_markdown(raw)
    assert "**从这里切入，缩短轮次**" in md
    assert "**，**" not in md


def test_wps_document_card_becomes_link():
    raw = _doc(
        _para("相关案例："),
        {
            "type": "WPSDocument",
            "attrs": {
                "viewType": "titleView",
                "wpsDocumentId": "517223200561",
                "wpsDocumentLink": "https://365.kdocs.cn/l/crbp7aGFHPwr?from=koa",
                "wpsDocumentName": "民企案例丨长江存储：IM是半导体的核心业务系统？.otl",
                "wpsDocumentType": "otl",
            },
        },
    )
    md = otl.otl_to_markdown(raw)
    assert "相关案例：" in md
    assert "<!-- WPS nested document (otl) -->" in md
    assert (
        "[民企案例丨长江存储：IM是半导体的核心业务系统？.otl]"
        "(https://365.kdocs.cn/l/crbp7aGFHPwr?from=koa)"
    ) in md
    pptx = otl.otl_to_markdown(
        _doc(
            {
                "type": "WPSDocument",
                "attrs": {
                    "wpsDocumentLink": "https://365.kdocs.cn/l/cuI2GFFvd1sr",
                    "wpsDocumentName": "架构.pptx",
                    "wpsDocumentType": "pptx",
                },
            }
        )
    )
    assert "<!-- WPS nested document (pptx) -->" in pptx
    assert "[架构.pptx](https://365.kdocs.cn/l/cuI2GFFvd1sr)" in pptx
    named = otl.otl_to_markdown(
        _doc({"type": "WPSDocument", "attrs": {"wpsDocumentName": "仅标题.otl"}})
    )
    assert "仅标题.otl" in named
    assert "](" not in named
    empty = otl.otl_to_markdown(_doc({"type": "WPSDocument", "attrs": {}}))
    assert "nested document" not in empty


def test_wps_document_card_inline_in_list_paragraph():
    raw = _doc(
        {
            "type": "paragraph",
            "attrs": {"listType": "bullet"},
            "content": [
                {"type": "text", "text": "长江存储一期案例", "marks": [{"type": "bold"}]},
                {"type": "text", "text": "："},
                {
                    "type": "WPSDocument",
                    "attrs": {
                        "wpsDocumentLink": "https://365.kdocs.cn/l/crbp7aGFHPwr?from=koa",
                        "wpsDocumentName": "民企案例丨长江存储：IM是半导体的核心业务系统？.otl",
                        "wpsDocumentType": "otl",
                    },
                },
            ],
        }
    )
    md = otl.otl_to_markdown(raw)
    assert md.strip().startswith("- **长江存储一期案例**：")
    assert "： [民企案例丨长江存储：IM是半导体的核心业务系统？.otl]" in md
    assert "(https://365.kdocs.cn/l/crbp7aGFHPwr?from=koa)" in md


def test_wps_document_card_in_table_cell():
    cell = {
        "type": "outline-table-cell",
        "content": [
            {
                "type": "WPSDocument",
                "attrs": {
                    "wpsDocumentName": "子文档.otl",
                    "wpsDocumentLink": "https://365.kdocs.cn/l/abc",
                    "wpsDocumentType": "otl",
                },
            }
        ],
    }
    raw = _doc(
        {
            "type": "outline-table",
            "content": [{"type": "outline-table-row", "content": [cell]}],
        }
    )
    md = otl.otl_to_markdown(raw)
    assert "[子文档.otl](https://365.kdocs.cn/l/abc)" in md


def test_iter_wps_document_cards_unique_and_skips_empty():
    raw = _doc(
        {
            "type": "WPSDocument",
            "attrs": {
                "wpsDocumentName": "一.otl",
                "wpsDocumentLink": "https://www.kdocs.cn/l/aaa111?from=koa",
                "wpsDocumentType": "otl",
            },
        },
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "WPSDocument",
                    "attrs": {
                        "wpsDocumentName": "一（重复）.otl",
                        "wpsDocumentLink": "https://365.kdocs.cn/l/aaa111",
                        "wpsDocumentType": "otl",
                    },
                }
            ],
        },
        {
            "type": "outline-table",
            "content": [
                {
                    "type": "outline-table-row",
                    "content": [
                        {
                            "type": "outline-table-cell",
                            "content": [
                                {
                                    "type": "WPSDocument",
                                    "attrs": {
                                        "wpsDocumentName": "表内.pptx",
                                        "wpsDocumentLink": "https://365.kdocs.cn/l/bbb222",
                                        "wpsDocumentType": "pptx",
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        },
        {"type": "WPSDocument", "attrs": {}},
        {
            "type": "WPSDocument",
            "attrs": {"wpsDocumentName": "无链接.otl"},
        },
    )
    cards = otl.iter_wps_document_cards(raw)
    hrefs = [c["href"] for c in cards]
    names = [c["name"] for c in cards]
    assert hrefs.count("https://www.kdocs.cn/l/aaa111?from=koa") == 1
    assert "https://365.kdocs.cn/l/bbb222" in hrefs
    assert "无链接.otl" in names
    assert all(c["name"] or c["href"] for c in cards)
    assert len(cards) == 3


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
    src = tmp_path / "in.otl.json"
    src.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out.md"
    stats = otl.convert_file(src, out)
    assert out.is_file()
    assert "测试标题" in out.read_text(encoding="utf-8")
    assert stats["pictures_in_otl"] == 0


def test_image_map_by_source_key_not_emit_index():
    """Files keyed by sourceKey must not shift when earlier pictures are in a table."""
    cell_pic = {
        "type": "outline-table-cell",
        "content": [{
            "type": "picture",
            "attrs": {"sourceKey": "SK_TABLE", "imgID": "ID_TABLE"},
        }],
    }
    row = {"type": "outline-table-row", "content": [cell_pic]}
    raw = _doc(
        {"type": "outline-table", "content": [row]},
        {"type": "picture", "attrs": {"sourceKey": "SK_AFTER", "imgID": "ID_AFTER"}},
    )
    image_map = {"SK_TABLE": "image_001.png", "SK_AFTER": "image_002.png"}
    md = otl.otl_to_markdown(raw, image_map=image_map, assets_rel="assets")
    assert "assets/image_001.png" in md
    assert "![image 2](assets/image_002.png)" in md


def test_table_cell_includes_picture():
    cell = {
        "type": "outline-table-cell",
        "content": [
            {"type": "paragraph", "attrs": {}, "content": [_text_node("说明")]},
            {"type": "picture", "attrs": {"sourceKey": "SK1", "imgID": "ID1"}},
        ],
    }
    raw = _doc({
        "type": "outline-table",
        "content": [{"type": "outline-table-row", "content": [cell]}],
    })
    md = otl.otl_to_markdown(
        raw, image_map={"SK1": "image_001.png"}, assets_rel="assets"
    )
    assert "| " in md
    assert "说明" in md
    assert "assets/image_001.png" in md


def test_build_image_map_from_files(tmp_path: Path):
    raw = _doc(
        {"type": "picture", "attrs": {"sourceKey": "A", "imgID": "IA"}},
        {"type": "picture", "attrs": {"sourceKey": "B", "imgID": "IB"}},
    )
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    a.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    b.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x01" * 8)
    assets = tmp_path / "assets"
    amap, names = otl.build_image_map_from_files(raw, [a, b], assets)
    assert amap["A"].startswith("image_")
    assert amap["B"].startswith("image_")
    assert amap["IA"] == amap["A"]
    assert names[0] and names[1]
    assert (assets / names[0]).is_file()


def test_convert_file_key_map_survives_table_skip(tmp_path: Path):
    cell_pic = {
        "type": "outline-table-cell",
        "content": [{"type": "picture", "attrs": {"sourceKey": "SK_T", "imgID": "ID_T"}}],
    }
    raw = _doc(
        {"type": "outline-table", "content": [
            {"type": "outline-table-row", "content": [cell_pic]}
        ]},
        {"type": "picture", "attrs": {"sourceKey": "SK_X", "imgID": "ID_X"}},
    )
    src = tmp_path / "in.otl.json"
    src.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    t = tmp_path / "t.png"
    x = tmp_path / "x.png"
    t.write_bytes(b"\x89PNG\r\n\x1a\nTTTT")
    x.write_bytes(b"\x89PNG\r\n\x1a\nXXXX")
    out = tmp_path / "out.md"
    assets = tmp_path / "out_assets"
    otl.convert_file(src, out, assets_dir=assets, image_files=[t, x])
    md = out.read_text(encoding="utf-8")
    assert "image_002" in md
    assert md.count("image_001") >= 1
    assert (assets / "image_002.png").read_bytes().endswith(b"XXXX")
    m = re.search(r"!\[image 2\]\(([^)]+)\)", md)
    assert m and m.group(1).endswith("image_002.png")
