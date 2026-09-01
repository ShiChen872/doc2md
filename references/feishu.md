# Feishu / Lark

Read this when converting a `feishu.cn` / `larksuite.com` / `larkoffice.com` URL.

## Commands

```bash
~/.config/doc2md/venv/bin/python <this-skill>/scripts/feishu_login.py 'https://xxx.feishu.cn/wiki/XXXX'
~/.config/doc2md/venv/bin/python <this-skill>/scripts/feishu_to_md.py 'https://xxx.feishu.cn/wiki/XXXX' -o /path/to/out.md
```

Session: `~/.config/doc2md/feishu_storage_state.json` (Playwright; 0600).

Use `--insecure` only for an enterprise proxy whose custom CA Chrome does not trust.

`--keep-work` writes `{stem}.blocks.json` beside the Markdown. Default: do not dump it.

`--headed` shows the browser. `--timeout-ms` defaults to 60000.

## Type notes

Playwright opens the page, waits for `PageMain` blockManager when present, serializes the block tree, and downloads images/files into `*_assets/`.

- Code fences keep language (numeric CodeLanguage mapped).
- File attachments download when present; bookmarks from fallback blocks are kept.
- **Board / bitable / sheet / mindnote:** standalone `/board/`, `/base/` (including `/share/base/` forms), `/sheets/`, and `/mindnotes/` screenshot the visible web viewer. Matching blocks inside a wiki/docx become screenshots instead of an HTML skip comment.
- Poll / chat cards are skipped with an HTML comment.
- Legacy `/docs/` URLs often need upgrade to new docx; the CLI still tries `PageMain` if available.
- Heading and text blocks render children (folded titles / indented paragraphs).
- Mermaid ISV widgets accept string `snapshot.data`.
- Failed asset downloads become HTML comments, not leftover `feishu-asset://` links.

WPS `.dbt` is handled by `wps_to_md`, not this Feishu skip list.
