#!/usr/bin/env python3
"""Write Markdown pipe tables to an Excel workbook (one sheet per table).

Usage:
  md_to_xlsx.py /path/to/out.md
  md_to_xlsx.py /path/to/out.md -o /path/to/out.xlsx

This rebuilds tables for viewing. It does not restore merged cells, dropdowns,
or colors. A downloaded original .xlsx / .ksheet is still the fuller file.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_H2_RE = re.compile(r"^##\s+(.+?)\s*$")
_INVALID_SHEET_CHARS = re.compile(r"[:\\/?*\[\]]")


def default_xlsx_output(md_path: Path) -> Path:
    return md_path.with_suffix(".xlsx")


def split_table_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    cells: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text) and text[i + 1] == "|":
            buf.append("|")
            i += 2
            continue
        if text[i] == "|":
            cells.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(text[i])
        i += 1
    cells.append("".join(buf).strip())
    return cells


def _is_pipe_row(line: str) -> bool:
    text = line.strip()
    return text.startswith("|") and text.count("|") >= 2


def _is_separator(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def _cell_value(raw: str) -> str:
    text = raw.strip()
    if text == "NaN":
        return ""
    return text


def iter_markdown_tables(md_text: str) -> list[tuple[str, list[list[str]]]]:
    """Return (heading, rows) for each pipe table. The separator row is dropped."""
    tables: list[tuple[str, list[list[str]]]] = []
    heading = ""
    lines = (md_text or "").splitlines()
    i = 0
    while i < len(lines):
        h2 = _H2_RE.match(lines[i].strip())
        if h2:
            heading = h2.group(1).strip()
        if not _is_pipe_row(lines[i]):
            i += 1
            continue
        block: list[list[str]] = []
        while i < len(lines) and _is_pipe_row(lines[i]):
            block.append(split_table_row(lines[i]))
            i += 1
        if len(block) >= 2 and _is_separator(block[1]):
            rows = [block[0]] + block[2:]
        else:
            rows = block
        if rows:
            tables.append((heading, rows))
            heading = ""
    return tables


def unique_sheet_name(title: str, used: set[str]) -> str:
    base = _INVALID_SHEET_CHARS.sub(" ", title or "").strip() or "Sheet"
    base = re.sub(r"\s+", " ", base)[:31] or "Sheet"
    name = base
    n = 2
    while name in used:
        suffix = f" {n}"
        name = (base[: 31 - len(suffix)] + suffix).strip() or f"Sheet{n}"
        n += 1
    used.add(name)
    return name


def build_workbook(md_text: str):
    from openpyxl import Workbook

    tables = iter_markdown_tables(md_text)
    if not tables:
        raise ValueError("No markdown tables found")
    wb = Workbook()
    default = wb.active
    wb.remove(default)
    used: set[str] = set()
    unnamed = 0
    for heading, rows in tables:
        if heading:
            title = heading
        else:
            unnamed += 1
            title = f"Sheet{unnamed}"
        ws = wb.create_sheet(unique_sheet_name(title, used))
        width = max(len(row) for row in rows)
        for r, row in enumerate(rows, start=1):
            padded = row + [""] * (width - len(row))
            for c, cell in enumerate(padded, start=1):
                ws.cell(r, c, _cell_value(cell))
    return wb


def write_sidecar_xlsx(md_path: Path, xlsx_path: Path | None = None) -> Path:
    src = md_path.expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"Markdown not found: {src}")
    dest = (xlsx_path or default_xlsx_output(src)).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    wb = build_workbook(src.read_text(encoding="utf-8"))
    wb.save(dest)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write Markdown pipe tables to an Excel workbook."
    )
    parser.add_argument("markdown", type=Path, help="Input .md path")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output .xlsx path")
    args = parser.parse_args(argv)
    try:
        dest = write_sidecar_xlsx(args.markdown, args.output)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print("OK")
    print(f"markdown: {args.markdown.expanduser().resolve()}")
    print(f"xlsx: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
