#!/usr/bin/env python3
"""Convert a WPS/kdocs share link to Markdown (docx/xlsx/pptx/pdf or .otl).

Usage:
  wps_to_md.py <share_url> [-o OUTPUT.md]
  wps_to_md.py <share_url> -o out.md --recursive   # OTL nested cards, depth 1

Uses Playwright storage from wps_login.py:
  ~/.config/doc2md/wps_storage_state.json

Flow:
  1. Open share URL with saved session (wiki/l/ ids resolved to the file share)
  2. Resolve file meta via drive links API
  3. Try binary download (Office files)
  4. If blocked PDF: screenshot web-viewer `.pdf-page` tiles + OCR → Markdown
  5. If blocked presentation (`.pptx` / office_type=p): screenshot each slide
  6. If blocked / `.otl` intelligent doc: capture open/otl JSON + CDN images → Markdown
  7. If `.dbt` / office_type=d (download notAllowType): screenshot each web-viewer sheet
  8. Otherwise run convert.py on the downloaded Office file (`.ksheet` is xlsx-compatible)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

CFG = Path.home() / ".config" / "doc2md"
DEFAULT_STATE = CFG / "wps_storage_state.json"
SCRIPTS = Path(__file__).resolve().parent
SHARE_ID_RE = re.compile(
    r"(?:kdocs\.cn|wps\.cn)/(?:wiki/l|l|view/l|view/media/l)/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
SAFE_NAME_RE = re.compile(r"[^\w.\u4e00-\u9fff\-]+")
MEDIA_EXTS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
    ".m4v",
    ".wmv",
    ".flv",
    ".mpeg",
    ".mpg",
}
PDF_PAGE_SEL = ".pdf-page"
PDF_PAGE_INPUT_SEL = "input.kd-input-inner-align-center"
PDF_PAGE_LABEL_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
MAX_PDF_PREVIEW_PAGES = 200
WPP_SLIDE_SEL = ".slide-uil-view"
PPT_EXTS = {".ppt", ".pptx", ".pptm", ".pps", ".ppsx"}
MAX_WPP_PREVIEW_PAGES = 200
DB_SHEET_ITEM_SEL = ".sheet-panel-items .sheet-panel-item, .ks-component-panel-item.view-item"
DB_VIEW_SEL = (
    ".workbench-main-content, .workbench-view-content, "
    ".div_et_grid, .grid-view, .db-grid-view-wrapper, .workbench-content.main"
)
MAX_DBSHEET_SHEETS = 40
KSHEET_EXTS = {".ksheet"}
DBSHEET_EXTS = {".dbt", ".dbsheet"}


class WpsError(Exception):
    pass


def extract_share_id(url: str) -> str:
    m = SHARE_ID_RE.search(url)
    if not m:
        raise WpsError(f"Cannot parse share id from URL: {url}")
    return m.group(1)


def share_id_candidates(url: str) -> list[str]:
    """WPS 知识库 wiki/l/0l<id> often needs the inner share id without the 0l prefix."""
    sid = extract_share_id(url)
    out = [sid]
    if re.search(r"/(?:wiki/l)/", url, re.I) and sid.startswith("0l") and len(sid) > 10:
        out.append(sid[2:])
    return list(dict.fromkeys(out))


def viewer_share_url(sid: str) -> str:
    return f"https://365.kdocs.cn/l/{sid}"


def is_presentation_share(fname: str = "", office_type: str = "") -> bool:
    if Path(fname or "").suffix.lower() in PPT_EXTS:
        return True
    return str(office_type or "").lower() in {"p", "wpp", "presentation"}


def is_ksheet_share(fname: str = "", office_type: str = "") -> bool:
    if Path(fname or "").suffix.lower() in KSHEET_EXTS:
        return True
    return str(office_type or "").lower() in {"k", "ksheet"}


def is_dbsheet_share(fname: str = "", office_type: str = "") -> bool:
    if Path(fname or "").suffix.lower() in DBSHEET_EXTS:
        return True
    return str(office_type or "").lower() in {"d", "db", "dbt", "dbsheet"}


def is_media_filename(fname: str) -> bool:
    return Path(fname or "").suffix.lower() in MEDIA_EXTS


def is_pdf_share(fname: str = "", office_type: str = "", ftype: str = "") -> bool:
    """True when share meta / viewer looks like a PDF (not an OTL / Office binary)."""
    if Path(fname or "").suffix.lower() == ".pdf":
        return True
    ot = str(office_type or "").lower()
    ft = str(ftype or "").lower()
    if ot in {"f", "pdf"} or ft in {"f", "pdf"}:
        return True
    return False


def parse_pdf_page_label(text: str) -> tuple[int | None, int | None]:
    """Parse a viewer label like '3/24' or '3 / 24' into (current, total)."""
    if not text:
        return None, None
    compact = re.sub(r"\s+", "", str(text))
    m = PDF_PAGE_LABEL_RE.search(compact)
    if not m:
        return None, None
    cur, total = int(m.group(1)), int(m.group(2))
    if cur < 1 or total < 1 or total > MAX_PDF_PREVIEW_PAGES:
        return None, None
    return cur, total


def format_bytes(n: int | float | None) -> str:
    if n is None:
        return "unknown"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "unknown"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    if i == 0:
        return f"{int(n)} {units[i]}"
    return f"{n:.1f} {units[i]}"


def find_ffmpeg() -> str | None:
    """Return ffmpeg binary path if available on PATH / Homebrew."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    for candidate in (
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def cookie_header_from_playwright(cookies: list[dict]) -> str:
    """Build a Cookie header from Playwright cookie dicts (WPS-related domains)."""
    parts: list[str] = []
    seen: set[str] = set()
    for c in cookies:
        domain = c.get("domain") or ""
        if not any(x in domain for x in ("wps.cn", "kdocs.cn", "wpscdn.cn", "ksyuncs.com")):
            continue
        name = c.get("name") or ""
        if not name or name in seen:
            continue
        seen.add(name)
        parts.append(f"{name}={c.get('value') or ''}")
    return "; ".join(parts)


