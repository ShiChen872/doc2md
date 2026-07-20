#!/usr/bin/env python3
"""Open a headed Chrome window for WPS/kdocs login and save session.

Usage:
  wps_login.py [share_url]

Saves:
  ~/.config/doc2md/wps_storage_state.json   (Playwright storage — preferred)
  ~/.config/doc2md/wps_cookie.txt           (Cookie header string — fallback)

Requires: playwright + system Chrome (channel=chrome).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

CFG = Path.home() / ".config" / "doc2md"
DEFAULT_STATE = CFG / "wps_storage_state.json"
DEFAULT_COOKIE = CFG / "wps_cookie.txt"
DEFAULT_URL = "https://365.kdocs.cn/"


def run_login(url: str, timeout_sec: int = 300) -> None:
    from playwright.sync_api import sync_playwright

    CFG.mkdir(parents=True, exist_ok=True)
    print("=" * 60)
    print("请在弹出的 Chrome 窗口中完成登录（企业 SSO / 扫码均可）。")
    print("检测到 wps_sid 且离开登录页后，会自动保存会话并关闭窗口。")
    print(f"目标: {url}")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")

        deadline = time.time() + timeout_sec
        ok = False
        while time.time() < deadline:
            time.sleep(2)
            cur = page.url
            cookies = context.cookies()
            names = {c["name"] for c in cookies}
            has_sid = "wps_sid" in names or "kso_sid" in names
            on_login = any(
                x in cur for x in ("passport", "singlesign", "singlesso", "chooseaccount", "/login")
            )
            print(
                f"wait url={cur[:100]} cookies={len(cookies)} "
                f"wps_sid={'wps_sid' in names} on_login={on_login}"
            )
            if has_sid and not on_login:
                context.storage_state(path=str(DEFAULT_STATE))
                preferred = [
                    c
                    for c in cookies
                    if any(
                        x in (c.get("domain") or "")
                        for x in ("kdocs.cn", "wps.cn", "wpscdn.cn")
                    )
                ]
                use = preferred or cookies
                # Deduplicate by name (keep last)
                by_name: dict[str, str] = {}
                for c in use:
                    by_name[c["name"]] = c["value"]
                cookie_str = "; ".join(f"{k}={v}" for k, v in by_name.items())
                DEFAULT_COOKIE.write_text(cookie_str + "\n", encoding="utf-8")
                print(f"OK wrote {DEFAULT_STATE}")
                print(f"OK wrote {DEFAULT_COOKIE} ({len(by_name)} cookies)")
                ok = True
                break

        browser.close()
        if not ok:
            raise SystemExit(
                f"TIMEOUT: {timeout_sec}s 内未检测到完整登录。"
                "请重试并完成企业账号登录。"
            )
    print("DONE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Login to WPS/kdocs and save session for doc2md.")
    parser.add_argument(
        "url",
        nargs="?",
        default=DEFAULT_URL,
        help="Page to open (default: 365.kdocs.cn home, or pass a share link)",
    )
    parser.add_argument("--timeout", type=int, default=300, help="Login timeout seconds")
    args = parser.parse_args(argv)

    try:
        run_login(args.url, args.timeout)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
