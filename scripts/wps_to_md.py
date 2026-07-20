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
import subprocess
import sys
import zipfile
from pathlib import Path

CFG = Path.home() / ".config" / "doc2md"
DEFAULT_STATE = CFG / "wps_storage_state.json"
SCRIPTS = Path(__file__).resolve().parent
SHARE_ID_RE = re.compile(
    r"(?:kdocs\.cn|wps\.cn)/(?:l|view/l)/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
SAFE_NAME_RE = re.compile(r"[^\w.\u4e00-\u9fff\-]+")


class WpsError(Exception):
    pass


def extract_share_id(url: str) -> str:
    m = SHARE_ID_RE.search(url)
    if not m:
        raise WpsError(f"Cannot parse share id from URL: {url}")
    return m.group(1)


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


def ensure_session() -> Path:
    if not DEFAULT_STATE.is_file():
        raise WpsError(
            f"Session not found: {DEFAULT_STATE}\n"
            "Run first:\n"
            f"  {sys.executable} {SCRIPTS / 'wps_login.py'} '<share_url>'\n"
            "Then retry."
        )
    return DEFAULT_STATE


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


def share_to_markdown(url: str, output_md: Path) -> dict:
    from playwright.sync_api import sync_playwright
    from otl_to_md import convert_file

    url = normalize_url(url)
    sid = extract_share_id(url)
    state = ensure_session()
    output_md = output_md.expanduser().resolve()
    output_md.parent.mkdir(parents=True, exist_ok=True)
    work = output_md.parent / f".doc2md_work_{sid}"
    work.mkdir(parents=True, exist_ok=True)

    result: dict = {"url": url, "share_id": sid, "mode": None, "output": str(output_md)}

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(storage_state=str(state))

        # --- link meta ---
        meta_urls = [
            f"https://drive.kdocs.cn/api/v5/links/{sid}",
            f"https://www.kdocs.cn/3rd/drive/api/v5/links/{sid}",
            f"https://365.kdocs.cn/3rd/drive/api/v5/links/{sid}",
        ]
        meta = None
        for mu in meta_urls:
            r = context.request.get(
                mu,
                headers={
                    "Accept": "application/json",
                    "Referer": url,
                    "Origin": "https://365.kdocs.cn",
                },
            )
            if r.status == 200:
                try:
                    meta = r.json()
                    break
                except Exception:
                    continue
        if not meta:
            browser.close()
            raise WpsError(
                "Failed to load share meta. Session may be expired — re-run wps_login.py."
            )

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

        # --- try binary download for Office files ---
        downloaded: Path | None = None
        if file_id and group_id and not is_otl:
            dl_apis = [
                (
                    f"https://drive.kdocs.cn/api/v5/groups/{group_id}/files/{file_id}/download"
                    f"?isblocks=false&support_checksums=md5,sha1"
                ),
                (
                    f"https://www.kdocs.cn/3rd/drive/api/v5/groups/{group_id}/files/{file_id}/download"
                    f"?isblocks=false&support_checksums=md5,sha1"
                ),
            ]
            for api in dl_apis:
                r = context.request.get(
                    api,
                    headers={
                        "Accept": "application/json",
                        "Referer": url,
                        "Origin": "https://365.kdocs.cn",
                    },
                )
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
                fr = context.request.get(dl_url)
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

        page = context.new_page()

        def on_response(resp) -> None:
            u = resp.url
            ctype = resp.headers.get("content-type") or ""
            if resp.status != 200:
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
        page.goto(url, wait_until="networkidle", timeout=120000)
        page.wait_for_timeout(4000)
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

        browser.close()

        data = otl_bytes["data"]
        if not data:
            raise WpsError(
                "Could not capture open/otl content. "
                "Session may lack permission, or the doc type is unsupported. "
                "Export manually from WPS UI and run convert.py."
            )

        stem = safe_stem(Path(fname).stem if fname else sid)
        otl_path = work / f"{stem}.otl.json"
        # normalize to pretty json text
        try:
            parsed = json.loads(data.decode("utf-8"))
            otl_path.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
        except Exception:
            otl_path.write_bytes(data)
            parsed = json.loads(otl_path.read_text(encoding="utf-8"))

        assets_dir = output_md.parent / f"{output_md.stem}_assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        # clear previous
        for old in assets_dir.glob("image_*"):
            old.unlink()

        pictures = iter_otl_pictures(parsed)
        ordered = match_images_to_pictures(pictures, images)

        image_names: list[str] = []
        for i, (ext, body) in enumerate(ordered, 1):
            name = f"image_{i:03d}.{ext}"
            (assets_dir / name).write_bytes(body)
            image_names.append(name)

        # If matching found fewer images than pictures, keep placeholders via otl_to_md
        stats = convert_file(
            otl_path,
            output_md,
            assets_dir=assets_dir,
            image_files=[assets_dir / n for n in image_names],
            source_url=url,
        )
        result["mode"] = "otl"
        result["otl_json"] = str(otl_path)
        result["pictures_in_otl"] = len(pictures)
        result["images"] = len(image_names)
        result["image_order"] = "otl-picture-matched"
        result["convert"] = stats
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert WPS/kdocs share link to Markdown.")
    parser.add_argument("url", help="Share URL (kdocs.cn / 365.kdocs.cn)")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output .md path")
    args = parser.parse_args(argv)

    # Allow importing sibling modules
    sys.path.insert(0, str(SCRIPTS))

    try:
        result = share_to_markdown(args.url, args.output)
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
