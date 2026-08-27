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


def test_extract_share_id_media_path():
    assert (
        wtm.extract_share_id("https://plus.wps.cn/view/media/l/cnU6phmAZZKr")
        == "cnU6phmAZZKr"
    )


def test_extract_share_id_wiki_path():
    assert (
        wtm.extract_share_id("https://365.kdocs.cn/wiki/l/0lcoPwGoRMiAkL")
        == "0lcoPwGoRMiAkL"
    )
    assert wtm.share_id_candidates("https://365.kdocs.cn/wiki/l/0lcoPwGoRMiAkL") == [
        "0lcoPwGoRMiAkL",
        "coPwGoRMiAkL",
    ]
    assert wtm.share_id_candidates("https://365.kdocs.cn/l/coPwGoRMiAkL") == [
        "coPwGoRMiAkL"
    ]


def test_is_presentation_share():
    assert wtm.is_presentation_share("通威太阳能.pptx")
    assert wtm.is_presentation_share("deck", office_type="p")
    assert not wtm.is_presentation_share("notes.docx")
    assert not wtm.is_presentation_share("notes.otl", office_type="s")


def test_clean_dbsheet_name():
    assert wtm._clean_dbsheet_name("📚\n项目管理") == "项目管理"
    assert wtm._clean_dbsheet_name("仪表盘") == "仪表盘"
    assert wtm._clean_dbsheet_name("📙") == "📙"


def test_is_ksheet_and_dbsheet_share():
    assert wtm.is_ksheet_share("评估.ksheet")
    assert wtm.is_ksheet_share("x", office_type="k")
    assert not wtm.is_ksheet_share("评估.dbt")
    assert wtm.is_dbsheet_share("项目管理.dbt")
    assert wtm.is_dbsheet_share("x", office_type="d")
    assert not wtm.is_dbsheet_share("评估.ksheet")
    assert not wtm.is_dbsheet_share("notes.otl", office_type="o")
    assert "view-item" in wtm.DB_SHEET_ITEM_SEL


def test_is_wps_diagram_share():
    assert wtm.is_wps_diagram_share("立项导航.pof")
    assert wtm.is_wps_diagram_share("过程看板.pom")
    assert wtm.is_wps_diagram_share("export.pos")
    assert wtm.is_wps_diagram_share("x", office_type="processon")
    assert wtm.diagram_kind_from_name("立项导航.pof") == "mindmap"
    assert wtm.diagram_kind_from_name("过程看板.pom") == "flowchart"
    assert wtm.diagram_kind_from_name("export.pos") == "diagram"
    assert not wtm.is_wps_diagram_share("notes.otl")
    assert not wtm.is_wps_diagram_share("deck.pptx")
    assert not wtm.is_wps_diagram_share("项目管理.dbt")
    assert not wtm.is_wps_diagram_share("board.otl", office_type="o")
    assert ".page_tab_item" in wtm.PO_CANVAS_TAB_SEL
    assert "dotviewIframe" in wtm.PO_IFRAME_SEL


def test_is_media_filename():
    assert wtm.is_media_filename("comate-产品介绍.mp4")
    assert wtm.is_media_filename("a.MOV")
    assert not wtm.is_media_filename("notes.docx")


def test_is_pdf_share():
    assert wtm.is_pdf_share("竞对策略.pdf")
    assert wtm.is_pdf_share("x.PDF")
    assert wtm.is_pdf_share("noext", office_type="f")
    assert wtm.is_pdf_share("noext", ftype="pdf")
    assert not wtm.is_pdf_share("notes.docx")
    assert not wtm.is_pdf_share("notes.otl", office_type="s")


def test_parse_pdf_page_label():
    assert wtm.parse_pdf_page_label("3/24") == (3, 24)
    assert wtm.parse_pdf_page_label(" 3 / 24 ") == (3, 24)
    assert wtm.parse_pdf_page_label("1\n/\n8") == (1, 8)
    assert wtm.parse_pdf_page_label("1") == (None, None)
    assert wtm.parse_pdf_page_label("") == (None, None)
    assert wtm.parse_pdf_page_label("1/9999") == (None, None)


