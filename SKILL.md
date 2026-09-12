---
name: doc2md
description: >-
  Converts local Office/PDF/images, WPS/金山文档 shares (kdocs, 365.kdocs,
  plus.wps.cn), and Feishu/Lark cloud shares to Markdown, extracting images
  into a local assets folder. Also covers WPS intelligent docs (.otl), WPS
  media shares, and Feishu wiki/docx/board/base/sheets/mindnotes. Optional
  HTML sidecar or PDF when the user asks. Typical requests: 转markdown, 转md,
  doc2md, 转html, kdocs or Feishu share. Out of scope: creating flowcharts,
  whiteboards, spreadsheets, or PowerPoint from scratch.
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
2. A missing or expired WPS/Feishu session opens Chrome so the user can log in. CI may pass `--no-login`.
3. After conversion, report image counts and confirm `*_assets/` beside the `.md`.
4. If the user asks for HTML / 网页预览稿, also pass `--html` (handbook-style sidecar `.html`, same assets; PPT / page decks become per-page talk cards). Keep the `.md`.
5. PDF: only if the user asks, run `md_to_pdf.py`. Chrome is default; for 品牌样式 / Typst add `--engine typst --theme brand`.

## Type notes

Comate install zip is `SKILL.md` + `scripts/` only. Use this list on that host. A local git checkout also has longer notes under `references/`.

- **PPT / 演示**: original download is often denied; then screenshot each slide. A knowledge-wiki `/wiki/l/` URL resolves to the inner file share.
- **Excel / ksheet**: download becomes Markdown tables when allowed; otherwise screenshot each bottom sheet tab (visible grid, not a full dump).
- **`.dbt` 多维表**: cannot download; screenshot each left-rail view (grid / form / dashboard).
- **流程图 / 思维导图** (`.pom` / `.pof`): ProcessOn canvas tabs. Skip Office unzip.
- **白板** (`.kw`): screenshot the canvas. Handle before PPT (same slide viewer class).
- **PDF 分享**: download denied → one image per web-viewer page + OCR.
- **媒体视频**: original file is often blocked; with ffmpeg, remux the share-page HLS preview (transcoded, not the upload).
- **OTL**: parse `open/otl` JSON. Nested file cards stay kdocs links unless `--recursive`.
- **飞书** `/board/` `/base/` `/sheets/` `/mindnotes/`: screenshot the visible viewer. Poll stays a comment. Public-share attachments are often missing.

Local extra notes:

- WPS / kdocs / plus.wps / `.otl` / nested cards → [references/wps.md](references/wps.md)
- Feishu / Lark URL → [references/feishu.md](references/feishu.md)
- Local Office / image OCR / PPTX screenshots → [references/local.md](references/local.md)
- User asked for PDF → [references/pdf.md](references/pdf.md)

Entry point:

```bash
~/.config/doc2md/venv/bin/python <this-skill>/scripts/doc2md.py '<path_or_url>' -o /path/to/out.md
~/.config/doc2md/venv/bin/python <this-skill>/scripts/doc2md.py '<path_or_url>' -o /path/to/out.md --html
```

If the CLI fails, report its stderr. An expired session: run the CLI again so Chrome can open for login. Password-protected or unsupported types: the user can export from the product UI, then `convert.py` on the local file.

WPS OTL nested cards stay as kdocs links unless the user asks to expand them (`--recursive`). Large collections can take a long time.

WPS/Feishu debug dumps go to a temp dir and are deleted after convert. To keep them, pass `--keep-work`.

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
