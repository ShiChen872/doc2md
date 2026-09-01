---
name: doc2md
display_name: 文档转Markdown
description: >-
  将本地文档、WPS/金山文档（kdocs / 365.kdocs / plus.wps.cn）与飞书/Lark 云文档（wiki / docx）分享链接转为 Markdown，图片提取到本地 assets 目录。
  支持 docx、pdf、pptx、xlsx、epub、html、图片 OCR、WPS 智能文档（.otl）、WPS 媒体/视频分享（view/media）、WPS 流程图（.pom）/思维导图（.pof）/白板（.kw）、飞书画板/多维表格/电子表格/思维笔记及云文档分享链接。
  使用场景：(1) 云文档/分享链接转 Markdown；(2) 本地 Office/PDF 转 md 并保留图片；(3) OTL / 飞书文档结构化导出；(4) WPS 视频分享转 md（封面 + 预览 mp4）；(5) 已有 Markdown 再转 PDF（用户明确要求时）。
  触发关键词：转markdown、转md、doc2md、文档转markdown、云文档转md、kdocs转md、plus.wps、wps视频、媒体分享、view/media、飞书转md、feishu转md、otl转md、流程图、思维导图、白板、画板、电子表格、思维笔记、转pdf、markdown转pdf、anything to markdown。
---

# doc2md — documents to Markdown

Platform-neutral skill: all logic lives in Python CLI scripts under `scripts/`.
Copy this whole directory to another agent platform's skills folder (Cursor desktop, Cursor CLI, Codex, WPS Comate, etc.) and it works the same way.

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
4. **PDF is optional.** Only if the user asks to export PDF, run `md_to_pdf.py` on the `.md`. Do not emit PDF by default. Chrome is the default engine; if they ask for 品牌样式 / 更好排版 / Typst, add `--engine typst --theme brand`.

### Do not improvise (especially Comate)

The CLI is the conversion path. **Do not** invent a parallel one.

```bash
~/.config/doc2md/venv/bin/python <this-skill>/scripts/doc2md.py '<path_or_url>' -o /path/to/out.md
```

**Never:**

- Call WPS/kdocs official product APIs or host-bundled WPS tools (`file-content`, file download, `doc exports`, `convert/to/pdf`, `WPS_SID`, cookie/token replay). Specified-user shares often return 403 even when the user can open the same link in Chrome.
- Drive the user's already-open Chrome or WPS window via AppleScript / `osascript`, or ask them to enable Chrome **View → Developer → Allow JavaScript from Apple Events**.
- Treat “the user can open this in the browser” as proof that those APIs will work. The CLI uses Playwright + `~/.config/doc2md/wps_storage_state.json`. If original download is denied, it uses the **web viewer** (PDF page screenshots + OCR, OTL JSON, or media HLS preview).

If the CLI fails, report its stderr. Do not ask the user to toggle Chrome Apple Events. If the session expired, rerun **without** `--no-login` so Chrome opens for login. Last resort: user exports in the product UI, then `convert.py` on the local file.

### Recommended (any input)

```bash
~/.config/doc2md/venv/bin/python <this-skill>/scripts/doc2md.py <path_or_url> -o /path/to/out.md
```

Accepts: local Office/PDF/OTL-JSON; `kdocs.cn` / `365.kdocs.cn` / `plus.wps.cn` shares (including `view/media` video); Feishu/Lark `wiki` / `docx` URLs.

WPS OTL nested cards stay as kdocs links unless the user asks to expand them (`--recursive`).

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

# Optional: also convert nested OTL file cards (one level). Do not use by default.
~/.config/doc2md/venv/bin/python <this-skill>/scripts/doc2md.py 'https://365.kdocs.cn/l/XXXX' -o /path/to/out.md --recursive