def remux_hls_with_ffmpeg(
    stream_url: str,
    output_mp4: Path,
    *,
    cookie_header: str,
    referer: str,
    ffmpeg_bin: str | None = None,
    timeout_sec: int = 600,
) -> dict:
    """Remux HLS preview stream to MP4 via ffmpeg (-c copy). Returns stats dict."""
    ffmpeg_bin = ffmpeg_bin or find_ffmpeg()
    if not ffmpeg_bin:
        return {"ok": False, "error": "ffmpeg not found"}
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    headers = (
        f"Cookie: {cookie_header}\r\n"
        f"Referer: {referer}\r\n"
        "User-Agent: Mozilla/5.0\r\n"
    )
    cmd = [
        ffmpeg_bin,
        "-y",
        "-headers",
        headers,
        "-i",
        stream_url,
        "-c",
        "copy",
        "-bsf:a",
        "aac_adtstoasc",
        str(output_mp4),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"ffmpeg timeout after {timeout_sec}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    if proc.returncode != 0 or not output_mp4.is_file() or output_mp4.stat().st_size < 1000:
        err = (proc.stderr or proc.stdout or "")[-800:]
        return {"ok": False, "error": err or f"ffmpeg exit {proc.returncode}"}
    return {
        "ok": True,
        "path": str(output_mp4),
        "bytes": output_mp4.stat().st_size,
        "ffmpeg": ffmpeg_bin,
    }


def build_media_markdown(
    *,
    title: str,
    source_url: str,
    fname: str,
    fsize: int | None,
    cover_rel: str | None,
    stream_path: str | None,
    download_blocked: bool,
    permission: str | None = None,
    preview_rel: str | None = None,
    preview_bytes: int | None = None,
) -> str:
    """Markdown card for a WPS media (video/audio) share — no Office body."""
    lines = [
        f"> 来源: {source_url}",
        "> 类型: WPS 媒体文件 (video/audio)",
    ]
    if permission:
        lines.append(f"> 权限: {permission}")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- 文件名: `{fname}`")
    lines.append(f"- 原始大小: {format_bytes(fsize)}")
    lines.append(f"- 在线打开: [{source_url}]({source_url})")
    lines.append("")
    if cover_rel:
        lines.append(f"![封面]({cover_rel})")
        lines.append("")
    lines.append("## 视频")
    lines.append("")
    if preview_rel:
        lines.append("本地预览版（分享页 HLS 转码流，ffmpeg 合成，非原始上传文件）:")
        lines.append("")
        lines.append(f"[{Path(preview_rel).name}]({preview_rel})")
        lines.append("")
        lines.append(
            f'<video src="{preview_rel}" controls preload="metadata" width="100%"></video>'
        )
        lines.append("")
        if preview_bytes is not None:
            lines.append(f"- 本地预览文件大小: {format_bytes(preview_bytes)}")
            lines.append("")
    lines.append(f"在线预览（分享页）: [{title}]({source_url})")
    lines.append("")
    if stream_path and not preview_rel:
        lines.append(f"预览流 (HLS): `{stream_path}`")
        lines.append("")
        lines.append(
            "说明: 分享页提供转码预览流（m3u8）。安装 ffmpeg 后再次运行可尝试合成本地 `preview.mp4`。"
        )
        lines.append("")
    elif preview_rel:
        lines.append("说明: 本地文件来自分享页转码预览流，不是原始上传文件。")
        lines.append("")
    if download_blocked:
        lines.append(
            "<!-- download: original file download denied for this share "
            "(preview stream / cover may still be available) -->"
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_pdf_preview_markdown(
    *,
    title: str,
    source_url: str,
    pages: list[tuple[str, str]],
    kind: str = "pdf",
    headings: list[str] | None = None,
) -> str:
    """Markdown for a WPS PDF / presentation share captured from the web viewer."""
    if kind == "presentation":
        type_line = "> 类型: WPS 演示文稿分享（网页预览分页截图；分享禁止原文件下载）"
    elif kind == "dbsheet":
        type_line = "> 类型: WPS 多维表分享（网页预览分页截图；按左侧视图截图，原文件类型不允许下载）"
    else:
        type_line = "> 类型: WPS PDF 分享（网页预览分页截图 + OCR）"
    lines = [
        f"> 来源: {source_url}",
        type_line,
        "",
        f"# {title}",
        "",
    ]
    for i, (rel, ocr) in enumerate(pages, 1):
        if kind == "dbsheet":
            heading = ""
            if headings and i - 1 < len(headings):
                heading = str(headings[i - 1] or "").strip()
            lines.append(f"## {heading or f'视图 {i}'}")
        else:
            lines.append(f"## 第 {i} 页")
        lines.append("")
        lines.append(f"![]({rel})")
        lines.append("")
        text = (ocr or "").strip()
        if text:
            lines.append(text)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url


def safe_stem(name: str) -> str:
    base = Path(name).stem or name
    return SAFE_NAME_RE.sub("_", base).strip("._") or "wps_document"


def detect_office_ext(data: bytes) -> str:
    import io

    if data[:4] == b"%PDF":
        return "pdf"
    if data[:4] != b"PK\x03\x04":
        return "bin"
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
    except Exception:
        return "bin"
    if any(n.startswith("word/") for n in names):
        return "docx"
    if any(n.startswith("ppt/") for n in names):
        return "pptx"
    if any(n.startswith("xl/") for n in names):
        return "xlsx"
    return "docx"


def iter_otl_pictures(raw: dict) -> list[dict]:
    """Return picture attrs in document order."""
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


def _ext_from_shape(entry: dict, body: bytes, ctype: str = "") -> str:
    ext = str(entry.get("raw_ext") or "").lower().lstrip(".")
    if ext in {"png", "jpg", "jpeg", "webp", "gif"}:
        return "jpg" if ext == "jpeg" else ext
    if "webp" in ctype:
        return "webp"
    if "jpeg" in ctype or "jpg" in ctype or body.startswith(b"\xff\xd8"):
        return "jpg"
    if "gif" in ctype or body[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return "png"


def merge_shapes_payload(payload: object, into: dict[str, dict]) -> int:
    """Merge `/attachment/shapes` JSON into sourceKey → shape entry. Returns new keys."""
    added = 0
    data = None
    if isinstance(payload, dict):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else None
        if data is None and any(isinstance(v, dict) and ("url" in v or "raw" in v) for v in payload.values()):
            data = payload
    if not isinstance(data, dict):
        return 0
    for key, entry in data.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        if not (entry.get("raw") or entry.get("url") or entry.get("thumbnail")):
            continue
        if key not in into:
            added += 1
        into[key] = entry
    return added


def shapes_cover_pictures(pictures: list[dict], shapes: dict[str, dict]) -> bool:
    keys = [str(a.get("sourceKey") or "") for a in pictures]
    wanted = [k for k in keys if k]
    if not wanted:
        return False
    return all(k in shapes for k in wanted)


def scroll_until_shapes(
    page,
    pictures: list[dict],
    shapes: dict[str, dict],
    *,
    max_rounds: int = 100,
    step_px: int = 1600,
    pause_ms: int = 280,
) -> None:
    """Scroll the weboffice page to force lazy `/attachment/shapes` batches."""
    if shapes_cover_pictures(pictures, shapes):
        return
    for _ in range(max_rounds):
        if shapes_cover_pictures(pictures, shapes):
            return
        try:
            page.mouse.wheel(0, step_px)
            page.wait_for_timeout(pause_ms)
        except Exception:
            break
    # one reverse pass then forward again for stragglers
    try:
        for _ in range(15):
            page.mouse.wheel(0, -2500)
            page.wait_for_timeout(180)
        for _ in range(40):
            if shapes_cover_pictures(pictures, shapes):
                return
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(250)
    except Exception:
        pass


def fetch_images_by_source_keys(
    context,
    pictures: list[dict],
    shapes: dict[str, dict],
    *,
    referer: str,
) -> list[tuple[str, bytes] | None]:
    """Download shape `raw` (else url) for each picture in order. Missing → None."""
    out: list[tuple[str, bytes] | None] = []
    headers = {"Referer": referer, "Accept": "image/*,*/*"}
    for attrs in pictures:
        key = str(attrs.get("sourceKey") or "")
        entry = shapes.get(key) if key else None
        if not isinstance(entry, dict):
            out.append(None)
            continue
        url = entry.get("raw") or entry.get("url") or entry.get("thumbnail")
        if not url:
            out.append(None)
            continue
        try:
            r = context.request.get(str(url), headers=headers)
            if r.status != 200:
                out.append(None)
                continue
            body = r.body()
            if not body or len(body) < 100:
                out.append(None)
                continue
            ctype = r.headers.get("content-type") or ""
            out.append((_ext_from_shape(entry, body, ctype), body))
        except Exception:
            out.append(None)
    return out


def fill_images_cdn_or_shapes(
    pictures: list[dict],
    cdn_ordered: list[tuple[str, bytes]],
    shaped: list[tuple[str, bytes] | None] | None,
) -> tuple[list[tuple[str, bytes] | None], str]:
    """Choose image list aligned 1:1 with pictures.

    Returns (aligned slots, strategy_name). Slot is None when missing.
    """
    n = len(pictures)
    if n == 0:
        return [], "none"
    # Prefer CDN when complete; else fill via /attachment/shapes sourceKey map
    if len(cdn_ordered) >= n:
        return list(cdn_ordered[:n]), "otl-picture-matched"
    # Incomplete CDN capture: sourceKey via /attachment/shapes
    if shaped is not None and any(x is not None for x in shaped):
        aligned: list[tuple[str, bytes] | None] = []
        for i in range(n):
            aligned.append(shaped[i] if i < len(shaped) else None)
        return aligned, "otl-shapes-sourcekey"
    # Degraded: keep whatever CDN matched (prefix only — may mis-align if gaps
    # were in the middle; still better than empty for light docs)
    aligned = list(cdn_ordered) + [None] * max(0, n - len(cdn_ordered))
    return aligned[:n], "otl-picture-matched-partial"

def image_pixel_size(data: bytes) -> tuple[int, int] | None:
    import io

    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            return int(im.size[0]), int(im.size[1])
    except Exception:
        return None


def _aspect(w: float, h: float) -> float:
    return w / h if h else 0.0


def match_images_to_pictures(
    pictures: list[dict],
    captured: list[tuple[str, str, bytes]],
) -> list[tuple[str, bytes]]:
    """Order captured CDN images to match OTL picture nodes (by aspect / scale).

    Returns list of (ext, bytes) aligned to `pictures`. Missing matches omit entries
    only when no candidates remain; prefer one image per picture.
    """
    # Unique candidates with pixel size
    seen: set[int] = set()
    candidates: list[dict] = []
    for url, ctype, body in captured:
        h = hash(body)
        if h in seen:
            continue
        seen.add(h)
        size = image_pixel_size(body)
        if not size:
            continue
        ext = "png"
        if "webp" in ctype:
            ext = "webp"
        elif "jpeg" in ctype or "jpg" in ctype or body[:3] == b"\xff\xd8":
            ext = "jpg"
        candidates.append(
            {
                "url": url,
                "ctype": ctype,
                "body": body,
                "ext": ext,
                "w": size[0],
                "h": size[1],
                "aspect": _aspect(size[0], size[1]),
            }
        )

    used: set[int] = set()
    ordered: list[tuple[str, bytes]] = []

    for attrs in pictures:
        try:
            ow = float(attrs.get("oriWidth") or 0)
            oh = float(attrs.get("oriHeight") or 0)
        except (TypeError, ValueError):
            ow = oh = 0.0
        if ow <= 0 or oh <= 0:
            # no size hint — take next unused by capture order
            for i, c in enumerate(candidates):
                if i not in used:
                    used.add(i)
                    ordered.append((c["ext"], c["body"]))
                    break
            continue

        target_aspect = _aspect(ow, oh)
        best_i = None
        best_score = 1e18
        for i, c in enumerate(candidates):
            if i in used:
                continue
            # Prefer similar aspect; also prefer scale factors close between axes
            aspect_diff = abs(c["aspect"] - target_aspect) / max(target_aspect, 1e-6)
            sx = c["w"] / ow
            sy = c["h"] / oh
            scale_skew = abs(sx - sy) / max(max(sx, sy), 1e-6)
            # Prefer scales <= 1.05 (thumbnails / originals), lightly penalize huge upscales
            scale_pen = 0.0 if sx <= 1.05 else min(sx - 1.0, 2.0)
            score = aspect_diff * 10.0 + scale_skew * 5.0 + scale_pen
            if score < best_score:
                best_score = score
                best_i = i

        if best_i is None:
            continue
        used.add(best_i)
        c = candidates[best_i]
        ordered.append((c["ext"], c["body"]))

    return ordered


def ensure_session(url: str | None = None, *, auto_login: bool = True) -> Path:
    if DEFAULT_STATE.is_file():
        return DEFAULT_STATE
    if auto_login:
        interactive_wps_login(url or "https://365.kdocs.cn/")
        if DEFAULT_STATE.is_file():
            return DEFAULT_STATE
    raise WpsError(
        f"Session not found: {DEFAULT_STATE}\n"
        "Run first:\n"
        f"  {sys.executable} {SCRIPTS / 'wps_login.py'} '<share_url>'\n"
        "Then retry."
    )


def interactive_wps_login(url: str) -> None:
    """Open headed Chrome for the user to log in; do not scrape credentials."""
    print(
        "WPS session missing or expired — opening Chrome. "
        "Complete login in the window; conversion will continue.",
        file=sys.stderr,
    )
    from wps_login import LoginError, run_login

    try:
        run_login(url)
    except LoginError as e:
        raise WpsError(str(e)) from e


def convert_office(src: Path, md_out: Path) -> dict:
    cmd = [
        sys.executable,
        str(SCRIPTS / "convert.py"),
        str(src),
        "-o",
        str(md_out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise WpsError(proc.stderr.strip() or proc.stdout.strip() or "convert.py failed")
    stats = {}
    for line in proc.stdout.splitlines():
        if ": " in line and not line.startswith("OK"):
            k, v = line.split(": ", 1)
            stats[k] = v
    return stats


def read_pdf_viewer_label(page) -> str:
    """Read the WPS PDF toolbar page label (input value + nearby text)."""
    try:
        info = page.evaluate(
            """() => {
              const inp = document.querySelector('input.kd-input-inner-align-center');
              const val = (inp && inp.value) || '';
              const nearby = inp && inp.parentElement
                ? (inp.parentElement.innerText || '')
                : '';
              return {val, nearby};
            }"""
        )
    except Exception:
        return ""
    if not isinstance(info, dict):
        return ""
    return f"{info.get('val') or ''} {info.get('nearby') or ''}"


def goto_pdf_preview_page(page, n: int) -> None:
    loc = page.locator(PDF_PAGE_INPUT_SEL).first
    if loc.count() == 0:
        return
    loc.click(timeout=5000)
    loc.fill(str(n), timeout=5000)
    loc.press("Enter")
    page.wait_for_timeout(800)


def screenshot_visible_pdf_page(page, dest: Path) -> bool:
    """Screenshot the `.pdf-page` closest to the viewport center."""
    try:
        idx = page.evaluate(
            """() => {
              const pages = [...document.querySelectorAll('.pdf-page')];
              if (!pages.length) return -1;
              const mid = window.innerHeight / 2;
              let best = 0, bestDist = 1e9;
              pages.forEach((el, i) => {
                const r = el.getBoundingClientRect();
                const c = r.top + r.height / 2;
                const d = Math.abs(c - mid);
                if (d < bestDist) { bestDist = d; best = i; }
              });
              pages[best]?.scrollIntoView({block: 'center'});
              return best;
            }"""
        )
    except Exception:
        return False
    if not isinstance(idx, int) or idx < 0:
        return False
    page.wait_for_timeout(350)
    loc = page.locator(PDF_PAGE_SEL).nth(idx)
    try:
        loc.wait_for(state="visible", timeout=8000)
        loc.screenshot(path=str(dest))
    except Exception:
        return False
    return dest.is_file() and dest.stat().st_size > 500


def capture_pdf_preview_pages(page, assets_dir: Path) -> list[Path]:
    """Capture each PDF viewer page as PNG. Empty list if the viewer did not load."""
    try:
        page.wait_for_selector(PDF_PAGE_SEL, timeout=25000)
    except Exception:
        return []
    page.wait_for_timeout(800)
    try:
        page.set_viewport_size({"width": 1600, "height": 1000})
    except Exception:
        pass

    _, total = parse_pdf_page_label(read_pdf_viewer_label(page))
    assets_dir.mkdir(parents=True, exist_ok=True)
    for old in assets_dir.glob("page_*.png"):
        old.unlink()

    saved: list[Path] = []
    seen: set[str] = set()
    limit = total or MAX_PDF_PREVIEW_PAGES
    consecutive_dupes = 0
    for n in range(1, limit + 1):
        if n > 1 or total:
            goto_pdf_preview_page(page, n)
            if n > 1 and not total and page.locator(PDF_PAGE_INPUT_SEL).count() == 0:
                try:
                    page.mouse.wheel(0, 900)
                    page.wait_for_timeout(500)
                except Exception:
                    pass
        dest = assets_dir / f"page_{n:03d}.png"
        if not screenshot_visible_pdf_page(page, dest):
            break
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        if digest in seen:
            dest.unlink(missing_ok=True)
            consecutive_dupes += 1
            if total:
                continue
            if consecutive_dupes >= 2:
                break
            continue
        consecutive_dupes = 0
        seen.add(digest)
        saved.append(dest)
        if not total:
            _, discovered = parse_pdf_page_label(read_pdf_viewer_label(page))
            if discovered:
                total = discovered
                limit = discovered
    return saved


def _wpp_total_pages(page) -> int | None:
    try:
        n = page.evaluate("() => window.__WPSENV__ && window.__WPSENV__.wpp_total_pages")
    except Exception:
        return None
    if isinstance(n, int) and 1 <= n <= MAX_WPP_PREVIEW_PAGES:
        return n
    return None


def capture_wpp_preview_pages(page, assets_dir: Path) -> list[Path]:
    """Screenshot each WPS presentation slide (download-denied .pptx)."""
    try:
        page.wait_for_selector(WPP_SLIDE_SEL, timeout=25000)
    except Exception:
        return []
    try:
        page.set_viewport_size({"width": 1600, "height": 1000})
    except Exception:
        pass
    page.wait_for_timeout(800)
    loc = page.locator(WPP_SLIDE_SEL).first
    try:
        thumb = page.locator(".thumbnail_slide").first
        if thumb.count() > 0:
            thumb.click(timeout=5000)
            page.wait_for_timeout(700)
    except Exception:
        pass
    try:
        loc.click(timeout=5000)
    except Exception:
        pass

    total = _wpp_total_pages(page)
    assets_dir.mkdir(parents=True, exist_ok=True)
    for old in assets_dir.glob("page_*.png"):
        old.unlink()

    saved: list[Path] = []
    seen: set[str] = set()
    limit = total or MAX_WPP_PREVIEW_PAGES
    consecutive_dupes = 0
    for n in range(1, limit + 1):
        if n > 1:
            prev = hashlib.sha256(saved[-1].read_bytes()).hexdigest() if saved else ""
            try:
                loc.click(timeout=3000)
            except Exception:
                pass
            page.keyboard.press("PageDown")
            changed = False
            for _ in range(20):
                page.wait_for_timeout(200)
                probe = assets_dir / ".wpp_probe.png"
                try:
                    loc.screenshot(path=str(probe))
                    digest_p = hashlib.sha256(probe.read_bytes()).hexdigest()
                except Exception:
                    digest_p = prev
                finally:
                    probe.unlink(missing_ok=True)
                if digest_p and digest_p != prev:
                    changed = True
                    break
            if not changed and not total:
                break
        dest = assets_dir / f"page_{n:03d}.png"
        try:
            loc.wait_for(state="visible", timeout=8000)
            loc.screenshot(path=str(dest))
        except Exception:
            break
        if not dest.is_file() or dest.stat().st_size < 500:
            dest.unlink(missing_ok=True)
            break
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        if digest in seen:
            dest.unlink(missing_ok=True)
            consecutive_dupes += 1
            if total and n < total:
                continue
            if consecutive_dupes >= 2:
                break
            continue
        consecutive_dupes = 0
        seen.add(digest)
        saved.append(dest)
        if total is None:
            total = _wpp_total_pages(page)
            if total:
                limit = total
    return saved


def _clean_dbsheet_name(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for line in reversed(lines):
        letters = re.sub(r"[^\w\u4e00-\u9fff]+", "", line, flags=re.UNICODE)
        if len(letters) >= 2:
            return line[:80]
    return (lines[-1] if lines else "")[:80]


def _dbsheet_sheet_items(page) -> list[tuple[int, str, str]]:
    loc = page.locator(DB_SHEET_ITEM_SEL)
    items: list[tuple[int, str, str]] = []
    try:
        count = loc.count()
    except Exception:
        return items
    for i in range(count):
        el = loc.nth(i)
        try:
            box = el.bounding_box()
        except Exception:
            box = None
        if not box or box.get("height", 0) < 8 or box.get("width", 0) < 8:
            continue
        try:
            content = el.locator(
                ".sheet-panel-item-content, .view-item-content, .sheet-item-name-wrapper"
            ).first
            raw = content.inner_text(timeout=1000) if content.count() else el.inner_text()
        except Exception:
            raw = ""
        name = _clean_dbsheet_name(raw)
        cls = ""
        try:
            cls = str(el.get_attribute("class") or "")
        except Exception:
            cls = ""
        if "disabled" in cls or "db-hollow-guide" in cls:
            continue
        kind = "view" if "view-item" in cls else "sheet"
        items.append((i, name, kind))
    return items


DBSHEET_VIEW_PARENT_JS = """el => {
  let p = el.previousElementSibling;
  while (p) {
    const cls = (p.className || '').toString();
    if (cls.includes('et-status-sheet-item')) {
      const n = p.querySelector('.sheet-item-name-wrapper, .sheet-panel-item-content');
      return (n && n.innerText) || p.innerText || '';
    }
    p = p.previousElementSibling;
  }
  return '';
}"""


def _dbsheet_view_parent(el) -> str:
    try:
        return _clean_dbsheet_name(el.evaluate(DBSHEET_VIEW_PARENT_JS) or "")
    except Exception:
        return ""


def _dbsheet_clip(page) -> dict | None:
    """Viewport clip of the main view, excluding the left sheet rail."""
    try:
        box = page.evaluate(
            """() => {
              const panel = document.querySelector('.sheet-panel');
              const main = document.querySelector('.workbench-main-content')
                || document.querySelector('.workbench-view-content')
                || document.querySelector('.div_et_grid')
                || document.querySelector('.grid-view')
                || document.querySelector('.db-grid-view-wrapper')
                || document.querySelector('.workbench-content.main')
                || document.querySelector('.workbench-content');
              if (!main) return null;
              const r = main.getBoundingClientRect();
              const left = panel ? Math.max(r.left, panel.getBoundingClientRect().right) : r.left;
              const x = Math.max(0, Math.floor(left));
              const y = Math.max(0, Math.floor(r.top));
              const width = Math.floor(r.right - x);
              const height = Math.floor(r.bottom - y);
              if (width < 80 || height < 80) return null;
              return {x, y, width, height};
            }"""
        )
    except Exception:
        return None
    if not isinstance(box, dict):
        return None
    return box


def capture_dbsheet_preview_pages(page, assets_dir: Path) -> list[tuple[Path, str]]:
    """Screenshot each visible dbsheet / dashboard view (download notAllowType)."""
    try:
        page.set_viewport_size({"width": 1600, "height": 1000})
    except Exception:
        pass
    try:
        page.wait_for_selector(f"{DB_VIEW_SEL}, {DB_SHEET_ITEM_SEL}", timeout=25000)
    except Exception:
        return []
    page.wait_for_timeout(800)
    items = _dbsheet_sheet_items(page)
    assets_dir.mkdir(parents=True, exist_ok=True)
    for old in assets_dir.glob("page_*.png"):
        old.unlink()

    def _shot(dest: Path) -> bool:
        clip = _dbsheet_clip(page)
        try:
            if clip:
                page.screenshot(path=str(dest), clip=clip)
            else:
                view = page.locator(DB_VIEW_SEL).first
                if view.count() > 0:
                    view.screenshot(path=str(dest))
                else:
                    page.screenshot(path=str(dest))
        except Exception:
            return False
        return dest.is_file() and dest.stat().st_size >= 500

    saved: list[tuple[Path, str]] = []
    seen: set[str] = set()
    if not items:
        dest = assets_dir / "page_001.png"
        if _shot(dest):
            return [(dest, "当前视图")]
        dest.unlink(missing_ok=True)
        return []

    clicked: set[str] = set()
    n = 0
    while n < MAX_DBSHEET_SHEETS:
        loc = page.locator(DB_SHEET_ITEM_SEL)
        pending = []
        for idx, name, kind in _dbsheet_sheet_items(page):
            parent_name = _dbsheet_view_parent(loc.nth(idx)) if kind == "view" else ""
            key = f"{kind}:{parent_name}:{name or idx}"
            if key not in clicked:
                pending.append((idx, name, kind, key, parent_name))
        if not pending:
            break
        idx, name, kind, key, parent_name = pending[0]
        clicked.add(key)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        try:
            loc.nth(idx).click(timeout=5000, force=True)
        except Exception:
            continue
        page.wait_for_timeout(1600)
        n += 1
        dest = assets_dir / f"page_{n:03d}.png"
        if not _shot(dest):
            dest.unlink(missing_ok=True)
            n -= 1
            continue
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        if digest in seen and kind == "view":
            dest.unlink(missing_ok=True)
            n -= 1
            continue
        seen.add(digest)
        label = name
        if kind == "view" and parent_name and name:
            label = f"{parent_name} / {name}"
        saved.append((dest, label or f"视图 {len(saved) + 1}"))
    return saved


def write_pdf_preview_markdown(
    *,
    title: str,
    source_url: str,
    output_md: Path,
    page_files: list[Path],
    kind: str = "pdf",
    ocr: bool = True,
    headings: list[str] | None = None,
) -> dict:
    from convert import ocr_image_text

    assets_dir = page_files[0].parent if page_files else output_md.parent
    pages: list[tuple[str, str]] = []
    engines: set[str] = set()
    for img in page_files:
        rel = f"{assets_dir.name}/{img.name}"
        text = ""
        if ocr:
            text, engine = ocr_image_text(img)
            engines.add(engine)
        pages.append((rel, text))
    md = build_pdf_preview_markdown(
        title=title,
        source_url=source_url,
        pages=pages,
        kind=kind,
        headings=headings,
    )
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(md, encoding="utf-8")
    return {
        "pages": len(page_files),
        "ocr_engines": sorted(engines),
        "markdown_chars": len(md),
        "assets_dir": str(assets_dir),
    }


def convert_otl(otl_json: Path, md_out: Path, assets_dir: Path, source_url: str) -> dict:
    from otl_to_md import convert_file

    return convert_file(
        otl_json,
        md_out,
        assets_dir=assets_dir,
        source_url=source_url,
    )


NESTED_HREF_RE = re.compile(r"https?://[^\s)>\"]+", re.IGNORECASE)


def resolve_nested_depth(*, recursive: bool = False, max_depth: int | None = None) -> int:
    """`--recursive` means depth 1. Explicit `--max-depth` wins."""
    if max_depth is not None:
        if max_depth < 0:
            raise ValueError("--max-depth must be >= 0")
        return max_depth
    return 1 if recursive else 0


def rewrite_nested_share_links(md: str, replacements: dict[str, str]) -> str:
    """Replace kdocs/wps share URLs with local relative paths, keyed by share id."""
    if not replacements:
        return md

    def repl(match: re.Match[str]) -> str:
        url = match.group(0)
        try:
            sid = extract_share_id(url)
        except WpsError:
            return url
        return replacements.get(sid) or url

    return NESTED_HREF_RE.sub(repl, md)


def expand_nested_otl_documents(
    raw: dict,
    parent_md: Path,
    *,
    max_depth: int,
    visited: set[str],
    auto_login: bool = False,
    convert_child=None,
) -> list[dict]:
    """Convert unique nested WPSDocument cards one level (or max_depth) down.

    Success: rewrite parent Markdown links to `{parent}_nested/{child}.md`.
    Failure / cycle: keep the original kdocs URL. Never fails the parent.
    """
    from otl_to_md import iter_wps_document_cards

    reports: list[dict] = []
    if max_depth < 1:
        return reports

    converter = convert_child or share_to_markdown
    parent_md = parent_md.expanduser().resolve()
    nested_dir = parent_md.parent / f"{parent_md.stem}_nested"
    replacements: dict[str, str] = {}
    used_stems: set[str] = set()

    for card in iter_wps_document_cards(raw):
        href = str(card.get("href") or "").strip()
        name = str(card.get("name") or "").strip()
        dtype = str(card.get("type") or "").strip()
        if not href:
            reports.append(
                {
                    "ok": False,
                    "name": name,
                    "type": dtype,
                    "skipped": "no share url",
                }
            )
            continue
        try:
            child_sid = extract_share_id(href)
        except WpsError as e:
            reports.append(
                {
                    "ok": False,
                    "name": name,
                    "href": href,
                    "type": dtype,
                    "error": str(e)[:300],
                }
            )
            continue
        if child_sid in visited:
            reports.append(
                {
                    "ok": False,
                    "name": name,
                    "share_id": child_sid,
                    "type": dtype,
                    "skipped": "already visited",
                }
            )
            continue

        stem = safe_stem(Path(name).stem if name else child_sid)
        if stem in used_stems or (nested_dir / f"{stem}.md").exists():
            stem = f"{stem}_{child_sid[:8]}"
        used_stems.add(stem)
        dest = nested_dir / f"{stem}.md"
        try:
            nested_dir.mkdir(parents=True, exist_ok=True)
            child_result = converter(
                href,
                dest,
                auto_login=auto_login,
                max_depth=max_depth - 1,
                _visited=visited,
            )
            rel = dest.relative_to(parent_md.parent).as_posix()
            replacements[child_sid] = rel
            reports.append(
                {
                    "ok": True,
                    "name": name,
                    "share_id": child_sid,
                    "type": dtype,
                    "output": str(dest),
                    "mode": (child_result or {}).get("mode") if isinstance(child_result, dict) else None,
                }
            )
        except Exception as e:
            reports.append(
                {
                    "ok": False,
                    "name": name,
                    "share_id": child_sid,
                    "href": href,
                    "type": dtype,
                    "error": str(e)[:300],
                }
            )

    if replacements and parent_md.is_file():
        text = parent_md.read_text(encoding="utf-8")
        parent_md.write_text(rewrite_nested_share_links(text, replacements), encoding="utf-8")
    return reports


def share_to_markdown(
    url: str,
    output_md: Path,
    *,
    auto_login: bool = True,
    _login_retried: bool = False,
    max_depth: int = 0,
    _visited: set[str] | None = None,
) -> dict:
    url = normalize_url(url)
    visited = _visited if _visited is not None else set()
    try:
        return _share_to_markdown_once(
            url,
            output_md,
            auto_login=auto_login,
            max_depth=max_depth,
            visited=visited,
        )
    except _SessionExpired:
        if auto_login and not _login_retried:
            interactive_wps_login(url)
            return share_to_markdown(
                url,
                output_md,
                auto_login=auto_login,
                _login_retried=True,
                max_depth=max_depth,
                _visited=visited,
            )
        raise WpsError(
            "Failed to load share meta. Session may be expired — re-run wps_login.py."
        )


class _SessionExpired(WpsError):
    """Internal: share meta failed; wrapper may prompt login and retry once."""


def _share_to_markdown_once(
    url: str,
    output_md: Path,
    *,
    auto_login: bool = True,
    max_depth: int = 0,
    visited: set[str] | None = None,
) -> dict:
    from playwright.sync_api import sync_playwright
    from otl_to_md import convert_file, load_otl

    sid = extract_share_id(url)
    seen = visited if visited is not None else set()
    seen.add(sid)
    state = ensure_session(url, auto_login=auto_login)
    output_md = output_md.expanduser().resolve()
    output_md.parent.mkdir(parents=True, exist_ok=True)
    work = output_md.parent / f".doc2md_work_{sid}"
    work.mkdir(parents=True, exist_ok=True)

    result: dict = {"url": url, "share_id": sid, "mode": None, "output": str(output_md)}
    nested_otl_path: Path | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(storage_state=str(state))

        # --- link meta ---
        # Prefer 365 / www first: drive.kdocs.cn often hangs from some networks.
        # drive.wps.cn works well for plus.wps.cn media shares.
        meta = None
        resolved_sid = sid
        for cand in share_id_candidates(url):
            meta_urls = [
                f"https://drive.wps.cn/api/v5/links/{cand}?review=true",
                f"https://365.kdocs.cn/3rd/drive/api/v5/links/{cand}",
                f"https://www.kdocs.cn/3rd/drive/api/v5/links/{cand}",
                f"https://drive.kdocs.cn/api/v5/links/{cand}",
            ]
            for mu in meta_urls:
                try:
                    r = context.request.get(
                        mu,
                        headers={
                            "Accept": "application/json",
                            "Referer": url,
                            "Origin": "https://365.kdocs.cn",
                        },
                        timeout=15000,
                    )
                except Exception:
                    continue
                if r.status != 200:
                    continue
                try:
                    payload = r.json()
                except Exception:
                    continue
                fi_try = payload.get("fileinfo") or {}
                if fi_try.get("id") or fi_try.get("fname") or fi_try.get("name"):
                    meta = payload
                    resolved_sid = cand
                    break
            if meta:
                break
        if not meta:
            browser.close()
            raise _SessionExpired()

        sid = resolved_sid
        result["share_id"] = sid
        seen.add(sid)
        open_url = viewer_share_url(sid)

        fi = meta.get("fileinfo") or {}
        file_id = str(fi.get("id") or "")
        group_id = str(fi.get("groupid") or "")
        fname = str(fi.get("fname") or fi.get("name") or sid)
        ftype = str(fi.get("ftype") or "")
        result.update(
            {
                "file_id": file_id,
                "group_id": group_id,
                "name": fname,
                "ftype": ftype,
            }
        )

        is_otl = fname.lower().endswith(".otl") or ftype.lower() in {"otl", "o", "outline"}
        is_media = is_media_filename(fname) or "/view/media/" in url.lower()
        is_pdf = is_pdf_share(fname, ftype=ftype)
        is_wpp = is_presentation_share(fname)
        is_dbt = is_dbsheet_share(fname)

        # --- media / video share: Markdown card + cover (no Office body) ---
        if is_media and file_id and group_id:
            stem = safe_stem(Path(fname).stem if fname else sid)
            if output_md.name in {"out.md", "output.md"} or output_md.stem == "wps_out":
                output_md = output_md.with_name(f"{stem}.md")
                result["output"] = str(output_md)

            assets_dir = output_md.parent / f"{output_md.stem}_assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            cover_rel = None
            stream_path = None
            download_blocked = True
            permission = str(
                (meta.get("user_permission") or (meta.get("linkinfo") or {}).get("link_permission") or "")
            )
            fsize = (meta.get("fileinfo") or {}).get("fsize")
            try:
                fsize_i = int(fsize) if fsize is not None else None
            except (TypeError, ValueError):
                fsize_i = None

            preview_urls = [
                f"https://api.wps.cn/office/v5/extensions/preview/groups/{group_id}/files/{file_id}/media/preview?preview_style=link",
                f"https://plus.wps.cn/office/v5/extensions/preview/groups/{group_id}/files/{file_id}/media/preview?preview_style=link",
            ]
            preview = None
            for pu in preview_urls:
                try:
                    pr = context.request.get(
                        pu,
                        headers={"Accept": "application/json", "Referer": url},
                        timeout=20000,
                    )
                except Exception:
                    continue
                if pr.status != 200:
                    continue
                try:
                    preview = pr.json()
                    break
                except Exception:
                    continue

            if isinstance(preview, dict):
                pdata = preview.get("data") if isinstance(preview.get("data"), dict) else preview
                if isinstance(pdata, dict):
                    stream_path = pdata.get("stream_path") or pdata.get("streamPath")
                    cover_url = pdata.get("video_cover") or pdata.get("videoCover")
                    if cover_url:
                        try:
                            cr = context.request.get(str(cover_url), timeout=30000)
                            if cr.status == 200:
                                body = cr.body()
                                ctype = (cr.headers.get("content-type") or "").lower()
                                ext = ".jpg"
                                if "png" in ctype:
                                    ext = ".png"
                                elif "webp" in ctype:
                                    ext = ".webp"
                                cover_name = f"cover{ext}"
                                (assets_dir / cover_name).write_bytes(body)
                                cover_rel = f"{assets_dir.name}/{cover_name}"
                                result["cover"] = str(assets_dir / cover_name)
                        except Exception as e:
                            result["cover_error"] = str(e)[:200]

            # Probe original download (usually denied for link shares)
            try:
                dr = context.request.get(
                    f"https://drive.wps.cn/api/v3/groups/{group_id}/files/{file_id}/download",
                    headers={"Accept": "application/json", "Referer": url},
                    timeout=15000,
                )
                if dr.status == 200:
                    download_blocked = False
                    result["download_probe"] = "ok"
                else:
                    try:
                        result["download_probe"] = dr.json()
                    except Exception:
                        result["download_probe"] = {"status": dr.status, "text": dr.text()[:200]}
            except Exception as e:
                result["download_probe"] = {"error": str(e)[:200]}

            preview_rel = None
            preview_bytes = None
            # Optional: remux HLS preview with ffmpeg when original download is blocked
            if stream_path and download_blocked and find_ffmpeg():
                try:
                    page = context.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=90000)
                    page.wait_for_timeout(1500)
                    cookie_header = cookie_header_from_playwright(context.cookies())
                    page.close()
                except Exception as e:
                    cookie_header = ""
                    result["preview_cookie_error"] = str(e)[:200]
                if cookie_header:
                    mp4_path = assets_dir / "preview.mp4"
                    remux = remux_hls_with_ffmpeg(
                        str(stream_path),
                        mp4_path,
                        cookie_header=cookie_header,
                        referer=url,
                    )
                    result["preview_remux"] = {
                        k: v for k, v in remux.items() if k != "error" or not remux.get("ok")
                    }
                    if remux.get("ok"):
                        preview_rel = f"{assets_dir.name}/preview.mp4"
                        preview_bytes = int(remux["bytes"])
                    else:
                        result["preview_remux_error"] = str(remux.get("error") or "")[:500]
            elif stream_path and download_blocked and not find_ffmpeg():
                result["preview_remux"] = {"ok": False, "error": "ffmpeg not found"}

            title = Path(fname).stem or stem
            md = build_media_markdown(
                title=title,
                source_url=url,
                fname=fname,
                fsize=fsize_i,
                cover_rel=cover_rel,
                stream_path=str(stream_path) if stream_path else None,
                download_blocked=download_blocked,
                permission=permission or None,
                preview_rel=preview_rel,
                preview_bytes=preview_bytes,
            )
            output_md.parent.mkdir(parents=True, exist_ok=True)
            output_md.write_text(md, encoding="utf-8")
            if stream_path:
                (work / "stream_path.txt").write_text(str(stream_path) + "\n", encoding="utf-8")
            result["mode"] = "media"
            result["stream_path"] = stream_path
            result["download_blocked"] = download_blocked
            result["preview_video"] = str(assets_dir / "preview.mp4") if preview_rel else None
            result["markdown_chars"] = len(md)
            result["assets_dir"] = (
                str(assets_dir) if (cover_rel or preview_rel) else None
            )
            browser.close()
            return result

        # --- try binary download for Office files ---
        downloaded: Path | None = None
        if file_id and group_id and not is_otl:
            dl_apis = [
                (
                    f"https://365.kdocs.cn/3rd/drive/api/v5/groups/{group_id}/files/{file_id}/download"
                    f"?isblocks=false&support_checksums=md5,sha1"
                ),
                (
                    f"https://www.kdocs.cn/3rd/drive/api/v5/groups/{group_id}/files/{file_id}/download"
                    f"?isblocks=false&support_checksums=md5,sha1"
                ),
                (
                    f"https://drive.kdocs.cn/api/v5/groups/{group_id}/files/{file_id}/download"
                    f"?isblocks=false&support_checksums=md5,sha1"
                ),
            ]
            for api in dl_apis:
                try:
                    r = context.request.get(
                        api,
                        headers={
                            "Accept": "application/json",
                            "Referer": url,
                            "Origin": "https://365.kdocs.cn",
                        },
                        timeout=15000,
                    )
                except Exception as e:
                    result["download_error"] = {"timeout_or_error": str(e)[:200]}
                    continue
                if r.status != 200:
                    # notAllowType / auth errors → fall through to OTL path
                    try:
                        err = r.json()
                    except Exception:
                        err = {"raw": r.text()[:200]}
                    result["download_error"] = err
                    continue
                payload = r.json()
                dl_url = (
                    payload.get("url")
                    or (payload.get("data") or {}).get("url")
                    or (payload.get("fileinfo") or {}).get("url")
                )
                if not dl_url:
                    continue
                try:
                    fr = context.request.get(dl_url, timeout=60000)
                except Exception:
                    continue
                if fr.status != 200:
                    continue
                data = fr.body()
                ext = detect_office_ext(data)
                if ext == "bin":
                    continue
                downloaded = work / f"{safe_stem(fname)}.{ext}"
                downloaded.write_bytes(data)
                break

        if downloaded and downloaded.is_file():
            result["mode"] = "office"
            result["source_file"] = str(downloaded)
            browser.close()
            stats = convert_office(downloaded, output_md)
            result["convert"] = stats
            return result

        # --- PDF web viewer (download denied) / OTL / online-only ---
        otl_bytes: dict[str, bytes | None] = {"data": None}
        images: list[tuple[str, str, bytes]] = []
        shapes_map: dict[str, dict] = {}

        page = context.new_page()

        def on_response(resp) -> None:
            u = resp.url
            ctype = resp.headers.get("content-type") or ""
            if resp.status != 200:
                return
            if "/attachment/shapes" in u:
                try:
                    merge_shapes_payload(resp.json(), shapes_map)
                except Exception:
                    pass
                return
            if "/open/otl" in u and "octet-stream" in ctype:
                try:
                    otl_bytes["data"] = resp.body()
                except Exception:
                    pass
                return
            if "image/" not in ctype:
                return
            if "weboffice-temporary" not in u and "ks3" not in u:
                return
            try:
                body = resp.body()
            except Exception:
                return
            if len(body) < 20000:
                return
            images.append((u, ctype, body))

        page.on("response", on_response)
        # WPS weboffice keeps websockets/polling alive — networkidle often never settles.
        page.goto(open_url, wait_until="domcontentloaded", timeout=120000)
        try:
            page.wait_for_load_state("load", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(4000)

        # Fallback: read __WPSENV__ and confirm office type
        try:
            env = page.evaluate("() => window.__WPSENV__")
            if isinstance(env, dict):
                result["office_type"] = env.get("office_type")
                fobj = ((env.get("file_info") or {}).get("file")) or {}
                if fobj.get("name") and not fname:
                    fname = str(fobj["name"])
                if not is_pdf:
                    is_pdf = is_pdf_share(
                        fname,
                        office_type=str(env.get("office_type") or ""),
                        ftype=ftype,
                    )
                is_wpp = is_wpp or is_presentation_share(
                    fname, office_type=str(env.get("office_type") or "")
                )
                is_dbt = is_dbt or is_dbsheet_share(
                    fname, office_type=str(env.get("office_type") or "")
                )
        except Exception:
            pass

        # PDF shares often deny original download; capture the web viewer pages.
        pdf_ready = False
        if is_pdf or page.locator(PDF_PAGE_SEL).count() > 0:
            try:
                page.wait_for_selector(PDF_PAGE_SEL, timeout=15000)
                pdf_ready = True
            except Exception:
                pdf_ready = False
        if pdf_ready:
            stem = safe_stem(Path(fname).stem if fname else sid)
            if output_md.name in {"out.md", "output.md"} or output_md.stem == "wps_out":
                output_md = output_md.with_name(f"{stem}.md")
                result["output"] = str(output_md)
            assets_dir = output_md.parent / f"{output_md.stem}_assets"
            page_files = capture_pdf_preview_pages(page, assets_dir)
            browser.close()
            if not page_files:
                raise WpsError(
                    "Could not capture PDF preview pages. "
                    "Re-run wps_login.py, or export the file from the WPS UI and run convert.py."
                )
            stats = write_pdf_preview_markdown(
                title=Path(fname).stem or stem,
                source_url=url,
                output_md=output_md,
                page_files=page_files,
            )
            result["mode"] = "pdf-preview"
            result["convert"] = stats
            result["pages"] = stats.get("pages")
            result["assets_dir"] = stats.get("assets_dir")
            result["markdown_chars"] = stats.get("markdown_chars")
            return result

        # Presentation shares often deny original download; screenshot each slide.
        wpp_ready = False
        if is_wpp or page.locator(WPP_SLIDE_SEL).count() > 0:
            try:
                page.wait_for_selector(WPP_SLIDE_SEL, timeout=15000)
                wpp_ready = True
            except Exception:
                wpp_ready = False
        if wpp_ready:
            stem = safe_stem(Path(fname).stem if fname else sid)
            if output_md.name in {"out.md", "output.md"} or output_md.stem == "wps_out":
                output_md = output_md.with_name(f"{stem}.md")
                result["output"] = str(output_md)
            assets_dir = output_md.parent / f"{output_md.stem}_assets"
            page_files = capture_wpp_preview_pages(page, assets_dir)
            browser.close()
            if not page_files:
                raise WpsError(
                    "Could not capture presentation slides. "
                    "Re-run wps_login.py, or export the .pptx from the WPS UI and run convert.py."
                )
            stats = write_pdf_preview_markdown(
                title=Path(fname).stem or stem,
                source_url=url,
                output_md=output_md,
                page_files=page_files,
                kind="presentation",
                ocr=False,
            )
            result["mode"] = "wpp-preview"
            result["convert"] = stats
            result["pages"] = stats.get("pages")
            result["assets_dir"] = stats.get("assets_dir")
            result["markdown_chars"] = stats.get("markdown_chars")
            return result

        # Dbsheet shares deny original download (notAllowType); screenshot each view.
        dbt_ready = False
        if is_dbt:
            try:
                page.wait_for_selector(
                    f"{DB_VIEW_SEL}, {DB_SHEET_ITEM_SEL}", timeout=15000
                )
                dbt_ready = True
            except Exception:
                dbt_ready = False
        if dbt_ready:
            stem = safe_stem(Path(fname).stem if fname else sid)
            if output_md.name in {"out.md", "output.md"} or output_md.stem == "wps_out":
                output_md = output_md.with_name(f"{stem}.md")
                result["output"] = str(output_md)
            assets_dir = output_md.parent / f"{output_md.stem}_assets"
            captured = capture_dbsheet_preview_pages(page, assets_dir)
            browser.close()
            if not captured:
                raise WpsError(
                    "Could not capture dbsheet views. "
                    "Re-run wps_login.py, or export from the WPS UI and run convert.py."
                )
            page_files = [p for p, _ in captured]
            headings = [name for _, name in captured]
            stats = write_pdf_preview_markdown(
                title=Path(fname).stem or stem,
                source_url=url,
                output_md=output_md,
                page_files=page_files,
                kind="dbsheet",
                headings=headings,
            )
            result["mode"] = "dbt-preview"
            result["convert"] = stats
            result["pages"] = stats.get("pages")
            result["views"] = headings
            result["assets_dir"] = stats.get("assets_dir")
            result["markdown_chars"] = stats.get("markdown_chars")
            return result

        if is_dbt:
            browser.close()
            raise WpsError(
                "Could not load the dbsheet web viewer. "
                "Re-run wps_login.py, or export from the WPS UI and run convert.py."
            )

        # OTL path: scroll to lazy-load CDN images / shapes.
        try:
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(2500)
        except Exception:
            pass

        data = otl_bytes["data"]
        if not data:
            browser.close()
            raise WpsError(
                "Could not capture open/otl content. "
                "Session may lack permission, or the doc type is unsupported. "
                "Export manually from WPS UI and run convert.py."
            )

        stem = safe_stem(Path(fname).stem if fname else sid)
        otl_path = work / f"{stem}.otl.json"
        try:
            parsed = json.loads(data.decode("utf-8"))
            otl_path.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
        except Exception:
            otl_path.write_bytes(data)
            parsed = json.loads(otl_path.read_text(encoding="utf-8"))

        pictures = iter_otl_pictures(parsed)
        cdn_ordered = match_images_to_pictures(pictures, images)

        shaped: list[tuple[str, bytes] | None] | None = None
        if len(cdn_ordered) < len(pictures) and pictures:
            # CDN incomplete: scroll + /attachment/shapes by sourceKey
            scroll_until_shapes(page, pictures, shapes_map)
            shaped = fetch_images_by_source_keys(
                context, pictures, shapes_map, referer=url
            )
            # One more pass for any still-missing keys
            if any(x is None for x in shaped):
                scroll_until_shapes(page, pictures, shapes_map, max_rounds=40)
                shaped = fetch_images_by_source_keys(
                    context, pictures, shapes_map, referer=url
                )
            result["shapes_keys"] = len(shapes_map)
            result["shapes_downloaded"] = sum(1 for x in shaped if x is not None)

        browser.close()

        aligned, order_name = fill_images_cdn_or_shapes(pictures, cdn_ordered, shaped)

        assets_dir = output_md.parent / f"{output_md.stem}_assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        for old in assets_dir.glob("image_*"):
            old.unlink()

        image_files: list[Path | None] = []
        saved = 0
        for i, slot in enumerate(aligned, 1):
            if slot is None:
                image_files.append(None)
                continue
            ext, body = slot
            name = f"image_{i:03d}.{ext}"
            dest = assets_dir / name
            dest.write_bytes(body)
            image_files.append(dest)
            saved += 1

        stats = convert_file(
            otl_path,
            output_md,
            assets_dir=assets_dir,
            image_files=image_files,
            source_url=url,
        )
        result["mode"] = "otl"
        result["otl_json"] = str(otl_path)
        result["pictures_in_otl"] = len(pictures)
        result["images"] = saved
        result["image_order"] = order_name
        result["convert"] = stats
        if max_depth > 0:
            nested_otl_path = otl_path

    if nested_otl_path is not None:
        result["nested"] = expand_nested_otl_documents(
            load_otl(nested_otl_path),
            output_md,
            max_depth=max_depth,
            visited=seen,
            auto_login=False,
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert WPS/kdocs share link to Markdown.")
    parser.add_argument("url", help="Share URL (kdocs.cn / 365.kdocs.cn)")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output .md path")
    parser.add_argument(
        "--no-login",
        action="store_true",
        help="Do not open Chrome if the WPS session is missing or expired",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Convert nested OTL file cards one level (same as --max-depth 1)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=None,
        metavar="N",
        help="Nested OTL conversion depth (0=links only; default 0, or 1 with --recursive)",
    )
    args = parser.parse_args(argv)

    # Allow importing sibling modules
    sys.path.insert(0, str(SCRIPTS))

    try:
        depth = resolve_nested_depth(recursive=args.recursive, max_depth=args.max_depth)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    try:
        result = share_to_markdown(
            args.url,
            args.output,
            auto_login=not args.no_login,
            max_depth=depth,
        )
    except WpsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(
            f"ERROR: Unexpected failure: {e}\n"
            "Re-run wps_login.py, or export the file manually and use convert.py.",
            file=sys.stderr,
        )
        return 1

    print("OK")
    for k, v in result.items():
        if k == "convert" and isinstance(v, dict):
            for ck, cv in v.items():
                print(f"convert.{ck}: {cv}")
        elif k == "nested" and isinstance(v, list):
            print(f"nested: {len(v)}")
            for i, item in enumerate(v, 1):
                print(f"nested.{i}: {item}")
        else:
            print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
