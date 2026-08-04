# doc2md

Agent Skill that converts local documents, WPS / 金山文档 (kdocs) share links, and Feishu / Lark wiki or docx links to Markdown, extracting images into a local `*_assets/` folder.

Works with Cursor, Codex, and other Agent Skills–compatible hosts. Copy this directory into the platform’s skills folder (e.g. `~/.agents/skills/doc2md`).

## Features

- Local: docx / pptx / xlsx / pdf / html / epub (via [microsoft/markitdown](https://github.com/microsoft/markitdown))
- **PPTX**: theme text per slide + full-slide screenshots via `office2pdf-python` (LibreOffice optional fallback)
- **PDF**: text via markitdown + embedded images via PyMuPDF; **scanned/image-only PDFs** auto-detected and OCR'd page-by-page
- **Images** (png/jpg/…): keep original in `*_assets/` + OCR via [RapidOCR](https://github.com/RapidAI/RapidOCR) (`rapidocr-onnxruntime`; tesseract fallback)
- Cloud: `kdocs.cn` / `365.kdocs.cn` share links; `feishu.cn` / `larksuite.com` wiki & docx
- WPS intelligent docs (`.otl`): parse `open/otl` JSON; tables rendered as Markdown tables (including images in cells)
- **Feishu**: Playwright session (`feishu_login.py`) + in-page `PageMain` block tree → Markdown + assets
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

### Local file

```bash
~/.config/doc2md/venv/bin/python scripts/convert.py /path/to/doc.docx -o /path/to/out.md
```

### WPS share link

```bash
# One-time / when session expires — complete login in the Chrome window
~/.config/doc2md/venv/bin/python scripts/wps_login.py 'https://365.kdocs.cn/l/XXXX'

# Convert to Markdown
~/.config/doc2md/venv/bin/python scripts/wps_to_md.py 'https://365.kdocs.cn/l/XXXX' -o /path/to/out.md
```

### Feishu / Lark share link

```bash
~/.config/doc2md/venv/bin/python scripts/feishu_login.py 'https://xxx.feishu.cn/wiki/XXXX'
~/.config/doc2md/venv/bin/python scripts/feishu_to_md.py 'https://xxx.feishu.cn/wiki/XXXX' -o /path/to/out.md
```

Session files live under `~/.config/doc2md/` (not in this repo):

- `wps_storage_state.json` / `wps_cookie.txt`
- `feishu_storage_state.json` / `feishu_cookie.txt`

## Scripts

| Script | Role |
|--------|------|
| `convert.py` | Local Office/PDF/OTL-JSON → Markdown |
| `wps_login.py` | Headed Chrome login |
| `wps_to_md.py` | Share URL → Markdown |
| `wps_download.py` | Share URL → raw file / `.otl.json` |
| `otl_to_md.py` | OTL JSON → Markdown |
| `feishu_login.py` | Headed Chrome login (Feishu/Lark) |
| `feishu_to_md.py` | Feishu wiki/docx URL → Markdown |

See [SKILL.md](SKILL.md) for agent-oriented workflow instructions.

## Notes

- WPS cloud access uses unofficial web APIs and may break when WPS changes their frontend.
- Prefer re-login via `wps_login.py`, or manually export from the WPS UI and run `convert.py`.
- Do not commit cookies or `~/.config/doc2md/` session files.

## License

MIT
