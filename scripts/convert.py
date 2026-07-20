#!/usr/bin/env python3
"""Convert documents to Markdown with images extracted to a local assets folder.

Usage:
  convert.py <input_file> [-o OUTPUT.md] [--assets-dir DIR]

Images embedded as data URIs are decoded and saved under <stem>_assets/.
For PDF, markitdown drops images; PyMuPDF extracts them per page and appends
markdown image links after each page's content.
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path

DATA_URI_RE = re.compile(
    r"!\[([^\]]*)\]\((data:image/([a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+))\)",
    re.MULTILINE,
)
# Also catch bare data URIs in HTML-ish or markitdown Image: forms
BARE_DATA_URI_RE = re.compile(
    r"(data:image/([a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+))",
    re.MULTILINE,
)

EXT_MAP = {
    "jpeg": "jpg",
    "jpg": "jpg",
    "png": "png",
    "gif": "gif",
    "webp": "webp",
    "bmp": "bmp",
    "svg+xml": "svg",
    "x-icon": "ico",
    "tiff": "tiff",
}


def _ext_for_mime(subtype: str) -> str:
    subtype = subtype.lower().split(";")[0].strip()
    return EXT_MAP.get(subtype, subtype.replace("+", "_") or "bin")


def extract_data_uris(markdown: str, assets_dir: Path, rel_prefix: str) -> tuple[str, int]:
    """Replace data-URI images with files under assets_dir. Returns (md, count)."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    counter = {"n": 0}

    def save_blob(subtype: str, b64: str) -> str:
        counter["n"] += 1
        ext = _ext_for_mime(subtype)
        filename = f"image_{counter['n']:03d}.{ext}"
        path = assets_dir / filename
        raw = base64.b64decode(re.sub(r"\s+", "", b64))
        path.write_bytes(raw)
        return f"{rel_prefix}/{filename}"

    def repl_md(m: re.Match) -> str:
        alt, _full, subtype, b64 = m.group(1), m.group(2), m.group(3), m.group(4)
        rel = save_blob(subtype, b64)
        return f"![{alt}]({rel})"

    out = DATA_URI_RE.sub(repl_md, markdown)

    # Remaining bare data URIs (e.g. inside HTML img src or markitdown variants)
    def repl_bare(m: re.Match) -> str:
        subtype, b64 = m.group(2), m.group(3)
        rel = save_blob(subtype, b64)
        return rel

    out = BARE_DATA_URI_RE.sub(repl_bare, out)
    return out, counter["n"]


def extract_pdf_images(pdf_path: Path, assets_dir: Path, rel_prefix: str) -> list[tuple[int, list[str]]]:
    """Return list of (1-based page_number, [relative image paths])."""
    import fitz  # PyMuPDF

    assets_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    results: list[tuple[int, list[str]]] = []
    global_idx = 0
    for page_index in range(len(doc)):
        page = doc[page_index]
        refs: list[str] = []
        for img in page.get_images(full=True):
            xref = img[0]
            try:
                extracted = doc.extract_image(xref)
            except Exception:
                continue
            ext = extracted.get("ext", "png")
            global_idx += 1
            filename = f"pdf_p{page_index + 1:03d}_{global_idx:03d}.{ext}"
            (assets_dir / filename).write_bytes(extracted["image"])
            refs.append(f"{rel_prefix}/{filename}")
        if refs:
            results.append((page_index + 1, refs))
    doc.close()
    return results


def inject_pdf_images(markdown: str, page_images: list[tuple[int, list[str]]]) -> str:
    """Append per-page image blocks. markitdown PDF output is usually continuous text;
    we append a dedicated section so images are not lost.
    """
    if not page_images:
        return markdown

    note = (
        "\n\n---\n\n"
        "> **Note:** PDF embedded images were extracted with PyMuPDF and grouped by page "
        "(approximate placement, not pixel-perfect original layout).\n"
    )
    blocks: list[str] = []
    for page_no, refs in page_images:
        lines = [f"\n### Page {page_no} images\n"]
        for i, rel in enumerate(refs, 1):
            lines.append(f"![Page {page_no} image {i}]({rel})")
        blocks.append("\n".join(lines))
    return markdown.rstrip() + note + "\n".join(blocks) + "\n"


def convert(input_path: Path, output_path: Path, assets_dir: Path | None = None) -> dict:
    if not input_path.is_file():
        raise FileNotFoundError(f"Input not found: {input_path}")

    # WPS intelligent-document JSON (from wps_download / open/otl)
    name_l = input_path.name.lower()
    if name_l.endswith(".otl.json") or name_l.endswith(".otl") or (
        input_path.suffix.lower() == ".json"
        and '"schemaVersion"' in input_path.read_text(encoding="utf-8", errors="ignore")[:2000]
    ):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from otl_to_md import convert_file

        return convert_file(input_path, output_path, assets_dir=assets_dir)

    from markitdown import MarkItDown

    output_path.parent.mkdir(parents=True, exist_ok=True)
    stem = output_path.stem
    if assets_dir is None:
        assets_dir = output_path.parent / f"{stem}_assets"
    # Relative path from markdown file to assets (POSIX style for markdown)
    try:
        rel_prefix = assets_dir.resolve().relative_to(output_path.parent.resolve()).as_posix()
    except ValueError:
        rel_prefix = assets_dir.as_posix()

    # keep_data_uris must be passed to convert(), not __init__
    md = MarkItDown()
    result = md.convert(str(input_path), keep_data_uris=True)
    text = result.text_content or ""

    text, uri_count = extract_data_uris(text, assets_dir, rel_prefix)

    pdf_count = 0
    if input_path.suffix.lower() == ".pdf":
        page_images = extract_pdf_images(input_path, assets_dir, rel_prefix)
        pdf_count = sum(len(refs) for _, refs in page_images)
        text = inject_pdf_images(text, page_images)

    output_path.write_text(text, encoding="utf-8")

    # Clean empty assets dir if nothing was saved
    if assets_dir.exists() and not any(assets_dir.iterdir()):
        assets_dir.rmdir()
        assets_dir_str = None
    else:
        assets_dir_str = str(assets_dir)

    stats = {
        "input": str(input_path),
        "output": str(output_path),
        "assets_dir": assets_dir_str,
        "images_from_data_uri": uri_count,
        "images_from_pdf": pdf_count,
        "images_total": uri_count + pdf_count,
        "markdown_chars": len(text),
    }
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert documents to Markdown with local image assets.")
    parser.add_argument("input", type=Path, help="Input document path")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output .md path")
    parser.add_argument("--assets-dir", type=Path, default=None, help="Directory for extracted images")
    args = parser.parse_args(argv)

    input_path = args.input.expanduser().resolve()
    if args.output:
        output_path = args.output.expanduser().resolve()
    else:
        output_path = input_path.with_suffix(".md")

    assets_dir = args.assets_dir.expanduser().resolve() if args.assets_dir else None

    try:
        stats = convert(input_path, output_path, assets_dir)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print("OK")
    for k, v in stats.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
