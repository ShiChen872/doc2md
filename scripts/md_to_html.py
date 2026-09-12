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
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


SCREEN_CSS = """
:root {
  --blue: #0A65CC;
  --blue2: #4874CB;
  --dark: #0F1423;
  --ink: #22304a;
  --gray: #647280;
  --line: #E7E6E6;
  --bg: #F5F9FF;
  --orange: #EE822F;
  color-scheme: light;
}
* { box-sizing: border-box; }
html { background: #f2f4f8; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
  font-size: 16px;
  line-height: 1.75;
  color: var(--ink);
  background: #f2f4f8;
}
.hero {
  background: linear-gradient(135deg, #0A65CC 0%, #4874CB 55%, #002B6E 100%);
  color: #fff;
  padding: 52px 24px 46px;
  text-align: center;
}
.hero .tag {
  display: inline-block;
  background: rgba(255,255,255,.16);
  border: 1px solid rgba(255,255,255,.4);
  padding: 4px 14px;
  border-radius: 999px;
  font-size: 13px;
  letter-spacing: 2px;
  margin-bottom: 18px;
}
.hero h1 { font-size: 32px; margin: 0 0 14px; font-weight: 800; letter-spacing: 1px; }
.hero .sub { font-size: 16px; opacity: .95; max-width: 720px; margin: 0 auto; }
.hero .quote {
  font-size: 15px;
  margin-top: 20px;
  padding: 12px 20px;
  border-radius: 12px;
  background: rgba(255,255,255,.12);
  display: inline-block;
  font-weight: 500;
}
.wrap { max-width: 920px; margin: 0 auto; padding: 32px 20px 80px; }
h1 { font-size: 26px; color: var(--dark); border-left: 5px solid var(--blue); padding-left: 14px; margin: 36px 0 14px; }
h2 { font-size: 21px; color: var(--blue); margin: 32px 0 12px; padding-bottom: 8px; border-bottom: 2px solid var(--blue); }
h3 { font-size: 17px; color: var(--dark); margin: 20px 0 8px; }
p { margin: 10px 0; }
ul, ol { margin: 10px 0; padding-left: 26px; }
li { margin: 6px 0; }
blockquote {
  margin: 14px 0;
  padding: 12px 18px;
  background: var(--bg);
  border-left: 4px solid var(--blue);
  border-radius: 0 10px 10px 0;
  color: #3d4a5c;
}
table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 14.5px; }
th, td { border: 1px solid var(--line); padding: 10px 12px; text-align: left; vertical-align: top; }
th { background: var(--bg); color: var(--dark); font-weight: 700; }
tr:nth-child(even) td { background: #fafbfd; }
img, img.doc-img { width: 100%; height: auto; border-radius: 12px; border: 1px solid var(--line); margin: 12px 0; }
strong { color: var(--dark); }
pre, code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
pre { white-space: pre-wrap; word-break: break-word; background: #f6f7f9; padding: 10px 12px; }
div.toc { font-size: 0.95em; margin: 0 0 1.8em; padding: 16px 20px; background: #fff; border: 1px solid var(--line); border-radius: 16px; }
div.toc .toctitle { display: block; font-weight: 700; color: var(--dark); margin: 0 0 0.45em; }
div.toc ul { padding-left: 1.2em; margin: 0.2em 0; }
div.toc a { color: inherit; }
.story { background: #fff7ef; border: 1px solid #f6d9bd; border-left: 4px solid var(--orange); border-radius: 10px; padding: 12px 18px; margin: 14px 0; }
.canon { background: #fff; border: 1px solid var(--line); border-left: 4px solid var(--blue); border-radius: 10px; padding: 12px 18px; margin: 14px 0; }
.hint { background: #eef5ff; border: 1px solid #d4e4fb; border-left: 4px solid var(--blue2); border-radius: 10px; padding: 12px 18px; margin: 14px 0; }
.one-liner { background: #f0f9f2; border: 1px solid #cdebd4; border-left: 4px solid #30C0B4; border-radius: 10px; padding: 12px 18px; margin: 14px 0; }
.exam { background: #f6f0fb; border: 1px solid #e4d3f4; border-left: 4px solid #7E1FAD; border-radius: 10px; padding: 12px 18px; margin: 14px 0; }
.diagram { background: #fff; border: 1px solid var(--line); border-left: 4px solid var(--blue); border-radius: 10px; padding: 12px 18px; margin: 14px 0; font-weight: 600; color: var(--blue); }
.foot, .sidecar-note { margin-top: 40px; text-align: center; color: var(--gray); font-size: 13px; border-top: 0; }
.hero.deck { padding: 40px 24px 36px; }
.wrap.deck { max-width: 880px; }
.deck-page {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 20px 22px 24px;
  margin: 28px 0;
  box-shadow: 0 4px 18px rgba(15,20,35,.05);
}
.deck-page h2 {
  margin: 0 0 14px;
  padding: 0;
  border-bottom: 0;
  font-size: 18px;
}
.deck-slide img, .deck-slide img.doc-img { margin: 0 0 8px; }
.deck-notes { margin-top: 4px; }
.deck-notes ol, .deck-notes ul { margin-top: 0; }
@media (max-width: 600px) {
  .hero h1 { font-size: 24px; }
  .wrap { padding: 20px 16px 64px; }
  table { font-size: 13px; }
}
"""

