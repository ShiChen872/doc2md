#!/usr/bin/env python3
"""Convert WPS intelligent-document (.otl) JSON to Markdown.

Usage:
  otl_to_md.py <otl.json> [-o OUTPUT.md] [--assets-dir DIR] [--image IMAGE ...]
  otl_to_md.py <otl.json> -o out.md --assets-dir out_assets --image img1.png --image img2.png

Images are keyed by OTL picture `sourceKey` / `imgID` whenever possible.
`--image` still accepts files in full-tree picture order (legacy); convert_file
builds a key→file map from the OTL so emit order cannot shift assignments.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


CONTAINER_TYPES = (
    "logic_block",
    "block_tile",
    "image_column",
    "image_column_container",
    "doc",
    "sub_doc",
    "sub_doc_tile",
    "HighlightBlock",
    "native_inline_container",
    "circle_object",
    "sub_doc_layout_object",
    "sub_doc_object",
)


def picture_keys(attrs: dict | None) -> list[str]:
    """Stable lookup keys for a picture node (sourceKey preferred, then imgID)."""
    if not isinstance(attrs, dict):
        return []
    keys: list[str] = []
    for field in ("sourceKey", "imgID"):
        v = attrs.get(field)
        if v is None:
            continue
        s = str(v).strip()
        if s and s not in keys:
            keys.append(s)
    return keys


def iter_otl_picture_attrs(raw: dict) -> list[dict]:
    """Return picture attrs in full-tree document order."""
    pics: list[dict] = []

    def walk(n: object) -> None:
        if isinstance(n, dict):
            if n.get("type") == "picture":
                attrs = n.get("attrs") if isinstance(n.get("attrs"), dict) else {}
                pics.append(attrs)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for i in n:
                walk(i)

    walk(raw.get("content") or raw)
    return pics


def render_inline(node: dict) -> str:
    if node.get("type") == "text":
        t = node.get("text") or ""
        for m in node.get("marks") or []:
            if not isinstance(m, dict):
                continue
            mt = m.get("type")
            if mt in ("bold", "strong"):
                t = f"**{t}**"
            elif mt in ("italic", "em"):
                t = f"*{t}*"
            elif mt == "code":
                t = f"`{t}`"
            elif mt == "link":
                href = (m.get("attrs") or {}).get("href") or ""
                t = f"[{t}]({href})"
        return t
    if node.get("type") == "emoji":
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        return str(attrs.get("emoji") or "")
    return "".join(
        render_inline(c) for c in (node.get("content") or []) if isinstance(c, dict)
    )


def _resolve_image_name(
    attrs: dict,
    *,
    image_map: dict[str, str],
    image_names: list[str],
    emit_index: int,
) -> str:
    for key in picture_keys(attrs):
        name = image_map.get(key)
        if name:
            return name
    # Legacy fallback: emit-order list (only safe when no pictures were skipped)
    if 0 <= emit_index < len(image_names):
        return image_names[emit_index] or ""
    return ""


def _picture_markdown(
    attrs: dict,
    *,
    image_map: dict[str, str],
    image_names: list[str],
    emit_index: int,
    assets_rel: str,
    n: int,
) -> str:
    name = _resolve_image_name(
        attrs, image_map=image_map, image_names=image_names, emit_index=emit_index
    )
    if name:
        rel = f"{assets_rel}/{name}" if assets_rel else name
        return f"![image {n}]({rel})"
    img_id = attrs.get("imgID") or attrs.get("sourceKey") or ""
    return f"<!-- missing picture {n} {img_id} -->"


def _collect_cell_md(
    node: object,
    *,
    image_map: dict[str, str],
    image_names: list[str],
    pic_i: dict,
    assets_rel: str,
) -> str:
    """Collect cell markdown: text + any pictures (keyed, not index-shifted)."""
    parts: list[str] = []

    def walk(n: object) -> None:
        if isinstance(n, dict):
            t = n.get("type") or ""
            attrs = n.get("attrs") if isinstance(n.get("attrs"), dict) else {}
            if t == "text" or t == "emoji":
                parts.append(render_inline(n))
                return
            if t == "outline-table":
                return
            if t == "picture":
                pic_i["n"] += 1
                md = _picture_markdown(
                    attrs,
                    image_map=image_map,
                    image_names=image_names,
                    emit_index=pic_i["n"] - 1,
                    assets_rel=assets_rel,
                    n=pic_i["n"],
                )
                # Keep pipe-safe for table cells
                parts.append(md.replace("|", "\\|"))
                return
            for c in n.get("content") or []:
                walk(c)
        elif isinstance(n, list):
            for x in n:
                walk(x)

    walk(node)
    text = " ".join(p for p in parts if p).strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return " "
    return re.sub(r"(?<!\\)\|", r"\\|", text)


def otl_to_markdown(
    raw: dict,
    *,
    image_names: list[str] | None = None,
    image_map: dict[str, str] | None = None,
    assets_rel: str = "",
    source_note: str | None = None,
) -> str:
    """Convert parsed OTL JSON to Markdown text.

    Prefer `image_map` keyed by sourceKey/imgID. `image_names` remains as a
    legacy emit-order fallback when a key is missing from the map.
    """
    image_names = list(image_names or [])
    image_map = dict(image_map or {})
    pic_i = {"n": 0}
    lines: list[str] = []

    def emit(node: object, depth: int = 0) -> None:
        if not isinstance(node, dict) or depth > 50:
            return
        t = node.get("type") or ""
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}

        if t in CONTAINER_TYPES:
            for c in node.get("content") or []:
                emit(c, depth + 1)
            return

        inline = render_inline(node).strip()

        if t == "outline-title":
            if inline:
                lines.append(f"# {inline}")
                lines.append("")
            return

        if t == "horizontal_rule":
            lines.append("\n---\n")
            return

        if t == "blockquote":
            if inline:
                for ln in inline.splitlines():
                    lines.append(f"> {ln}" if ln else ">")
                lines.append("")
            return

        if t == "outline-table":
            rows: list[list[str]] = []
            for row_node in node.get("content") or []:
                if not isinstance(row_node, dict) or row_node.get("type") != "outline-table-row":
                    continue
                cells: list[str] = []
                for cell_node in row_node.get("content") or []:
                    if not isinstance(cell_node, dict) or cell_node.get("type") != "outline-table-cell":
                        continue
                    cells.append(
                        _collect_cell_md(
                            cell_node,
                            image_map=image_map,
                            image_names=image_names,
                            pic_i=pic_i,
                            assets_rel=assets_rel,
                        )
                    )
                if cells:
                    rows.append(cells)
            if rows:
                width = max(len(r) for r in rows)
                for r in rows:
                    while len(r) < width:
                        r.append(" ")
                lines.append("| " + " | ".join(rows[0]) + " |")
                lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
                for r in rows[1:]:
                    lines.append("| " + " | ".join(r) + " |")
                lines.append("")
            return

        if t == "paragraph":
            lt = str(attrs.get("listType") or "")
            if lt and inline:
                prefix = "- " if "bullet" in lt else "1. "
                lines.append(prefix + inline)
                return
            if inline:
                lines.append(inline)
                lines.append("")
            return

        if t == "picture":
            pic_i["n"] += 1
            lines.append(
                _picture_markdown(
                    attrs,
                    image_map=image_map,
                    image_names=image_names,
                    emit_index=pic_i["n"] - 1,
                    assets_rel=assets_rel,
                    n=pic_i["n"],
                )
            )
            lines.append("")
            return

        if "heading" in t:
            m = re.search(r"(\d+)", t)
            lvl = int(m.group(1)) if m else int(attrs.get("level") or 2)
            if inline:
                lines.append(f"{'#' * min(max(lvl, 1), 6)} {inline}")
                lines.append("")
            return

        if t == "code_block":
            lang = ""
            if isinstance(attrs, dict):
                lang = str(attrs.get("lang") or attrs.get("language") or "").strip()

            def text_of(n: object) -> str:
                if isinstance(n, dict):
                    if n.get("type") == "text":
                        return n.get("text") or ""
                    return "".join(text_of(c) for c in (n.get("content") or []))
                if isinstance(n, list):
                    return "".join(text_of(x) for x in n)
                return ""

            lines.append(f"```{lang}")
            lines.append(text_of(node))
            lines.append("```")
            lines.append("")
            return

        for c in node.get("content") or []:
            emit(c, depth + 1)

    root = raw.get("content") or raw
    emit(root)
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines).strip() + "\n")

    header_parts: list[str] = []
    if source_note:
        header_parts.append(source_note.rstrip() + "\n")
    header = ("\n".join(header_parts) + "\n") if header_parts else ""
    return header + body


def load_otl(path: Path) -> dict:
    data = path.read_bytes()
    text = data.decode("utf-8")
    return json.loads(text)


def build_image_map_from_files(
    raw: dict,
    image_files: list[Path | None],
    assets_dir: Path,
) -> tuple[dict[str, str], list[str]]:
    """Save image_files (full-tree order) and return (key→name, ordered names)."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    pictures = iter_otl_picture_attrs(raw)
    image_map: dict[str, str] = {}
    image_names: list[str] = []

    for i, attrs in enumerate(pictures, 1):
        src = image_files[i - 1] if i - 1 < len(image_files) else None
        if src is None:
            image_names.append("")
            continue
        src = Path(src)
        if not src.is_file():
            image_names.append("")
            continue
        dest_name = src.name if src.parent == assets_dir else f"image_{i:03d}{src.suffix or '.png'}"
        dest = assets_dir / dest_name
        if src.resolve() != dest.resolve():
            dest.write_bytes(src.read_bytes())
        image_names.append(dest.name)
        for key in picture_keys(attrs):
            image_map[key] = dest.name
    return image_map, image_names


