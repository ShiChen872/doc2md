# doc2md

Agent Skill that converts local documents and WPS / 金山文档 (kdocs) share links to Markdown, extracting images into a local `*_assets/` folder.

Works with Cursor, Codex, and other Agent Skills–compatible hosts. Copy this directory into the platform’s skills folder (e.g. `~/.agents/skills/doc2md`).

## Features

- Local: docx / pptx / xlsx / pdf / html / epub (via [microsoft/markitdown](https://github.com/microsoft/markitdown))
- Cloud: `kdocs.cn` / `365.kdocs.cn` share links
- WPS intelligent docs (`.otl`): parse `open/otl` JSON + align CDN images to document order
- Images saved as relative Markdown links (not base64)

## Setup

```bash
python3 -m venv ~/.config/doc2md/venv
~/.config/doc2md/venv/bin/pip install -r scripts/requirements.txt
# Uses system Google Chrome via Playwright (channel=chrome)
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

Session files live under `~/.config/doc2md/` (not in this repo):

- `wps_storage_state.json`
- `wps_cookie.txt`

## Scripts

| Script | Role |
|--------|------|
| `convert.py` | Local Office/PDF/OTL-JSON → Markdown |
| `wps_login.py` | Headed Chrome login |
| `wps_to_md.py` | Share URL → Markdown |
| `wps_download.py` | Share URL → raw file / `.otl.json` |
| `otl_to_md.py` | OTL JSON → Markdown |

See [SKILL.md](SKILL.md) for agent-oriented workflow instructions.

## Notes

- WPS cloud access uses unofficial web APIs and may break when WPS changes their frontend.
- Prefer re-login via `wps_login.py`, or manually export from the WPS UI and run `convert.py`.
- Do not commit cookies or `~/.config/doc2md/` session files.

## License

MIT
