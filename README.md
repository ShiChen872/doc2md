# doc2md

Agent Skill that converts local documents, WPS / 金山文档 (kdocs) share links, and Feishu / Lark wiki or docx links to Markdown, extracting images into a local `*_assets/` folder.

Works with Cursor (desktop or CLI), Codex, and other Agent Skills–compatible hosts. Copy this directory into the platform’s skills folder (e.g. `~/.agents/skills/doc2md`).

## Features

- Local: docx / pptx / xlsx / pdf / html / epub (via [microsoft/markitdown](https://github.com/microsoft/markitdown))
- **PPTX**: theme text per slide + full-slide screenshots via `office2pdf-python` (LibreOffice optional fallback)
- **PDF**: text via markitdown + embedded images via PyMuPDF; **scanned/image-only PDFs** auto-detected and OCR'd page-by-page
- **Images** (png/jpg/…): keep original in `*_assets/` + OCR via [RapidOCR](https://github.com/RapidAI/RapidOCR) (`rapidocr-onnxruntime`; tesseract fallback)
- Cloud: `kdocs.cn` / `365.kdocs.cn` / `plus.wps.cn` share links; `feishu.cn` / `larksuite.com` wiki, docx, board, base, sheets, mindnotes
- WPS intelligent docs (`.otl`): parse `open/otl` JSON; tables rendered as Markdown tables (including images in cells); nested file cards become Markdown links; `--recursive` optionally converts those children one level
- **WPS media** (`.mp4` / `view/media/l/`): Markdown card + cover; optional local `preview.mp4` via ffmpeg HLS remux when original download is denied
- **WPS PDF shares**: if original download is denied, screenshot web-viewer pages (`page_NNN.png`) + OCR
- **WPS presentations**: if `.pptx` download is denied, screenshot each web-viewer slide; `wiki/l/` knowledge links resolve to the file share
- **WPS ksheet**: downloads as xlsx-compatible zip → Markdown tables
- **WPS dbsheet** (`.dbt`): if download is denied, screenshot each web-viewer sheet/dashboard
- **WPS 流程图 / 思维导图** (`.pom` / `.pof`): screenshot each ProcessOn canvas tab (not 画板/白板)
- **WPS 白板** (`.kw`, `office_type=b`): screenshot the web canvas (handled before PPT; not Feishu 画板)
- **Feishu 画板 / 多维表格 / 电子表格 / 思维笔记**: standalone `/board/` `/base/` `/sheets/` `/mindnotes/` screenshot the visible viewer; matching in-doc blocks screenshot instead of an HTML skip
- **Markdown → PDF** (optional): `md_to_pdf.py` prints a local `.md` via Chrome by default (目录 / 页眉 / 页码). Page/slide screenshots are JPEG-compressed for print (`--no-compress` to keep PNG). `--engine typst --theme brand` is optional branded typesetting (needs Typst). `--engine=wps` is not supported (no silent fallback). WPS Save As PDF is a manual GUI fallback
- **Feishu**: Playwright session (`feishu_login.py`) + in-page `PageMain` block tree → Markdown + assets; code fences keep language (enum mapped); file attachments and bookmarks from fallback blocks
- **OTL images**: place by `sourceKey` / `imgID` (not array index); capture CDN and `/attachment/shapes` `raw`, keep the sharper (more pixels). If CDN is incomplete, use shapes by `sourceKey` only
- Images saved as relative Markdown links (not base64)

## Setup

```bash
python3 -m venv ~/.config/doc2md/venv
~/.config/doc2md/venv/bin/pip install -r scripts/requirements.txt
# Uses system Google Chrome via Playwright (channel=chrome)
```

### OCR (optional but recommended)

Image files and **scanned/image-only PDFs** are OCR'd to recover text.

- **RapidOCR** (`rapidocr-onnxruntime`, installed by `requirements.txt`) is the primary
  engine — pure pip, downloads ONNX models on first run, no system package needed, and
  handles Chinese far better than tesseract.
- **Tesseract** is an optional fallback. If you want it, install the binary plus the
  Chinese language pack:
  - macOS: `brew install tesseract` then `brew install tesseract-lang` (provides `chi_sim`)
  - Debian/Ubuntu: `apt install tesseract-ocr tesseract-ocr-chi-sim`
- If neither is available, the image is still copied to `*_assets/` and a note is added.

### Tests (optional)

```bash
~/.config/doc2md/venv/bin/pip install pytest
~/.config/doc2md/venv/bin/python -m pytest tests/ -q
```

## Usage

### Unified CLI (recommended)

```bash
~/.config/doc2md/venv/bin/python scripts/doc2md.py /path/to/doc.docx -o /path/to/out.md
~/.config/doc2md/venv/bin/python scripts/doc2md.py 'https://365.kdocs.cn/l/XXXX' -o /path/to/out.md
~/.config/doc2md/venv/bin/python scripts/doc2md.py 'https://plus.wps.cn/view/media/l/XXXX' -o /path/to/out.md
~/.config/doc2md/venv/bin/python scripts/doc2md.py 'https://xxx.feishu.cn/wiki/XXXX' -o /path/to/out.md
```

If a WPS or Feishu session is missing or expired, a Chrome window opens for you to log in; conversion then continues. Pass `--no-login` to skip that prompt.

WPS OTL nested file cards stay as kdocs links by default. Pass `--recursive` (or `--max-depth N`) to convert those children into `{stem}_nested/*.md`.

Agents (Cursor / Codex / Comate) should run `doc2md.py` for conversion to Markdown. Do not call WPS official APIs, replay `WPS_SID`, or drive Chrome/WPS with AppleScript. Run `md_to_pdf.py` only when the user asks for a PDF.

### Local file

```bash
~/.config/doc2md/venv/bin/python scripts/convert.py /path/to/doc.docx -o /path/to/out.md
```

### WPS share link

```bash
# Optional: log in ahead of time (conversion also opens Chrome if the session expired)
~/.config/doc2md/venv/bin/python scripts/wps_login.py 'https://365.kdocs.cn/l/XXXX'

# Convert share link → Markdown (+ assets)
~/.config/doc2md/venv/bin/python scripts/wps_to_md.py 'https://365.kdocs.cn/l/XXXX' -o /path/to/out.md

# Optional: also convert nested OTL file cards (one level)
~/.config/doc2md/venv/bin/python scripts/wps_to_md.py 'https://365.kdocs.cn/l/XXXX' -o /path/to/out.md --recursive

# Video / media share (needs ffmpeg on PATH for local preview.mp4)
~/.config/doc2md/venv/bin/python scripts/wps_to_md.py 'https://plus.wps.cn/view/media/l/XXXX' -o /path/to/out.md
```

### Feishu / Lark share link

```bash
~/.config/doc2md/venv/bin/python scripts/feishu_login.py 'https://xxx.feishu.cn/wiki/XXXX'
~/.config/doc2md/venv/bin/python scripts/feishu_to_md.py 'https://xxx.feishu.cn/wiki/XXXX' -o /path/to/out.md
```

### Markdown → PDF (optional)

```bash
# Default: Chrome print (page/slide screenshots JPEG-compressed for print)
~/.config/doc2md/venv/bin/python scripts/md_to_pdf.py /path/to/out.md -o /path/to/out.pdf

# Keep original PNG tiles in the PDF
~/.config/doc2md/venv/bin/python scripts/md_to_pdf.py /path/to/out.md -o /path/to/out.pdf --no-compress

# Optional: Typst + brand theme (CLI on PATH, or `pip install typst`)
~/.config/doc2md/venv/bin/python scripts/md_to_pdf.py /path/to/out.md -o /path/to/out.pdf --engine typst --theme brand
```

Typst is **not macOS-only**. Install the official binary, then the same `--engine typst` flag works:

- macOS: `brew install typst`
- Windows: `winget install --id Typst.Typst -e` (or `scoop install typst`, or unzip [GitHub Releases](https://github.com/typst/typst/releases) `typst-*-pc-windows-msvc.zip` onto PATH)
- Linux: same Releases page

Chrome inserts a 目录 from h2/h3, header title, and page numbers (`--no-toc` to skip). `--theme brand` uses navy/accent report colors (no logo). PDF-preview Markdown skips the TOC. `--engine=wps` errors (no official Mac/Linux CLI; Windows COM would drive the client). If Chrome print is unavailable, open the `.md` in WPS and 另存为 PDF (GUI only — not scripted). Without Typst, keep `--engine chrome` (the default).

Session files live under `~/.config/doc2md/` (not in this repo):

- `wps_storage_state.json`
- `feishu_storage_state.json`

The config directory is `0700` and session files are `0600`. Plaintext `*_cookie.txt` backups are no longer written.

## Scripts

| Script | Role |
|--------|------|
| `doc2md.py` | Unified CLI (local / WPS / Feishu) |
| `convert.py` | Local Office/PDF/OTL-JSON → Markdown |
| `wps_login.py` | Headed Chrome login |
| `wps_to_md.py` | Share URL → Markdown |
| `wps_download.py` | Share URL → raw file / `.otl.json` |
| `otl_to_md.py` | OTL JSON → Markdown |
| `feishu_login.py` | Headed Chrome login (Feishu/Lark) |
| `feishu_to_md.py` | Feishu wiki/docx URL → Markdown |
| `md_to_pdf.py` | Local Markdown → PDF (Chrome default; optional Typst brand theme) |

See [SKILL.md](SKILL.md) for agent-oriented workflow instructions.

### Comate install zip

Comate's security audit times out if the zip includes tests (code=500102 / LLM 504).
The cloud package is **slim**: `SKILL.md` + `scripts/` only.

```bash
./pack-comate.sh 0.4.16 /path/to/doc2md-0.4.16-comate.zip
```

GitHub source still includes `tests/` (clone + pytest). Do not pack `tests/`, `README.md`, or `CHANGELOG.md` into the Comate zip.

## Notes

- WPS cloud access uses unofficial web APIs and may break when WPS changes their frontend.
- Prefer re-login via the conversion prompt (or `wps_login.py` / `feishu_login.py`), or manually export from the product UI and run `convert.py`.
- Do not commit cookies or `~/.config/doc2md/` session files.

## License

MIT
