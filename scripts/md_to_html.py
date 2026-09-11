#!/usr/bin/env python3
"""Write a readable HTML sidecar from Markdown (same assets, no extra convert).

Usage:
  md_to_html.py /path/to/out.md
  md_to_html.py /path/to/out.md -o /path/to/out.html

Markdown stays the conversion result. HTML is a local reading view: relative
image links are kept so `*_assets/` next to the .html still resolve.
"""

from __future__ import annotations

import argparse
import html as html_lib
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


SCREEN_CSS = """
:root { color-scheme: light; }
html { background: #f4f5f7; }
body {
  margin: 0 auto;
  padding: 32px 24px 64px;
  max-width: 52rem;
  font-family: "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC",
    "Microsoft YaHei", "Source Han Sans SC", sans-serif;
  font-size: 16px;
  line-height: 1.65;
  color: #1f2329;
  background: #fff;
  box-shadow: 0 0 0 1px #e8eaed;
}
img { max-width: 100%; height: auto; }
h1, h2, h3 { line-height: 1.35; }
h1 { font-size: 1.7rem; margin: 0 0 0.8em; }
h2 { font-size: 1.25rem; margin: 1.6em 0 0.6em; padding-top: 0.4em; border-top: 1px solid #eee; }
h3 { font-size: 1.08rem; }
p { margin: 0.7em 0; }
pre, code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
pre { white-space: pre-wrap; word-break: break-word; background: #f6f7f9; padding: 10px 12px; }
table { border-collapse: collapse; width: 100%; font-size: 0.92em; margin: 0.8em 0; }
th, td { border: 1px solid #d0d3d8; padding: 6px 10px; vertical-align: top; }
th { background: #f6f7f9; }
blockquote { color: #444; border-left: 3px solid #c5cad3; margin: 0.8em 0; padding: 0.1em 0 0.1em 12px; }
div.toc { font-size: 0.92em; margin: 0 0 1.8em; padding: 12px 16px; background: #f6f7f9; }
div.toc .toctitle { display: block; font-weight: 600; margin: 0 0 0.45em; }
div.toc ul { padding-left: 1.2em; margin: 0.2em 0; }
div.toc a { color: inherit; }
.sidecar-note { margin-top: 2.5em; font-size: 0.82em; color: #6b7075; border-top: 1px solid #eee; padding-top: 0.8em; }
"""


def default_html_output(md_path: Path) -> Path:
    return md_path.with_suffix(".html")


def build_sidecar_html(md_text: str, *, fallback_title: str = "document") -> str:
    import md_to_pdf as mtp

    text = mtp.strip_html_comments(md_text or "")
    title = mtp.document_title(text, fallback_title)
    if not mtp.is_pdf_preview_markdown(text):
        text = mtp.inject_toc_marker(text)
    body = mtp.markdown_to_body_html(text)
    safe_title = html_lib.escape(title or "document")
    note = (
        '<p class="sidecar-note">由 doc2md 从同一份 Markdown 生成的阅读页；'
        "图与正文共用旁边的资源目录。演示/表/画布类页面是网页预览截图，不是原稿排版还原。</p>"
    )
    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
        '<meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        f"<title>{safe_title}</title>\n"
        f"<style>{SCREEN_CSS}</style>\n"
        "</head>\n<body>\n"
        f"{body}\n"
        f"{note}\n"
        "</body>\n</html>\n"
    )


def write_sidecar_html(md_path: Path, html_path: Path | None = None) -> Path:
    src = md_path.expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"Markdown not found: {src}")
    dest = (html_path or default_html_output(src)).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    html = build_sidecar_html(src.read_text(encoding="utf-8"), fallback_title=src.stem)
    dest.write_text(html, encoding="utf-8")
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write a readable HTML sidecar from a local Markdown file."
    )
    parser.add_argument("markdown", type=Path, help="Input .md path")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output .html path")
    args = parser.parse_args(argv)
    try:
        dest = write_sidecar_html(args.markdown, args.output)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print("OK")
    print(f"markdown: {args.markdown.expanduser().resolve()}")
    print(f"html: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
