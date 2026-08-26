#!/usr/bin/env python3
"""Convert a local Markdown file (plus sibling *_assets/) to PDF.

Usage:
  md_to_pdf.py <input.md> [-o OUTPUT.pdf] [--engine chrome|typst]
               [--theme default|brand] [--no-toc] [--keep-ocr]

Default engine is Chrome print (no extra install). Typst is optional and used
for branded typesetting (`--engine typst --theme brand`). Markdown stays the
source of truth. Do not call WPS convert APIs or drive the WPS client.
"""

from __future__ import annotations

import argparse
import html as html_lib
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from md_to_typst import (  # noqa: E402
    TypstError,
    compile_typst,
    markdown_to_typst_source,
    theme_tokens,
)

HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
VIDEO_TAG_RE = re.compile(r"<video\b([^>]*)>(.*?)</video>", re.IGNORECASE | re.DOTALL)
IFRAME_TAG_RE = re.compile(r"<iframe\b([^>]*)>(.*?)</iframe>", re.IGNORECASE | re.DOTALL)
ATTR_SRC_RE = re.compile(r"""\bsrc\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
HTML_SRC_RE = re.compile(
    r"""(?P<attr>\b(?:src|href)\s*=\s*)(?P<q>["'])(?P<url>[^"']+)(?P=q)""",
    re.IGNORECASE,
)
PDF_PREVIEW_HINT_RE = re.compile(r"网页预览分页截图")
PAGE_HEADING_RE = re.compile(r"^## 第\s+\d+\s+页\s*$", re.MULTILINE)
HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)

ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TOC_MARKER_RE = re.compile(r"(?m)^\[TOC\]\s*$")

def print_css(theme: str = "default") -> str:
    c = theme_tokens(theme)
    h1_extra = (
        f"color: {c['navy']}; border-bottom: 1.5px solid {c['accent']}; "
        "padding-bottom: 0.18em;"
        if theme == "brand"
        else ""
    )
    h2_extra = f"color: {c['navy']};" if theme == "brand" else ""
    return f"""
@page {{ size: A4; margin: 20mm 14mm 18mm 14mm; }}
html, body {{
  font-family: "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC",
    "Microsoft YaHei", "Source Han Sans SC", sans-serif;
  font-size: 12pt;
  line-height: 1.45;
  color: {c["text"]};
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}}
img {{ max-width: 100%; height: auto; page-break-inside: avoid; }}
h1, h2, h3 {{ page-break-after: avoid; }}
h1 {{ {h1_extra} }}
h2 {{ {h2_extra} }}
pre, code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
pre {{ white-space: pre-wrap; word-break: break-word; background: {c["code_bg"]}; padding: 8px 10px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.9em; margin: 0.6em 0; }}
th, td {{ border: 1px solid {c["table_stroke"]}; padding: 4px 8px; vertical-align: top; }}
th {{ background: {c["table_head"]}; color: {c["navy"]}; }}
a {{ color: {c["accent"]}; }}
blockquote {{ color: #444; border-left: 3px solid {c["quote"]}; margin-left: 0; padding-left: 12px; }}
.ocr-aux {{
  font-size: 8px;
  line-height: 1.25;
  color: #888;
  max-height: 4.8em;
  overflow: hidden;
  margin: 0.15em 0 0.8em;
}}
.video-fallback, .iframe-fallback {{ margin: 0.6em 0; }}
.page-figure {{ margin: 0.4em 0 0.2em; }}
div.toc {{ font-size: 0.92em; margin: 0 0 1.6em; }}
div.toc .toctitle {{
  display: block;
  font-size: 1.15em;
  font-weight: 600;
  margin: 0 0 0.45em;
  color: {c["navy"]};
}}
div.toc ul {{ padding-left: 1.2em; margin: 0.2em 0; }}
div.toc a {{ color: inherit; text-decoration: none; }}
"""


# Back-compat for tests that look for PingFang in PRINT_CSS / default HTML.
PRINT_CSS = print_css("default")


class MdPdfError(Exception):
    pass


def default_pdf_output(md_path: Path) -> Path:
    return md_path.with_suffix(".pdf")


def document_title(md_text: str, fallback: str) -> str:
    """First ATX h1, else fallback (usually the file stem)."""
    for level, title in iter_headings(md_text):
        if level == 1 and title:
            return title
    return fallback or "document"


def iter_headings(md_text: str) -> list[tuple[int, str]]:
    """ATX headings outside fenced code blocks."""
    heads: list[tuple[int, str]] = []
    in_fence = False
    for line in (md_text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = ATX_HEADING_RE.match(stripped)
        if m:
            heads.append((len(m.group(1)), m.group(2).strip()))
    return heads


def inject_toc_marker(md_text: str) -> str:
    """Insert [TOC] after the first h1 when there are at least two h2/h3 sections."""
    text = md_text or ""
    if TOC_MARKER_RE.search(text):
        return text
    sections = [t for level, t in iter_headings(text) if level in {2, 3} and t]
    if len(sections) < 2:
        return text
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    inserted = False
    i = 0
    while i < len(lines):
        out.append(lines[i])
        if not inserted and re.match(r"^# [^#]", lines[i].strip("\n")):
            i += 1
            while i < len(lines) and not lines[i].strip():
                out.append(lines[i])
                i += 1
            out.append("\n[TOC]\n\n")
            inserted = True
            continue
        i += 1
    if not inserted:
        return "[TOC]\n\n" + text
    return "".join(out)


def strip_html_comments(text: str) -> str:
    return HTML_COMMENT_RE.sub("", text)


def _attr_src(attrs: str) -> str:
    m = ATTR_SRC_RE.search(attrs or "")
    return (m.group(1) if m else "").strip()


def degrade_video_tags(text: str) -> str:
    """Replace <video> with a plain link — PDF cannot play embedded video."""

    def repl(match: re.Match[str]) -> str:
        src = _attr_src(match.group(1))
        if not src:
            return ""
        label = Path(unquote(src.split("?")[0])).name or "视频"
        return (
            f'\n\n<p class="video-fallback">'
            f'<a href="{html_lib.escape(src, quote=True)}">{html_lib.escape(label)}</a>'
            f"（PDF 无法内嵌播放）</p>\n\n"
        )

    return VIDEO_TAG_RE.sub(repl, text)


def degrade_iframe_tags(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        src = _attr_src(match.group(1))
        if not src:
            return ""
        return (
            f'\n\n<p class="iframe-fallback">'
            f'<a href="{html_lib.escape(src, quote=True)}">打开嵌入内容</a>'
            f"</p>\n\n"
        )

    return IFRAME_TAG_RE.sub(repl, text)


def is_pdf_preview_markdown(text: str) -> bool:
    return bool(PDF_PREVIEW_HINT_RE.search(text or ""))


def _consume_pdf_preview_ocr_lines(lines: list[str], i: int) -> tuple[int, str]:
    """Advance past OCR text under a page image. Returns (next_index, ocr_text)."""
    ocr: list[str] = []
    while i < len(lines):
        nxt = lines[i]
        stripped = nxt.strip()
        if not stripped:
            if ocr:
                ocr.append(nxt)
                i += 1
                continue
            break
        if PAGE_HEADING_RE.match(stripped) or (
            stripped.startswith("#") and HEADING_RE.match(stripped)
        ):
            break
        if MD_IMAGE_RE.search(nxt):
            break
        if stripped.startswith("<"):
            break
        ocr.append(nxt)
        i += 1
    while ocr and not ocr[-1].strip():
        ocr.pop()
    return i, "".join(ocr).strip("\n")


def demote_pdf_preview_ocr(text: str, *, keep_ocr: bool = False) -> str:
    """Keep page images as the source of truth.

    Default: drop OCR under each page image (it duplicates slide text in the PDF).
    ``keep_ocr=True`` wraps OCR in a small gray ``.ocr-aux`` block.
    """
    if not is_pdf_preview_markdown(text):
        return text
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        if PAGE_HEADING_RE.match(line.strip("\n")):
            i += 1
            while i < len(lines) and not lines[i].strip():
                out.append(lines[i])
                i += 1
            if i < len(lines) and MD_IMAGE_RE.search(lines[i]):
                out.append(lines[i])
                i += 1
                while i < len(lines) and not lines[i].strip():
                    out.append(lines[i])
                    i += 1
                i, body = _consume_pdf_preview_ocr_lines(lines, i)
                if keep_ocr and body:
                    escaped = html_lib.escape(body).replace("\n", "<br>\n")
                    out.append(f'<div class="ocr-aux">{escaped}</div>\n')
                continue
        i += 1
    return "".join(out)


def is_remote_or_data_url(url: str) -> bool:
    raw = (url or "").strip()
    if not raw:
        return True
    lower = raw.lower()
    if lower.startswith(("http://", "https://", "data:", "mailto:", "#")):
        return True
    parsed = urlparse(raw)
    return bool(parsed.scheme in {"http", "https", "data", "mailto"})


def resolve_local_url(url: str, md_dir: Path) -> str | None:
    """Turn a relative Markdown/HTML URL into a file:// URI if the file exists."""
    raw = (url or "").strip()
    if not raw or is_remote_or_data_url(raw):
        return None
    if raw.startswith("file:"):
        return raw
    path_part = unquote(raw.split("#", 1)[0].split("?", 1)[0])
    candidate = Path(path_part)
    if not candidate.is_absolute():
        candidate = (md_dir / candidate).resolve()
    if not candidate.is_file():
        return None
    return candidate.as_uri()


def rewrite_local_urls(html: str, md_dir: Path) -> str:
    """Rewrite relative img/src and href to file:// so Chrome can load assets."""

    def repl_html(match: re.Match[str]) -> str:
        url = match.group("url")
        resolved = resolve_local_url(url, md_dir)
        if not resolved:
            return match.group(0)
        return f"{match.group('attr')}{match.group('q')}{resolved}{match.group('q')}"

    html = HTML_SRC_RE.sub(repl_html, html)

    def repl_md_img(match: re.Match[str]) -> str:
        alt, url = match.group(1), match.group(2)
        resolved = resolve_local_url(url, md_dir)
        target = resolved or url
        return f"![{alt}]({target})"

    return MD_IMAGE_RE.sub(repl_md_img, html)


def preprocess_markdown(
    text: str,
    md_dir: Path,
    *,
    keep_ocr: bool = False,
    toc: bool = True,
    rewrite_urls: bool = True,
) -> str:
    text = strip_html_comments(text)
    text = degrade_video_tags(text)
    text = degrade_iframe_tags(text)
    text = demote_pdf_preview_ocr(text, keep_ocr=keep_ocr)
    if toc and not is_pdf_preview_markdown(text):
        text = inject_toc_marker(text)
    if rewrite_urls:
        return rewrite_local_urls(text, md_dir)
    return text


def markdown_to_body_html(text: str) -> str:
    try:
        import markdown as md_lib
    except ImportError as e:
        raise MdPdfError(
            "Missing dependency 'markdown'. Install with:\n"
            f"  {sys.executable} -m pip install markdown"
        ) from e
    return md_lib.markdown(
        text,
        extensions=["extra", "sane_lists", "nl2br", "toc"],
        extension_configs={
            "toc": {
                "marker": "[TOC]",
                "title": "目录",
                "toc_depth": "2-3",
                "permalink": False,
            }
        },
        output_format="html",
    )


def wrap_document(body_html: str, *, title: str, theme: str = "default") -> str:
    safe_title = html_lib.escape(title or "document")
    css = print_css(theme)
    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
        '<meta charset="utf-8"/>\n'
        f"<title>{safe_title}</title>\n"
        f"<style>{css}</style>\n"
        "</head>\n<body>\n"
        f"{body_html}\n"
        "</body>\n</html>\n"
    )


def build_print_html(
    md_text: str,
    md_path: Path,
    *,
    keep_ocr: bool = False,
    toc: bool = True,
    theme: str = "default",
) -> str:
    md_dir = md_path.parent.resolve()
    prepared = preprocess_markdown(md_text, md_dir, keep_ocr=keep_ocr, toc=toc)
    body = markdown_to_body_html(prepared)
    body = rewrite_local_urls(body, md_dir)
    title = document_title(md_text, md_path.stem)
    return wrap_document(body, title=title, theme=theme)


def header_template(theme: str = "default") -> str:
    c = theme_tokens(theme)
    return f"""
<div style="font-size:9px;color:{c['muted']};width:100%;padding:0 14mm;
  font-family:'PingFang SC','Microsoft YaHei',sans-serif;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  border-bottom:1.5px solid {c['header_bar']};">
  <span class="title" style="color:{c['navy']};font-weight:600;"></span>
</div>
"""


def footer_template(theme: str = "default") -> str:
    c = theme_tokens(theme)
    return f"""
<div style="font-size:9px;color:{c['muted']};width:100%;padding:0 14mm;text-align:center;
  font-family:'PingFang SC','Microsoft YaHei',sans-serif;">
  <span class="pageNumber"></span> / <span class="totalPages"></span>
</div>
"""


HEADER_TEMPLATE = header_template("default")
FOOTER_TEMPLATE = footer_template("default")


def render_pdf_with_chrome(
    html: str, output_pdf: Path, *, md_dir: Path, theme: str = "default"
) -> None:
    """Print HTML via system Chrome. Writes a sibling temp file so local images load."""
    from playwright.sync_api import sync_playwright

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    tmp = md_dir / f".doc2md_print_{output_pdf.stem}.html"
    try:
        tmp.write_text(html, encoding="utf-8")
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page()
            page.goto(tmp.as_uri(), wait_until="load", timeout=60000)
            try:
                page.evaluate(
                    """() => Promise.all([...document.images].map((img) =>
                      img.complete ? Promise.resolve() :
                      new Promise((r) => { img.onload = img.onerror = r; })
                    ))"""
                )
            except Exception:
                pass
            page.pdf(
                path=str(output_pdf),
                format="A4",
                print_background=True,
                display_header_footer=True,
                header_template=header_template(theme),
                footer_template=footer_template(theme),
                margin={
                    "top": "20mm",
                    "bottom": "18mm",
                    "left": "14mm",
                    "right": "14mm",
                },
            )
            browser.close()
    except MdPdfError:
        raise
    except Exception as e:
        raise MdPdfError(
            f"Chrome print failed: {e}\n"
            "Need system Google Chrome (Playwright channel=chrome)."
        ) from e
    finally:
        tmp.unlink(missing_ok=True)
    if not output_pdf.is_file() or output_pdf.stat().st_size < 100:
        raise MdPdfError("Chrome print produced an empty PDF.")


def render_pdf_with_typst(
    md_text: str,
    md_path: Path,
    output_pdf: Path,
    *,
    keep_ocr: bool = False,
    toc: bool = True,
    theme: str = "brand",
) -> str:
    """Write a temp .typ next to the Markdown and compile. Returns Typst source."""
    md_dir = md_path.parent.resolve()
    # Keep relative asset paths; Typst resolves them from the .typ file.
    prepared = preprocess_markdown(
        md_text,
        md_dir,
        keep_ocr=keep_ocr,
        toc=False,  # Typst outline is generated from headings, not [TOC]
        rewrite_urls=False,
    )
    title = document_title(md_text, md_path.stem)
    sections = [t for level, t in iter_headings(md_text) if level in {2, 3} and t]
    want_toc = toc and len(sections) >= 2
    source = markdown_to_typst_source(
        prepared,
        title=title,
        theme=theme,
        toc=want_toc,
        pdf_preview=is_pdf_preview_markdown(md_text),
    )
    tmp = md_dir / f".doc2md_print_{output_pdf.stem}.typ"
    try:
        tmp.write_text(source, encoding="utf-8")
        compile_typst(tmp, output_pdf, root=md_dir)
    except TypstError as e:
        raise MdPdfError(str(e)) from e
    except Exception as e:
        raise MdPdfError(f"Typst compile failed: {e}") from e
    finally:
        tmp.unlink(missing_ok=True)
    if not output_pdf.is_file() or output_pdf.stat().st_size < 100:
        raise MdPdfError("Typst produced an empty PDF.")
    return source


def markdown_file_to_pdf(
    md_path: Path,
    output_pdf: Path | None = None,
    *,
    keep_ocr: bool = False,
    toc: bool = True,
    engine: str = "chrome",
    theme: str = "default",
) -> dict:
    src = md_path.expanduser().resolve()
    if not src.is_file():
        raise MdPdfError(f"Markdown file not found: {src}")
    if src.suffix.lower() not in {".md", ".markdown"}:
        raise MdPdfError(f"Expected a .md file, got: {src}")
    dest = (output_pdf or default_pdf_output(src)).expanduser().resolve()
    text = src.read_text(encoding="utf-8")
    engine_key = (engine or "chrome").strip().lower()
    theme_key = (theme or "default").strip().lower()
    try:
        theme_tokens(theme_key)
    except TypstError as e:
        raise MdPdfError(str(e)) from e

    if engine_key == "chrome":
        html = build_print_html(
            text, src, keep_ocr=keep_ocr, toc=toc, theme=theme_key
        )
        render_pdf_with_chrome(html, dest, md_dir=src.parent, theme=theme_key)
        used_toc = '<div class="toc">' in html
    elif engine_key == "typst":
        html = ""
        source = render_pdf_with_typst(
            text,
            src,
            dest,
            keep_ocr=keep_ocr,
            toc=toc,
            theme=theme_key,
        )
        used_toc = toc and not is_pdf_preview_markdown(text) and "#outline(" in source
    else:
        raise MdPdfError(f"Unknown engine: {engine!r} (use chrome or typst)")

    return {
        "input": str(src),
        "output": str(dest),
        "bytes": dest.stat().st_size,
        "pdf_preview": is_pdf_preview_markdown(text),
        "keep_ocr": keep_ocr,
        "toc": used_toc,
        "engine": engine_key,
        "theme": theme_key,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert local Markdown (+ *_assets/) to PDF (Chrome default; Typst optional)."
    )
    parser.add_argument("input", help="Path to a .md file")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output .pdf path")
    parser.add_argument(
        "--engine",
        choices=("chrome", "typst"),
        default="chrome",
        help="PDF engine. chrome is default; typst needs the Typst CLI (win/mac/linux) or pip wheel",
    )
    parser.add_argument(
        "--theme",
        choices=("default", "brand"),
        default="default",
        help="Layout theme. brand is navy/accent report styling (no logo)",
    )
    parser.add_argument(
        "--keep-ocr",
        action="store_true",
        help="For WPS PDF-preview Markdown, keep OCR text under each page image",
    )
    parser.add_argument(
        "--no-toc",
        action="store_true",
        help="Do not insert a table of contents from h2/h3 headings",
    )
    args = parser.parse_args(argv)

    try:
        result = markdown_file_to_pdf(
            Path(args.input),
            args.output,
            keep_ocr=args.keep_ocr,
            toc=not args.no_toc,
            engine=args.engine,
            theme=args.theme,
        )
    except MdPdfError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: Unexpected failure: {e}", file=sys.stderr)
        return 1

    print("OK")
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
