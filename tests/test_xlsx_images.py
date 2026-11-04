"""Tests for Excel DISPIMG cell-picture extraction."""

from __future__ import annotations

import io
import struct
import sys
import zipfile
import zlib
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import convert as conv  # noqa: E402
import xlsx_images as xi  # noqa: E402


def _png_1x1() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    raw = b"\x00\x00\x00\x00\xff"
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _cellimages_xml(image_id: str, rid: str = "rId1") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<etc:cellImages xmlns:etc="http://www.wps.cn/officeDocument/2017/etCustomData"
  xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <etc:cellImage>
    <xdr:pic>
      <xdr:nvPicPr><xdr:cNvPr id="1" name="{image_id}"/></xdr:nvPicPr>
      <xdr:blipFill><a:blip r:embed="{rid}"/></xdr:blipFill>
    </xdr:pic>
  </etc:cellImage>
</etc:cellImages>
"""


def _rels_xml(rid: str = "rId1", target: str = "../media/image1.png") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{target}"/>
</Relationships>
"""


def _write_cellimages_zip(path: Path, image_id: str = "ID_TEST01") -> None:
    png = _png_1x1()
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/cellimages.xml", _cellimages_xml(image_id))
        zf.writestr("xl/_rels/cellimages.xml.rels", _rels_xml())
        zf.writestr("xl/media/image1.png", png)


def test_load_dispimg_bytes_maps_id(tmp_path: Path):
    xlsx = tmp_path / "shot.xlsx"
    _write_cellimages_zip(xlsx)
    blobs = xi.load_dispimg_bytes(xlsx)
    assert "ID_TEST01" in blobs
    member, data = blobs["ID_TEST01"]
    assert member.endswith("image1.png")
    assert data.startswith(b"\x89PNG")


def test_rewrite_dispimg_replaces_formula_in_table(tmp_path: Path):
    xlsx = tmp_path / "shot.xlsx"
    _write_cellimages_zip(xlsx)
    assets = tmp_path / "assets"
    md = '| 截图 | =_xlfn.DISPIMG("ID_TEST01",1) |\n'
    out, n = xi.inject_xlsx_cell_images(xlsx, md, assets, "assets")
    assert n == 1
    assert "DISPIMG" not in out
    assert "![](assets/image_xlsx_001.png)" in out
    assert (assets / "image_xlsx_001.png").read_bytes().startswith(b"\x89PNG")
    assert "单元格图片" not in out


def test_rewrite_dispimg_handles_escaped_underscores(tmp_path: Path):
    xlsx = tmp_path / "shot.xlsx"
    _write_cellimages_zip(xlsx, image_id="ID_7B6C022F1BD84FDBBCBE3D7F08098640")
    assets = tmp_path / "assets"
    md = r'| =DISPIMG("ID\_7B6C022F1BD84FDBBCBE3D7F08098640",1) |'
    out, n = xi.inject_xlsx_cell_images(xlsx, md, assets, "assets")
    assert n == 1
    assert "DISPIMG" not in out
    assert "![](assets/image_xlsx_001.png)" in out
    assert "单元格图片" not in out


def test_unused_dispimg_gets_appendix(tmp_path: Path):
    xlsx = tmp_path / "shot.xlsx"
    _write_cellimages_zip(xlsx)
    assets = tmp_path / "assets"
    out, n = xi.inject_xlsx_cell_images(xlsx, "| a | b |\n", assets, "assets")
    assert n == 1
    assert "单元格图片" in out
    assert "ID_TEST01" in out
    assert "image_xlsx_001.png" in out


def _drawing_zip(path: Path) -> None:
    png = _png_1x1()
    drawing = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <xdr:twoCellAnchor>
    <xdr:from>
      <xdr:col>1</xdr:col><xdr:colOff>0</xdr:colOff>
      <xdr:row>1</xdr:row><xdr:rowOff>0</xdr:rowOff>
    </xdr:from>
    <xdr:pic>
      <xdr:nvPicPr><xdr:cNvPr id="2" name="Picture 1"/></xdr:nvPicPr>
      <xdr:blipFill><a:blip r:embed="rId1"/></xdr:blipFill>
    </xdr:pic>
    <xdr:clientData/>
  </xdr:twoCellAnchor>
