# Markdown → PDF (optional)

Only when the user asks for PDF. Markdown stays the source of truth. Do **not** emit PDF by default.

```bash
~/.config/doc2md/venv/bin/python <this-skill>/scripts/md_to_pdf.py /path/to/out.md -o /path/to/out.pdf
```

## Chrome (default)

`--engine chrome`. Adds a **目录** from h2/h3, a header title, and page numbers. Local `*_assets/` images are resolved; `<video>` / iframe become links.

Print isolation: JavaScript disabled, CSP blocks script/connect/frame, and `http(s)` requests are aborted. Raw HTML (tables, page images) is kept.

WPS PDF-preview Markdown prints **page images only** (OCR stays in the `.md`; `--keep-ocr` adds a tiny gray OCR block) and skips the TOC so “第 N 页” is not an outline entry. `--no-toc` skips the table of contents.

Page/slide screenshots are JPEG-compressed for print by default (Markdown assets are not modified). `--no-compress` keeps the original PNG in the PDF.

`--theme brand` (navy/accent, no logo) also works with Chrome.

## Typst

If the user asks for **更好排版 / 品牌样式 / Typst**:

```bash
~/.config/doc2md/venv/bin/python <this-skill>/scripts/md_to_pdf.py /path/to/out.md -o /path/to/out.pdf --engine typst --theme brand
```

Needs the **Typst CLI** on PATH, or `pip install typst` when a wheel exists. Cross-platform:

- macOS: `brew install typst`
- Windows: `winget install --id Typst.Typst -e` (or `scoop install typst`, or unzip `typst-x86_64-pc-windows-msvc.zip` from [GitHub Releases](https://github.com/typst/typst/releases) onto PATH)
- Linux: same Releases linux archive

Do not silently fall back to Chrome if Typst was requested. Without Typst, keep `--engine chrome`.

## Not supported

Do **not** call WPS `convert/to/pdf` or automate the WPS client. `--engine=wps` errors: no official Mac/Linux CLI, and Windows COM would drive the client.

If Chrome print is unavailable and Typst was not requested, tell the user they can open the `.md` in WPS and 另存为 PDF (manual GUI, not a CLI engine).
