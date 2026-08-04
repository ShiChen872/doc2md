# Changelog

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
