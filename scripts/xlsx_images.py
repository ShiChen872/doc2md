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


def is_xlsx_like(path: Path) -> bool:
    return path.suffix.lower() in XLSX_SUFFIXES
