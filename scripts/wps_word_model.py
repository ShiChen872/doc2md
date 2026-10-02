"""Restore WPS Writer / Word structure from the in-page document model.

Share links often deny the original .docx. After weboffice loads, APP.data.doc
exposes the text stream plus paragraph styles (标题 1 / 正文 / 目录), tables,
and lists. That is enough to emit real Markdown instead of page screenshots.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

import session as sess

EXTRACT_WORD_MODEL_JS = r"""() => {
  const doc = window.APP && window.APP.data && window.APP.data.doc;
  if (!doc || !doc.textStream || !doc.textStream.getPureTextStream) return null;
  let ts;
  try { ts = doc.textStream.getPureTextStream(); } catch (e) { return null; }
  if (!ts || !ts.naked_textStream || !ts.getText) return null;
  let len = 0;
  try { len = ts.naked_textStream.getTextLength(); } catch (e) { return null; }
  if (!len || len < 20) return null;
  const raw = ts.getText(0, len);
  if (!raw || raw.replace(/[\r\n\s\x00-\x1f]/g, '').length < 10) return null;
  const ss = doc.stylesheet;
  const paras = [];
  let i = 0;
  while (i < raw.length) {
    const end = raw.indexOf('\r', i);
    const stop = end < 0 ? raw.length : end;
    const text = raw.slice(i, stop);
    let style = '正文';
    let align = null, list_id = null, list_level = null;
    let table = false, table_row = false, nest_level = 0;
    try {
      const pap = ts.getPap(i) || {};
      try {
        const st = ss && ss.getStyleByObjId && ss.getStyleByObjId(pap._basestyleObjId);
        if (st && st.name) style = String(st.name);
      } catch (e) {}
      align = pap.horizontal_align_mode == null ? null : pap.horizontal_align_mode;
      list_id = pap.list_id == null ? null : pap.list_id;
      list_level = pap.list_level == null ? null : pap.list_level;
      table = pap.type === 2;
      table_row = !!(pap.table_row) || pap.para_type === 2;
      nest_level = pap.nest_level || 0;
    } catch (e) {}
    paras.push({
      text, style, align, list_id, list_level, table, table_row, nest_level,
    });
    if (end < 0) break;
    i = end + 1;
  }
  const images = [];
  try {
    const map = window.APP.data.shapeManager && window.APP.data.shapeManager.shapeMap;
    if (map) {
      for (const [id, sh] of Object.entries(map)) {
        if (!sh || typeof sh !== 'object') continue;
        const url = sh.url || sh.originUrl || sh.src || sh.picUrl || sh.origin_url;
        if (url) images.push({id: String(id), url: String(url)});
      }
    }
  } catch (e) {}
  return {len, paras, images};
}"""

FIELD_INNER_RE = re.compile(r"\x13[^\x13\x14\x15]*\x14([^\x13\x15]*)\x15")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
HEADING_RE = re.compile(r"^标题\s*(\d+)$")
TOC_STYLE_RE = re.compile(r"^目录\s*\d*$")
FIGURE_CAPTION_RE = re.compile(r"^图\s*\d")
FIND_WORD_FIGURES_JS = r"""(needles) => {
  const norm = (s) => (s || '').replace(/\s+/g, '');
  const tailOf = (s) => norm(s).replace(/^图\d+(?:[-–]\d+)?/, '');
  const texts = [...document.querySelectorAll('text, tspan')].map((el) => {
    const r = el.getBoundingClientRect();
    return {el, t: (el.textContent || '').trim(), r};
  }).filter((x) => x.t && x.r.width > 0);
  const images = [...document.querySelectorAll('svg image')].filter((el) => {
    const r = el.getBoundingClientRect();
    return r.width >= 160 && r.height >= 80;
  });
  const pickImage = (cr) => {
    let best = null;
    let bestDist = 1e9;
    for (const img of images) {
      const r = img.getBoundingClientRect();
      if (r.bottom > cr.top + 40) continue;
      const dist = cr.top - r.bottom;
      if (dist >= 0 && dist < 480 && dist < bestDist) {
        best = img;
        bestDist = dist;
      }
    }
    return best;
  };
  const out = [];
  const used = new Set();
  (needles || []).forEach((needle, idx) => {
    const compact = norm(needle);
    const tail = tailOf(needle);
    if (tail.length < 4) return;
    let hit = null;
    for (const item of texts) {
      const t = norm(item.t);
      if (t.length < 4) continue;
      if (t === compact || t === tail || compact.includes(t) || t.includes(tail)) {
        if (pickImage(item.r)) {
          hit = item;
          break;
        }
        if (!hit) hit = item;
      }
    }
    if (!hit) return;
    const best = pickImage(hit.r);
    if (!best) return;
    const mark = 'fig' + idx + '_' + Math.round(hit.r.y);
    if (used.has(mark)) return;
    used.add(mark);
    best.setAttribute('data-doc2md-fig', mark);
    const r = best.getBoundingClientRect();
    out.push({
      caption: String(needle),
      key: mark,
      w: Math.round(r.width),
      h: Math.round(r.height),
    });
  });
  return out;
}"""


def strip_word_fields(text: str) -> str:
    """Keep Word field display text; drop TOC/HYPERLINK instructions."""
    s = str(text or "")
    prev = None
    while prev != s:
        prev = s
        s = FIELD_INNER_RE.sub(r"\1", s)
    s = CONTROL_RE.sub("", s)
    s = re.sub(r"\x13[^\x14\x15]*\x14?", "", s)
    s = re.sub(r'^TOC\s*\\o\s*"[^"]*"\s*\\h\s*\\u\s*', "", s)
    s = s.replace("\t", " ")
    return re.sub(r" {2,}", " ", s).strip()


def heading_level(style: str) -> int | None:
    name = (style or "").strip()
    if name == "标题":
        return 1
    m = HEADING_RE.fullmatch(name)
    if not m:
        return None
    return max(1, min(int(m.group(1)), 6))


def norm_caption(text: str) -> str:
    return re.sub(r"\s+", "", strip_word_fields(text))


def is_figure_caption(text: str) -> bool:
    cleaned = strip_word_fields(text)
    return bool(FIGURE_CAPTION_RE.match(cleaned) or FIGURE_CAPTION_RE.match(norm_caption(text)))


def figure_captions_from_paras(paras: list[dict]) -> list[str]:
    """Captions that follow a picture placeholder, plus standalone 图N lines."""
    caps: list[str] = []
    seen: set[str] = set()
    pending = False
    for para in paras:
        text = str(para.get("text") or "")
        if "\x01" in text and not strip_word_fields(text):
            pending = True
            continue
        cleaned = strip_word_fields(text)
        if pending and cleaned:
            key = norm_caption(cleaned)
            if key and key not in seen:
                seen.add(key)
                caps.append(cleaned)
            pending = False
            continue
        pending = False
        if cleaned and is_figure_caption(cleaned):
            key = norm_caption(cleaned)
            if key not in seen:
                seen.add(key)
                caps.append(cleaned)
    return caps


def _is_control_only(text: str) -> bool:
    return not strip_word_fields(text) and not any(
        ch not in "\r\n\t \x01\x03\x08\x0f\x13\x14\x15" for ch in (text or "")
    )


def _esc_cell(text: str) -> str:
    return strip_word_fields(text).replace("|", "\\|").replace("\n", "<br>")


def _flush_table(rows: list[list[str]], lines: list[str]) -> None:
    if not rows:
        return
    width = max(len(r) for r in rows)
    if width < 1:
        return
    norm = [r + [""] * (width - len(r)) for r in rows]
    if all(not any(c.strip() for c in r) for r in norm):
        return
    lines.append("| " + " | ".join(_esc_cell(c) for c in norm[0]) + " |")
    lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
    for r in norm[1:]:
        lines.append("| " + " | ".join(_esc_cell(c) for c in r) + " |")
    lines.append("")


def _next_captured_caption(
    paras: list[dict], index: int, figures: dict[str, str]
) -> bool:
    """True when the next visible paragraph already has a captured figure."""
    for nxt in paras[index + 1 :]:
        cleaned = strip_word_fields(str(nxt.get("text") or ""))
        if not cleaned:
            continue
        return norm_caption(cleaned) in figures
    return False


def paragraphs_to_markdown(
    paras: list[dict],
    figures: dict[str, str] | None = None,
    loose_images: list[str] | None = None,
) -> str:
    lines: list[str] = []
    table_rows: list[list[str]] = []
    table_row: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            lines.append("")
            in_list = False

    def close_table() -> None:
        nonlocal table_row, table_rows
        if table_row:
            table_rows.append(table_row)
            table_row = []
        if table_rows:
            close_list()
            _flush_table(table_rows, lines)
            table_rows = []

    figures = figures or {}
    loose: list[str] = list(loose_images or [])

    def take_loose(n: int) -> list[str]:
        got = loose[:n]
        del loose[: len(got)]
        return got

    for index, para in enumerate(paras):
        text = str(para.get("text") or "")
        style = str(para.get("style") or "正文")
        placeholders = text.count("\x01")
        picture_only = bool(placeholders) and not strip_word_fields(text)
        claimed = picture_only and _next_captured_caption(paras, index, figures)
        if para.get("table"):
            if para.get("table_row"):
                if table_row:
                    table_rows.append(table_row)
                    table_row = []
            else:
                cell = _esc_cell(text)
                if placeholders and not claimed:
                    imgs = " ".join(f"![]({rel})" for rel in take_loose(placeholders))
                    cell = f"{imgs} {cell}".strip() if cell else imgs
                table_row.append(cell)
            continue
        if claimed:
            continue
        if placeholders:
            close_table()
            for rel in take_loose(placeholders):
                close_list()
                lines.append(f"![]({rel})")
                lines.append("")
            if picture_only:
                continue
        close_table()
        cleaned = strip_word_fields(text)
        if not cleaned:
            if in_list:
                close_list()
            continue
        level = heading_level(style)
        if level:
            close_list()
            lines.append(f"{'#' * level} {cleaned}")
            lines.append("")
            continue
        if TOC_STYLE_RE.match(style):
            close_list()
            lines.append(f"- {cleaned}")
            in_list = True
            continue
        bullet = para.get("list_id") is not None or cleaned.startswith(
            ("●", "•", "·", "- ")
        )
        if bullet:
            item = re.sub(r"^[●•·]\s*", "", cleaned)
            lines.append(f"- {item}")
            in_list = True
            continue
        close_list()
        rel = figures.get(norm_caption(cleaned))
        if rel and is_figure_caption(cleaned):
            lines.append(f"![{cleaned}]({rel})")
            lines.append("")
        lines.append(cleaned)
        lines.append("")

    close_table()
    close_list()
    for rel in loose:
        lines.append(f"![]({rel})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_word_model_markdown(
    *,
    title: str,
    source_url: str,
    body: str,
) -> str:
    lines = [
        f"> 来源: {source_url}",
        "> 类型: WPS 文字分享（按文档样式还原：标题 / 表格 / 列表；「图N」用原图，其余插图按占位插入）",
        "",
        f"# {title}",
        "",
        body.strip(),
        "",
    ]
    return "\n".join(lines)


def extract_word_model(page) -> dict | None:
    """Read APP.data.doc from a loaded Writer page. None if the model is missing."""
    try:
        data = page.evaluate(EXTRACT_WORD_MODEL_JS)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    paras = data.get("paras")
    if not isinstance(paras, list) or len(paras) < 3:
        return None
    return data


def image_bytes_from_data_uri(href: str) -> bytes | None:
    """Decode a data:image/... URI. Writer tiles often embed the original PNG."""
    s = str(href or "").strip()
    if not s.startswith("data:image/") or "," not in s:
        return None
    meta, payload = s.split(",", 1)
    try:
        if ";base64" in meta.lower():
            raw = base64.b64decode(payload)
        else:
            from urllib.parse import unquote_to_bytes

            raw = unquote_to_bytes(payload)
    except Exception:
        return None
    return raw or None


def write_figure_png(dest: Path, raw: bytes) -> bool:
    """Write PNG bytes, or transcode JPEG, to dest. False if too small / unknown."""
    if not raw or len(raw) < 800:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        dest.write_bytes(raw)
        return dest.is_file() and dest.stat().st_size >= 800
    if raw[:2] == b"\xff\xd8":
        try:
            from io import BytesIO

            from PIL import Image

            Image.open(BytesIO(raw)).save(dest, format="PNG")
        except Exception:
            return False
        return dest.is_file() and dest.stat().st_size >= 800
    return False


def set_writer_zoom(page, percent: int = 200) -> bool:
    """Click the Writer status-bar zoom (100% → 200%) so fallback crops are larger."""
    label = f"{int(percent)}%"
    try:
        cur = page.evaluate(
            "() => ((document.querySelector('.zoom-value')||{}).textContent || '').trim()"
        )
        if str(cur).replace(" ", "") == label:
            return True
        page.locator(".zoom-value").first.click(timeout=2500)
        page.wait_for_timeout(250)
        page.get_by_text(label, exact=True).first.click(timeout=2500)
        page.wait_for_timeout(400)
        return True
    except Exception:
        return False


def _figure_href(page, mark: str) -> str:
    try:
        href = page.evaluate(
            """(mark) => {
              const el = document.querySelector(
                'svg image[data-doc2md-fig="' + mark + '"]'
              );
              if (!el) return '';
              return el.getAttribute('href')
                || el.getAttributeNS('http://www.w3.org/1999/xlink', 'href')
                || '';
            }""",
            mark,
        )
    except Exception:
        return ""
    return str(href or "")


def _workspace_scroll(page, top: float) -> None:
    try:
        page.evaluate(
            """(y) => {
              const ws = document.querySelector('#workspace');
              if (ws) ws.scrollTop = y;
            }""",
            float(top),
        )
    except Exception:
        pass


def _workspace_height(page) -> tuple[float, float]:
    try:
        info = page.evaluate(
            """() => {
              const ws = document.querySelector('#workspace');
              return {top: ws ? ws.scrollTop : 0, height: ws ? ws.scrollHeight : 0};
            }"""
        )
    except Exception:
        return 0.0, 0.0
    if not isinstance(info, dict):
        return 0.0, 0.0
    return float(info.get("top") or 0), float(info.get("height") or 0)


def capture_word_figures(
    page,
    assets_dir: Path,
    captions: list[str],
) -> dict[str, str]:
    """Save each 图N picture: original data-URI bytes when present, else a 200% crop."""
    wanted = {norm_caption(c): c for c in captions if norm_caption(c)}
    if not wanted:
        return {}
    assets_dir.mkdir(parents=True, exist_ok=True)
    sess.clear_generated_assets(assets_dir, patterns=("fig_*.png", "page_*.png"))
    set_writer_zoom(page, 200)

    found: dict[str, Path] = {}
    seen_hash: set[str] = set()
    _workspace_scroll(page, 0)
    page.wait_for_timeout(400)
    _, height = _workspace_height(page)
    step = 700.0
    y = 0.0
    slot = 0
    guard = 0
    while y <= max(height, 1) + step and guard < 80:
        guard += 1
        _workspace_scroll(page, y)
        page.wait_for_timeout(350)
        try:
            pairs = page.evaluate(FIND_WORD_FIGURES_JS, list(wanted.values()))
        except Exception:
            pairs = []
        if not isinstance(pairs, list):
            pairs = []
        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            key = norm_caption(str(pair.get("caption") or ""))
            if key not in wanted or key in found:
                continue
            mark = str(pair.get("key") or "")
            if not mark:
                continue
            loc = page.locator(f'svg image[data-doc2md-fig="{mark}"]').first
            try:
                loc.evaluate("el => el.scrollIntoView({block: 'center'})")
                page.wait_for_timeout(250)
                loc.wait_for(state="visible", timeout=4000)
            except Exception:
                continue
            slot += 1
            dest = assets_dir / f"fig_{slot:03d}.png"
            raw = image_bytes_from_data_uri(_figure_href(page, mark))
            wrote = write_figure_png(dest, raw) if raw else False
            if not wrote:
                try:
                    loc.screenshot(path=str(dest))
                except Exception:
                    dest.unlink(missing_ok=True)
                    continue
            if not dest.is_file() or dest.stat().st_size < 800:
                dest.unlink(missing_ok=True)
                slot -= 1
                continue
            digest = hashlib.sha256(dest.read_bytes()).hexdigest()
            if digest in seen_hash:
                dest.unlink(missing_ok=True)
                slot -= 1
                continue
            seen_hash.add(digest)
            found[key] = dest
        if len(found) >= len(wanted):
            break
        _, height = _workspace_height(page)
        y += step
        if height and y > height + step:
            break

    rels: dict[str, str] = {}
    for key, path in found.items():
        rels[key] = f"{assets_dir.name}/{path.name}"
    return rels


LIST_LOOSE_WORD_IMAGES_JS = r"""() => {
  const ws = document.querySelector('#workspace');
  const scroll = ws ? ws.scrollTop : 0;
  const images = [...document.querySelectorAll('svg image')].filter((el) => {
    if (el.getAttribute('data-doc2md-fig')) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 48 && r.height >= 48;
  });
  return images.map((el) => {
    const r = el.getBoundingClientRect();
    const href = el.getAttribute('href')
      || el.getAttributeNS('http://www.w3.org/1999/xlink', 'href')
      || '';
    const y = Math.round(scroll + r.top);
    const x = Math.round(r.left);
    const id = 'loose_' + y + '_' + x;
    el.setAttribute('data-doc2md-loose', id);
    return {id, href, y, x};
  });
}"""


def _save_picture_bytes(dest: Path, raw: bytes | None, seen_hash: set[str]) -> bool:
    if not raw or not write_figure_png(dest, raw):
        dest.unlink(missing_ok=True)
        return False
    if not dest.is_file() or dest.stat().st_size < 800:
        dest.unlink(missing_ok=True)
        return False
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    if digest in seen_hash:
        dest.unlink(missing_ok=True)
        return False
    seen_hash.add(digest)
    return True


def _shape_image_bytes(page, url: str) -> bytes | None:
    raw = image_bytes_from_data_uri(url)
    if raw:
        return raw
    if not str(url).startswith("http"):
        return None
    try:
        resp = page.context.request.get(str(url), timeout=15000)
        if resp.status != 200:
            return None
        body = resp.body()
    except Exception:
        return None
    if body[:8] == b"\x89PNG\r\n\x1a\n" or body[:2] == b"\xff\xd8":
        return body
    return None


def capture_loose_word_pictures(page, assets_dir: Path, model: dict | None = None) -> list[str]:
    """Save pictures that are not tied to a 图N caption, in reading order.

    DOM `svg image` tiles come first. shapeMap URLs fill anything the tiles missed.
    """
    assets_dir.mkdir(parents=True, exist_ok=True)
    sess.clear_generated_assets(assets_dir, patterns=("pic_*.png",))
    set_writer_zoom(page, 200)
    found: list[tuple[int, int, Path]] = []
    seen_id: set[str] = set()
    seen_href: set[str] = set()
    seen_hash: set[str] = set()
    _workspace_scroll(page, 0)
    page.wait_for_timeout(300)
    _, height = _workspace_height(page)
    step = 700.0
    y = 0.0
    slot = 0
    guard = 0
    while y <= max(height, 1) + step and guard < 80:
        guard += 1
        _workspace_scroll(page, y)
        page.wait_for_timeout(250)
        try:
            hits = page.evaluate(LIST_LOOSE_WORD_IMAGES_JS)
        except Exception:
            hits = []
        if not isinstance(hits, list):
            hits = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            mark = str(hit.get("id") or "")
            href = str(hit.get("href") or "")
            if not mark or mark in seen_id:
                continue
            if href and href in seen_href:
                seen_id.add(mark)
                continue
            loc = page.locator(f'svg image[data-doc2md-loose="{mark}"]').first
            slot += 1
            dest = assets_dir / f"_loose_{slot:03d}.png"
            raw = image_bytes_from_data_uri(href)
            if not _save_picture_bytes(dest, raw, seen_hash):
                try:
                    loc.screenshot(path=str(dest))
                except Exception:
                    dest.unlink(missing_ok=True)
                    slot -= 1
                    continue
                if not _save_picture_bytes(dest, dest.read_bytes() if dest.is_file() else None, seen_hash):
                    slot -= 1
                    continue
            seen_id.add(mark)
            if href:
                seen_href.add(href)
            found.append((int(hit.get("y") or 0), int(hit.get("x") or 0), dest))
        _, height = _workspace_height(page)
        y += step
        if height and y > height + step:
            break

    for item in (model or {}).get("images") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if not url or url in seen_href:
            continue
        raw = _shape_image_bytes(page, url)
        slot += 1
        dest = assets_dir / f"_loose_{slot:03d}.png"
        if not _save_picture_bytes(dest, raw, seen_hash):
            slot -= 1
            continue
        seen_href.add(url)
        found.append((10**9, slot, dest))

    found.sort()
    rels: list[str] = []
    for i, (_, _, path) in enumerate(found, start=1):
        dest = assets_dir / f"pic_{i:03d}.png"
        if path != dest:
            path.replace(dest)
        rels.append(f"{assets_dir.name}/{dest.name}")
    return rels


def write_word_model_markdown(
    *,
    title: str,
    source_url: str,
    output_md: Path,
    model: dict,
    figures: dict[str, str] | None = None,
    loose_images: list[str] | None = None,
) -> dict:
    body = paragraphs_to_markdown(
        list(model.get("paras") or []),
        figures=figures,
        loose_images=loose_images,
    )
    md = build_word_model_markdown(title=title, source_url=source_url, body=body)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(md, encoding="utf-8")
    image_count = len(figures or {}) + len(loose_images or [])
    return {
        "paragraphs": len(model.get("paras") or []),
        "text_len": model.get("len"),
        "images": image_count,
        "markdown_chars": len(md),
        "assets_dir": str((output_md.parent / f"{output_md.stem}_assets"))
        if image_count
        else None,
    }


def model_from_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
