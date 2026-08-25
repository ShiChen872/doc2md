# Changelog

## v0.4.6

- Optional second step: `md_to_pdf.py` prints local Markdown (+ `*_assets/`) to PDF via system Chrome
- WPS PDF-preview Markdown prints page images only (OCR stays in `.md`; `--keep-ocr` optional)
- SKILL: only run PDF export when the user asks; WPS 「另存为 PDF」 is a manual fallback, not a CLI engine

## v0.4.5

- WPS PDF shares: when original download is denied, screenshot web-viewer `.pdf-page` tiles + OCR (same idea as media HLS preview)
- SKILL: convert only via `doc2md.py`; do not use host WPS APIs, `WPS_SID`, or Chrome AppleScript / “JavaScript from Apple Events”

## v0.4.4

- Feishu code blocks: map CodeLanguage enum (e.g. 49 → `python`) instead of dropping numeric languages
- Feishu `fallback` blocks: unwrap `snapshot.type` so code / file / bookmark still render; wait recursively for code and file to hydrate
- File attachments nested under views/grids are collected and downloaded
- WPS/Feishu: if the session is missing or expired, conversion opens headed Chrome for the user to log in, then retries once (`--no-login` to skip)

## v0.4.3

- Unified CLI `doc2md.py`: classify local path / WPS share / Feishu URL and dispatch
- SKILL triggers: `plus.wps.cn`, `view/media`, WPS video/media share wording
- Tests for URL/path classification and default output names

## v0.4.2

- WPS media shares (`plus.wps.cn/view/media/l/…`, `.mp4` etc.): export Markdown card + cover image
- When original file download is denied, remux the share-page HLS preview stream to local `preview.mp4` with ffmpeg (if installed); embed `<video>` in Markdown
- Note: preview MP4 is a transcoded stream, not the original upload

## v0.4.1

- Feishu iframe embeds: use document height + 16:9 sizing, disable autoplay on common players, add plain video link fallback
- Tests for iframe rendering / autoplay URL rewrite

## v0.4.0

- Feishu / Lark cloud docs: session-based export via Playwright (`feishu_login.py` + `feishu_to_md.py`)
- Supports `/wiki/` and `/docx/` URLs; extracts in-page `PageMain` block tree → Markdown + local `*_assets/`
- Image path rewrite: placeholders end with `/`, longest-first replace, assets saved as `image_NNN.ext` (avoids short id mangling longer ones)
- Unit tests for URL parsing, block→Markdown, and placeholder prefix safety
- Docs: SKILL / README classify `feishu.cn` / `larksuite.com` → `feishu_to_md.py`

## v0.3.2

- OTL image placement: map by `sourceKey` / `imgID` instead of emit-order index (fixes wholesale misalignment when some pictures sit in tables or containers)
- Table cells: emit pictures inside `outline-table` cells as Markdown images
- Pass through additional OTL containers (`circle_object`, nested sub-doc layouts) so pictures are not skipped
- WPS: if any shape key is still missing after the first scroll/download pass, scroll again and retry
- Regression tests for key-based image maps and in-table pictures

## v0.3.1

- OTL images: when CDN matching is incomplete, scroll and merge `/attachment/shapes`, download by `sourceKey`
- More resilient WPS page open: prefer 365 meta endpoints; use `domcontentloaded` instead of `networkidle`
- Comate-friendly skill metadata (`display_name`, Chinese trigger wording)
- Tests for shapes merge / image strategy helpers

## v0.3.0

- Scanned / image-only PDF pages: render + OCR fallback
- OTL tables (`outline-table`) → Markdown tables; code blocks keep language
- Unit tests (convert / OTL / WPS helpers)
- OCR setup notes in README

## v0.2.1

- Image OCR prefers RapidOCR (`rapidocr-onnxruntime`), tesseract fallback

## v0.2.0

- PPTX: per-slide theme text + full-slide screenshots via `office2pdf-python`

## v0.1.0

- Initial skill: local convert + WPS login/share links + OTL
