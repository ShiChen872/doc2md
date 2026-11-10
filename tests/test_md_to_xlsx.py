"""Unit tests for Markdown pipe tables → Excel."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import md_to_xlsx as mtx  # noqa: E402


def test_tables_become_sheets_named_from_h2():
    openpyxl = pytest.importorskip("openpyxl")
    md = (
        "## 版本交付文档清单\n\n"
        "| 类别 | 交付件 | 备注 |\n"
        "| --- | --- | --- |\n"
        "| NaN | 环境部署要求 | a\\|b |\n"
        "| 变更 | 常用变更手册 | 是 |\n\n"
        "## 另一张\n\n"
        "| 序号 | 问题 |\n"
        "| --- | --- |\n"
        "| 1 | 你好 |\n"
    )
    wb = mtx.build_workbook(md)
    assert wb.sheetnames == ["版本交付文档清单", "另一张"]
    first = wb["版本交付文档清单"]
    assert first["A2"].value == ""
    assert first["B2"].value == "环境部署要求"
    assert first["C2"].value == "a|b"
    assert first["A3"].value == "变更"
    second = wb["另一张"]
    assert second["B2"].value == "你好"
    assert openpyxl is not None


def test_unnamed_tables_use_sheet_numbers():
    md = (
        "| A | B |\n"
        "| --- | --- |\n"
        "| 1 | 2 |\n\n"
        "| C |\n"
        "| --- |\n"
        "| 3 |\n"
    )
    wb = mtx.build_workbook(md)
    assert wb.sheetnames == ["Sheet1", "Sheet2"]


def test_write_sidecar_xlsx(tmp_path: Path):
    md = tmp_path / "out.md"
    md.write_text(
        "## 清单\n\n| 名称 |\n| --- |\n| NaN |\n",
        encoding="utf-8",
    )
    dest = mtx.write_sidecar_xlsx(md)
    assert dest == tmp_path / "out.xlsx"
    from openpyxl import load_workbook

    wb = load_workbook(dest)
    assert wb.sheetnames == ["清单"]
    assert wb["清单"]["A2"].value in (None, "")
