"""Unit tests for feishu_to_md.py pure helpers (no network / browser)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import feishu_to_md as ftm  # noqa: E402


def test_parse_wiki_url():
    info = ftm.parse_feishu_url(
        "https://waytoagi.feishu.cn/wiki/DyQPwr5Uui6n0HktnoxcYDrwngd"
    )
    assert info["kind"] == "wiki"
    assert info["token"] == "DyQPwr5Uui6n0HktnoxcYDrwngd"
    assert info["host"] == "waytoagi.feishu.cn"


def test_parse_docx_url():
    info = ftm.parse_feishu_url("https://my.feishu.cn/docx/ABC123xyz")
    assert info["kind"] == "docx"
    assert info["token"] == "ABC123xyz"


def test_parse_docs_legacy():
    info = ftm.parse_feishu_url("https://foo.feishu.cn/docs/doctoken99")
    assert info["kind"] == "docs"
    assert info["token"] == "doctoken99"


def test_parse_larksuite():
    info = ftm.parse_feishu_url("https://acme.larksuite.com/wiki/WIKI_TOKEN_1")
    assert info["kind"] == "wiki"
    assert "larksuite.com" in info["host"]


def test_parse_invalid_host():
    with pytest.raises(ftm.FeishuError):
        ftm.parse_feishu_url("https://example.com/wiki/abc")


def test_parse_missing_token():
    with pytest.raises(ftm.FeishuError):
        ftm.parse_feishu_url("https://www.feishu.cn/drive/home/")


def test_normalize_url_adds_scheme():
    assert ftm.normalize_url("waytoagi.feishu.cn/wiki/x").startswith("https://")


def test_safe_stem():
    assert ftm.safe_stem("高30 英文.md") == "高30_英文"
    assert ftm.safe_stem("...") == "feishu_document"


def test_blocks_to_markdown_basic():
    model = {
        "title": "示例文档",
        "root": {
            "id": "root",
            "type": "page",
            "children": [
                {
                    "id": "h1",
                    "type": "heading1",
                    "zone_state": {
                        "all_text": "第一章",
                        "content": {"ops": [{"insert": "第一章", "attributes": {}}]},
                    },
                    "snapshot": {"type": "heading1"},
                    "children": [],
                },
                {
                    "id": "p1",
                    "type": "text",
                    "zone_state": {
                        "all_text": "你好世界",
                        "content": {
                            "ops": [
                                {"insert": "你好", "attributes": {"bold": True}},
                                {"insert": "世界", "attributes": {}},
                            ]
                        },
                    },
                    "snapshot": {"type": "text"},
                    "children": [],
                },
                {
                    "id": "img1",
                    "type": "image",
                    "snapshot": {
                        "type": "image",
                        "image": {"token": "TOK", "name": "a.png", "caption": "图注"},
                    },
                    "children": [],
                },
                {"id": "div", "type": "divider", "snapshot": {"type": "divider"}, "children": []},
            ],
        },
    }
    md = ftm.blocks_to_markdown(
        model,
        source_url="https://waytoagi.feishu.cn/wiki/TOK",
        doc_kind="wiki",
    )
    assert md.startswith("> 来源:")
    assert "# 示例文档" in md
    assert "# 第一章" in md
    assert "**你好**世界" in md or "**你好**" in md
    assert "![图注](feishu-asset://image/img1/)" in md
    assert "---" in md


def test_rewrite_placeholders_no_prefix_collision():
    """Short block ids must not corrupt longer ids (image/7 vs image/73)."""
    md = (
        "a ![x](feishu-asset://image/7/) b "
        "![y](feishu-asset://image/73/) c "
        "![z](feishu-asset://image/76/)"
    )
    out = ftm.rewrite_asset_placeholders(
        md,
        {
            "feishu-asset://image/7/": "assets/image_001.png",
            "feishu-asset://image/73/": "assets/image_002.png",
            "feishu-asset://image/76/": "assets/image_003.png",
        },
    )
    assert "assets/image_001.png" in out
    assert "assets/image_002.png" in out
    assert "assets/image_003.png" in out
    assert "image_001.png3" not in out
    assert "feishu-asset://" not in out


def test_disable_embed_autoplay_bilibili():
    url = "https://player.bilibili.com/player.html?bvid=1D7421N7xN&vd_source=abc"
    out = ftm.disable_embed_autoplay(url)
    assert "autoplay=0" in out
    assert "bvid=1D7421N7xN" in out


def test_render_iframe_uses_height_and_link():
    md = ftm.render_iframe_markdown(
        "https://player.bilibili.com/player.html?bvid=1D7421N7xN",
        height=461,
    )
    assert 'height="461"' in md
    assert "width=\"100%\"" in md
    assert "autoplay=0" in md
    assert "[打开视频](" in md
    assert "allowfullscreen" in md


def test_blocks_to_markdown_iframe():
    model = {
        "title": "视频页",
        "root": {
            "type": "page",
            "children": [
                {
                    "id": 3,
                    "type": "iframe",
                    "snapshot": {
                        "type": "iframe",
                        "iframe": {
                            "height": 461,
                            "component": {
                                "url": "https://player.bilibili.com/player.html?bvid=1D7421N7xN"
                            },
                        },
                    },
                    "children": [],
                }
            ],
        },
    }
    md = ftm.blocks_to_markdown(model)
    assert 'height="461"' in md
    assert "autoplay=0" in md
    assert "[打开视频](" in md


def test_blocks_to_markdown_list_and_table():
    model = {
        "title": "列表表",
        "root": {
            "type": "page",
            "children": [
                {
                    "id": "b1",
                    "type": "bullet",
                    "zone_state": {
                        "content": {"ops": [{"insert": "一项", "attributes": {}}]},
                    },
                    "snapshot": {"type": "bullet"},
                    "children": [],
                },
                {
                    "id": "o1",
                    "type": "ordered",
                    "zone_state": {
                        "content": {"ops": [{"insert": "第二", "attributes": {}}]},
                    },
                    "snapshot": {"type": "ordered", "seq": "1"},
                    "children": [],
                },
                {
                    "id": "t1",
                    "type": "table",
                    "snapshot": {
                        "type": "table",
                        "columns_id": ["c1", "c2"],
                        "rows_id": ["r1"],
                    },
                    "children": [
                        {
                            "id": "cell1",
                            "type": "table_cell",
                            "children": [
                                {
                                    "id": "c1t",
                                    "type": "text",
                                    "zone_state": {
                                        "content": {
                                            "ops": [{"insert": "A", "attributes": {}}]
                                        }
                                    },
                                    "children": [],
                                }
                            ],
                        },
                        {
                            "id": "cell2",
                            "type": "table_cell",
                            "children": [
                                {
                                    "id": "c2t",
                                    "type": "text",
                                    "zone_state": {
                                        "content": {
                                            "ops": [{"insert": "B", "attributes": {}}]
                                        }
                                    },
                                    "children": [],
                                }
                            ],
                        },
                    ],
                },
            ],
        },
    }
    md = ftm.blocks_to_markdown(model)
    assert "- 一项" in md
    assert "1. 第二" in md
    assert "| A | B |" in md


def test_collect_assets():
    root = {
        "type": "page",
        "children": [
            {"id": "i1", "type": "image", "snapshot": {}, "children": []},
            {
                "id": "g",
                "type": "grid",
                "children": [
                    {"id": "f1", "type": "file", "snapshot": {}, "children": []},
                ],
            },
        ],
    }
    assets = ftm.collect_assets(root)
    assert len(assets) == 2
    assert {a["asset_type"] for a in assets} == {"image", "file"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (49, "python"),
        ("49", "python"),
        (30, "javascript"),
        (63, "typescript"),
        (1, ""),
        (75, "toml"),
        (999, ""),
        ("python", "python"),
        ("JavaScript", "javascript"),
        ("js", "javascript"),
        ("C++", "cpp"),
        ("Bash", "bash"),
        ("Plain Text", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_resolve_code_language(raw, expected):
    assert ftm.resolve_code_language(raw) == expected


def test_code_block_numeric_language():
    model = {
        "title": "code",
        "root": {
            "type": "page",
            "children": [
                {
                    "id": "c1",
                    "type": "code",
                    "zone_state": {"all_text": "print(1)\n"},
                    "snapshot": {"type": "code", "language": 49},
                    "children": [],
                }
            ],
        },
    }
    md = ftm.blocks_to_markdown(model)
    assert "```python\nprint(1)\n```" in md


def test_fallback_code_and_file_blocks():
    model = {
        "title": "fallback",
        "root": {
            "type": "page",
            "children": [
                {
                    "id": 81,
                    "type": "fallback",
                    "zone_state": {"all_text": "echo hi\n"},
                    "snapshot": {"type": "code", "language": 7},
                    "children": [],
                },
                {
                    "id": 34,
                    "type": "fallback",
                    "snapshot": {
                        "type": "file",
                        "file": {"name": "notes.pdf", "token": "TOK"},
                    },
                    "children": [],
                },
                {
                    "id": 162,
                    "type": "fallback",
                    "snapshot": {
                        "type": "bookmark",
                        "url": "https://example.com/a",
                        "title": "示例",
                    },
                    "children": [],
                },
            ],
        },
    }
    md = ftm.blocks_to_markdown(model)
    assert "```bash\necho hi\n```" in md
    assert "[notes.pdf](feishu-asset://file/34/)" in md
    assert "[示例](https://example.com/a)" in md
    assets = ftm.collect_assets(model["root"])
    assert assets == [
        {
            "asset_type": "file",
            "block_id": "34",
            "placeholder": "feishu-asset://file/34/",
        }
    ]


def test_effective_block_type_unwraps_fallback():
    assert ftm.effective_block_type({"type": "code"}) == "code"
    assert ftm.effective_block_type({"type": "fallback", "snapshot": {"type": "file"}}) == "file"
    assert ftm.effective_block_type({"type": "fallback", "snapshot": {}}) == "fallback"


def test_is_login_error():
    assert ftm.is_login_error("需要登录。请先运行: python feishu_login.py")
    assert ftm.is_login_error(ftm.FeishuError("需要登录"))
    assert not ftm.is_login_error("飞书限流：页面访问人数过多")


def test_page_needs_login():
    class DummyPage:
        def __init__(self, url: str, text: str = "") -> None:
            self.url = url
            self._text = text

        def query_selector(self, _sel: str):
            return True

        def inner_text(self, _sel: str) -> str:
            return self._text

    assert ftm._page_needs_login(
        DummyPage("https://accounts.feishu.cn/accounts/page/login")
    )
    assert ftm._page_needs_login(
        DummyPage("https://waytoagi.feishu.cn/wiki/abc", "登录后即可查看")
    )
    assert not ftm._page_needs_login(
        DummyPage("https://waytoagi.feishu.cn/wiki/abc", "文档正文")
    )


def test_interactive_feishu_login_is_invoked(monkeypatch):
    calls = {"login": 0}

    def fake_login(url: str) -> None:
        calls["login"] += 1
        assert "feishu.cn" in url

    monkeypatch.setattr(ftm, "interactive_feishu_login", fake_login)
    ftm.interactive_feishu_login("https://x.feishu.cn/wiki/abc")
    assert calls["login"] == 1
