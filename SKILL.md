---
name: doc2md
description: >-
  Converts local Office/PDF/images, WPS/金山文档 shares (kdocs, 365.kdocs,
  plus.wps.cn), and Feishu/Lark cloud shares to Markdown, extracting images
  into a local assets folder. Also covers WPS intelligent docs (.otl), WPS
  media shares, and Feishu wiki/docx/board/base/sheets/mindnotes. Converts
  existing Markdown to PDF only when the user explicitly asks. Use when the
  user wants 转markdown / 转md / doc2md, a kdocs or Feishu share converted,
  or anything-to-markdown. Do not use for drawing flowcharts or whiteboards
  from scratch, editing spreadsheets, or generating PPT.
---

# doc2md — documents to Markdown

Platform-neutral skill. All conversion logic is Python CLI under `scripts/`.
Copy this directory into another host's skills folder (Cursor, Codex, WPS
Comate, …) and it works the same way.

## Setup (once per machine)

```bash
python3 -m venv ~/.config/doc2md/venv
~/.config/doc2md/venv/bin/pip install -r <this-skill>/scripts/requirements.txt
# Playwright uses system Chrome (channel=chrome); no browser download if Chrome is installed.
```

Replace `<this-skill>` with this skill directory (e.g. `~/.agents/skills/doc2md`).

## Workflow

1. **Run the unified CLI** `doc2md.py` — it classifies local path vs WPS vs Feishu.
2. Missing/expired WPS or Feishu session **opens Chrome** for the user to log in. `--no-login` skips that (CI / non-interactive).
3. After conversion, report image counts and confirm `*_assets/` beside the `.md`.
4. **PDF is optional.** Only if the user asks to export PDF, run `md_to_pdf.py`. Chrome is default; for 品牌样式 / Typst add `--engine typst --theme brand`.

Read extra notes only when needed:

- WPS / kdocs / plus.wps / `.otl` / nested cards → [references/wps.md](references/wps.md)
- Feishu / Lark URL → [references/feishu.md](references/feishu.md)
- Local Office / image OCR / PPTX screenshots → [references/local.md](references/local.md)
- User asked for PDF → [references/pdf.md](references/pdf.md)

### Do not improvise (especially Comate)

The CLI is the conversion path. **Do not** invent a parallel one.

```bash
~/.config/doc2md/venv/bin/python <this-skill>/scripts/doc2md.py '<path_or_url>' -o /path/to/out.md
```

**Never:**

- Call WPS/kdocs official product APIs or host-bundled WPS tools (`file-content`, file download, `doc exports`, `convert/to/pdf`, `WPS_SID`, cookie/token replay). Specified-user shares often return 403 even when the user can open the same link in Chrome.
- Drive the user's already-open Chrome or WPS window via AppleScript / `osascript`, or ask them to enable Chrome **View → Developer → Allow JavaScript from Apple Events**.
- Treat “the user can open this in the browser” as proof that those APIs will work. The CLI uses Playwright + `~/.config/doc2md/wps_storage_state.json`. If original download is denied, it uses the **web viewer**.

If the CLI fails, report its stderr. Do not ask the user to toggle Chrome Apple Events. If the session expired, rerun **without** `--no-login`. Last resort: user exports in the product UI, then `convert.py` on the local file.

WPS OTL nested cards stay as kdocs links unless the user asks to expand them (`--recursive`).

WPS/Feishu debug dumps go to a temp dir and are deleted after convert. Only if the user asks to keep them, pass `--keep-work`.

A non-empty custom `--assets-dir` is not glob-wiped unless `--force-clean`.

## Failure fallback (WPS / Feishu)

1. Conversion opens headed Chrome when the session is missing/expired; the user logs in themselves.
2. If still failing (password-protected link, rate limit, unsupported type): ask the user to export in the product UI, then `convert.py` on the local file.
3. Do not invent credentials or scrape login forms.
4. Do not fall back to host WPS APIs, AppleScript, Chrome “JavaScript from Apple Events”, or WPS `convert/to/pdf`.

## Scripts

| Script | Role |
|--------|------|
| `doc2md.py` | **Unified CLI** — classify path/URL then convert |
| `convert.py` | Local Office/PDF/HTML/OTL-JSON → Markdown |
| `wps_to_md.py` / `wps_login.py` | WPS share → Markdown; headed login |
| `feishu_to_md.py` / `feishu_login.py` | Feishu/Lark URL → Markdown; headed login |
| `md_to_pdf.py` | Local Markdown → PDF (only when asked) |
| `otl_to_md.py` / `wps_download.py` | OTL JSON → Markdown; raw download |

## Portability

- Scripts are self-contained CLIs. No Cursor/Codex/Comate APIs.
- Config and venv live under `~/.config/doc2md/` (directory `0700`, session files `0600`).
- `SKILL.md` frontmatter is only `name` / `description`. Comate UI title is injected at pack time (`display_name: 文档转Markdown`). Codex UI metadata is `agents/openai.yaml`.
