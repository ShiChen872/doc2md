#!/usr/bin/env python3
"""Open a headed Chrome window for WPS/kdocs login and save session.

Usage:
  wps_login.py [share_url]

Saves:
  ~/.config/doc2md/wps_storage_state.json   (Playwright storage)

Requires: playwright + system Chrome (channel=chrome).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import session as sess
from wps_to_md import WpsError, check_wps_host

CFG = sess.CFG
DEFAULT_STATE = CFG / "wps_storage_state.json"
DEFAULT_URL = "https://365.kdocs.cn/"


class LoginError(Exception):
    """Interactive login failed or timed out."""


def run_login(url: str, timeout_sec: int = 300) -> None:
    from playwright.sync_api import sync_playwright

    try:
        url = check_wps_host(url or DEFAULT_URL)
    except WpsError as e:
        raise LoginError(str(e)) from e

    sess.ensure_config_dir()
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
                f"wait url={sess.redact_url_for_log(cur)} cookies={len(cookies)} "
                f"wps_sid={'wps_sid' in names} on_login={on_login}"
            )
            if has_sid and not on_login:
                sess.write_storage_state(context, DEFAULT_STATE)
                print(f"OK wrote {DEFAULT_STATE}")
                ok = True
                break

        browser.close()
        if not ok:
            raise LoginError(
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