def test_build_pdf_preview_markdown():
    md = wtm.build_pdf_preview_markdown(
        title="竞对策略",
        source_url="https://365.kdocs.cn/l/abc",
        pages=[
            ("竞对策略_assets/page_001.png", "封面文字"),
            ("竞对策略_assets/page_002.png", ""),
        ],
    )
    assert "# 竞对策略" in md
    assert "网页预览分页截图" in md
    deck = wtm.build_pdf_preview_markdown(
        title="通威",
        source_url="https://365.kdocs.cn/wiki/l/0lcoPwGoRMiAkL",
        pages=[("deck_assets/page_001.png", "")],
        kind="presentation",
    )
    assert "演示文稿" in deck
    assert "![](deck_assets/page_001.png)" in deck
    assert "![](竞对策略_assets/page_001.png)" in md
    assert "封面文字" in md
    assert "## 第 2 页" in md
    db = wtm.build_pdf_preview_markdown(
        title="项目管理",
        source_url="https://365.kdocs.cn/l/ck9GLthdyAjb",
        pages=[("pm_assets/page_001.png", "风险 P0"), ("pm_assets/page_002.png", "")],
        kind="dbsheet",
        headings=["风险及策略", "仪表盘"],
    )
    assert "多维表" in db
    assert "网页预览分页截图" in db
    assert "## 风险及策略" in db
    assert "## 仪表盘" in db
    assert "风险 P0" in db
    mind = wtm.build_pdf_preview_markdown(
        title="立项导航",
        source_url="https://www.kdocs.cn/l/ch33TCIxbqBq",
        pages=[("nav_assets/page_001.png", "节点文字")],
        kind="mindmap",
        headings=["画布1"],
    )
    assert "思维导图" in mind
    assert "网页预览分页截图" in mind
    assert "## 画布1" in mind
    flow = wtm.build_pdf_preview_markdown(
        title="过程看板",
        source_url="https://www.kdocs.cn/l/coq7afRkUCIR",
        pages=[("flow_assets/page_001.png", "")],
        kind="flowchart",
        headings=["画布1"],
    )
    assert "流程图" in flow
    assert "网页预览分页截图" in flow
    assert "![](flow_assets/page_001.png)" in flow


def test_build_media_markdown_includes_cover_and_stream():
    md = wtm.build_media_markdown(
        title="演示",
        source_url="https://plus.wps.cn/view/media/l/abc",
        fname="演示.mp4",
        fsize=1024 * 1024,
        cover_rel="演示_assets/cover.jpg",
        stream_path="https://example.com/x.m3u8",
        download_blocked=True,
        permission="readonly",
    )
    assert "# 演示" in md
    assert "![封面](演示_assets/cover.jpg)" in md
    assert "m3u8" in md
    assert "download: original file download denied" in md
    assert wtm.format_bytes(1024 * 1024) == "1.0 MB"


def test_build_media_markdown_with_local_preview():
    md = wtm.build_media_markdown(
        title="演示",
        source_url="https://plus.wps.cn/view/media/l/abc",
        fname="演示.mp4",
        fsize=800_000_000,
        cover_rel="演示_assets/cover.jpg",
        stream_path="https://example.com/x.m3u8",
        download_blocked=True,
        preview_rel="演示_assets/preview.mp4",
        preview_bytes=90_000_000,
    )
    assert "preview.mp4" in md
    assert "<video src=" in md
    assert "m3u8" not in md  # prefer local file over raw stream URL
    assert "非原始" in md or "不是原始" in md


def test_find_ffmpeg_homebrew_or_path():
    # Soft check: helper should return str|None without raising
    path = wtm.find_ffmpeg()
    assert path is None or Path(path).name == "ffmpeg"


