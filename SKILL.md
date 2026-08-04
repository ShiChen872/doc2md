---
name: doc2md
display_name: 文档转Markdown
description: >-
  将本地文档与 WPS/金山文档（kdocs / 365.kdocs）分享链接转为 Markdown，图片提取到本地 assets 目录。
  支持 docx、pdf、pptx、xlsx、epub、html、图片 OCR、WPS 智能文档（.otl）及云文档分享链接。
  使用场景：(1) 云文档/分享链接转 Markdown；(2) 本地 Office/PDF 转 md 并保留图片；(3) OTL 智能文档结构化导出。
  触发关键词：转markdown、转md、doc2md、文档转markdown、云文档转md、kdocs转md、otl转md、anything to markdown。
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

- **图片文件**（png/jpg/…）：保留原图到 `*_assets/`；OCR 优先 **RapidOCR**（`rapidocr-onnxruntime`，PaddleOCR 模型 / 中文更好），其次本机 tesseract。复杂架构图仍以原图为准，OCR 作检索辅助。
- **PDF**：markitdown 抽文字 + PyMuPDF 抽内嵌图。若某页几乎无文字（疑似扫描件），自动渲染该页为 PNG 并 OCR 补文本；全篇扫描件则整篇以 OCR 为主体输出。
- DOCX / EPUB / HTML: markitdown `keep_data_uris=True` on **convert()**, then decode data URIs to `<stem>_assets/`.
- **PPTX**: per-slide **theme text** + **one full-slide screenshot**.
  PPTX→PDF via `office2pdf-python` (no system Office required); LibreOffice `soffice` is optional fallback; then PyMuPDF renders page PNGs.
- WPS `.otl` intelligent docs: cannot use drive binary download (`notAllowType`); capture `open/otl` JSON + temporary CDN images via Playwright. **表格**（`outline-table`）渲染为 Markdown 表格；代码块带 `attrs.lang` 语言标签。
  - 图片：优先 CDN 懒加载 + 尺寸对齐；若仍缺图，深滚并合并 `/attachment/shapes`，按 OTL `sourceKey` 下载 `raw`。

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
