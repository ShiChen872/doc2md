#!/usr/bin/env python3
"""Open a headed Chrome window for Feishu/Lark login and save session.

Usage:
  feishu_login.py [doc_or_home_url]

Saves:
  ~/.config/doc2md/feishu_storage_state.json   (Playwright storage)

Requires: playwright + system Chrome (channel=chrome).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import session as sess
from feishu_to_md import FeishuError, check_feishu_host

CFG = sess.CFG
DEFAULT_STATE = CFG / "feishu_storage_state.json"
DEFAULT_URL = "https://www.feishu.cn/"

SESSION_COOKIE_NAMES = {
    "session",
    "sid",
    "ssoticket",
    "passport_app_access_token",
    "session_list",
}
LOGIN_HINTS = (
    "accounts.feishu.cn",
    "accounts.larksuite.com",
    "passport",
    "/accounts/page/login",
    "/accounts/page/home",
    "choose_account",
)
DOC_HOST_HINTS = ("feishu.cn", "larksuite.com", "larkoffice.com")


class LoginError(Exception):
    """Interactive login failed or timed out."""


def _on_login_page(url: str) -> bool:
    low = (url or "").lower()
    return any(h in low for h in LOGIN_HINTS)


def _has_session(cookies: list[dict]) -> bool:
    names = {c.get("name") for c in cookies}
    if names & SESSION_COOKIE_NAMES:
        return True
    for c in cookies:
        domain = (c.get("domain") or "").lower()
        name = c.get("name") or ""
        if any(h in domain for h in DOC_HOST_HINTS) and name.lower() in {
            "session",
            "sid",
            "_csrf_token",
            "lang",
            "landing_url",
        }:
            if name.lower() in {"session", "sid"}:
                return True
    return False


def run_login(url: str, timeout_sec: int = 300) -> None:
    from playwright.sync_api import sync_playwright

    try:
        url = check_feishu_host(url or DEFAULT_URL)
    except FeishuError as e:
        raise LoginError(str(e)) from e

    sess.ensure_config_dir()
    print("=" * 60)
    print("请在弹出的 Chrome 窗口中完成飞书登录（扫码 / 手机 / SSO 均可）。")
    print("检测到会话 Cookie 且离开登录页后，会自动保存并关闭窗口。")
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
            has_sid = _has_session(cookies)
            on_login = _on_login_page(cur)
            print(
                f"wait url={sess.redact_url_for_log(cur)} cookies={len(cookies)} "
                f"session={has_sid} on_login={on_login}"
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
                "请重试并完成飞书账号登录。"
            )
    print("DONE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Login to Feishu/Lark and save session for doc2md."
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=DEFAULT_URL,
        help="Page to open (default: feishu.cn home, or pass a wiki/docx URL)",
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