# Media / video shares (plus.wps.cn/view/media/l/… or .mp4 share)
~/.config/doc2md/venv/bin/python <this-skill>/scripts/wps_to_md.py 'https://plus.wps.cn/view/media/l/XXXX' -o /path/to/out.md
```

Session files (platform-agnostic):

- `~/.config/doc2md/wps_storage_state.json` (Playwright; directory 0700, file 0600)

**WPS media notes:** original file download is often denied on link shares. If `ffmpeg` is installed, doc2md remuxes the share-page HLS **preview** stream to `*_assets/preview.mp4` (transcoded, not the original upload). Cover image is saved when available.

**WPS PDF notes:** when original PDF download is denied, the CLI screenshots each web-viewer page (`.pdf-page`) into `*_assets/page_NNN.png` and OCRs the tiles. Page images are the source of truth; OCR is for search.

**WPS presentation notes:** `.pptx` link shares often return `ErrForbidDownloadLinkFile`. The CLI opens the web viewer (`office_type=p`) and screenshots each `.slide-uil-view` slide. Knowledge-wiki URLs (`365.kdocs.cn/wiki/l/0l…`) are the same files; the inner share id is used. Do not use WPS `file-content` reading-mode markdown for decks — that is text-only.

**WPS ksheet / dbsheet notes:** `.ksheet` (金山在线表格, `office_type=k`) downloads as an xlsx-compatible zip and becomes Markdown tables. `.dbt` 多维表 (`office_type=d`) cannot be downloaded (`notAllowType`); the CLI screenshots each left-rail sheet and nested view (grid / form / dashboard), clipping the main pane. That is the visible viewer, not a full record dump.

**WPS 流程图 / 思维导图 notes:** `.pom` (流程图) and `.pof` (思维导图) open in a ProcessOn iframe (`#dotviewIframe`). Original download is skipped (not an Office zip). The CLI screenshots each bottom **画布** tab. This is the visible canvas, not a vector dump.

**WPS 白板 notes:** `.kw` (`office_type=b`) is the document-center 白板/画板, not 会议白板. The CLI screenshots the web canvas (`.kw_container`). This viewer also uses `.slide-uil-view`, so it is handled **before** PPT slide capture.

**Feishu 画板 / 多维表格 / 电子表格 / 思维笔记 notes:** standalone `/board/`, `/base/` (including `/share/base/` forms), `/sheets/`, and `/mindnotes/` screenshot the visible web viewer. Matching blocks inside a wiki/docx become screenshots instead of an HTML skip comment. Poll / chat cards still skipped.

### Markdown → PDF (optional)

Only when the user asks for PDF. Markdown stays the source of truth.

```bash
~/.config/doc2md/venv/bin/python <this-skill>/scripts/md_to_pdf.py /path/to/out.md -o /path/to/out.pdf
```

Default engine is **Chrome print** (`--engine chrome`). Adds a **目录** from h2/h3, a header title, and page numbers. Local `*_assets/` images are resolved; `<video>` / iframe become links. WPS PDF-preview exports print **page images only** (OCR stays in the `.md` for search; pass `--keep-ocr` to include a tiny gray OCR block) and skip the TOC so “第 N 页” is not treated as an outline. `--no-toc` skips the table of contents. Page/slide screenshots are JPEG-compressed for print by default (Markdown assets are not modified); `--no-compress` keeps the original PNG in the PDF.

If the user asks for **更好排版 / 品牌样式 / Typst**, use:

```bash
~/.config/doc2md/venv/bin/python <this-skill>/scripts/md_to_pdf.py /path/to/out.md -o /path/to/out.pdf --engine typst --theme brand
```

Needs the **Typst CLI** on PATH, or `pip install typst` when a wheel exists. Typst is cross-platform (macOS / Windows / Linux), not macOS-only:

