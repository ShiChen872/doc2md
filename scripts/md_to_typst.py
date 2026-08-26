"""Markdown → Typst body + branded document wrapper.

Used by md_to_pdf.py when --engine=typst. Chrome remains the default PDF path.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

THEMES: dict[str, dict[str, str]] = {
    "default": {
        "navy": "#111111",
        "accent": "#444444",
        "muted": "#666666",
        "text": "#111111",
        "table_head": "#f6f8fa",
        "table_stroke": "#cccccc",
        "quote": "#dddddd",
        "code_bg": "#f6f8fa",
        "header_bar": "#dddddd",
    },
    "brand": {
        # Professional WPS-365-like report colors. No logo artwork.
        "navy": "#163A5F",
        "accent": "#2B6CB0",
        "muted": "#5C6B73",
        "text": "#1A1A1A",
        "table_head": "#E8EEF4",
        "table_stroke": "#C5D0DC",
        "quote": "#2B6CB0",
        "code_bg": "#F4F7FA",
        "header_bar": "#2B6CB0",
    },
}

FENCE_RE = re.compile(r"^(`{3,}|~{3,})(.*)$")
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
UL_RE = re.compile(r"^(\s*)([-*+])\s+(.*)$")
OL_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
ATX_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
HR_RE = re.compile(r"^\s*((?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})\s*$")
PAGE_HEADING_RE = re.compile(r"^## 第\s+\d+\s+页\s*$")

INLINE_TOKEN_RE = re.compile(
    r"!\[([^\]]*)\]\(([^)]+)\)"
    r"|\[([^\]]+)\]\(([^)]+)\)"
    r"|`([^`]+)`"
    r"|\*\*(.+?)\*\*"
    r"|__(.+?)__"
    r"|<br\s*/?>"
    r"|<a\s+href=\"([^\"]+)\"[^>]*>(.*?)</a>"
    r"|<(?:p|div)[^>]*class=\"(?:video-fallback|iframe-fallback)\"[^>]*>(.*?)</(?:p|div)>"
    r"|<div\s+class=\"ocr-aux\">(.*?)</div>",
    re.IGNORECASE | re.DOTALL,
)

VIDEO_P_RE = re.compile(
    r'<p class="(?:video-fallback|iframe-fallback)">\s*(.*?)</p>',
    re.IGNORECASE | re.DOTALL,
)
ATTR_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


def _simplify_html_fallbacks(text: str) -> str:
    """Turn preprocess <p class=video-fallback> HTML into Markdown links."""

    def repl(match: re.Match[str]) -> str:
        inner = match.group(1) or ""
        href_m = ATTR_HREF_RE.search(inner)
        label = TAG_RE.sub("", inner).strip() or "打开链接"
        if href_m:
            return f"[{label}]({href_m.group(1)})"
        return label

    return VIDEO_P_RE.sub(repl, text or "")


class TypstError(Exception):
    pass


def theme_tokens(name: str) -> dict[str, str]:
    key = (name or "default").strip().lower()
    if key not in THEMES:
        raise TypstError(f"Unknown theme: {name!r} (use default or brand)")
    return THEMES[key]


def escape_text(text: str) -> str:
    out: list[str] = []
    for ch in text or "":
        if ch in "\\#$[]*_`<>@":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def escape_string(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace('"', '\\"')


def _typst_image(path: str, alt: str = "") -> str:
    raw = (path or "").strip()
    if not raw:
        return escape_text(alt or "")
    if raw.lower().startswith(("http://", "https://", "data:", "mailto:")):
        label = escape_text(alt or raw)
        return f'#link("{escape_string(raw)}")[{label}]'
    img = f'#image("{escape_string(raw)}", width: 100%)'
    if alt.strip():
        return f"#block(breakable: false)[{img}]"
    return f"#block(breakable: false)[{img}]"


def convert_inline(text: str) -> str:
    """Markdown / leftover HTML inline → Typst content."""
    src = text or ""
    out: list[str] = []
    pos = 0
    for m in INLINE_TOKEN_RE.finditer(src):
        if m.start() > pos:
            out.append(escape_text(src[pos : m.start()]))
        g = m.groups()
        raw = m.group(0)
        if raw.startswith("!["):
            out.append(_typst_image(g[1] or "", g[0] or ""))
        elif raw.startswith("[") and g[2] is not None:
            out.append(
                f'#link("{escape_string(g[3] or "")}")[{convert_inline(g[2] or "")}]'
            )
        elif raw.startswith("`"):
            out.append("`" + (g[4] or "").replace("`", "") + "`")
        elif raw.startswith("**") or raw.startswith("__"):
            inner = g[5] if raw.startswith("**") else g[6]
            out.append("*" + convert_inline(inner or "") + "*")
        elif raw.lower().startswith("<br"):
            out.append(" \\\n")
        elif raw.lower().startswith("<a "):
            out.append(
                f'#link("{escape_string(g[7] or "")}")[{convert_inline(g[8] or "")}]'
            )
        elif "fallback" in raw.lower():
            inner = g[9] or ""
            href_m = ATTR_HREF_RE.search(inner)
            label = TAG_RE.sub("", inner).strip() or "打开链接"
            if href_m:
                out.append(
                    f'#link("{escape_string(href_m.group(1))}")[{escape_text(label)}]'
                )
            else:
                out.append(escape_text(label))
        elif "ocr-aux" in raw.lower():
            inner = TAG_RE.sub("", g[10] or "")
            out.append(
                "#block(text(size: 7pt, fill: rgb(\"#888888\"))["
                + escape_text(inner)
                + "])"
            )
        else:
            out.append(escape_text(raw))
        pos = m.end()
    out.append(escape_text(src[pos:]))
    # leftover simple HTML tags
    merged = "".join(out)
    merged = re.sub(r"</?(?:p|div|span|strong|em|b|i)[^>]*>", "", merged, flags=re.I)
    return merged


def _split_table_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_table_sep(line: str) -> bool:
    return bool(TABLE_SEP_RE.match(line or ""))


def _emit_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    padded = [r + [""] * (width - len(r)) for r in rows]
    cols = ", ".join(["1fr"] * width)
    cells: list[str] = []
    for y, row in enumerate(padded):
        for cell in row:
            body = convert_inline(cell).strip()
            if y == 0:
                cells.append(f"[*{body}*]")
            else:
                cells.append(f"[{body}]")
    joined = ",\n  ".join(cells)
    return (
        f"#block(breakable: true, width: 100%, "
        f"table(columns: ({cols}), inset: 6pt, stroke: 0.4pt, "
        f"align: left, {joined}))\n\n"
    )


def _emit_heading(level: int, title: str) -> str:
    marks = "=" * max(1, min(level, 6))
    return f"{marks} {convert_inline(title)}\n\n"


def _emit_code(lang: str, body: str) -> str:
    lang = (lang or "").strip().split()[0] if lang else ""
    ticks = "```"
    while ticks in (body or "") or ticks in lang:
        ticks += "`"
    return f"{ticks}{lang}\n{body}\n{ticks}\n\n"


def markdown_to_typst(md_text: str, *, pdf_preview: bool = False) -> str:
    """Convert CommonMark-ish Markdown (doc2md output) to Typst content."""
    md_text = _simplify_html_fallbacks(md_text or "")
    lines = md_text.splitlines()
    out: list[str] = []
    i = 0
    para: list[str] = []
    preview_pages = 0

    def flush_para() -> None:
        nonlocal para
        if not para:
            return
        text = " ".join(p.strip() for p in para if p.strip())
        para = []
        if text:
            out.append(convert_inline(text) + "\n\n")

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        fence = FENCE_RE.match(stripped)
        if fence:
            flush_para()
            ticks, info = fence.group(1), fence.group(2)
            lang = (info or "").strip()
            i += 1
            buf: list[str] = []
            while i < len(lines):
                if lines[i].strip().startswith(ticks[0] * len(ticks)) and len(
                    lines[i].strip()
                ) >= len(ticks):
                    break
                buf.append(lines[i])
                i += 1
            out.append(_emit_code(lang, "\n".join(buf)))
            if i < len(lines):
                i += 1
            continue

        if TABLE_ROW_RE.match(line) and i + 1 < len(lines) and _is_table_sep(lines[i + 1]):
            flush_para()
            header = _split_table_row(line)
            i += 2
            rows = [header]
            while i < len(lines) and TABLE_ROW_RE.match(lines[i]):
                rows.append(_split_table_row(lines[i]))
                i += 1
            out.append(_emit_table(rows))
            continue

        if not stripped:
            flush_para()
            i += 1
            continue

        if HR_RE.match(stripped) and not stripped.startswith("#"):
            flush_para()
            out.append("#line(length: 100%)\n\n")
            i += 1
            continue

        atx = ATX_RE.match(stripped)
        if atx:
            flush_para()
            level = len(atx.group(1))
            title = atx.group(2)
            if pdf_preview and PAGE_HEADING_RE.match(stripped):
                if preview_pages:
                    out.append("#pagebreak(weak: true)\n")
                preview_pages += 1
                i += 1
                continue
            if pdf_preview and level == 1:
                i += 1
                continue
            if PAGE_HEADING_RE.match(stripped) and out:
                out.append("#pagebreak(weak: true)\n")
            out.append(_emit_heading(level, title))
            i += 1
            continue

        ul = UL_RE.match(line)
        ol = OL_RE.match(line)
        if ul or ol:
            flush_para()
            items: list[tuple[int, str, str]] = []
            while i < len(lines):
                u = UL_RE.match(lines[i])
                o = OL_RE.match(lines[i])
                if not (u or o):
                    if lines[i].strip() and items and lines[i].startswith("  "):
                        indent, kind, text = items[-1]
                        items[-1] = (indent, kind, text + " " + lines[i].strip())
                        i += 1
                        continue
                    break
                m = u or o
                indent = len(m.group(1).replace("\t", "    "))
                kind = "ul" if u else "ol"
                items.append((indent, kind, m.group(3)))
                i += 1
            out.append(_emit_list(items))
            continue

        if stripped.startswith(">"):
            flush_para()
            quote: list[str] = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            body = convert_inline(" ".join(q.strip() for q in quote if q.strip()))
            out.append(f"#quote[{body}]\n\n")
            continue

        para.append(line)
        i += 1

    flush_para()
    return "".join(out).rstrip() + "\n"


def _emit_list(items: list[tuple[int, str, str]]) -> str:
    if not items:
        return ""
    # Flatten to Typst nested lists by indent buckets of 2 spaces.
    lines: list[str] = []

    def marker(kind: str) -> str:
        return "-" if kind == "ul" else "+"

    min_indent = min(it[0] for it in items)
    for indent, kind, text in items:
        depth = max(0, (indent - min_indent) // 2)
        pad = "  " * depth
        lines.append(f"{pad}{marker(kind)} {convert_inline(text)}")
    return "\n".join(lines) + "\n\n"


def _inject_outline_after_first_h1(body: str, toc_markup: str) -> str:
    """Put 目录 after the first `= title`, matching Chrome's post-h1 TOC."""
    lines = (body or "").splitlines(keepends=True)
    out: list[str] = []
    inserted = False
    i = 0
    while i < len(lines):
        out.append(lines[i])
        stripped = lines[i].lstrip()
        if not inserted and stripped.startswith("= ") and not stripped.startswith("=="):
            i += 1
            while i < len(lines) and not lines[i].strip():
                out.append(lines[i])
                i += 1
            out.append(toc_markup if toc_markup.endswith("\n") else toc_markup + "\n")
            inserted = True
            continue
        i += 1
    if not inserted:
        return toc_markup + (body or "")
    return "".join(out)


