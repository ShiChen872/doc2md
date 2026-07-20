#!/usr/bin/env python3
"""Convert WPS intelligent-document (.otl) JSON to Markdown.

Usage:
  otl_to_md.py <otl.json> [-o OUTPUT.md] [--assets-dir DIR] [--image IMAGE ...]
  otl_to_md.py <otl.json> -o out.md --assets-dir out_assets --image img1.png --image img2.png

Images are referenced in document order as picture nodes appear in the OTL tree.
Pass local image filenames (already saved under assets-dir) with --image in order.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


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
    return "".join(
        render_inline(c) for c in (node.get("content") or []) if isinstance(c, dict)
    )


def otl_to_markdown(
    raw: dict,
    *,
    image_names: list[str] | None = None,
    assets_rel: str = "",
    source_note: str | None = None,
) -> str:
    """Convert parsed OTL JSON to Markdown text."""
    image_names = list(image_names or [])
    pic_i = {"n": 0}
    lines: list[str] = []

    def emit(node: object, depth: int = 0) -> None:
        if not isinstance(node, dict) or depth > 50:
            return
        t = node.get("type") or ""
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}

        if t in ("logic_block", "block_tile", "image_column", "image_column_container", "doc"):
            for c in node.get("content") or []:
                emit(c, depth + 1)
            return

        inline = render_inline(node).strip()

        if t == "outline-title":
            if inline:
                lines.append(f"# {inline}")
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
            idx = pic_i["n"] - 1
            if 0 <= idx < len(image_names):
                name = image_names[idx]
                rel = f"{assets_rel}/{name}" if assets_rel else name
                lines.append(f"![image {pic_i['n']}]({rel})")
                lines.append("")
            else:
                img_id = attrs.get("imgID") or attrs.get("sourceKey") or ""
                lines.append(f"<!-- missing picture {pic_i['n']} {img_id} -->")
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
            def text_of(n: object) -> str:
                if isinstance(n, dict):
                    if n.get("type") == "text":
                        return n.get("text") or ""
                    return "".join(text_of(c) for c in (n.get("content") or []))
                if isinstance(n, list):
                    return "".join(text_of(x) for x in n)
                return ""

            lines.append("```")
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
    # allow raw json or utf-8 text
    text = data.decode("utf-8")
    return json.loads(text)


def convert_file(
    input_path: Path,
    output_path: Path,
    assets_dir: Path | None = None,
    image_files: list[Path] | None = None,
    source_url: str | None = None,
) -> dict:
    raw = load_otl(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if assets_dir is None:
        assets_dir = output_path.parent / f"{output_path.stem}_assets"

    image_names: list[str] = []
    if image_files:
        assets_dir.mkdir(parents=True, exist_ok=True)
        for i, src in enumerate(image_files, 1):
            src = Path(src)
            if not src.is_file():
                continue
            dest_name = src.name if src.parent == assets_dir else f"image_{i:03d}{src.suffix or '.png'}"
            dest = assets_dir / dest_name
            if src.resolve() != dest.resolve():
                dest.write_bytes(src.read_bytes())
            image_names.append(dest.name)
    elif assets_dir.is_dir():
        # pick image_* in sorted order
        image_names = sorted(
            p.name
            for p in assets_dir.iterdir()
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        )

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

    md = otl_to_markdown(raw, image_names=image_names, assets_rel=rel, source_note=note)
    output_path.write_text(md, encoding="utf-8")

    # count pictures in tree
    pic_count = {"n": 0}

    def count_pics(n: object) -> None:
        if isinstance(n, dict):
            if n.get("type") == "picture":
                pic_count["n"] += 1
            for v in n.values():
                count_pics(v)
        elif isinstance(n, list):
            for i in n:
                count_pics(i)

    count_pics(raw)

    return {
        "input": str(input_path),
        "output": str(output_path),
        "assets_dir": str(assets_dir) if image_names else None,
        "pictures_in_otl": pic_count["n"],
        "images_saved": len(image_names),
        "markdown_chars": len(md),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert WPS .otl JSON to Markdown.")
    parser.add_argument("input", type=Path, help="OTL JSON file")
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--assets-dir", type=Path, default=None)
    parser.add_argument("--image", type=Path, action="append", default=[], help="Image file (repeatable, in order)")
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
