"""Extract Excel / ksheet cell pictures (DISPIMG) from the xlsx zip.

WPS and Excel 365 store in-cell screenshots as DISPIMG("ID_…") formulas.
The bytes live in xl/media/; xl/cellimages.xml maps the DISPIMG id to a
relationship, then to the media part. markitdown only emits the formula
(or an empty cell), so we rewrite those to local Markdown images.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

DISPIMG_RE = re.compile(
    r'=?_xlfn\.DISPIMG\(\s*"(?P<id>[^"]+)"\s*(?:,\s*[^)]*)?\s*\)'
    r'|=?DISPIMG\(\s*"(?P<id2>[^"]+)"\s*(?:,\s*[^)]*)?\s*\)',
    re.IGNORECASE,
)
XLSX_SUFFIXES = {".xlsx", ".xlsm", ".xltx", ".xltm", ".ksheet"}


def _local(tag: str) -> str:
    if tag.startswith("{"):
        return tag.rsplit("}", 1)[-1]
    return tag.split(":")[-1]


def _attr(el: ET.Element, *names: str) -> str:
    want = {n.lower() for n in names}
    for key, val in el.attrib.items():
        if _local(key).lower() in want:
            return val
    return ""


def _zip_candidates(target: str) -> list[str]:
    raw = (target or "").replace("\\", "/").lstrip("/")
    if not raw:
        return []
    out: list[str] = []
    for item in (
        raw,
        posixpath.normpath(posixpath.join("xl", raw)),
        posixpath.normpath(posixpath.join("xl/_rels", raw)),
        posixpath.normpath("xl/media/" + posixpath.basename(raw)),
    ):
        if item and item not in out:
            out.append(item)
    return out


def _read_member(zf: zipfile.ZipFile, names: set[str], target: str) -> tuple[str, bytes] | None:
    for cand in _zip_candidates(target):
        if cand in names:
            return cand, zf.read(cand)
    return None


def _parse_cellimage_ids(xml: bytes) -> dict[str, str]:
    """DISPIMG id → rId."""
    root = ET.fromstring(xml)
    mapping: dict[str, str] = {}
    for pic in root.iter():
        if _local(pic.tag) != "pic":
            continue
        name = ""
        rid = ""
        for child in pic.iter():
            loc = _local(child.tag)
            if loc == "cNvPr":
                name = _attr(child, "name") or name
            elif loc == "blip":
                rid = _attr(child, "embed") or rid
        if name and rid:
            mapping[name] = rid
    return mapping


def _parse_rels(xml: bytes) -> dict[str, str]:
    """rId → Target."""
    root = ET.fromstring(xml)
    mapping: dict[str, str] = {}
    for el in root.iter():
        if _local(el.tag) != "Relationship":
            continue
        rid = _attr(el, "Id")
        target = _attr(el, "Target")
        if rid and target:
            mapping[rid] = target
    return mapping


def load_dispimg_bytes(xlsx_path: Path) -> dict[str, tuple[str, bytes]]:
    """Return DISPIMG id → (zip member name, image bytes)."""
    path = Path(xlsx_path)
    out: dict[str, tuple[str, bytes]] = {}
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            xml_name = next((n for n in names if n.rstrip("/").endswith("cellimages.xml")), "")
            rels_name = next(
                (n for n in names if n.rstrip("/").endswith("cellimages.xml.rels")),
                "",
            )
            if not xml_name or not rels_name:
                return out
            id_to_rid = _parse_cellimage_ids(zf.read(xml_name))
            rid_to_target = _parse_rels(zf.read(rels_name))
            for image_id, rid in id_to_rid.items():
                target = rid_to_target.get(rid)
                if not target:
                    continue
                hit = _read_member(zf, names, target)
                if hit is None:
                    continue
                out[image_id] = hit
    except (OSError, zipfile.BadZipFile, ET.ParseError):
        return {}
    return out


def _ext_from_member(member: str) -> str:
    ext = posixpath.splitext(member)[1].lower().lstrip(".")
    if ext == "jpeg":
        return "jpg"
    return ext or "png"


def save_dispimg_assets(
    xlsx_path: Path,
    assets_dir: Path,
    rel_prefix: str,
) -> dict[str, str]:
    """Write cell pictures to assets_dir. Returns DISPIMG id → markdown relative path."""
    blobs = load_dispimg_bytes(xlsx_path)
    if not blobs:
        return {}
    assets_dir.mkdir(parents=True, exist_ok=True)
    id_to_rel: dict[str, str] = {}
    saved_members: dict[str, str] = {}
    n = 0
    for image_id, (member, data) in blobs.items():
        if member in saved_members:
            id_to_rel[image_id] = saved_members[member]
            continue
        n += 1
        ext = _ext_from_member(member)
        filename = f"image_xlsx_{n:03d}.{ext}"
        dest = assets_dir / filename
        dest.write_bytes(data)
        rel = f"{rel_prefix}/{filename}"
        saved_members[member] = rel
        id_to_rel[image_id] = rel
    return id_to_rel


def _norm_dispimg_id(raw: str) -> str:
    """markitdown may emit ID\\_ABC instead of ID_ABC."""
    return (raw or "").replace("\\_", "_").replace("\\", "")


def rewrite_dispimg_markdown(md: str, id_to_rel: dict[str, str]) -> tuple[str, set[str]]:
    """Replace DISPIMG formulas with Markdown images. Returns (text, used ids)."""
    if not id_to_rel:
        return md, set()
    used: set[str] = set()

    def repl(match: re.Match[str]) -> str:
        image_id = _norm_dispimg_id(match.group("id") or match.group("id2") or "")
        rel = id_to_rel.get(image_id)
        if not rel:
            return match.group(0)
        used.add(image_id)
        return f"![]({rel})"

    return DISPIMG_RE.sub(repl, md), used


def append_unused_cell_images(md: str, id_to_rel: dict[str, str], used: set[str]) -> str:
    leftover = [(iid, rel) for iid, rel in id_to_rel.items() if iid not in used]
    if not leftover:
        return md
    lines = [
        "",
        "### 单元格图片",
        "",
        "原表用 DISPIMG 把截图嵌在格子里；下面按原始文件写出。",
        "",
    ]
    for image_id, rel in leftover:
        lines.append(f"- {image_id}: ![]({rel})")
    lines.append("")
    return md.rstrip() + "\n" + "\n".join(lines)


def inject_xlsx_cell_images(
    xlsx_path: Path,
    markdown: str,
    assets_dir: Path,
    rel_prefix: str,
) -> tuple[str, int]:
    """Save DISPIMG media and splice them into Markdown. Returns (md, image count)."""
    id_to_rel = save_dispimg_assets(xlsx_path, assets_dir, rel_prefix)
    if not id_to_rel:
        return markdown, 0
    text, used = rewrite_dispimg_markdown(markdown, id_to_rel)
    text = append_unused_cell_images(text, id_to_rel, used)
    return text, len({rel for rel in id_to_rel.values()})


def _sheet_drawings(zf: zipfile.ZipFile, names: set[str]) -> list[tuple[str, str]]:
    """Return (sheet name, drawing zip path) in workbook order."""
    book_name = next((n for n in names if n.rstrip("/") == "xl/workbook.xml"), "")
    rels_name = next((n for n in names if n.rstrip("/") == "xl/_rels/workbook.xml.rels"), "")
    if not book_name or not rels_name:
        return []
    rid_to_sheet = _parse_rels(zf.read(rels_name))
    root = ET.fromstring(zf.read(book_name))
    out: list[tuple[str, str]] = []
    for el in root.iter():
        if _local(el.tag) != "sheet":
            continue
        name = _attr(el, "name")
        rid = _attr(el, "id")
        target = rid_to_sheet.get(rid) or ""
        if not name or not target:
            continue
        sheet_path = posixpath.normpath(posixpath.join("xl", target.lstrip("/")))
        sheet_rels = posixpath.normpath(
            posixpath.join(posixpath.dirname(sheet_path), "_rels", posixpath.basename(sheet_path) + ".rels")
        )
        if sheet_rels not in names:
            continue
        for rel_target in _parse_rels(zf.read(sheet_rels)).values():
            if "drawing" not in rel_target.lower():
                continue
            drawing = posixpath.normpath(
                posixpath.join(posixpath.dirname(sheet_path), rel_target)
            )
            if drawing in names:
                out.append((name, drawing))
    return out


def _anchor_pictures(xml: bytes) -> list[tuple[int, int, str]]:
    """(row, col, rId) for each picture anchor. Rows and columns are 0-based."""
    root = ET.fromstring(xml)
    pics: list[tuple[int, int, str]] = []
    for anchor in root.iter():
        if _local(anchor.tag) not in {"twoCellAnchor", "oneCellAnchor"}:
            continue
        origin = None
        rid = ""
        for child in list(anchor):
            if _local(child.tag) == "from" and origin is None:
                origin = child
            elif _local(child.tag) == "pic":
                for el in child.iter():
                    if _local(el.tag) == "blip":
                        rid = _attr(el, "embed") or rid
        if origin is None or not rid:
            continue
        row = col = None
        for el in list(origin):
            loc = _local(el.tag)
            if loc == "row" and el.text and el.text.strip().isdigit():
                row = int(el.text.strip())
            elif loc == "col" and el.text and el.text.strip().isdigit():
                col = int(el.text.strip())
        if row is None or col is None:
            continue
        pics.append((row, col, rid))
    return pics


def _split_md_row(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [cell.strip() for cell in inner.split("|")]


def _join_md_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _is_sep_row(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def splice_drawing_into_markdown(
    markdown: str, sheet: str, row: int, col: int, rel: str
) -> str:
    """Put a floating picture into the Markdown cell at that sheet anchor."""
    image = f"![]({rel})"
    lines = markdown.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == f"## {sheet}":
            start = i + 1
            break
    if start is None:
        return markdown.rstrip() + f"\n\n{image}\n"
    section_end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].startswith("## "):
            section_end = i
            break
    table_at = None
    for i in range(start, section_end):
        if lines[i].strip().startswith("|"):
            table_at = i
            break
    if table_at is None:
        return markdown.rstrip() + f"\n\n{image}\n"

    table_end = table_at
    while table_end < section_end and lines[table_end].strip().startswith("|"):
        table_end += 1
    rows = [_split_md_row(lines[i]) for i in range(table_at, table_end)]
    sep_at = next((i for i, cells in enumerate(rows) if _is_sep_row(cells)), None)
    # markitdown puts Excel row 0 in the header and a separator on the next line.
    if sep_at == 1:
        md_index = 0 if row == 0 else row + 1
    else:
        md_index = row
    if md_index < 0 or md_index >= len(rows) or (sep_at is not None and md_index == sep_at):
        lines.insert(table_end, image)
        return "\n".join(lines).rstrip() + "\n"
    cells = rows[md_index]
    while len(cells) <= col:
        cells.append("")
    current = cells[col]
    if current in {"", "NaN"}:
        cells[col] = image
    else:
        cells[col] = f"{current} {image}"
    lines[table_at + md_index] = _join_md_row(cells)
    return "\n".join(lines).rstrip() + "\n"


def inject_xlsx_drawing_images(
    xlsx_path: Path,
    markdown: str,
    assets_dir: Path,
    rel_prefix: str,
) -> tuple[str, int]:
    """Save xl/drawings pictures and splice them into the anchored cell."""
    path = Path(xlsx_path)
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        return markdown, 0
    text = markdown
    saved = 0
    seen_members: dict[str, str] = {}
    with zf:
        names = set(zf.namelist())
        for sheet, drawing in _sheet_drawings(zf, names):
            rels_name = posixpath.normpath(
                posixpath.join(
                    posixpath.dirname(drawing),
                    "_rels",
                    posixpath.basename(drawing) + ".rels",
                )
            )
            if rels_name not in names:
                continue
            rid_to_target = _parse_rels(zf.read(rels_name))
            try:
                anchors = _anchor_pictures(zf.read(drawing))
            except ET.ParseError:
                continue
            for row, col, rid in anchors:
                target = rid_to_target.get(rid)
                if not target:
                    continue
                hit = _read_member(zf, names, target)
                if hit is None:
                    continue
                member, data = hit
                rel = seen_members.get(member)
                if rel is None:
                    saved += 1
                    ext = _ext_from_member(member)
                    filename = f"image_draw_{saved:03d}.{ext}"
                    assets_dir.mkdir(parents=True, exist_ok=True)
                    (assets_dir / filename).write_bytes(data)
                    rel = f"{rel_prefix}/{filename}"
                    seen_members[member] = rel
                text = splice_drawing_into_markdown(text, sheet, row, col, rel)
    return text, len(seen_members)


def is_xlsx_like(path: Path) -> bool:
    if path.suffix.lower() in XLSX_SUFFIXES:
        return True
    try:
        with zipfile.ZipFile(path) as zf:
            return any(name.rstrip("/") == "xl/workbook.xml" or name.startswith("xl/") for name in zf.namelist())
    except (OSError, zipfile.BadZipFile):
        return False
