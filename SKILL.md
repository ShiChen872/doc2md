---
name: doc2md
description: Convert local documents and WPS/金山文档 (kdocs / 365.kdocs) share links to Markdown with images extracted to a local assets folder. Use when the user asks to convert docx, pdf, pptx, xlsx, epub, html, WPS intelligent docs (.otl), or WPS cloud docs to Markdown, mentions markitdown, kdocs.cn share links, or wants document-to-markdown with preserved images.
---

# doc2md — documents to Markdown

Platform-neutral skill: all logic lives in Python CLI scripts under `scripts/`.
Copy this whole directory to another agent platform's skills folder (Cursor, Codex, WPS Comate, etc.) and it works the same way.

## Setup (once per machine)

```bash
python3 -m venv ~/.config/doc2md/venv
~/.config/doc2md/venv/bin/pip install -r <this-skill>/scripts/requirements.txt
# Playwright uses system Chrome (channel=chrome); no browser download required if Chrome is installed.
```

Replace `<this-skill>` with the absolute path of this skill directory
(e.g. `~/.agents/skills/doc2md`).

## Workflow

1. Classify input:
   - **Local path** → `convert.py`
   - **kdocs / 365 share URL** → `wps_to_md.py` (one-shot to Markdown)
2. If WPS session missing/expired → run `wps_login.py` first (opens Chrome for the user to log in).
3. After conversion, report image counts and confirm `*_assets/` beside the `.md`.

### Local file

```bash
~/.config/doc2md/venv/bin/python <this-skill>/scripts/convert.py /path/to/doc.docx -o /path/to/out.md
```

Also accepts `.otl.json` (WPS intelligent-doc JSON).

### WPS share link (recommended)

```bash
# First time / cookie expired — user completes login in Chrome
~/.config/doc2md/venv/bin/python <this-skill>/scripts/wps_login.py 'https://365.kdocs.cn/l/XXXX'

# Convert share link → Markdown (+ assets)
~/.config/doc2md/venv/bin/python <this-skill>/scripts/wps_to_md.py 'https://365.kdocs.cn/l/XXXX' -o /path/to/out.md
```

Session files (platform-agnostic):

- `~/.config/doc2md/wps_storage_state.json` (Playwright — preferred)
- `~/.config/doc2md/wps_cookie.txt` (Cookie string backup)

### Scripts

| Script | Role |
|--------|------|
| `convert.py` | Local Office/PDF/HTML/OTL-JSON → Markdown |
| `wps_login.py` | Headed Chrome login, save session |
| `wps_to_md.py` | Share URL → Markdown (Office download or OTL parse) |
| `wps_download.py` | Share URL → raw file / `.otl.json` only |
| `otl_to_md.py` | OTL JSON → Markdown |

## Image handling

- DOCX / PPTX / EPUB / HTML: markitdown `keep_data_uris=True` on **convert()**, then decode data URIs to `<stem>_assets/`.
- PDF: PyMuPDF extracts embedded images (approximate per-page placement).
- WPS `.otl` intelligent docs: cannot use drive binary download (`notAllowType`); capture `open/otl` JSON + temporary CDN images via Playwright.

## Failure fallback (WPS)

1. Re-run `wps_login.py` if session expired.
2. If still failing (password-protected link, unsupported type): ask user to export/download in WPS UI, then `convert.py` on the local file.
3. Do not invent credentials or scrape login forms — only open a browser for the user to log in themselves.

## Portability

- Scripts are self-contained CLIs. No Cursor/Codex/Comate APIs.
- Config and venv live under `~/.config/doc2md/`.
- `SKILL.md` uses only standard `name` / `description` frontmatter.

## Supported formats

markitdown formats (docx, pptx, xlsx, pdf, html, epub, …) + WPS share links including 365 enterprise and intelligent docs (`.otl`).