def wrap_typst_document(
    body: str,
    *,
    title: str,
    theme: str = "brand",
    toc: bool = True,
    pdf_preview: bool = False,
) -> str:
    colors = theme_tokens(theme)
    safe_title = escape_text(title or "document")
    show_toc = toc and not pdf_preview
    toc_markup = (
        '#outline(title: [目录], depth: 3, indent: 1em, '
        'target: heading.where(level: 2).or(heading.where(level: 3)))\n'
        '#pagebreak()\n'
        if show_toc
        else ""
    )
    if toc_markup:
        body = _inject_outline_after_first_h1(body, toc_markup)
    # PDF-preview pages should stay one image ≈ one page.
    preview_show = (
        '#show image: it => block(width: 100%, breakable: false, it)\n'
        if pdf_preview
        else '#show image: it => block(breakable: false, width: 100%, it)\n'
    )
    heading_show = f"""#show heading.where(level: 1): it => {{
  set text(fill: rgb("{colors["navy"]}"), weight: 700, size: 16pt)
  v(0.4em)
  it
  v(-0.35em)
  line(length: 100%, stroke: 1.1pt + rgb("{colors["accent"]}"))
  v(0.55em)
}}
#show heading.where(level: 2): it => {{
  set text(fill: rgb("{colors["navy"]}"), weight: 650, size: 13pt)
  v(0.35em)
  it
  v(0.25em)
}}
#show heading.where(level: 3): it => {{
  set text(fill: rgb("{colors["navy"]}"), weight: 600, size: 12pt)
  it
}}
"""
    table_show = f"""#set table(
  stroke: 0.45pt + rgb("{colors["table_stroke"]}"),
  fill: (x, y) => if y == 0 {{ rgb("{colors["table_head"]}") }} else {{ none }},
)
#show table.cell.where(y: 0): set text(fill: rgb("{colors["navy"]}"), weight: 600)
"""
    return f"""#set document(title: "{escape_string(title or "document")}")
#set page(
  paper: "a4",
  margin: (top: 22mm, bottom: 18mm, left: 16mm, right: 16mm),
  header: context {{
    set text(size: 8.5pt, fill: rgb("{colors["muted"]}"))
    grid(
      columns: (1fr, auto),
      align: (left + horizon, right + horizon),
      text(fill: rgb("{colors["navy"]}"), weight: 600)[{safe_title}],
      [],
    )
    v(4pt)
    line(length: 100%, stroke: 1.15pt + rgb("{colors["header_bar"]}"))
  }},
  footer: context {{
    set text(size: 8.5pt, fill: rgb("{colors["muted"]}"))
    align(center, counter(page).display("1 / 1", both: true))
  }},
)
#set text(
  font: (
    "PingFang SC",
    "Hiragino Sans GB",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "Microsoft YaHei",
    "Source Han Sans",
  ),
  size: 11pt,
  fill: rgb("{colors["text"]}"),
)
#set par(leading: 0.78em, justify: true)
#set heading(numbering: none)
#show link: set text(fill: rgb("{colors["accent"]}"))
#show raw.where(block: true): it => block(
  fill: rgb("{colors["code_bg"]}"),
  inset: 8pt,
  radius: 3pt,
  width: 100%,
  it,
)
#show quote: it => block(
  stroke: (left: 2.5pt + rgb("{colors["quote"]}")),
  inset: (left: 10pt, y: 4pt),
  it,
)
{heading_show}{table_show}{preview_show}{body}
"""