</xdr:wsDr>
"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        )
        zf.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
        zf.writestr(
            "xl/worksheets/_rels/sheet1.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/>
</Relationships>""",
        )
        zf.writestr("xl/drawings/drawing1.xml", drawing)
        zf.writestr("xl/drawings/_rels/drawing1.xml.rels", _rels_xml(target="../media/image1.png"))
        zf.writestr("xl/media/image1.png", png)


def test_drawing_image_splices_into_cell(tmp_path: Path):
    xlsx = tmp_path / "float.xlsx"
    _drawing_zip(xlsx)
    md = "\n".join(
        [
            "## Sheet1",
            "",
            "| 名称 | 图 |",
            "| --- | --- |",
            "| 架构 |  |",
            "",
        ]
    )
    out, n = xi.inject_xlsx_drawing_images(xlsx, md, tmp_path / "assets", "assets")
    assert n == 1
    assert "| 架构 | ![](assets/image_draw_001.png) |" in out
    assert (tmp_path / "assets" / "image_draw_001.png").read_bytes().startswith(b"\x89PNG")


def test_missing_cellimages_is_noop(tmp_path: Path):
    xlsx = tmp_path / "plain.xlsx"
    with zipfile.ZipFile(xlsx, "w") as zf:
        zf.writestr("xl/workbook.xml", "<workbook/>")
    out, n = xi.inject_xlsx_cell_images(xlsx, "hello", tmp_path / "assets", "assets")
    assert n == 0
    assert out == "hello"


def test_duplicate_ids_share_one_file(tmp_path: Path):
    xlsx = tmp_path / "dup.xlsx"
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<etc:cellImages xmlns:etc="http://www.wps.cn/officeDocument/2017/etCustomData"
  xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <etc:cellImage>
    <xdr:pic>
      <xdr:nvPicPr><xdr:cNvPr id="1" name="ID_A"/></xdr:nvPicPr>
      <xdr:blipFill><a:blip r:embed="rId1"/></xdr:blipFill>
    </xdr:pic>
  </etc:cellImage>
  <etc:cellImage>
    <xdr:pic>
      <xdr:nvPicPr><xdr:cNvPr id="2" name="ID_B"/></xdr:nvPicPr>
      <xdr:blipFill><a:blip r:embed="rId1"/></xdr:blipFill>
    </xdr:pic>
  </etc:cellImage>
</etc:cellImages>
"""
    with zipfile.ZipFile(xlsx, "w") as zf:
        zf.writestr("xl/cellimages.xml", xml)
        zf.writestr("xl/_rels/cellimages.xml.rels", _rels_xml())
        zf.writestr("xl/media/image1.png", _png_1x1())
    assets = tmp_path / "assets"
    _out, n = xi.inject_xlsx_cell_images(
        xlsx, '=DISPIMG("ID_A",1) =DISPIMG("ID_B",1)', assets, "assets"
    )
    assert n == 1
    assert list(assets.glob("image_xlsx_*")) == [assets / "image_xlsx_001.png"]


def test_convert_xlsx_extracts_dispimg(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    image_id = "ID_CONVERT1"
    xlsx = tmp_path / "demo.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "截图"
    ws["B1"] = f'=DISPIMG("{image_id}",1)'
    wb.save(xlsx)
    png = _png_1x1()
    buf = io.BytesIO()
    with zipfile.ZipFile(xlsx, "r") as src, zipfile.ZipFile(buf, "w") as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        dst.writestr("xl/cellimages.xml", _cellimages_xml(image_id))
        dst.writestr("xl/_rels/cellimages.xml.rels", _rels_xml())
        dst.writestr("xl/media/image1.png", png)
    xlsx.write_bytes(buf.getvalue())

    out_md = tmp_path / "demo.md"
    stats = conv.convert(xlsx, out_md)
    text = out_md.read_text(encoding="utf-8")
    assert int(stats["images_from_xlsx"]) == 1
    assert "image_xlsx_001.png" in text
    saved = tmp_path / "demo_assets" / "image_xlsx_001.png"
    assert saved.is_file()
    assert saved.read_bytes().startswith(b"\x89PNG")
    assert "无法提取" not in text


def _inject_validation_id(xlsx: Path, rule_id: str = "{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}") -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(xlsx, "r") as src, zipfile.ZipFile(buf, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename.startswith("xl/worksheets/") and item.filename.endswith(".xml"):
                text = data.decode("utf-8")
                text = text.replace(
                    "</worksheet>",
                    (
                        "<dataValidations count=\"1\">"
                        f'<dataValidation type="list" allowBlank="1" id="{rule_id}" sqref="B1">'
                        "<formula1>&quot;是,否&quot;</formula1>"
                        "</dataValidation></dataValidations></worksheet>"
                    ),
                    1,
                )
                data = text.encode("utf-8")
            dst.writestr(item, data)
    xlsx.write_bytes(buf.getvalue())


def test_strip_datavalidation_id_keeps_rid():
    xml = (
        '<worksheet><hyperlinks><hyperlink ref="D38" r:id="rId1"/></hyperlinks>'
        '<dataValidations count="1">'
        '<dataValidation type="list" id="{abc}" sqref="C2">'
        "<formula1>&quot;是,否&quot;</formula1></dataValidation>"
        "</dataValidations></worksheet>"
    )
    out, n = xi.strip_datavalidation_id_attrs(xml)
    assert n == 1
    assert "id=" not in out.split("<dataValidation", 1)[1].split(">", 1)[0]
    assert 'r:id="rId1"' in out
    assert "sqref=\"C2\"" in out


def test_workbook_without_validation_ids_leaves_clean_file(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    src = tmp_path / "plain.xlsx"
    wb = openpyxl.Workbook()
    wb.active["A1"] = "物料"
    wb.save(src)
    wb.close()
    out, holder = xi.workbook_without_validation_ids(src)
    assert out == src.resolve()
    assert holder is None


def test_workbook_without_validation_ids_and_convert(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    src = tmp_path / "rules.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "清单"
    ws["A1"] = "物料"
    ws["B1"] = "是"
    wb.save(src)
    wb.close()
    _inject_validation_id(src)
    before = src.read_bytes()
    with pytest.raises(TypeError, match="id"):
        openpyxl.load_workbook(src)

    stripped, holder = xi.workbook_without_validation_ids(src)
    try:
        assert stripped != src.resolve()
        loaded = openpyxl.load_workbook(stripped)
        assert loaded.active["A1"].value == "物料"
        assert loaded.active["B1"].value == "是"
    finally:
        if holder is not None:
            holder.cleanup()
    assert src.read_bytes() == before

    out_md = tmp_path / "rules.md"
    conv.convert(src, out_md)
    text = out_md.read_text(encoding="utf-8")
    assert "物料" in text
    assert "是" in text
    assert src.read_bytes() == before
