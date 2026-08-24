---
name: doc2md
display_name: 文档转Markdown
description: >-
  将本地文档、WPS/金山文档（kdocs / 365.kdocs / plus.wps.cn）与飞书/Lark 云文档（wiki / docx）分享链接转为 Markdown，图片提取到本地 assets 目录。
  支持 docx、pdf、pptx、xlsx、epub、html、图片 OCR、WPS 智能文档（.otl）、WPS 媒体/视频分享（view/media）及云文档分享链接。
  使用场景：(1) 云文档/分享链接转 Markdown；(2) 本地 Office/PDF 转 md 并保留图片；(3) OTL / 飞书文档结构化导出；(4) WPS 视频分享转 md（封面 + 预览 mp4）。
  触发关键词：转markdown、转md、doc2md、文档转markdown、云文档转md、kdocs转md、plus.wps、wps视频、媒体分享、view/media、飞书转md、feishu转md、otl转md、anything to markdown。
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

1. **Prefer the unified CLI** `doc2md.py` — it classifies local path vs WPS vs Feishu.
2. If a WPS/Feishu session is missing or expired, conversion **opens Chrome** for the user to log in, then continues. Pass `--no-login` to skip (CI / non-interactive).
3. After conversion, report image counts and confirm `*_assets/` beside the `.md`.

### Do not improvise (especially Comate)

The CLI is the conversion path. **Do not** invent a parallel one.

```bash
~/.config/doc2md/venv/bin/python <this-skill>/scripts/doc2md.py '<path_or_url>' -o /path/to/out.md
```

**Never:**

- Call WPS/kdocs official product APIs or host-bundled WPS tools (`file-content`, file download, `doc exports`, `WPS_SID`, cookie/token replay). Specified-user shares often return 403 even when the user can open the same link in Chrome.
- Drive the user's already-open Chrome via AppleScript / `osascript`, or ask them to enable Chrome **View → Developer → Allow JavaScript from Apple Events**.
- Treat “the user can open this in the browser” as proof that those APIs will work. The CLI uses Playwright + `~/.config/doc2md/wps_storage_state.json`. If original download is denied, it uses the **web viewer** (PDF page screenshots + OCR, OTL JSON, or media HLS preview).

If the CLI fails, report its stderr. Do not ask the user to toggle Chrome Apple Events. If the session expired, rerun **without** `--no-login` so Chrome opens for login. Last resort: user exports in the product UI, then `convert.py` on the local file.

### Recommended (any input)

```bash
~/.config/doc2md/venv/bin/python <this-skill>/scripts/doc2md.py <path_or_url> -o /path/to/out.md
```

Accepts: local Office/PDF/OTL-JSON; `kdocs.cn` / `365.kdocs.cn` / `plus.wps.cn` shares (including `view/media` video); Feishu/Lark `wiki` / `docx` URLs.

### Local file

```bash
~/.config/doc2md/venv/bin/python <this-skill>/scripts/convert.py /path/to/doc.docx -o /path/to/out.md
```

Also accepts `.otl.json` (WPS intelligent-doc JSON).

### WPS share link

```bash
# Optional: log in ahead of time (wps_to_md also opens Chrome if the session expired)
~/.config/doc2md/venv/bin/python <this-skill>/scripts/wps_login.py 'https://365.kdocs.cn/l/XXXX'

# Convert share link → Markdown (+ assets)
~/.config/doc2md/venv/bin/python <this-skill>/scripts/wps_to_md.py 'https://365.kdocs.cn/l/XXXX' -o /path/to/out.md

# Media / video shares (plus.wps.cn/view/media/l/… or .mp4 share)
~/.config/doc2md/venv/bin/python <this-skill>/scripts/wps_to_md.py 'https://plus.wps.cn/view/media/l/XXXX' -o /path/to/out.md
```

Session files (platform-agnostic):

- `~/.config/doc2md/wps_storage_state.json` (Playwright — preferred)
- `~/.config/doc2md/wps_cookie.txt` (Cookie string backup)

**WPS media notes:** original file download is often denied on link shares. If `ffmpeg` is installed, doc2md remuxes the share-page HLS **preview** stream to `*_assets/preview.mp4` (transcoded, not the original upload). Cover image is saved when available.