def find_typst_compiler() -> tuple[str, str]:
    """Return ('python'|'cli', locator). Raises TypstError if missing."""
    try:
        import typst as typst_mod  # noqa: F401

        return "python", "typst"
    except ImportError:
        pass
    exe = shutil.which("typst")
    if exe:
        return "cli", exe
    raise TypstError(
        "Typst is not installed. Install the official CLI (macOS / Windows / Linux),\n"
        "or `pip install typst` if a wheel exists for this Python.\n"
        "  macOS:  brew install typst\n"
        "  Windows: winget install --id Typst.Typst -e\n"
        "           (or scoop install typst; or unzip GitHub release onto PATH)\n"
        "  Linux:  see https://github.com/typst/typst/releases\n"
        "Chrome remains the default PDF engine (--engine chrome) and needs no Typst."
    )


def compile_typst(typ_path: Path, output_pdf: Path, *, root: Path) -> None:
    kind, locator = find_typst_compiler()
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    if kind == "python":
        import typst as typst_mod

        kwargs = {"output": str(output_pdf)}
        # typst-py 0.13+ accepts root; older wheels ignore extra kwargs.
        try:
            typst_mod.compile(str(typ_path), root=str(root), **kwargs)
        except TypeError:
            typst_mod.compile(str(typ_path), **kwargs)
        return
    cmd = [locator, "compile", "--root", str(root), str(typ_path), str(output_pdf)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise TypstError(f"typst compile failed: {err}")


def markdown_to_typst_source(
    md_text: str,
    *,
    title: str,
    theme: str = "brand",
    toc: bool = True,
    pdf_preview: bool = False,
) -> str:
    body = markdown_to_typst(md_text, pdf_preview=pdf_preview)
    return wrap_typst_document(
        body, title=title, theme=theme, toc=toc, pdf_preview=pdf_preview
    )