def convert_file(
    input_path: Path,
    output_path: Path,
    assets_dir: Path | None = None,
    image_files: list[Path | None] | None = None,
    source_url: str | None = None,
    image_map: dict[str, str] | None = None,
) -> dict:
    raw = load_otl(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if assets_dir is None:
        assets_dir = output_path.parent / f"{output_path.stem}_assets"

    image_names: list[str] = []
    resolved_map: dict[str, str] = dict(image_map or {})

    if image_files is not None:
        resolved_map, image_names = build_image_map_from_files(raw, image_files, assets_dir)
        # allow explicit image_map to override filenames if provided
        if image_map:
            resolved_map.update(image_map)
    elif resolved_map:
        # map already points at names under assets_dir
        image_names = []
    elif assets_dir.is_dir():
        # Legacy: sorted image_* — also try to key by matching picture order
        sorted_names = sorted(
            p.name
            for p in assets_dir.iterdir()
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        )
        image_names = list(sorted_names)
        pictures = iter_otl_picture_attrs(raw)
        for attrs, name in zip(pictures, sorted_names):
            for key in picture_keys(attrs):
                resolved_map.setdefault(key, name)

    try:
        rel = assets_dir.resolve().relative_to(output_path.parent.resolve()).as_posix()
    except ValueError:
        rel = assets_dir.as_posix()

    note = None
    if source_url:
        note = (
            f"> 来源: {source_url}\n"
            f"> 类型: WPS 智能文档 (.otl)\n"
            f"> 说明: 正文由 open/otl JSON 解析；图片来自页面临时 CDN（若有）。"
        )

    md = otl_to_markdown(
        raw,
        image_names=image_names,
        image_map=resolved_map,
        assets_rel=rel,
        source_note=note,
    )
    output_path.write_text(md, encoding="utf-8")

    pic_count = len(iter_otl_picture_attrs(raw))
    saved = len({n for n in resolved_map.values() if n}) or sum(1 for n in image_names if n)

    return {
        "input": str(input_path),
        "output": str(output_path),
        "assets_dir": str(assets_dir) if saved else None,
        "pictures_in_otl": pic_count,
        "images_saved": saved,
        "markdown_chars": len(md),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert WPS .otl JSON to Markdown.")
    parser.add_argument("input", type=Path, help="OTL JSON file")
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--assets-dir", type=Path, default=None)
    parser.add_argument("--image", type=Path, action="append", default=[], help="Image file (repeatable, full-tree order)")
    parser.add_argument("--source-url", default=None, help="Optional source URL note in Markdown")
    args = parser.parse_args(argv)

    inp = args.input.expanduser().resolve()
    out = (args.output or inp.with_suffix(".md")).expanduser().resolve()
    assets = args.assets_dir.expanduser().resolve() if args.assets_dir else None

    try:
        stats = convert_file(inp, out, assets, args.image or None, args.source_url)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print("OK")
    for k, v in stats.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
