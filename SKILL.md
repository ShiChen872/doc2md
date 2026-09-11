---
name: doc2md
description: >-
  Converts local Office/PDF/images, WPS/金山文档 shares (kdocs, 365.kdocs,
  plus.wps.cn), and Feishu/Lark cloud shares to Markdown, extracting images
  into a local assets folder. Also covers WPS intelligent docs (.otl), WPS
  media shares, and Feishu wiki/docx/board/base/sheets/mindnotes. Converts
  existing Markdown to PDF or an HTML sidecar only when the user explicitly asks.
  Use when the user wants 转markdown / 转md / doc2md / 转html, a kdocs or Feishu
  share converted, or anything-to-markdown. Do not use for drawing flowcharts
  or whiteboards from scratch, editing spreadsheets, or generating PPT.
---

# doc2md — documents to Markdown

Platform-neutral skill. Conversion runs as Python CLIs under `scripts/`.
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

1. Run the unified CLI `doc2md.py`. It classifies a local path vs a WPS vs Feishu URL.
2. A missing or expired WPS/Feishu session opens Chrome so the user can log in. `--no-login` skips that (CI / non-interactive).
3. After conversion, report image counts and confirm `*_assets/` beside the `.md`.
4. If the user asks for HTML / 网页预览稿, pass `--html` (sidecar `.html` next to the Markdown, same assets). Do not skip the `.md`.
5. **PDF is optional.** Only if the user asks to export PDF, run `md_to_pdf.py`. Chrome is default; for 品牌样式 / Typst add `--engine typst --theme brand`.

Read extra notes only when needed:

- WPS / kdocs / plus.wps / `.otl` / nested cards → [references/wps.md](references/wps.md)
- Feishu / Lark URL → [references/feishu.md](references/feishu.md)
- Local Office / image OCR / PPTX screenshots → [references/local.md](references/local.md)
- User asked for PDF → [references/pdf.md](references/pdf.md)

Supported conversion is the bundled CLI:

```bash
~/.config/doc2md/venv/bin/python <this-skill>/scripts/doc2md.py '<path_or_url>' -o /path/to/out.md
# Optional reading view (same assets):
~/.config/doc2md/venv/bin/python <this-skill>/scripts/doc2md.py '<path_or_url>' -o /path/to/out.md --html
```

If the CLI fails, report its stderr. An expired session can be retried without `--no-login`. For an unsupported or password-protected file, the user can export from the product UI and run `convert.py` on the local file.

WPS OTL nested cards stay as kdocs links unless the user asks to expand them (`--recursive`).

WPS/Feishu debug dumps go to a temp dir and are deleted after convert. Only if the user asks to keep them, pass `--keep-work`.

A non-empty custom `--assets-dir` is not glob-wiped unless `--force-clean`.

## Scripts

| Script | Role |
|--------|------|
| `doc2md.py` | **Unified CLI** — classify path/URL then convert |
| `convert.py` | Local Office/PDF/HTML/OTL-JSON → Markdown |
| `wps_to_md.py` / `wps_login.py` | WPS share → Markdown; headed login |
| `feishu_to_md.py` / `feishu_login.py` | Feishu/Lark URL → Markdown; headed login |
| `md_to_pdf.py` | Local Markdown → PDF (only when asked) |
| `md_to_html.py` | Local Markdown → HTML sidecar (only when asked) |
| `otl_to_md.py` / `wps_download.py` | OTL JSON → Markdown; raw download |

## Portability

- Scripts are self-contained CLIs.
- Config and venv live under `~/.config/doc2md/` (directory `0700`, session files `0600`).
- `SKILL.md` frontmatter is only `name` / `description`. Comate UI title is injected at pack time (`display_name: 文档转Markdown`). Codex UI metadata is `agents/openai.yaml`.