_BLOCK_RE = re.compile(
    r"<(p|h[1-6]|ul|ol|table|blockquote|div|pre)(\s[^>]*)?>"
    r".*?"
    r"</\1>"
    r"|<hr\s*/?>",
    re.IGNORECASE | re.DOTALL,
)
_CALLOUT_MARKERS = (
    ("🎬", "story"),
    ("📗", "canon"),
    ("🎯", "one-liner"),
    ("💡", "hint"),
    ("🎤", "exam"),
    ("📖", "diagram"),
)
_META_QUOTE_RE = re.compile(r"^(来源|类型|说明|Note)\s*[:：]", re.IGNORECASE)
_TYPE_LINE_RE = re.compile(r"^类型\s*[:：]\s*(.+)$", re.MULTILINE)
_CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百零0-9]+章")
_APPENDIX_RE = re.compile(r"^附录\s*([A-Za-z0-9一二三四五六七八九十])")
_PAGE_H2_RE = re.compile(
    r"^第\s*[一二三四五六七八九十百零0-9]+\s*页$|^第\s*\d+\s*页$"
)
_CN_COUNT = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}


def default_html_output(md_path: Path) -> Path:
    return md_path.with_suffix(".html")


def _plain(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    return re.sub(r"\s+", " ", text).strip()


def _blockquote_chunks(md_text: str) -> list[str]:
    chunks: list[str] = []
    cur: list[str] = []
    for line in (md_text or "").splitlines():
        if line.startswith(">"):
            cur.append(re.sub(r"^>\s?", "", line))
            continue
        if cur:
            chunks.append("\n".join(cur).strip())
            cur = []
    if cur:
        chunks.append("\n".join(cur).strip())
    return chunks


def drop_meta_blockquotes(md_text: str) -> str:
    """Remove leading converter notes (来源/类型/说明) from the reading page."""
    lines = (md_text or "").splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        if not lines[i].startswith(">"):
            out.append(lines[i])
            i += 1
            continue
        j = i
        entries: list[str] = []
        while j < len(lines) and (lines[j].startswith(">") or (entries and not lines[j].strip())):
            if lines[j].startswith(">"):
                entries.append(re.sub(r"^>\s?", "", lines[j]).strip())
            j += 1
        if entries and all((not item) or _is_converter_note(item) for item in entries):
            i = j
            while i < len(lines) and not lines[i].strip():
                i += 1
            continue
        out.extend(lines[i:j])
        i = j
    return "".join(out)


def _is_converter_note(item: str) -> bool:
    plain = re.sub(r"[*_`]", "", item or "").strip()
    if _META_QUOTE_RE.match(plain):
        return True
    return "PPTX is exported" in (item or "")


def is_page_heading_text(title: str) -> bool:
    return bool(_PAGE_H2_RE.match((title or "").strip()))


def deck_page_count(headings: list[tuple[int, str]]) -> int:
    return sum(1 for level, title in headings if level == 2 and is_page_heading_text(title))


def is_deck_markdown(md_text: str, headings: list[tuple[int, str]]) -> bool:
    """PPT / screenshot decks: 第一页… or converter note. Not handbook 第一章."""
    if "PPTX is exported" in (md_text or ""):
        return True
    h2 = [title.strip() for level, title in headings if level == 2 and title.strip()]
    if len(h2) < 2:
        return False
    pages = [title for title in h2 if is_page_heading_text(title)]
    return len(pages) >= 2 and len(pages) * 10 >= len(h2) * 7


def lead_quote(md_text: str) -> str:
    """First blockquote that is not converter metadata."""
    for chunk in _blockquote_chunks(md_text):
        first = next((ln.strip() for ln in chunk.splitlines() if ln.strip()), "")
        if not first or _is_converter_note(first) or "PPTX is exported" in chunk:
            continue
        text = " ".join(ln.strip() for ln in chunk.splitlines() if ln.strip())
        if text:
            return text
    return ""


def type_label(md_text: str) -> str:
    for chunk in _blockquote_chunks(md_text):
        m = _TYPE_LINE_RE.search(chunk)
        if not m:
            continue
        raw = m.group(1).strip()
        raw = re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()
        return raw
    return ""


def hero_kicker(headings: list[tuple[int, str]]) -> str:
    """Short structure line from h2 titles, e.g. 六章正文 · 毕业背诵 · 附录A/B/C."""
    h2 = [title for level, title in headings if level == 2 and title]
    parts: list[str] = []
    n_ch = sum(1 for title in h2 if _CHAPTER_RE.match(title))
    if n_ch:
        parts.append(f"{_CN_COUNT.get(n_ch, str(n_ch))}章正文")
    if any("毕业" in title for title in h2):
        parts.append("毕业背诵")
    apps = [_APPENDIX_RE.match(title) for title in h2]
    letters = [m.group(1) for m in apps if m]
    if letters:
        parts.append("附录" + "/".join(letters))
    elif any(title.startswith("附录") for title in h2):
        parts.append("附录")
    return " · ".join(parts)


def _iter_blocks(html: str) -> list[str]:
    blocks: list[str] = []
    pos = 0
    for match in _BLOCK_RE.finditer(html or ""):
        if match.start() > pos:
            gap = html[pos : match.start()]
            if gap.strip():
                blocks.append(gap)
        blocks.append(match.group(0))
        pos = match.end()
    if pos < len(html or "") and (html or "")[pos:].strip():
        blocks.append(html[pos:])
    return blocks


def _callout_class(block: str) -> str | None:
    if not re.match(r"<p\b", block or "", re.IGNORECASE):
        return None
    plain = _plain(block)
    for emoji, cls in _CALLOUT_MARKERS:
        if plain.startswith(emoji):
            return cls
    return None


def _is_heading(block: str) -> bool:
    return bool(re.match(r"<h[1-6]\b", block or "", re.IGNORECASE))


def _has_img(block: str) -> bool:
    return bool(re.search(r"<img\b", block or "", re.IGNORECASE))


def _callout_emoji_alt() -> str:
    return "|".join(re.escape(emoji) for emoji, _ in _CALLOUT_MARKERS)


def _split_li_callout(inner: str) -> tuple[str, str | None]:
    """Peel a trailing handbook callout out of a list item."""
    alt = _callout_emoji_alt()
    after_br = re.search(rf"(<br\s*/?>)\s*({alt})", inner or "", re.IGNORECASE)
    if after_br:
        kept = (inner or "")[: after_br.start()].rstrip()
        lifted = (inner or "")[after_br.start(2) :].strip()
        return kept, lifted or None
    plain = _plain(inner)
    if any(plain.startswith(emoji) for emoji, _ in _CALLOUT_MARKERS):
        return "", (inner or "").strip()
    return inner, None


def lift_callouts_from_lists(html: str) -> str:
    """Markdown folds 📖 after a list into the last <li>; put it back as a <p>."""
    blocks = _iter_blocks(html)
    if not blocks:
        return html
    out: list[str] = []
    for block in blocks:
        if not re.match(r"<(ul|ol)\b", block or "", re.IGNORECASE):
            out.append(block)
            continue
        closes = list(re.finditer(r"</li>", block, re.IGNORECASE))
        opens = list(re.finditer(r"<li\b[^>]*>", block, re.IGNORECASE))
        if not closes or not opens:
            out.append(block)
            continue
        close = closes[-1]
        open_candidates = [m for m in opens if m.end() <= close.start()]
        if not open_candidates:
            out.append(block)
            continue
        open_m = open_candidates[-1]
        kept, lifted = _split_li_callout(block[open_m.end() : close.start()])
        if not lifted:
            out.append(block)
            continue
        if kept.strip():
            new_list = block[: open_m.end()] + kept + block[close.start() :]
            out.append(new_list)
        else:
            new_list = (block[: open_m.start()] + block[close.end() :]).strip()
            if re.search(r"<li\b", new_list, re.IGNORECASE):
                out.append(new_list)
        out.append(f"<p>{lifted}</p>")
    return "\n".join(out)


def decorate_callouts(html: str) -> str:
    """Wrap emoji-led handbook sections (story / 必背 / 口试) in colored cards."""
    html = lift_callouts_from_lists(html)
    blocks = _iter_blocks(html)
    if not blocks:
        return html
    out: list[str] = []
    i = 0
    while i < len(blocks):
        cls = _callout_class(blocks[i])
        if not cls:
            out.append(blocks[i])
            i += 1
            continue
        group = [blocks[i]]
        i += 1
        while i < len(blocks):
            nxt = blocks[i]
            if _callout_class(nxt) or _is_heading(nxt) or _has_img(nxt):
                break
            if re.match(r"<hr\b|<div\b|<table\b", nxt, re.IGNORECASE):
                break
            group.append(nxt)
            i += 1
        inner = "\n".join(group)
        out.append(f'<div class="{cls}">\n{inner}\n</div>')
    return "\n".join(out)


def enhance_images(html: str) -> str:
    def repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        if re.search(r"\bclass=", tag, re.IGNORECASE):
            if "doc-img" in tag:
                return tag
            return re.sub(r'\bclass="', 'class="doc-img ', tag, count=1, flags=re.IGNORECASE)
        if tag.endswith("/>"):
            return tag[:-2].rstrip() + ' class="doc-img"/>'
        return tag[:-1] + ' class="doc-img">'

    return re.sub(r"<img\b[^>]*>", repl, html or "", flags=re.IGNORECASE)


def drop_matching_h1(html: str, title: str) -> str:
    """Keep the document title in the hero only."""
    if not title:
        return html
    blocks = _iter_blocks(html)
    for i, block in enumerate(blocks):
        if re.match(r"<h1\b", block, re.IGNORECASE) and _plain(block) == title:
            return "\n".join(blocks[:i] + blocks[i + 1 :])
    return html


def wrap_deck_pages(html: str) -> str:
    """Group each 第一页 section into a card: screenshot first, then notes."""
    blocks = _iter_blocks(html)
    if not blocks:
        return html
    out: list[str] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if not (
            re.match(r"<h2\b", block, re.IGNORECASE) and is_page_heading_text(_plain(block))
        ):
            out.append(block)
            i += 1
            continue
        heading = block
        i += 1
        chunk: list[str] = []
        while i < len(blocks):
            nxt = blocks[i]
            if re.match(r"<h2\b", nxt, re.IGNORECASE) and is_page_heading_text(_plain(nxt)):
                break
            chunk.append(nxt)
            i += 1
        slides = [item for item in chunk if _has_img(item)]
        notes = [item for item in chunk if not _has_img(item)]
        parts = ['<section class="deck-page">', heading]
        if slides:
            parts.append('<div class="deck-slide">')
            parts.extend(slides)
            parts.append("</div>")
        if notes:
            parts.append('<div class="deck-notes">')
            parts.extend(notes)
            parts.append("</div>")
        parts.append("</section>")
        out.append("\n".join(parts))
    return "\n".join(out)


def build_hero_html(*, title: str, tag: str, kicker: str, quote: str, variant: str = "") -> str:
    cls = "hero deck" if variant == "deck" else "hero"
    parts = [f'<div class="{cls}">']
    if tag:
        parts.append(f'<div class="tag">{html_lib.escape(tag)}</div>')
    parts.append(f"<h1>{html_lib.escape(title or 'document')}</h1>")
    if kicker:
        parts.append(f'<div class="sub">{html_lib.escape(kicker)}</div>')
    if quote:
        parts.append(f'<div class="quote">{html_lib.escape(quote)}</div>')
    parts.append("</div>")
    return "\n".join(parts)


def build_sidecar_html(md_text: str, *, fallback_title: str = "document") -> str:
    import md_to_pdf as mtp

    text = mtp.strip_html_comments(md_text or "")
    title = mtp.document_title(text, fallback_title)
    headings = mtp.iter_headings(text)
    preview = mtp.is_pdf_preview_markdown(text)
    deck = is_deck_markdown(text, headings)
    pages = deck_page_count(headings)
    page_md = drop_meta_blockquotes(text)
    if not preview and not deck:
        page_md = mtp.inject_toc_marker(page_md)
    body = mtp.markdown_to_body_html(page_md)
    body = enhance_images(body)
    body = drop_matching_h1(body, title)
    if deck:
        body = wrap_deck_pages(body)
        hero = build_hero_html(
            title=title or "document",
            tag=type_label(md_text) or "演示文稿",
            kicker=f"{pages} 页讲稿" if pages else "",
            quote="",
            variant="deck",
        )
        wrap_cls = "wrap deck"
    else:
        body = decorate_callouts(body)
        hero = build_hero_html(
            title=title or "document",
            tag=type_label(md_text),
            kicker="" if preview else hero_kicker(headings),
            quote=lead_quote(md_text),
        )
        wrap_cls = "wrap"
    safe_title = html_lib.escape(title or "document")
    note = (
        '<p class="foot sidecar-note">由 doc2md 从同一份 Markdown 生成的阅读页 · '
        "图与正文共用旁边的资源目录</p>"
    )
    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
        '<meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        f"<title>{safe_title}</title>\n"
        f"<style>{SCREEN_CSS}</style>\n"
        "</head>\n<body>\n"
        f"{hero}\n"
        f'<div class="{wrap_cls}">\n{body}\n{note}\n</div>\n'
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
