# Changelog

## Unreleased

- Comate install zip is slim (`SKILL.md` + `scripts/` only). Tests stay in git; including them trips the cloud security-audit LLM (504).

## v0.4.16

- Session files: config dir `0700`, storage state `0600`; stop writing unused `*_cookie.txt`. Login logs omit SSO query strings.
- WPS/Feishu URLs: HTTPS + real hostname only; Feishu rejects reserved path tokens (`space`, `gallery`, …).
- Feishu: heading/text blocks render children; mermaid ISV accepts string `data`; failed assets become HTML comments; default HTTPS cert checks (`--insecure` to bypass).
- Bare data URIs no longer swallow following Markdown text.
- `tests/fixtures/page_screenshot.png` is part of the tree (clone + pytest).

## v0.4.15

- Feishu 画板 (`/board/`) and 多维表格 (`/base/`, `/share/base/`): screenshot the visible web viewer when there is no doc `PageMain`. Board and bitable blocks inside wiki/docx screenshot the embed instead of `<!-- skipped feishu block -->`.
- Feishu 电子表格 (`/sheets/`) and 思维笔记 (`/mindnotes/`): same web-viewer screenshot path. In-doc `sheet` / `mindnote` blocks screenshot the embed. Poll / chat cards still skipped.
- `--engine=wps` is an explicit error (no official Mac/Linux CLI; Windows COM would drive the WPS client). No silent Chrome fallback.
- OTL images: always fetch `/attachment/shapes` `raw` and keep it when it has more pixels than the CDN capture. Incomplete CDN still uses sourceKey shapes only.
- PDF print: JPEG-compress `page_` / `slide_` screenshots (4:4:4, quality 82) so preview PDFs shrink. Markdown `*_assets/` stay PNG. `--no-compress` keeps originals.

## v0.4.14

- WPS 白板 (`.kw`, `office_type=b`): screenshot the web canvas (`.kw_container`). Must run before PPT capture because this viewer also uses `.slide-uil-view`. Feishu bitable / 画板 still out of scope.

## v0.4.13

- WPS 流程图 (`.pom`) / 思维导图 (`.pof`, export often `.pos`): skip Office-zip convert; screenshot each ProcessOn canvas tab in `#dotviewIframe`. Visible canvas, not a vector dump. WPS 画板/白板 is still out of scope.

## v0.4.12

- WPS dbsheet (`.dbt`, `office_type=d`): original download is `notAllowType`; screenshot each web-viewer sheet **and nested view** (grid / form / dashboard), clipping the main pane. `.ksheet` already downloads as xlsx-compatible zip.

## v0.4.11

- Optional `--recursive` / `--max-depth` for WPS OTL nested file cards: convert unique child shares into `{stem}_nested/*.md` and rewrite parent links. Default remains links only (`max-depth 0`). One child failure does not fail the parent; share-id cycles are skipped.

## v0.4.10

- Recognize WPS knowledge-wiki share URLs (`365.kdocs.cn/wiki/l/…`); `wiki/l/0l<id>` resolves to the inner file share id.
- WPS presentation shares (`.pptx`, `office_type=p`) that deny original download: screenshot each web-viewer slide (same idea as PDF preview), instead of falling through to OTL and failing.

## v0.4.9

- Optional Typst PDF engine and `brand` theme (navy/accent report styling, no logo). Default remains Chrome print (`--engine chrome --theme default`).
- `md_to_pdf.py --engine typst --theme brand`: 目录 / 页眉标题 / 页码; PDF-preview Markdown still prints page images without a TOC.
- Typst needs the official CLI on PATH (macOS Homebrew, Windows winget/scoop/GitHub zip, or Linux release tarball) or `pip install typst`. Missing Typst is an error, not a silent Chrome fallback.

## v0.4.8

- OTL nested file cards (`WPSDocument`) emit as Markdown links instead of being dropped (block, inline, and table cells). Nested files are not recursively converted.

## v0.4.7

- `md_to_pdf.py`: table of contents from h2/h3, header title, and page numbers (Chrome print; `--no-toc` to skip). PDF-preview Markdown skips TOC so slide pages are not listed as outline entries.

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
