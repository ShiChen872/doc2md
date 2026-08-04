#!/usr/bin/env python3
"""Open a headed Chrome window for Feishu/Lark login and save session.

Usage:
  feishu_login.py [doc_or_home_url]

Saves:
  ~/.config/doc2md/feishu_storage_state.json   (Playwright storage)
  ~/.config/doc2md/feishu_cookie.txt           (Cookie header string — fallback)

Requires: playwright + system Chrome (channel=chrome).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

CFG = Path.home() / ".config" / "doc2md"
DEFAULT_STATE = CFG / "feishu_storage_state.json"
DEFAULT_COOKIE = CFG / "feishu_cookie.txt"
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


def _on_login_page(url: str) -> bool:
    low = (url or "").lower()
    return any(h in low for h in LOGIN_HINTS)


def _has_session(cookies: list[dict]) -> bool:
    names = {c.get("name") for c in cookies}
    if names & SESSION_COOKIE_NAMES:
        return True
    # Logged-in suite cookies often include domain-scoped session without exact name match
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

    CFG.mkdir(parents=True, exist_ok=True)
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
                f"wait url={cur[:120]} cookies={len(cookies)} "
                f"session={has_sid} on_login={on_login}"
            )
            if has_sid and not on_login:
                context.storage_state(path=str(DEFAULT_STATE))
                preferred = [
                    c
                    for c in cookies
                    if any(
                        x in (c.get("domain") or "")
                        for x in ("feishu.cn", "larksuite.com", "larkoffice.com", "bytedance.com")
                    )
                ]
                use = preferred or cookies
                by_name: dict[str, str] = {}
                for c in use:
                    by_name[c["name"]] = c["value"]
                cookie_str = "; ".join(f"{k}={v}" for k, v in by_name.items())
                DEFAULT_COOKIE.write_text(cookie_str + "\n", encoding="utf-8")
                print(f"OK wrote {DEFAULT_STATE}")
                print(f"OK wrote {DEFAULT_COOKIE} ({len(by_name)} cookies)")
                print(f"cookie_names sample: {sorted(names)[:12]}")
                ok = True
                break

        browser.close()
        if not ok:
            raise SystemExit(
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
