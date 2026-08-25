# doc2md

Agent Skill that converts local documents, WPS / 金山文档 (kdocs) share links, and Feishu / Lark wiki or docx links to Markdown, extracting images into a local `*_assets/` folder.

Works with Cursor (desktop or CLI), Codex, and other Agent Skills–compatible hosts. Copy this directory into the platform’s skills folder (e.g. `~/.agents/skills/doc2md`).

## Features

- Local: docx / pptx / xlsx / pdf / html / epub (via [microsoft/markitdown](https://github.com/microsoft/markitdown))
- **PPTX**: theme text per slide + full-slide screenshots via `office2pdf-python` (LibreOffice optional fallback)
- **PDF**: text via markitdown + embedded images via PyMuPDF; **scanned/image-only PDFs** auto-detected and OCR'd page-by-page
- **Images** (png/jpg/…): keep original in `*_assets/` + OCR via [RapidOCR](https://github.com/RapidAI/RapidOCR) (`rapidocr-onnxruntime`; tesseract fallback)
- Cloud: `kdocs.cn` / `365.kdocs.cn` / `plus.wps.cn` share links; `feishu.cn` / `larksuite.com` wiki & docx
- WPS intelligent docs (`.otl`): parse `open/otl` JSON; tables rendered as Markdown tables (including images in cells)
- **WPS media** (`.mp4` / `view/media/l/`): Markdown card + cover; optional local `preview.mp4` via ffmpeg HLS remux when original download is denied
- **WPS PDF shares**: if original download is denied, screenshot web-viewer pages (`page_NNN.png`) + OCR
- **Markdown → PDF** (optional): `md_to_pdf.py` prints a local `.md` via Chrome (目录 / 页眉 / 页码); WPS Save As PDF is a manual fallback
- **Feishu**: Playwright session (`feishu_login.py`) + in-page `PageMain` block tree → Markdown + assets; code fences keep language (enum mapped); file attachments and bookmarks from fallback blocks
- **OTL images**: place by `sourceKey` / `imgID` (not array index); prefer CDN match; if incomplete, scroll + `/attachment/shapes` by `sourceKey`, with a second pass for any still-missing keys
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

Agents (Cursor / Codex / Comate) should run `doc2md.py` for conversion to Markdown. Do not call WPS official APIs, replay `WPS_SID`, or drive Chrome/WPS with AppleScript. Run `md_to_pdf.py` only when the user asks for a PDF.

### Local file

```bash
~/.config/doc2md/venv/bin/python scripts/convert.py /path/to/doc.docx -o /path/to/out.md
```

### WPS share link

```bash
# Optional: log in ahead of time (conversion also opens Chrome if the session expired)
~/.config/doc2md/venv/bin/python scripts/wps_login.py 'https://365.kdocs.cn/l/XXXX'

# Convert to Markdown
~/.config/doc2md/venv/bin/python scripts/wps_to_md.py 'https://365.kdocs.cn/l/XXXX' -o /path/to/out.md

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
~/.config/doc2md/venv/bin/python scripts/md_to_pdf.py /path/to/out.md -o /path/to/out.pdf
```

Uses system Chrome. Inserts a 目录 from h2/h3, header title, and page numbers (`--no-toc` to skip). PDF-preview Markdown skips the TOC. If Chrome print is unavailable, open the `.md` in WPS and 另存为 PDF (GUI only — not scripted).

Session files live under `~/.config/doc2md/` (not in this repo):

- `wps_storage_state.json` / `wps_cookie.txt`
- `feishu_storage_state.json` / `feishu_cookie.txt`

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
| `md_to_pdf.py` | Local Markdown → PDF (Chrome print; 目录/页眉/页码) |

See [SKILL.md](SKILL.md) for agent-oriented workflow instructions.

## Notes

- WPS cloud access uses unofficial web APIs and may break when WPS changes their frontend.
- Prefer re-login via the conversion prompt (or `wps_login.py` / `feishu_login.py`), or manually export from the product UI and run `convert.py`.
- Do not commit cookies or `~/.config/doc2md/` session files.

## License

MIT
