#!/usr/bin/env python3
"""Download a WPS / 金山文档 share link to a local file.

Preferred path for Markdown output: use wps_to_md.py instead.

Usage:
  wps_download.py <share_url> [-o OUTPUT_PATH]

Requires prior login:
  wps_login.py <share_url>

Uses Playwright storage (~/.config/doc2md/wps_storage_state.json).
For intelligent docs (.otl) that cannot be downloaded as Office files,
saves <name>.otl.json instead (convert with otl_to_md.py or wps_to_md.py).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CFG = Path.home() / ".config" / "doc2md"
DEFAULT_STATE = CFG / "wps_storage_state.json"
SCRIPTS = Path(__file__).resolve().parent
SHARE_ID_RE = re.compile(
    r"(?:kdocs\.cn|wps\.cn)/(?:l|view/l)/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
SAFE_NAME_RE = re.compile(r"[^\w.\u4e00-\u9fff\-]+")


class WpsDownloadError(Exception):
    pass


def extract_share_id(url: str) -> str | None:
    m = SHARE_ID_RE.search(url)
    return m.group(1) if m else None


def normalize_share_url(url: str) -> str:
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url


def safe_name(name: str) -> str:
    return SAFE_NAME_RE.sub("_", name).strip("._") or "wps_document"


def download_share(url: str, output: Path | None) -> Path:
    from playwright.sync_api import sync_playwright
    import io
    import zipfile

    url = normalize_share_url(url)
    sid = extract_share_id(url)
    if not sid:
        raise WpsDownloadError(f"Cannot parse share id from URL: {url}")
    if not DEFAULT_STATE.is_file():
        raise WpsDownloadError(
            f"Session not found: {DEFAULT_STATE}\n"
            f"Run: {sys.executable} {SCRIPTS / 'wps_login.py'} '{url}'"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(storage_state=str(DEFAULT_STATE))

        meta = None
        for mu in (
            f"https://drive.kdocs.cn/api/v5/links/{sid}",
            f"https://www.kdocs.cn/3rd/drive/api/v5/links/{sid}",
            f"https://365.kdocs.cn/3rd/drive/api/v5/links/{sid}",
        ):
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
            raise WpsDownloadError("Failed to load share meta. Re-run wps_login.py.")

        fi = meta.get("fileinfo") or {}
        file_id = str(fi.get("id") or "")
        group_id = str(fi.get("groupid") or "")
        name = str(fi.get("fname") or fi.get("name") or sid)
        is_otl = name.lower().endswith(".otl")

        out: Path | None = None
        if output is not None:
            out = output.expanduser().resolve()
        else:
            out = Path.cwd() / safe_name(name)

        # Try Office download
        if file_id and group_id and not is_otl:
            api = (
                f"https://drive.kdocs.cn/api/v5/groups/{group_id}/files/{file_id}/download"
                f"?isblocks=false&support_checksums=md5,sha1"
            )
            r = context.request.get(
                api,
                headers={
                    "Accept": "application/json",
                    "Referer": url,
                    "Origin": "https://365.kdocs.cn",
                },
            )
            if r.status == 200:
                payload = r.json()
                dl_url = payload.get("url") or (payload.get("data") or {}).get("url")
                if dl_url:
                    fr = context.request.get(dl_url)
                    if fr.status == 200:
                        data = fr.body()
                        out.parent.mkdir(parents=True, exist_ok=True)
                        # fix extension if needed
                        if out.suffix.lower() in {"", ".bin"}:
                            ext = "bin"
                            if data[:4] == b"%PDF":
                                ext = "pdf"
                            elif data[:4] == b"PK\x03\x04":
                                try:
                                    with zipfile.ZipFile(io.BytesIO(data)) as z:
                                        names = z.namelist()
                                    if any(n.startswith("word/") for n in names):
                                        ext = "docx"
                                    elif any(n.startswith("ppt/") for n in names):
                                        ext = "pptx"
                                    elif any(n.startswith("xl/") for n in names):
                                        ext = "xlsx"
                                except Exception:
                                    ext = "docx"
                            out = out.with_suffix(f".{ext}")
                        out.write_bytes(data)
                        browser.close()
                        print("OK")
                        print(f"url: {url}")
                        print(f"file_id: {file_id}")
                        print(f"group_id: {group_id}")
                        print(f"name: {name}")
                        print(f"output: {out}")
                        print(f"size_bytes: {out.stat().st_size}")
                        print("mode: office")
                        return out

        # OTL capture
        otl_bytes: dict[str, bytes | None] = {"data": None}
        page = context.new_page()

        def on_response(resp) -> None:
            if resp.status == 200 and "/open/otl" in resp.url:
                ctype = resp.headers.get("content-type") or ""
                if "octet-stream" in ctype or "json" in ctype or "text" in ctype:
                    try:
                        body = resp.body()
                        if body[:1] == b"{":
                            otl_bytes["data"] = body
                    except Exception:
                        pass

        page.on("response", on_response)
        page.goto(url, wait_until="networkidle", timeout=120000)
        page.wait_for_timeout(3000)
        browser.close()

        data = otl_bytes["data"]
        if not data:
            raise WpsDownloadError(
                "Binary download blocked and open/otl not captured. "
                "Use wps_to_md.py, or export manually from WPS UI."
            )

        if out.suffix.lower() not in {".otl", ".json", ".otl.json"}:
            out = out.with_suffix(".otl.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            parsed = json.loads(data.decode("utf-8"))
            out.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
        except Exception:
            out.write_bytes(data)

        print("OK")
        print(f"url: {url}")
        print(f"file_id: {file_id}")
        print(f"group_id: {group_id}")
        print(f"name: {name}")
        print(f"output: {out}")
        print(f"size_bytes: {out.stat().st_size}")
        print("mode: otl")
        print(
            "hint: Prefer wps_to_md.py for OTL→Markdown with images, "
            "or otl_to_md.py on this JSON file."
        )
        return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download WPS/kdocs share link. Prefer wps_to_md.py for Markdown."
    )
    parser.add_argument("url", help="Share URL")
    parser.add_argument("-o", "--output", type=Path, default=None)
    # keep old flag for compatibility (ignored; session uses storage_state)
    parser.add_argument("--cookie-file", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        download_share(args.url, args.output)
    except WpsDownloadError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(
            f"ERROR: Unexpected failure: {e}\n"
            "Re-run wps_login.py, or export manually and use convert.py.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
