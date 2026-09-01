# WPS / 金山文档

Read this when converting a kdocs / 365.kdocs / plus.wps.cn share, a `.otl` dump, or nested OTL file cards.

## Commands

```bash
~/.config/doc2md/venv/bin/python <this-skill>/scripts/wps_login.py 'https://365.kdocs.cn/l/XXXX'
~/.config/doc2md/venv/bin/python <this-skill>/scripts/wps_to_md.py 'https://365.kdocs.cn/l/XXXX' -o /path/to/out.md
~/.config/doc2md/venv/bin/python <this-skill>/scripts/doc2md.py 'https://365.kdocs.cn/l/XXXX' -o /path/to/out.md --recursive
~/.config/doc2md/venv/bin/python <this-skill>/scripts/wps_to_md.py 'https://plus.wps.cn/view/media/l/XXXX' -o /path/to/out.md
```

Session: `~/.config/doc2md/wps_storage_state.json` (Playwright; directory 0700, file 0600).

`--keep-work` keeps `.doc2md_work_*` beside the Markdown (OTL JSON / stream URLs). Default is a temp dir, deleted after convert.

## Type notes

**Media / video** (`.mp4` / `view/media/l/`): original download is often denied. If `ffmpeg` is on PATH, remux the share-page HLS **preview** to `*_assets/preview.mp4` (transcoded, not the original upload). Cover image is saved when available.

**PDF shares:** when original download is denied, screenshot each web-viewer page (`.pdf-page`) into `*_assets/page_NNN.png` and OCR the tiles. Page images are the source of truth; OCR is for search.

**Presentations:** `.pptx` link shares often return `ErrForbidDownloadLinkFile`. Screenshot each `.slide-uil-view` slide. Knowledge-wiki URLs (`365.kdocs.cn/wiki/l/0l…`) resolve to the inner file share id. Do not use WPS `file-content` reading-mode markdown for decks — that is text-only.

**ksheet / dbsheet:** `.ksheet` (`office_type=k`) downloads as an xlsx-compatible zip and becomes Markdown tables. `.dbt` (`office_type=d`) cannot be downloaded (`notAllowType`); screenshot each left-rail sheet and nested view (grid / form / dashboard), clipping the main pane. Visible viewer, not a full record dump.

**流程图 / 思维导图:** `.pom` / `.pof` open in a ProcessOn iframe (`#dotviewIframe`). Skip original download (not an Office zip). Screenshot each bottom **画布** tab. Visible canvas, not a vector dump.

**白板:** `.kw` (`office_type=b`) is the document-center 白板/画板, not 会议白板. Screenshot `.kw_container`. This viewer also uses `.slide-uil-view`, so it is handled **before** PPT slide capture.

## OTL intelligent docs

Cannot use drive binary download (`notAllowType`). Capture `open/otl` JSON + CDN / `/attachment/shapes` `raw` images.

- Tables (`outline-table`) become Markdown tables (including cell images).
- Code blocks keep `attrs.lang`.
- Nested file cards (`WPSDocument`) become Markdown links. **Do not recurse by default.** Only if the user asks to 展开嵌套 / 递归 / convert inner SOP cards, pass `--recursive` (depth 1) or `--max-depth N`. Children land in `{stem}_nested/`; failed children keep the original kdocs link. A parent like 《微软替换物料合集》 has 20+ nested SOP/xlsx/pptx — warn that it can take a long time.
- Images map by `sourceKey` / `imgID` (not array index). Fetch CDN and shapes `raw`, **keep the sharper (more pixels)**. If CDN is incomplete, use shapes by `sourceKey` only. Retry a scroll round if keys are missing.