- macOS: `brew install typst`
- Windows: `winget install --id Typst.Typst -e`（也可用 `scoop install typst`，或从 [GitHub Releases](https://github.com/typst/typst/releases) 解压 `typst-x86_64-pc-windows-msvc.zip` 并把 `typst.exe` 加到 PATH）
- Linux: 同上 Releases 里的 linux 包

Do not silently fall back to Chrome if Typst was requested. `--theme brand` is navy/accent report styling with no logo artwork. `--theme brand` also works with Chrome. Windows 上没装 Typst 时，继续用默认 `--engine chrome` 即可。

Do **not** call WPS `convert/to/pdf` or automate the WPS client. `--engine=wps` is **not supported**: WPS has no official Mac/Linux CLI, and Windows COM would drive the client. Use Chrome (default) or Typst. If Chrome print is not available and Typst was not requested, tell the user they can open the `.md` in WPS and 另存为 PDF (manual GUI, not a CLI engine).

### Feishu / Lark share link

```bash
# Optional: log in ahead of time (feishu_to_md also opens Chrome if needed)
~/.config/doc2md/venv/bin/python <this-skill>/scripts/feishu_login.py 'https://xxx.feishu.cn/wiki/XXXX'

# Convert wiki/docx URL → Markdown (+ assets)
~/.config/doc2md/venv/bin/python <this-skill>/scripts/feishu_to_md.py 'https://xxx.feishu.cn/wiki/XXXX' -o /path/to/out.md
```

Session: `~/.config/doc2md/feishu_storage_state.json` (Playwright; 0600). Use `--insecure` only for an enterprise proxy with a custom CA that Chrome does not trust.

### Scripts

| Script | Role |
|--------|------|
| `doc2md.py` | **Unified CLI** — classify path/URL then convert |
| `convert.py` | Local Office/PDF/HTML/OTL-JSON → Markdown |
| `wps_login.py` | Headed Chrome login, save session |
| `wps_to_md.py` | WPS share URL → Markdown (Office / OTL / media / PDF preview / 演示文稿幻灯片截图 / 多维表视图截图) |
| `wps_download.py` | Share URL → raw file / `.otl.json` only |
| `otl_to_md.py` | OTL JSON → Markdown |
| `feishu_login.py` | Headed Chrome login for Feishu/Lark |
| `feishu_to_md.py` | Feishu wiki/docx/board/base/sheets/mindnotes URL → Markdown |
| `md_to_pdf.py` | Local Markdown (+ assets) → PDF (Chrome default; optional `--engine typst --theme brand`) |

## Image handling

- **图片文件**（png/jpg/…）：保留原图到 `*_assets/`；OCR 优先 **RapidOCR**（`rapidocr-onnxruntime`，PaddleOCR 模型 / 中文更好），其次本机 tesseract。复杂架构图仍以原图为准，OCR 作检索辅助。
- **PDF**：markitdown 抽文字 + PyMuPDF 抽内嵌图。若某页几乎无文字（疑似扫描件），自动渲染该页为 PNG 并 OCR 补文本；全篇扫描件则整篇以 OCR 为主体输出。WPS 分享若无法下载原 PDF，则截取网页预览分页 + OCR（见上）。
- DOCX / EPUB / HTML: markitdown `keep_data_uris=True` on **convert()**, then decode data URIs to `<stem>_assets/`.
- **PPTX**: per-slide **theme text** + **one full-slide screenshot**.
  PPTX→PDF via `office2pdf-python` (no system Office required); LibreOffice `soffice` is optional fallback; then PyMuPDF renders page PNGs.
- WPS `.otl` intelligent docs: cannot use drive binary download (`notAllowType`); capture `open/otl` JSON + temporary CDN images via Playwright. **表格**（`outline-table`）渲染为 Markdown 表格（单元格内图片一并输出）；代码块带 `attrs.lang` 语言标签。 Nested file cards (`WPSDocument`) become Markdown links. **Do not recurse by default.** Only if the user asks to 展开嵌套 / 递归 / 把里面的 SOP/卡片也转成 md, pass `--recursive` (depth 1) or `--max-depth N`. Children land in `{stem}_nested/`; failed children keep the original kdocs link. A parent like 《微软替换物料合集》 has 20+ nested SOP/xlsx/pptx — warn that it can take a long time.
  - 图片：按 OTL `sourceKey` / `imgID` 映射到本地文件（避免表内图导致整篇错位）；CDN 懒加载与 `/attachment/shapes` `raw` 都抓，**像素更多的留下**（架构大图优先 raw）。CDN 不齐时仍只按 sourceKey 用 shapes，避免错位。缺 key 时再滚一轮重试。

## Failure fallback (WPS / Feishu)

1. Conversion opens headed Chrome when the session is missing/expired; user logs in themselves. Use `--no-login` plus `wps_login.py` / `feishu_login.py` if you need to log in separately.
2. If still failing (password-protected link, rate limit, unsupported type): ask user to export/download in the product UI, then `convert.py` on the local file.
3. Do not invent credentials or scrape login forms — only open a browser for the user to log in themselves.
4. Do not fall back to host WPS APIs, AppleScript, Chrome “JavaScript from Apple Events”, or WPS `convert/to/pdf`.
5. Feishu: code fences keep language (numeric CodeLanguage mapped); file attachments download when present; **board / bitable / sheet / mindnote** screenshot the visible embed (standalone `/board/` `/base/` `/sheets/` `/mindnotes/` too); poll / chat cards still skipped with an HTML comment; legacy `/docs/` may need upgrade to new docx. WPS `.dbt` is handled by `wps_to_md` (view screenshots), not this Feishu skip list.

## Portability

- Scripts are self-contained CLIs. No Cursor/Codex/Comate APIs.
- Config and venv live under `~/.config/doc2md/`.
- `SKILL.md` uses only standard `name` / `description` frontmatter.

## Supported formats

markitdown formats (docx, pptx, xlsx, pdf, html, epub, …) + WPS share links (365 / `.otl` / `plus.wps.cn` media) + Feishu/Lark wiki, docx, board, base links. Optional: local Markdown → PDF via `md_to_pdf.py` (Chrome default; Typst brand theme optional).
