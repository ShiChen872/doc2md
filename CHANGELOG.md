# Changelog

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