**WPS PDF notes:** when original PDF download is denied, the CLI screenshots each web-viewer page (`.pdf-page`) into `*_assets/page_NNN.png` and OCRs the tiles. Page images are the source of truth; OCR is for search.

### Feishu / Lark share link

```bash
# Optional: log in ahead of time (feishu_to_md also opens Chrome if needed)
~/.config/doc2md/venv/bin/python <this-skill>/scripts/feishu_login.py 'https://xxx.feishu.cn/wiki/XXXX'

# Convert wiki/docx URL → Markdown (+ assets)
~/.config/doc2md/venv/bin/python <this-skill>/scripts/feishu_to_md.py 'https://xxx.feishu.cn/wiki/XXXX' -o /path/to/out.md
```

Session: `~/.config/doc2md/feishu_storage_state.json` (and `feishu_cookie.txt` backup).

### Scripts

| Script | Role |
|--------|------|
| `doc2md.py` | **Unified CLI** — classify path/URL then convert |
| `convert.py` | Local Office/PDF/HTML/OTL-JSON → Markdown |
| `wps_login.py` | Headed Chrome login, save session |
| `wps_to_md.py` | WPS share URL → Markdown (Office / OTL / media / PDF preview) |
| `wps_download.py` | Share URL → raw file / `.otl.json` only |
| `otl_to_md.py` | OTL JSON → Markdown |
| `feishu_login.py` | Headed Chrome login for Feishu/Lark |
| `feishu_to_md.py` | Feishu wiki/docx URL → Markdown |

## Image handling

- **图片文件**（png/jpg/…）：保留原图到 `*_assets/`；OCR 优先 **RapidOCR**（`rapidocr-onnxruntime`，PaddleOCR 模型 / 中文更好），其次本机 tesseract。复杂架构图仍以原图为准，OCR 作检索辅助。
- **PDF**：markitdown 抽文字 + PyMuPDF 抽内嵌图。若某页几乎无文字（疑似扫描件），自动渲染该页为 PNG 并 OCR 补文本；全篇扫描件则整篇以 OCR 为主体输出。WPS 分享若无法下载原 PDF，则截取网页预览分页 + OCR（见上）。
- DOCX / EPUB / HTML: markitdown `keep_data_uris=True` on **convert()**, then decode data URIs to `<stem>_assets/`.
- **PPTX**: per-slide **theme text** + **one full-slide screenshot**.
  PPTX→PDF via `office2pdf-python` (no system Office required); LibreOffice `soffice` is optional fallback; then PyMuPDF renders page PNGs.
- WPS `.otl` intelligent docs: cannot use drive binary download (`notAllowType`); capture `open/otl` JSON + temporary CDN images via Playwright. **表格**（`outline-table`）渲染为 Markdown 表格（单元格内图片一并输出）；代码块带 `attrs.lang` 语言标签。
  - 图片：按 OTL `sourceKey` / `imgID` 映射到本地文件（避免表内图导致整篇错位）；优先 CDN 懒加载；若仍缺图，深滚并合并 `/attachment/shapes` 按 `sourceKey` 下载 `raw`，缺 key 时再滚一轮重试。

## Failure fallback (WPS / Feishu)

1. Conversion opens headed Chrome when the session is missing/expired; user logs in themselves. Use `--no-login` plus `wps_login.py` / `feishu_login.py` if you need to log in separately.
2. If still failing (password-protected link, rate limit, unsupported type): ask user to export/download in the product UI, then `convert.py` on the local file.
3. Do not invent credentials or scrape login forms — only open a browser for the user to log in themselves.
4. Do not fall back to host WPS APIs, AppleScript, or Chrome “JavaScript from Apple Events”.
5. Feishu: code fences keep language (numeric CodeLanguage mapped); file attachments download when present; bitable / sheet / mindnote are skipped with an HTML comment; legacy `/docs/` may need upgrade to new docx.

## Portability

- Scripts are self-contained CLIs. No Cursor/Codex/Comate APIs.
- Config and venv live under `~/.config/doc2md/`.
- `SKILL.md` uses only standard `name` / `description` frontmatter.

## Supported formats

markitdown formats (docx, pptx, xlsx, pdf, html, epub, …) + WPS share links (365 / `.otl` / `plus.wps.cn` media) + Feishu/Lark wiki & docx links.