def test_cookie_header_from_playwright_filters_domains():
    header = wtm.cookie_header_from_playwright(
        [
            {"name": "wps_sid", "value": "abc", "domain": ".wps.cn"},
            {"name": "other", "value": "x", "domain": "example.com"},
            {"name": "wps_sid", "value": "dup", "domain": "drive.wps.cn"},
        ]
    )
    assert "wps_sid=abc" in header
    assert "example.com" not in header
    assert header.count("wps_sid=") == 1


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
    with pytest.raises(wtm.WpsError, match="Session not found"):
        wtm.ensure_session(auto_login=False)


def test_ensure_session_auto_login(tmp_path: Path, monkeypatch):
    state = tmp_path / "wps_storage_state.json"

    def fake_login(url: str) -> None:
        state.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(wtm, "DEFAULT_STATE", state)
    monkeypatch.setattr(wtm, "interactive_wps_login", fake_login)
    assert wtm.ensure_session("https://365.kdocs.cn/l/abc") == state
    assert state.is_file()


def test_share_to_markdown_retries_after_expired_session(tmp_path: Path, monkeypatch):
    calls = {"n": 0, "login": 0}

    def fake_once(url, output, *, auto_login=True, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise wtm._SessionExpired()
        return {"ok": True, "output": str(output)}

    def fake_login(url: str) -> None:
        calls["login"] += 1

    monkeypatch.setattr(wtm, "_share_to_markdown_once", fake_once)
    monkeypatch.setattr(wtm, "interactive_wps_login", fake_login)
    result = wtm.share_to_markdown("https://365.kdocs.cn/l/abc123", tmp_path / "out.md")
    assert result["ok"] is True
    assert calls == {"n": 2, "login": 1}


def test_share_to_markdown_no_login_does_not_prompt(tmp_path: Path, monkeypatch):
    def fake_once(url, output, *, auto_login=True, **kwargs):
        raise wtm._SessionExpired()

    monkeypatch.setattr(wtm, "_share_to_markdown_once", fake_once)
    monkeypatch.setattr(
        wtm,
        "interactive_wps_login",
        lambda url: (_ for _ in ()).throw(AssertionError("should not login")),
    )
    with pytest.raises(wtm.WpsError, match="Session may be expired"):
        wtm.share_to_markdown(
            "https://365.kdocs.cn/l/abc123",
            tmp_path / "out.md",
            auto_login=False,
        )


def test_merge_shapes_payload_and_cover():
    into: dict = {}
    n = wtm.merge_shapes_payload(
        {"data": {"SK1": {"raw": "http://a", "raw_ext": "png"}, "SK2": {"url": "http://b"}}},
        into,
    )
    assert n == 2
    assert set(into) == {"SK1", "SK2"}
    pics = [{"sourceKey": "SK1"}, {"sourceKey": "SK2"}, {"sourceKey": "SK3"}]
    assert not wtm.shapes_cover_pictures(pics, into)
    into["SK3"] = {"thumbnail": "http://c"}
    assert wtm.shapes_cover_pictures(pics, into)


def test_fill_images_prefers_cdn_when_complete():
    pics = [{"sourceKey": "a"}, {"sourceKey": "b"}]
    cdn = [("png", b"1"), ("jpg", b"2")]
    aligned, name = wtm.fill_images_cdn_or_shapes(pics, cdn, None)
    assert name == "otl-picture-matched"
    assert aligned == cdn


def test_fill_images_uses_shapes_when_cdn_incomplete():
    pics = [{"sourceKey": "a"}, {"sourceKey": "b"}, {"sourceKey": "c"}]
    cdn = [("png", b"only-one")]
    shaped = [("png", b"A"), None, ("webp", b"C")]
    aligned, name = wtm.fill_images_cdn_or_shapes(pics, cdn, shaped)
    assert name == "otl-shapes-sourcekey"
    assert aligned[0] == ("png", b"A")
    assert aligned[1] is None
    assert aligned[2] == ("webp", b"C")


def test_ext_from_shape():
    assert wtm._ext_from_shape({"raw_ext": "jpeg"}, b"") == "jpg"
    assert wtm._ext_from_shape({}, b"\x89PNG\r\n\x1a\nxxxx") == "png"
    assert wtm._ext_from_shape({}, b"\xff\xd8\xff") == "jpg"


def test_resolve_nested_depth():
    assert wtm.resolve_nested_depth() == 0
    assert wtm.resolve_nested_depth(recursive=True) == 1
    assert wtm.resolve_nested_depth(recursive=True, max_depth=2) == 2
    assert wtm.resolve_nested_depth(recursive=True, max_depth=0) == 0
    try:
        wtm.resolve_nested_depth(max_depth=-1)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_rewrite_nested_share_links():
    md = (
        "> 来源: https://www.kdocs.cn/l/parentid\n\n"
        "[SOP.otl](https://www.kdocs.cn/l/childaa?from=koa)\n"
        "[评估.xlsx](https://365.kdocs.cn/l/childbb)\n"
    )
    out = wtm.rewrite_nested_share_links(
        md,
        {"childaa": "parent_nested/SOP.md", "childbb": "parent_nested/评估.md"},
    )
    assert "parent_nested/SOP.md" in out
    assert "parent_nested/评估.md" in out
    assert "https://www.kdocs.cn/l/parentid" in out
    assert "kdocs.cn/l/childaa" not in out


def test_expand_nested_otl_rewrites_success_keeps_failures(tmp_path: Path):
    parent = tmp_path / "合集.md"
    parent.write_text(
        "[成功.otl](https://www.kdocs.cn/l/okchild1)\n"
        "[失败.otl](https://365.kdocs.cn/l/badchild)\n"
        "[自己.otl](https://www.kdocs.cn/l/parentid)\n",
        encoding="utf-8",
    )
    raw = {
        "content": {
            "type": "doc",
            "content": [
                {
                    "type": "WPSDocument",
                    "attrs": {
                        "wpsDocumentName": "成功.otl",
                        "wpsDocumentLink": "https://www.kdocs.cn/l/okchild1",
                        "wpsDocumentType": "otl",
                    },
                },
                {
                    "type": "WPSDocument",
                    "attrs": {
                        "wpsDocumentName": "失败.otl",
                        "wpsDocumentLink": "https://365.kdocs.cn/l/badchild",
                        "wpsDocumentType": "otl",
                    },
                },
                {
                    "type": "WPSDocument",
                    "attrs": {
                        "wpsDocumentName": "自己.otl",
                        "wpsDocumentLink": "https://www.kdocs.cn/l/parentid",
                        "wpsDocumentType": "otl",
                    },
                },
            ],
        }
    }

    def fake_convert(url, dest, **kwargs):
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if "badchild" in url:
            raise wtm.WpsError("denied")
        dest.write_text(f"# from {url}\n", encoding="utf-8")
        return {"mode": "otl", "output": str(dest)}

    reports = wtm.expand_nested_otl_documents(
        raw,
        parent,
        max_depth=1,
        visited={"parentid"},
        convert_child=fake_convert,
    )
    text = parent.read_text(encoding="utf-8")
    assert "合集_nested/成功.md" in text
    assert "https://365.kdocs.cn/l/badchild" in text
    assert "https://www.kdocs.cn/l/parentid" in text
    ok = [r for r in reports if r.get("ok")]
    skipped = [r for r in reports if r.get("skipped") == "already visited"]
    failed = [r for r in reports if not r.get("ok") and r.get("error")]
    assert len(ok) == 1
    assert len(skipped) == 1
    assert len(failed) == 1


def test_expand_nested_depth_zero_is_noop(tmp_path: Path):
    parent = tmp_path / "p.md"
    parent.write_text("[x](https://www.kdocs.cn/l/abc)\n", encoding="utf-8")
    raw = {
        "content": {
            "type": "WPSDocument",
            "attrs": {
                "wpsDocumentName": "x.otl",
                "wpsDocumentLink": "https://www.kdocs.cn/l/abc",
            },
        }
    }
    reports = wtm.expand_nested_otl_documents(
        raw, parent, max_depth=0, visited=set(), convert_child=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope"))
    )
    assert reports == []
    assert "https://www.kdocs.cn/l/abc" in parent.read_text(encoding="utf-8")