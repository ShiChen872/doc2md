#!/usr/bin/env python3
"""Unified doc2md entry: local file, WPS share, or Feishu/Lark URL → Markdown.

Usage:
  doc2md.py <path_or_url> [-o OUTPUT.md]

Routes:
  local path              → convert.py
  kdocs / wps share URL   → wps_to_md.py
  feishu / lark wiki|docx → feishu_to_md.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

Kind = str  # "local" | "wps" | "feishu"

WPS_HINT_RE = re.compile(
    r"(?:kdocs\.cn|wps\.cn)/(?:wiki/l|l|view/l|view/media/l)/[A-Za-z0-9_-]+",
    re.IGNORECASE,
)
FEISHU_PATH_RE = re.compile(
    r"/(wiki|docx|docs)/[A-Za-z0-9_-]+",
    re.IGNORECASE,
)


def looks_like_url(raw: str) -> bool:
    text = (raw or "").strip()
    if text.startswith(("http://", "https://")):
        return True
    return bool(
        re.search(
            r"(?:kdocs\.cn|wps\.cn|feishu\.cn|larksuite\.com|larkoffice\.com)/",
            text,
            re.IGNORECASE,
        )
    )


def classify(raw: str) -> Kind:
    """Classify input as local / wps / feishu. Raises ValueError if unknown."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty input")

    path = Path(text).expanduser()
    if path.is_file():
        return "local"

    if looks_like_url(text) or WPS_HINT_RE.search(text) or "feishu.cn" in text.lower():
        from urllib.parse import urlparse

        from feishu_to_md import HOST_RE as FEISHU_HOST_RE
        from wps_to_md import SHARE_ID_RE

        url = text if text.startswith("http") else f"https://{text}"
        if SHARE_ID_RE.search(url):
            return "wps"
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host and FEISHU_HOST_RE.search(host) and FEISHU_PATH_RE.search(parsed.path or ""):
            return "feishu"
        raise ValueError(
            f"Unrecognized cloud URL (need kdocs/wps share or feishu wiki/docx): {raw}"
        )

    if path.exists() and path.is_dir():
        raise ValueError(f"Input is a directory, not a file: {path}")
    raise ValueError(f"Input is not a local file or a supported URL: {raw}")


def default_output(raw: str, kind: Kind) -> Path:
    if kind == "local":
        return Path(raw).expanduser().resolve().with_suffix(".md")
    if kind == "wps":
        from wps_to_md import extract_share_id, normalize_url

        sid = extract_share_id(normalize_url(raw))
        return Path.cwd() / f"wps_{sid}.md"
    from feishu_to_md import parse_feishu_url

    info = parse_feishu_url(raw)
    return Path.cwd() / f"feishu_{info['token']}.md"


def _print_result(payload: object) -> None:
    if not isinstance(payload, dict):
        print(payload)
        return
    for key, value in payload.items():
        if key == "ok":
            continue
        if key == "convert" and isinstance(value, dict):
            for ck, cv in value.items():
                print(f"convert.{ck}: {cv}")
        else:
            print(f"{key}: {value}")


def run_convert(raw: str, output: Path, *, assets_dir: Path | None = None) -> int:
    from convert import convert

    input_path = Path(raw).expanduser().resolve()
    stats = convert(input_path, output, assets_dir)
    print("OK")
    print("route: local")
    _print_result(stats)
    return 0


def run_wps(raw: str, output: Path, *, auto_login: bool = True) -> int:
    from wps_to_md import WpsError, normalize_url, share_to_markdown

    try:
        result = share_to_markdown(normalize_url(raw), output, auto_login=auto_login)
    except WpsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        if not auto_login:
            print("Hint: re-run wps_login.py if the WPS session expired.", file=sys.stderr)
        return 1
    print("OK")
    print("route: wps")
    _print_result(result)
    return 0


def run_feishu(
    raw: str,
    output: Path,
    *,
    headed: bool = False,
    timeout_ms: int = 60000,
    auto_login: bool = True,
) -> int:
    from feishu_to_md import FeishuError, normalize_url, share_to_markdown

    try:
        result = share_to_markdown(
            normalize_url(raw),
            output,
            headless=not headed,
            timeout_ms=timeout_ms,
            auto_login=auto_login,
        )
    except FeishuError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        if not auto_login:
            print("Hint: re-run feishu_login.py if the Feishu session expired.", file=sys.stderr)
        return 1
    print("OK")
    print("route: feishu")
    _print_result(result)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a local document or WPS/Feishu share URL to Markdown."
    )
    parser.add_argument("input", help="Local file path, or WPS / Feishu / Lark URL")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output .md path")
    parser.add_argument(
        "--assets-dir",
        type=Path,
        default=None,
        help="Assets directory (local files only)",
    )
    parser.add_argument("--headed", action="store_true", help="Show browser (Feishu)")
    parser.add_argument("--timeout-ms", type=int, default=60000, help="Feishu page timeout")
    parser.add_argument(
        "--no-login",
        action="store_true",
        help="Do not open Chrome if a WPS/Feishu session is missing or expired",
    )
    args = parser.parse_args(argv)

    try:
        kind = classify(args.input)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    output = args.output.expanduser().resolve() if args.output else default_output(args.input, kind)
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        if kind == "local":
            assets = args.assets_dir.expanduser().resolve() if args.assets_dir else None
            return run_convert(args.input, output, assets_dir=assets)
        if kind == "wps":
            return run_wps(args.input, output, auto_login=not args.no_login)
        return run_feishu(
            args.input,
            output,
            headed=args.headed,
            timeout_ms=args.timeout_ms,
            auto_login=not args.no_login,
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
