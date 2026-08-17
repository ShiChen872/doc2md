#!/usr/bin/env python3
"""Convert a WPS/kdocs share link to Markdown (docx/xlsx/pptx/pdf or .otl).

Usage:
  wps_to_md.py <share_url> [-o OUTPUT.md]

Uses Playwright storage from wps_login.py:
  ~/.config/doc2md/wps_storage_state.json

Flow:
  1. Open share URL with saved session
  2. Resolve file meta via drive links API
  3. Try binary download (Office files)
  4. If blocked / .otl intelligent doc: capture open/otl JSON + CDN images → Markdown
  5. Otherwise run convert.py on the downloaded Office file
"""

from __future__ import annotations

import argparse
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
    r"(?:kdocs\.cn|wps\.cn)/(?:l|view/l|view/media/l)/([A-Za-z0-9_-]+)",
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


class WpsError(Exception):
    pass


def extract_share_id(url: str) -> str:
    m = SHARE_ID_RE.search(url)
    if not m:
        raise WpsError(f"Cannot parse share id from URL: {url}")
    return m.group(1)


def is_media_filename(fname: str) -> bool:
    return Path(fname or "").suffix.lower() in MEDIA_EXTS


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


def convert_otl(otl_json: Path, md_out: Path, assets_dir: Path, source_url: str) -> dict:
    from otl_to_md import convert_file

    return convert_file(
        otl_json,
        md_out,
        assets_dir=assets_dir,
        source_url=source_url,
    )


def share_to_markdown(
    url: str,
    output_md: Path,
    *,
    auto_login: bool = True,
    _login_retried: bool = False,
) -> dict:
    url = normalize_url(url)
    try:
        return _share_to_markdown_once(url, output_md, auto_login=auto_login)
    except _SessionExpired:
        if auto_login and not _login_retried:
            interactive_wps_login(url)
            return share_to_markdown(
                url, output_md, auto_login=auto_login, _login_retried=True
            )
        raise WpsError(
            "Failed to load share meta. Session may be expired — re-run wps_login.py."
        )


class _SessionExpired(WpsError):
    """Internal: share meta failed; wrapper may prompt login and retry once."""


def _share_to_markdown_once(url: str, output_md: Path, *, auto_login: bool = True) -> dict:
    from playwright.sync_api import sync_playwright
    from otl_to_md import convert_file

    sid = extract_share_id(url)
    state = ensure_session(url, auto_login=auto_login)
    output_md = output_md.expanduser().resolve()
    output_md.parent.mkdir(parents=True, exist_ok=True)
    work = output_md.parent / f".doc2md_work_{sid}"
    work.mkdir(parents=True, exist_ok=True)

    result: dict = {"url": url, "share_id": sid, "mode": None, "output": str(output_md)}

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(storage_state=str(state))

        # --- link meta ---
        # Prefer 365 / www first: drive.kdocs.cn often hangs from some networks.
        # drive.wps.cn works well for plus.wps.cn media shares.
        meta_urls = [
            f"https://drive.wps.cn/api/v5/links/{sid}?review=true",
            f"https://365.kdocs.cn/3rd/drive/api/v5/links/{sid}",
            f"https://www.kdocs.cn/3rd/drive/api/v5/links/{sid}",
            f"https://drive.kdocs.cn/api/v5/links/{sid}",
        ]
        meta = None
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
            if r.status == 200:
                try:
                    meta = r.json()
                    break
                except Exception:
                    continue
        if not meta:
            browser.close()
            raise _SessionExpired()

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

        # --- OTL / online-only path ---
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
        page.goto(url, wait_until="domcontentloaded", timeout=120000)
        try:
            page.wait_for_load_state("load", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(5000)
        try:
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(2500)
        except Exception:
            pass

        # Fallback: read __WPSENV__ and confirm office type
        try:
            env = page.evaluate("() => window.__WPSENV__")
            if isinstance(env, dict):
                result["office_type"] = env.get("office_type")
                fobj = ((env.get("file_info") or {}).get("file")) or {}
                if fobj.get("name") and not fname:
                    fname = str(fobj["name"])
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
    args = parser.parse_args(argv)

    # Allow importing sibling modules
    sys.path.insert(0, str(SCRIPTS))

    try:
        result = share_to_markdown(args.url, args.output, auto_login=not args.no_login)
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
        else:
            print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
