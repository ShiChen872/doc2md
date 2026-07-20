#!/usr/bin/env python3
"""Convert documents to Markdown with images extracted to a local assets folder.

Usage:
  convert.py <input_file> [-o OUTPUT.md] [--assets-dir DIR]

Images embedded as data URIs are decoded and saved under <stem>_assets/.
For PDF, markitdown drops images; PyMuPDF extracts them per page and appends
markdown image links after each page's content.
For PPTX, each slide becomes theme text + one full-slide screenshot
(office2pdf → PDF → PNG; LibreOffice is only an optional fallback).
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


MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
SLIDE_SPLIT_RE = re.compile(r"<!--\s*Slide number:\s*(\d+)\s*-->", re.IGNORECASE)


def _find_soffice() -> str | None:
    candidates = [
        "soffice",
        "/opt/homebrew/bin/soffice",
        "/usr/local/bin/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    import shutil

    for c in candidates:
        if Path(c).is_file():
            return c
        found = shutil.which(c)
        if found:
            return found
    return None


def pptx_to_pdf(pptx_path: Path, out_dir: Path) -> Path:
    """Convert PPTX to PDF. Prefer pure-Python office2pdf; fall back to LibreOffice."""
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "_slides_preview.pdf"

    # 1) office2pdf — pip package, no LibreOffice / MS Office required
    office2pdf_err: Exception | None = None
    try:
        from office2pdf import Format, convert_bytes

        result = convert_bytes(pptx_path.read_bytes(), Format.PPTX)
        dest.write_bytes(result.pdf)
        return dest
    except ImportError:
        office2pdf_err = None
    except Exception as e:
        office2pdf_err = e

    # 2) LibreOffice soffice — optional system dependency
    import subprocess
    import tempfile

    soffice = _find_soffice()
    if soffice:
        with tempfile.TemporaryDirectory(prefix="doc2md_pptx_") as tmp:
            tmp_path = Path(tmp)
            safe_in = tmp_path / "input.pptx"
            safe_in.write_bytes(pptx_path.read_bytes())
            cmd = [
                soffice,
                "--headless",
                "--nologo",
                "--nofirststartwizard",
                "--convert-to",
                "pdf",
                "--outdir",
                str(tmp_path),
                str(safe_in),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            pdf = tmp_path / "input.pdf"
            if pdf.is_file():
                dest.write_bytes(pdf.read_bytes())
                return dest
            lo_err = f"stdout={proc.stdout[:300]} stderr={proc.stderr[:300]}"
        raise RuntimeError(
            "PPTX→PDF failed with both office2pdf and LibreOffice.\n"
            f"office2pdf: {office2pdf_err!r}\n"
            f"LibreOffice: {lo_err}"
        )

    hint = (
        "Install the Python package: pip install office2pdf-python\n"
        "Or install LibreOffice (soffice) as a fallback."
    )
    if office2pdf_err is not None:
        raise RuntimeError(f"PPTX→PDF via office2pdf failed: {office2pdf_err}\n{hint}") from office2pdf_err
    raise RuntimeError(f"No PPTX→PDF backend available.\n{hint}")


def render_pdf_pages(
    pdf_path: Path, assets_dir: Path, rel_prefix: str, *, dpi: int = 144
) -> list[str]:
    """Render each PDF page to PNG. Returns relative markdown paths in page order."""
    import fitz

    assets_dir.mkdir(parents=True, exist_ok=True)
    # clear old slide_*.png
    for old in assets_dir.glob("slide_*.png"):
        old.unlink()

    doc = fitz.open(pdf_path)
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    refs: list[str] = []
    for i in range(len(doc)):
        page = doc[i]
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        filename = f"slide_{i + 1:03d}.png"
        pix.save(str(assets_dir / filename))
        refs.append(f"{rel_prefix}/{filename}")
    doc.close()
    return refs


def extract_slide_texts(pptx_path: Path) -> list[str]:
    """Get thematic text per slide via markitdown, stripping per-shape image placeholders."""
    from markitdown import MarkItDown

    raw = MarkItDown().convert(str(pptx_path), keep_data_uris=False).text_content or ""
    parts = SLIDE_SPLIT_RE.split(raw)
    # parts: [preamble, num1, body1, num2, body2, ...]
    slides: dict[int, str] = {}
    if len(parts) >= 3:
        for i in range(1, len(parts), 2):
            try:
                num = int(parts[i])
            except ValueError:
                continue
            body = parts[i + 1] if i + 1 < len(parts) else ""
            # Drop markitdown's fake image placeholders and empty noise
            body = MD_IMAGE_RE.sub("", body)
            body = re.sub(r"\n{3,}", "\n\n", body).strip()
            # Drop lonely "### Notes:" with no content
            if re.fullmatch(r"### Notes:\s*", body):
                body = ""
            body = re.sub(r"\n### Notes:\s*$", "", body).strip()
            slides[num] = body
    if slides:
        max_n = max(slides)
        return [slides.get(i, "") for i in range(1, max_n + 1)]

    # Fallback: whole deck as one text block
    text = MD_IMAGE_RE.sub("", raw)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return [text] if text else [""]


def convert_pptx_as_slides(
    pptx_path: Path, assets_dir: Path, rel_prefix: str, *, dpi: int = 144
) -> tuple[str, int]:
    """Build Markdown: per-slide theme text + one full-slide screenshot.

    Does NOT extract individual icons/pictures from the deck.
    """
    import tempfile

    texts = extract_slide_texts(pptx_path)

    with tempfile.TemporaryDirectory(prefix="doc2md_pptx_render_") as tmp:
        pdf = pptx_to_pdf(pptx_path, Path(tmp))
        slide_refs = render_pdf_pages(pdf, assets_dir, rel_prefix, dpi=dpi)

    n = max(len(texts), len(slide_refs))
    blocks: list[str] = [
        "> **Note:** PPTX is exported as per-slide text + full-slide screenshots "
        "(via office2pdf; not individual icons).\n"
    ]
    for i in range(n):
        num = i + 1
        text = texts[i].strip() if i < len(texts) else ""
        blocks.append(f"## Slide {num}\n")
        if text:
            blocks.append(text + "\n")
        if i < len(slide_refs):
            blocks.append(f"![Slide {num}]({slide_refs[i]})\n")
        blocks.append("")

    return "\n".join(blocks).strip() + "\n", len(slide_refs)


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

    suffix = input_path.suffix.lower()
    md = MarkItDown()
    uri_count = 0
    pdf_count = 0
    pptx_count = 0

    # PPTX: one screenshot per slide + theme text (not per-icon extraction).
    if suffix in {".pptx", ".pptm"}:
        # Clear previous icon dumps if re-converting
        if assets_dir.exists():
            for old in assets_dir.glob("image_*"):
                old.unlink()
            for old in assets_dir.glob("slide_*"):
                old.unlink()
        text, pptx_count = convert_pptx_as_slides(input_path, assets_dir, rel_prefix)
    else:
        # keep_data_uris must be passed to convert(), not __init__
        result = md.convert(str(input_path), keep_data_uris=True)
        text = result.text_content or ""
        text, uri_count = extract_data_uris(text, assets_dir, rel_prefix)

        if suffix == ".pdf":
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
        "images_from_pptx": pptx_count,
        "images_total": uri_count + pdf_count + pptx_count,
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
