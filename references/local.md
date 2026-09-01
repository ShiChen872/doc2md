# Local files

Read this when converting a path on disk (Office, PDF, HTML, EPUB, image, or `.otl.json`).

## Command

```bash
~/.config/doc2md/venv/bin/python <this-skill>/scripts/convert.py /path/to/doc.docx -o /path/to/out.md
```

`--assets-dir` is optional. The default is `{stem}_assets` beside the Markdown and may be glob-cleaned on re-convert. A **non-empty custom** `--assets-dir` is not wiped unless `--force-clean`.

Also accepts `.otl.json` (WPS intelligent-doc JSON) via `otl_to_md.py`.

## Format notes

- **Images** (png/jpg/…): keep the original in `*_assets/`. OCR prefers **RapidOCR** (`rapidocr-onnxruntime`; better Chinese), then local `tesseract` (`chi_sim`). Architecture diagrams stay image-first; OCR is search aid.
- **PDF:** markitdown extracts text; PyMuPDF extracts embedded images. Pages with almost no text are rendered to PNG and OCR'd. A fully scanned PDF uses OCR as the body.
- **DOCX / EPUB / HTML:** markitdown `keep_data_uris=True` on `convert()`, then decode data URIs into `<stem>_assets/`.
- **PPTX:** per-slide **theme text** + **one full-slide screenshot**. PPTX→PDF via `office2pdf-python` (no system Office); LibreOffice `soffice` is optional fallback; PyMuPDF renders page PNGs.

Tesseract is optional. If neither RapidOCR nor tesseract is available, the image is still copied and a note is added to the Markdown.
